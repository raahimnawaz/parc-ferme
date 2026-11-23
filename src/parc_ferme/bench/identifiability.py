"""The identifiability bench: every reported quantity's stated uncertainty, checked against synthetic truth with the
confounders the real feed carries switched on.

`parc-ferme bench` runs it and writes RESULTS, which the debrief reads to say, for each quantity on the page,
whether the bench backs its intervals and what the session's estimates resolve. Full runs take a few minutes;
the tests run a short version on every commit.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from . import coverage as cv
from . import grip as grip_bench
from . import pace as pace_bench

RESULTS = Path(__file__).with_name("coverage.json")

GRIP_QUANTITIES = {"slow_corner": "Grip in slow corners", "fast_corner": "Grip in fast corners",
                   "mech": "Tyre grip (split)", "downforce": "Downforce (split)"}
PACE_QUANTITIES = {"lap": "Race pace, lap gap", "sectors": "Race pace, sector gaps"}


def _summaries(df: pd.DataFrame, key: str, groups: dict) -> dict:
    out = {}
    for name in groups:
        sel = df[key] == name if name != "sectors" else df[key].isin(["s1", "s2", "s3"])
        s = cv.summary(df[sel].z)
        out[name] = s | {"calibrated": cv.calibrated(s)}
    return out


def run(quick: bool = False) -> dict:
    """Grip on synthetic races with every confounder (and on clean laps, which the model-error term rests on);
    race pace on a 20-car field as close at the front as Barcelona's, with car-specific wear and stint offsets."""
    n_grip, n_clean, n_pace = (4, 3, 10) if quick else (30, 12, 40)
    grip_kw = {"laps": 25} if quick else {}
    grip_real = grip_bench.coverage(range(100, 100 + n_grip), **grip_kw)
    grip_clean = grip_bench.coverage(range(200, 200 + n_clean), grip_bench.CLEAN, **grip_kw)
    field = pace_bench.field()
    pace_real = pace_bench.coverage(range(100, 100 + n_pace), cars=field)
    return {
        "grip": {"confounders": _summaries(grip_real, "param", GRIP_QUANTITIES),
                 "clean": _summaries(grip_clean, "param", GRIP_QUANTITIES),
                 "races": n_grip, "teams": int(grip_real.team.nunique())},
        "pace": {"confounders": _summaries(pace_real, "param", PACE_QUANTITIES),
                 "races": n_pace, "cars": len(field)},
    }


def save(results: dict, commit: str) -> Path:
    doc = {"commit": commit, "generated_utc": datetime.now(UTC).strftime("%Y-%m-%d %H:%M")} | results
    RESULTS.write_text(json.dumps(doc, indent=1) + "\n")
    return RESULTS


def load() -> dict | None:
    return json.loads(RESULTS.read_text()) if RESULTS.exists() else None


def session_rows(results: dict | None, grip_rel: pd.DataFrame, pace_cars: pd.DataFrame, pace_ref: str) -> list[dict]:
    """One row per reported quantity: what the bench says of its intervals, and what this session resolves."""
    rows = []

    def add(model, name, label, bench, est, se, unit):
        ok = bool(bench and bench["calibrated"])
        spread = float(pd.Series(est).std()) if len(est) > 1 else 0.0
        rows.append({"model": model, "quantity": name, "label": label, "unit": unit,
                     "bench_cover_95": None if not bench else bench["cover_95"],
                     "bench_sd_z": None if not bench else bench["sd_z"], "calibrated": ok,
                     "status": cv.resolution(est, se, ok), "median_se": float(pd.Series(se).median()),
                     "spread": spread})

    g = (results or {}).get("grip", {}).get("confounders", {})
    for q, label in GRIP_QUANTITIES.items():
        add("S3", q, label, g.get(q), grip_rel[f"{q}_pct"].to_numpy(), grip_rel[f"{q}_se"].to_numpy(), "%")
    p = (results or {}).get("pace", {}).get("confounders", {})
    others = pace_cars[pace_cars.driver != pace_ref]
    add("pace", "lap", PACE_QUANTITIES["lap"], p.get("lap"), others.lap.to_numpy(), others.lap_se.to_numpy(), "s")
    est = pd.concat([others[s] for s in ("s1", "s2", "s3")]).to_numpy()
    se = pd.concat([others[f"{s}_se"] for s in ("s1", "s2", "s3")]).to_numpy()
    add("pace", "sectors", PACE_QUANTITIES["sectors"], p.get("sectors"), est, se, "s")
    return rows
