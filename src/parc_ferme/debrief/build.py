"""Everything one session's debrief page shows, gathered into one JSON document.

The page is rendered from this document alone, so a published page can always be traced to the numbers, checks
and code version behind it.
"""

import json
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .. import checks as data_checks
from .. import jolpica
from ..bench import grip as grip_bench
from ..bench import identifiability
from ..bench import pace as pace_bench
from ..core.car import rules
from ..core.track import FEED_UNITS_PER_M, Track
from ..models import grip, pace
from ..session import Session
from . import channels, energy, summary

CIRCUIT_NAMES = {15: "Circuit de Barcelona-Catalunya"}
MAP_STEP_M = 10.0
LABEL_OFFSET_M = 55.0
SCHEMA = 2


def code_version() -> dict:
    root = Path(__file__).resolve().parents[3]

    def git(*args):
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True).stdout.strip()

    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    return {"commit": git("rev-parse", "--short", "HEAD"), "dirty": dirty}


def local_start(meta: dict) -> datetime:
    h, m, _ = (int(x) for x in meta["gmt_offset"].split(":"))
    return datetime.fromisoformat(meta["date_start"]) + timedelta(hours=h, minutes=m)


def sector_fractions(s: Session, laps: pd.DataFrame, ref: Track) -> list[float]:
    """Lap fractions of the two intermediate timing lines: where each green lap's car is when its first and second
    sector times run out, placed on the reference line through the position feed. Median over laps."""
    loc = s.location[(s.location.x != 0) | (s.location.y != 0)]
    by = {d: g.sort_values("date") for d, g in loc.groupby("driver_number")}
    tree = cKDTree(np.c_[ref.x, ref.y])
    found = {1: [], 2: []}
    for r in laps[laps.green & laps.s1.notna() & laps.s2.notna()].itertuples():
        g = by.get(r.driver_number)
        if g is None:
            continue
        for k, elapsed in ((1, r.s1), (2, r.s1 + r.s2)):
            at = r.date_start + pd.Timedelta(seconds=elapsed)
            w = g[(g.date > at - pd.Timedelta(seconds=1)) & (g.date < at + pd.Timedelta(seconds=1))]
            if len(w) < 2:
                continue
            _, j = tree.query(np.c_[w.x / FEED_UNITS_PER_M, w.y / FEED_UNITS_PER_M])
            sj = np.unwrap(ref.s[j] * 2 * np.pi / ref.length) * ref.length / (2 * np.pi)
            ts = (w.date - at).dt.total_seconds().to_numpy()
            found[k].append((np.interp(0.0, ts, sj) % ref.length) / ref.length)
    return [float(np.median(found[1])), float(np.median(found[2]))]


def _rotate(x, y, degrees: float) -> tuple[np.ndarray, np.ndarray]:
    """The circuit-info service's display rotation, as the official track maps use it."""
    a = np.radians(degrees)
    x, y = np.asarray(x, float), np.asarray(y, float)
    return x * np.cos(a) - y * np.sin(a), x * np.sin(a) + y * np.cos(a)


def track_map(s: Session, ref: Track, bounds: list[float], corner_kph: pd.Series, w: pd.Series,
              flat_out: list) -> dict:
    """Track outline, corners and sector lines in display coordinates (metres, y down)."""
    rot = s.circuit.rotation
    step = max(1, int(round(MAP_STEP_M / ref.ds)))
    x, y = _rotate(ref.x[::step], ref.y[::step], rot)
    corners = []
    for c in s.circuit.corners.itertuples():
        n = int(c.number)
        ox, oy = _rotate([LABEL_OFFSET_M], [0.0], c.angle_deg)
        cx, cy = _rotate([c.x_m], [c.y_m], rot)
        lx, ly = _rotate([c.x_m + ox[0]], [c.y_m + oy[0]], rot)
        corners.append({"number": n, "label": f"{n}{c.letter or ''}", "x": float(cx[0]), "y": float(-cy[0]),
                        "lx": float(lx[0]), "ly": float(-ly[0]),
                        "kph": float(corner_kph.get(n, np.nan)), "w": float(w[n]) if n in w.index else None,
                        "flat_out": n in flat_out})
    marks = []
    for k, f in enumerate([0.0, *bounds], start=1):
        i = int(round(f * len(ref.s))) % len(ref.s)
        nx, ny = ref.normals()
        px, py = _rotate([ref.x[i]], [ref.y[i]], rot)
        qx, qy = _rotate([nx[i]], [ny[i]], rot)
        marks.append({"line": "start" if k == 1 else f"S{k - 1}/S{k}", "x": float(px[0]), "y": float(-py[0]),
                      "nx": float(qx[0]), "ny": float(-qy[0])})
    return {"x": np.round(x, 1).tolist(), "y": np.round(-y, 1).tolist(), "corners": corners, "lines": marks}


def _plain(o):
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, list | tuple | np.ndarray):
        return [_plain(v) for v in o]
    if isinstance(o, bool | np.bool_):
        return bool(o)
    if isinstance(o, int | np.integer):
        return int(o)
    if isinstance(o, float | np.floating):
        return float(o) if np.isfinite(o) else None
    return o


def to_json(d: dict) -> str:
    """The document as compact JSON, with NaN as null so a browser can parse it."""
    return json.dumps(_plain(d), separators=(",", ":"), allow_nan=False)


def _team_colour(hex_rgb) -> str:
    return f"#{hex_rgb}" if isinstance(hex_rgb, str) and len(hex_rgb) == 6 else "#8a8a8a"


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: (v.item() if isinstance(v, np.generic) else v) for k, v in r.items()}
            for r in df.to_dict(orient="records")]


def _identifiability(rel: pd.DataFrame, p) -> dict:
    results = identifiability.load()
    bench = None if results is None else {
        "commit": results["commit"], "generated_utc": results["generated_utc"],
        "grip_races": results["grip"]["races"], "pace_races": results["pace"]["races"],
        "pace_cars": results["pace"]["cars"]}
    return {"bench": bench, "rows": identifiability.session_rows(results, rel, p.cars, p.reference),
            "pace": {"ref_age": p.ref_age, "ref_compound": p.ref_compound, "stint_sd_s": p.stint_sd_s,
                     "selection_bias_s": p.selection_bias_s}}


def build(s: Session) -> dict:
    checks, t = data_checks.run(s)
    t["gap_ahead"] = pace.gap_ahead(t, s.intervals)
    p = pace.sector_pace(t)
    g = grip.analyse(s, t)
    bench = grip_bench.recovery()
    pace_rec = pace_bench.recovery()

    start = local_start(s.meta)
    results = s.session_result.sort_values("position")
    try:
        official = jolpica.race_results(s.meta["year"], jolpica.race_round(s.meta["year"], f"{start:%Y-%m-%d}"))
        grid = dict(zip(official.driver_number, official.grid, strict=True))
        rnd = int(jolpica.race_round(s.meta["year"], f"{start:%Y-%m-%d}"))
    except Exception:  # Jolpica is a cross-check; the page doesn't depend on it
        grid, rnd = {}, None
    drivers = s.drivers.set_index("driver_number")
    cars = {r.name_acronym: {"name": f"{r.first_name} {r.last_name}", "last": r.last_name, "team": r.team_name,
                             "number": int(n), "colour": _team_colour(r.team_colour)} for n, r in drivers.iterrows()}
    podium = [{"position": int(r.position), "driver": drivers.name_acronym[r.driver_number],
               "team": drivers.team_name[r.driver_number], "grid": grid.get(r.driver_number)}
              for r in results.head(3).itertuples()]

    bounds = sector_fractions(s, t, g.model.reference)
    edges = [0.0, *bounds, 1.0]
    sectors = [{"sector": k + 1, "from": edges[k], "to": edges[k + 1],
                "corners": sorted(n for n, f in g.model.corner_fraction.items() if edges[k] <= f < edges[k + 1])}
               for k in range(3)]

    wx = s.weather
    corners = g.field.corners.assign(w=g.field.corners.corner.map(g.w))
    rel = g.relative
    clean = g.clean_air.set_index("team") if g.clean_air is not None else None
    sim_car = replace(g.field.car, fuel_kg=channels.SIM_FUEL_KG)
    lap_length = float(g.model.stats["speed_integrated_lap_m"])
    d = {
        "schema": SCHEMA,
        "session": {"key": s.key, "year": s.meta["year"], "round": rnd,
                    "name": s.meta["meeting"].get("meeting_name", s.meta["location"]),
                    "session_name": s.meta["session_name"],
                    "circuit": CIRCUIT_NAMES.get(s.meta["circuit_key"], s.meta["circuit_short_name"]),
                    "date": f"{start:%Y-%m-%d}", "laps": int(results.number_of_laps.max())},
        "conditions": {"air_c": float(wx.air_temperature.median()), "track_c": float(wx.track_temperature.median()),
                       "humidity_pct": float(wx.humidity.median()), "pressure_hpa": float(wx.pressure.median()),
                       "rain": bool((wx.rainfall > 0).any()), "air_density": g.rho},
        "podium": podium,
        "cars": cars,
        "sectors": sectors,
        "pace": {"reference": p.reference, "cars": _records(p.cars), "traffic": _records(p.traffic),
                 "holdout": p.holdout, "excluded": p.excluded, "min_laps": pace.MIN_LAPS,
                 "ref_age": p.ref_age, "ref_compound": p.ref_compound, "stint_sd_s": p.stint_sd_s,
                 "selection_bias_s": p.selection_bias_s},
        "grip": {"teams": _records(rel), "w_slow": rel.attrs["w_slow"], "w_fast": rel.attrs["w_fast"],
                 "laps": rel.attrs["laps"], "corners": _records(corners), "flat_out": g.flat_out,
                 "field": {"mu": g.field.car.mu, "cla": g.field.car.cla_corner, "rms_kph": g.field.rms_kph,
                           "mass_kg": g.field.car.mass},
                 "clean_air": None if clean is None else {
                     "gap_s": g.clean_air.attrs["gap_s"], "laps": g.clean_air.attrs["laps"],
                     "teams": [{"team": r["team"], "slow": float(clean.slow_corner_pct[r["team"]]),
                                "fast": float(clean.fast_corner_pct[r["team"]])} for r in _records(rel)]},
                 "sections": _records(g.sections)},
        "track": track_map(s, g.model.reference, bounds, g.corner_kph, g.w, g.flat_out),
        "telemetry": channels.telemetry(s.car_data, t, g.model, sectors, _records(rel), sim_car, lap_length),
        "car_model": channels.parameter_effects(g.model.line, g.model.zones, sim_car),
        "bench": {"rows": _records(bench), "tolerance_pct": grip_bench.TOLERANCE_PCT,
                  "passed": bool((bench.mech_err.abs() <= grip_bench.TOLERANCE_PCT["mech"]).all()
                                 and (bench.downforce_err.abs() <= grip_bench.TOLERANCE_PCT["downforce"]).all())},
        "pace_bench": {"cars": len(pace_bench.CARS), "laps": pace_bench.LAPS,
                       "max_error_s": float(pace_rec.error_s.abs().max()),
                       "tolerance_s": pace_bench.TOLERANCE_S,
                       "passed": bool((pace_rec.error_s.abs() <= pace_bench.TOLERANCE_S).all())},
        "identifiability": _identifiability(rel, p),
        "checks": [c.as_dict() for c in checks],
        "code": code_version(),
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
    }
    zones = rules()["active_aero"]["zones"]
    if s.meta["year"] == 2026 and str(s.meta["circuit_key"]) in zones and all(c.passed or not c.gating for c in checks):
        try:
            d["energy_fit"] = energy.study(s, channels.SIM_FUEL_KG, d["code"])
        except ValueError as err:
            d["energy_unavailable"] = str(err)
    d["summary"] = summary.findings(d)
    return d
