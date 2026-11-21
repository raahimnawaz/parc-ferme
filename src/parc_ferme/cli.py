import argparse
import json
import sys

from . import checks, warmup
from .circuit import load_circuit
from .openf1 import fetch_session
from .paths import REPORTS
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
    import pandas as pd

    from .core.car import Car, air_density
    from .models import grip as S3
    from .sim.model import circuit_model, run
    from .telemetry import placed_samples

    s = Session(args.session_key)
    t = warmup.laps(s)
    wx = s.weather
    rho = air_density(wx.pressure.median(), wx.air_temperature.median(), wx.humidity.median())
    car = Car(fuel_kg=S3.FUEL_AVG_KG, rho=rho)
    model = circuit_model(s, car, t)
    samples = placed_samples(s.car_data, s.location, t[t.green], model.reference)
    all_minima = S3.corner_minima(samples, model.corner_fraction)
    minima = S3.grip_limited(all_minima)
    used = sorted(minima.corner.unique())
    v_ref = minima.groupby("corner").v.median()
    for _ in range(2):  # the line depends on the car: fit, search the line for the fitted car, fit again
        field = S3.fit_car(model.line, model.zones, car, model.corner_fraction, v_ref)
        car = field.car
        model = circuit_model(s, car, t)
    field = S3.fit_car(model.line, model.zones, car, model.corner_fraction, v_ref)
    w = pd.Series(S3.aero_share(v_ref, field.car.mu, field.car.cla_corner, car.mass, rho), index=v_ref.index)
    rel = S3.relative_grip(minima, w)

    anchors = S3.straight_anchors(model.reference)
    driven = S3.path_lengths(samples, model.reference.s[anchors], model.reference.length)
    sections = pd.DataFrame({"from_m": model.reference.s[anchors][:-1], "to_m": model.reference.s[anchors][1:],
                             "driven_m": driven, "line_m": S3.line_lengths(model.line, model.reference, anchors)})
    sections["line_short_m"] = sections.driven_m - sections.line_m

    team = s.teams[int(t[t.driver == args.driver].driver_number.iloc[0])]
    r = rel.set_index("team").loc[team]
    fitted = Car(fuel_kg=args.fuel, rho=rho, mu=field.car.mu * np.exp(r.mech_pct / 100),
                 cla_corner=field.car.cla_corner * np.exp(r.downforce_pct / 100))
    _, res = run(s, args.driver, fitted)

    out = REPORTS / str(s.key)
    out.mkdir(parents=True, exist_ok=True)
    rel.to_csv(out / "grip_teams.csv", index=False)
    field.corners.assign(w=field.corners.corner.map(w)).to_csv(out / "grip_corners.csv", index=False)
    sections.to_csv(out / "path_lengths.csv", index=False)
    res.corners.to_csv(out / f"sim_corners_fitted_{args.driver}.csv", index=False)
    summary = {"air_density": rho, "mass_kg": car.mass, "field_mu": field.car.mu, "field_cla": field.car.cla_corner,
               "field_corner_rms_kph": field.rms_kph, "corners_used": [int(c) for c in used],
               "corners_flat_out": sorted(int(c) for c in set(all_minima.corner) - set(used)),
               "laps": rel.attrs["laps"], "w_slow": rel.attrs["w_slow"], "w_fast": rel.attrs["w_fast"],
               "fitted_car": {"team": team, "mu": fitted.mu, "cla_corner": fitted.cla_corner},
               "fitted_vs_" + args.driver: res.summary}
    (out / "grip.json").write_text(json.dumps(summary, indent=2, default=float))

    print(f"air density {rho:.3f} kg/m3; field mu {field.car.mu:.2f}, ClA {field.car.cla_corner:.2f} "
          f"(corner misfit {field.rms_kph:.1f} km/h rms on the modelled line); {rel.attrs['laps']} laps, "
          f"corners {[int(c) for c in used]}")
    print(field.corners.round(1).to_string(index=False))
    print(rel.round(2).to_string(index=False))
    print(sections.round(1).to_string(index=False))
    print(f"fitted {team} car vs {args.driver}: corner bias {res.summary['corner_min_bias_kph']:+.1f} km/h, "
          f"speed rms {res.summary['speed_rms_kph']:.1f} km/h, lap {res.summary['sim_lap_s']:.2f} s "
          f"vs {res.summary['real_lap_s']:.2f} s")
    print(f"report: {out}")
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

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
