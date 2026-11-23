import argparse
import json
import sys

from . import checks, warmup
from .circuit import load_circuit
from .openf1 import fetch_session
from .paths import REPORTS, SITE
from .session import Session


def ingest(args) -> int:
    meta = fetch_session(args.session_key, refresh=args.refresh)
    c = load_circuit(meta["circuit_key"], meta["year"])
    print(f"{c.name}: {len(c.corners)} corners, centreline {c.centreline_length_m:.0f} m")
    return 0


def check(args) -> int:
    s = Session(args.session_key)
    results, t = checks.run(s)
    out = REPORTS / str(s.key)
    out.mkdir(parents=True, exist_ok=True)

    lines = [f"# {s.name} — data checks", ""]
    for c in results:
        mark = "PASS" if c.passed else ("FAIL" if c.gating else "WARN")
        print(f"{mark:4}  {c.name:26} {c.detail}")
        lines.append(f"- **{mark}** `{c.name}`: {c.detail}")
    (out / "checks.md").write_text("\n".join(lines) + "\n")
    (out / "checks.json").write_text(json.dumps([c.as_dict() for c in results], indent=2))

    t.to_csv(out / "laps.csv", index=False)
    warmup.compound_summary(t).to_csv(out / "compounds.csv", index=False)
    warmup.best_long_run(t).to_csv(out / "long_runs.csv", index=False)
    warmup.stop_pace(t).to_csv(out / "stop_pace.csv", index=False)
    a, b = args.overlay
    warmup.overlay(s, t, a, b).to_csv(out / f"overlay_{a}_{b}.csv", index=False)
    print(f"report: {out}")
    return 0 if all(c.passed for c in results if c.gating) else 1


def sim(args) -> int:
    from .core.car import Car
    from .sim.model import run
    from .sim.plot import plot, plot_lines

    s = Session(args.session_key)
    model, r = run(s, args.driver, Car(fuel_kg=args.fuel))
    out = REPORTS / str(s.key)
    out.mkdir(parents=True, exist_ok=True)
    summary = model.stats | r.summary
    (out / "sim_vs_real.json").write_text(json.dumps(summary, indent=2, default=float))
    r.corners.to_csv(out / "sim_corners.csv", index=False)
    r.lap.trace.to_csv(out / "sim_lap.csv", index=False)
    r.fake_car_data.to_parquet(out / "fake_car_data.parquet", index=False)
    r.fake_location.to_parquet(out / "fake_location.parquet", index=False)
    plot(r, model, out / f"sim_vs_{args.driver}.png", f"{s.name}: nominal 2026 car vs {args.driver}")
    plot_lines(model, out / "racing_lines.png", ((650.0, 1350.0), (2750.0, 3650.0)))
    for k in ("min_curvature_line_m", "racing_line_m", "speed_integrated_lap_m", "min_curvature_lap_s", "sim_lap_s",
              "real_lap_s", "real_top_kph", "sim_top_kph", "speed_corr", "corner_min_bias_kph", "harvest_mj"):
        print(f"{k:24} {summary[k]:.3f}")
    print(f"report: {out}")
    return 0


def grip(args) -> int:
    import numpy as np

    from .core.car import Car
    from .models import grip as S3
    from .sim.model import run

    s = Session(args.session_key)
    t = warmup.laps(s)
    g = S3.analyse(s, t)
    team = s.teams[int(t[t.driver == args.driver].driver_number.iloc[0])]
    r = g.relative.set_index("team").loc[team]
    fitted = Car(fuel_kg=args.fuel, rho=g.rho, mu=g.field.car.mu * np.exp(r.mech_pct / 100),
                 cla_corner=g.field.car.cla_corner * np.exp(r.downforce_pct / 100))
    _, res = run(s, args.driver, fitted)

    out = REPORTS / str(s.key)
    out.mkdir(parents=True, exist_ok=True)
    g.relative.to_csv(out / "grip_teams.csv", index=False)
    g.field.corners.assign(w=g.field.corners.corner.map(g.w)).to_csv(out / "grip_corners.csv", index=False)
    g.sections.to_csv(out / "path_lengths.csv", index=False)
    res.corners.to_csv(out / f"sim_corners_fitted_{args.driver}.csv", index=False)
    summary = {"air_density": g.rho, "mass_kg": g.field.car.mass, "field_mu": g.field.car.mu,
               "field_cla": g.field.car.cla_corner, "field_corner_rms_kph": g.field.rms_kph,
               "corners_used": sorted(int(c) for c in g.minima.corner.unique()), "corners_flat_out": g.flat_out,
               "laps": g.relative.attrs["laps"], "w_slow": g.relative.attrs["w_slow"],
               "w_fast": g.relative.attrs["w_fast"],
               "fitted_car": {"team": team, "mu": fitted.mu, "cla_corner": fitted.cla_corner},
               "fitted_vs_" + args.driver: res.summary}
    (out / "grip.json").write_text(json.dumps(summary, indent=2, default=float))

    print(f"air density {g.rho:.3f} kg/m3; field mu {g.field.car.mu:.2f}, ClA {g.field.car.cla_corner:.2f} "
          f"(corner misfit {g.field.rms_kph:.1f} km/h rms on the modelled line); {g.relative.attrs['laps']} laps, "
          f"flat out: {g.flat_out}")
    print(g.field.corners.round(1).to_string(index=False))
    print(g.relative.round(2).to_string(index=False))
    print(g.sections.round(1).to_string(index=False))
    print(f"fitted {team} car vs {args.driver}: corner bias {res.summary['corner_min_bias_kph']:+.1f} km/h, "
          f"speed rms {res.summary['speed_rms_kph']:.1f} km/h, lap {res.summary['sim_lap_s']:.2f} s "
          f"vs {res.summary['real_lap_s']:.2f} s")
    print(f"report: {out}")
    return 0


def energy(args) -> int:
    from .models.energy import analyse

    try:
        if args.fit:
            return energy_fit(args)
        rows = analyse(Session(args.session_key), args.fuel)
    except ValueError as err:
        print(err)
        return 1
    if rows.empty:
        print("no usable straight-line windows")
        return 1
    path = REPORTS / str(args.session_key) / "energy_windows.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(path, index=False)
    print(f"{len(rows)} windows from {rows.driver.nunique()} cars. Conditional wheel power [kW] = "
          f"base_kw + drag_kw_per_m2 × CdA [m²], assuming still air and {args.fuel:g} kg fuel.")
    print(f"report: {path}")
    return 0


def energy_fit(args) -> int:
    import pandas as pd

    from .bench import energy as bench_energy
    from .core.car import Car
    from .debrief.build import code_version
    from .models.battery import ledger
    from .models.energy import analyse
    from .models.energy_fit import evaluate, scores

    calibration = bench_energy.load()
    battery_laps = {}
    rows = analyse(Session(args.session_key), args.fuel, multi_lap=True, battery_laps=battery_laps)
    if rows.empty:
        raise ValueError("no usable straight-line windows")
    car = Car(fuel_kg=args.fuel, rho=rows.rho_kg_m3.iloc[0])
    baseline, _, _, baseline_skipped = evaluate(rows, calibration["scales"], car)
    params, pred, runs, skipped = evaluate(rows, calibration["battery"]["scales"], car, battery_laps)
    if pred.empty:
        raise ValueError("no held-out laps with sufficient training data")
    full = rows[rows.phase == "full throttle"]
    held = full[full.lap % 5 == 0]
    trained = full[(full.lap % 5 != 0) & full.driver.isin(params.driver)]
    extended = runs[runs.windows >= 2]
    report = dict(version=code_version(), fingerprint=calibration["fingerprint"], session=args.session_key,
                  assumed_fuel_kg=args.fuel, rho_kg_m3=car.rho, split="hold out race lap numbers divisible by five",
                  fitted_cars=params.driver.nunique(), train_car_laps=len(trained.drop_duplicates(["driver", "lap"])),
                  training_windows=len(trained), available_holdout_windows=len(held), scored_windows=len(pred),
                  scored_cars=pred.driver.nunique(), scored_car_laps=len(pred.drop_duplicates(["driver", "lap"])),
                  median_window_s=float((pred.end_s - pred.start_s).median()), skipped_cars=skipped,
                  window_scores=scores(pred), by_zone={z: scores(g) for z, g in pred.groupby("zone")},
                  extended_runs=len(extended), extended_scores=scores(extended) if len(extended) else None,
                  extended_median_s=float((extended.end_s-extended.start_s).median()) if len(extended) else None)
    out = REPORTS / str(args.session_key)
    out.mkdir(parents=True, exist_ok=True)
    keys = ["driver", "zone", "quantity"]
    paired = baseline.merge(params, on=keys, how="outer", suffixes=("_windows", "_battery"),
                            indicator=True, validate="one_to_one")
    matched = paired[paired._merge == "both"].copy()
    widths = {}
    for quantity, group in matched.groupby("quantity"):
        before = group.sim95_high_windows - group.sim95_low_windows
        after = group.sim95_high_battery - group.sim95_low_battery
        raw_before = group.high_windows - group.low_windows
        raw_after = group.high_battery - group.low_battery
        widths[quantity] = dict(pairs=len(before), windows_median=float(before.median()),
                                battery_median=float(after.median()), narrower=int((after < before-1e-8).sum()),
                                wider=int((after > before+1e-8).sum()),
                                raw_narrower=int((raw_after < raw_before-1e-8).sum()),
                                max_raw_reduction=float((raw_before-raw_after).max()))
    budgets = []
    for q in params[params.quantity == "drag_m2"].itertuples():
        lap_ids = trained.loc[trained.driver == q.driver, "lap"].unique()
        parts = {lap: battery_laps[q.driver, lap] for lap in lap_ids}
        budgets.extend(dict(driver=q.driver, **row) for row in ledger(parts, q.estimate, car))
    budget = pd.DataFrame(budgets)
    budget.to_csv(out / "energy_lap_balance.csv", index=False)
    paired.to_csv(out / "energy_paired_intervals.csv", index=False)
    report.update(interval_comparison=widths, baseline_skipped_cars=baseline_skipped,
                  unmatched_intervals=int((paired._merge != "both").sum()),
                  feasible_training_laps=int(budget.feasible.sum()))
    params.to_csv(out / "energy_intervals.csv", index=False)
    pred.to_csv(out / "energy_heldout.csv", index=False)
    runs.to_csv(out / "energy_rollouts.csv", index=False)
    (out / "energy_fit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['fitted_cars']} fitted cars, {len(pred)}/{len(held)} held-out windows. "
          f"Speed MAE {scores(pred)['joint']['mae_kph']:.2f} km/h "
          f"(local baseline {scores(pred)['local_speed_gain']['mae_kph']:.2f}).")
    print(f"report: {out / 'energy_fit.json'}")
    return 0


def debrief(args) -> int:
    from .debrief.build import build, to_json

    s = Session(args.session_key)
    d = build(s)
    gating = [c for c in d["checks"] if c["gating"] and not c["passed"]]
    if gating:
        for c in gating:
            print(f"FAIL  {c['name']:26} {c['detail']}")
        print("not published: a gating data check failed")
        return 1
    out = REPORTS / str(s.key)
    out.mkdir(parents=True, exist_ok=True)
    (out / "debrief.json").write_text(to_json(d))
    t = d["telemetry"]
    print(f"telemetry: {len(t['laps'])} cars, {t['green_laps']} green laps on a {t['dx']:g} m grid over "
          f"{t['L']:.0f} m; lap sim for {len(t['sims'])} teams")
    for f in d["summary"]:
        print("-", f["text"])
    return site(args)


def bench(args) -> int:
    from .bench import identifiability
    from .debrief.build import code_version

    code = code_version()
    from .bench import energy as bench_energy

    study = bench_energy.run(quick=args.quick)
    for label, fit in (("windows", study), ("battery", study["battery"])):
        for quantity, groups in fit["quantities"].items():
            total = groups["all"]
            print(f"S4 {label} {quantity}: {total['covered_cars']}/{total['cars']} independent audit cars covered")
    if not args.quick:
        bench_energy.save(study, code)
    if args.energy_only:
        return int(any(not result["calibrated"] for fit in (study, study["battery"])
                       for group in fit["quantities"].values()
                       for result in group.values()) and not args.quick)
    results = identifiability.run(quick=args.quick)
    for model, label in (("grip", "S3 grip"), ("pace", "race pace")):
        for name, sm in results[model]["confounders"].items():
            mark = "PASS" if sm["calibrated"] else "WIDE" if sm["sd_z"] < 1 else "FAIL"
            print(f"{mark}  {label:10} {name:12} 95% covers {100 * sm['cover_95']:.0f}%, "
                  f"error / stated {sm['sd_z']:.2f}, mean {sm['mean_z']:+.2f} SE ({sm['n']} estimates)")
    if args.quick:
        print("quick run: not saved")
        return 0
    commit = code["commit"] + ("+" if code["dirty"] else "")
    print(f"saved {identifiability.save(results, commit)} (measured on {commit})")
    return 0


def site(args) -> int:
    from .debrief.build import SCHEMA
    from .site import render

    debriefs = []
    for p in sorted(REPORTS.glob("*/debrief.json")):
        d = json.loads(p.read_text())
        if d.get("schema") == SCHEMA:
            debriefs.append(d)
        else:
            print(f"skipped {p.parent.name}: built by an older version, rebuild it with `parc-ferme debrief`")
    pages = render.write(SITE, debriefs)
    for p in pages:
        print(f"page: {p}")
    print(f"index: {SITE / 'index.html'}")
    return 0


def publish(args) -> int:
    from .paths import ROOT
    from .site.publish import PublishError
    from .site.publish import publish as push_site

    site(args)
    try:
        commit = push_site(SITE, ROOT)
    except PublishError as err:
        print(f"not published: {err}")
        return 1
    print("site unchanged, nothing to publish" if commit is None else f"published {commit[:7]} to gh-pages")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="parc-ferme")
    sub = p.add_subparsers(required=True)

    pi = sub.add_parser("ingest", help="download a session from OpenF1")
    pi.add_argument("session_key", type=int)
    pi.add_argument("--refresh", action="store_true", help="download tables already on disk again")
    pi.set_defaults(func=ingest)

    pc = sub.add_parser("check", help="run the data checks and warm-up analyses on a session")
    pc.add_argument("session_key", type=int)
    pc.add_argument("--overlay", nargs=2, default=("HAM", "LEC"), metavar=("A", "B"))
    pc.set_defaults(func=check)

    ps = sub.add_parser("sim", help="simulate the nominal 2026 car here and compare with a driver's best lap")
    ps.add_argument("session_key", type=int)
    ps.add_argument("--driver", default="HAM")
    ps.add_argument("--fuel", type=float, default=20.0, help="fuel load assumed for the compared lap [kg]")
    ps.set_defaults(func=sim)

    pg = sub.add_parser("grip", help="S3: each team's mechanical grip and downforce from corner speeds")
    pg.add_argument("session_key", type=int)
    pg.add_argument("--driver", default="HAM", help="driver whose lap the fitted car is compared with")
    pg.add_argument("--fuel", type=float, default=20.0, help="fuel load assumed for the compared lap [kg]")
    pg.set_defaults(func=grip)

    pe = sub.add_parser("energy", help="S4: conditional wheel power on each driver's fastest green lap")
    pe.add_argument("session_key", type=int)
    pe.add_argument("--fuel", type=float, default=20.0, help="assumed fuel mass for every compared lap [kg]")
    pe.add_argument("--fit", action="store_true", help="fit across green laps and evaluate held-out speeds")
    pe.set_defaults(func=energy)

    pb = sub.add_parser("bench", help="identifiability bench: check every stated uncertainty against synthetic truth")
    pb.add_argument("--quick", action="store_true", help="a short run that isn't saved")
    pb.add_argument("--energy-only", action="store_true", help="only calibrate and audit S4 on hidden strategies")
    pb.set_defaults(func=bench)

    pd_ = sub.add_parser("debrief", help="build a session's debrief and rebuild the site")
    pd_.add_argument("session_key", type=int)
    pd_.set_defaults(func=debrief)

    pw = sub.add_parser("site", help="rebuild the site from every debrief already built")
    pw.set_defaults(func=site)

    pp = sub.add_parser("publish", help="rebuild the site and push it to the gh-pages branch")
    pp.set_defaults(func=publish)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
