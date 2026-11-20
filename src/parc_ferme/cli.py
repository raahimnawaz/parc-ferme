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

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
