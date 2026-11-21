"""Test bench for the pace model: a synthetic race with known per-car sector gaps, tyre, fuel and traffic effects,
lap-to-lap noise and a few wrecked laps, put through the same estimator as a real session."""

import numpy as np
import pandas as pd

from ..models import pace

CARS = {"AAA": (0.00, 0.00, 0.00), "BBB": (-0.06, 0.18, 0.05), "CCC": (0.10, 0.25, -0.08),
        "DDD": (0.35, 0.80, 0.50), "EEE": (0.50, 1.20, 0.70), "FFF": (0.20, 0.40, 0.30)}
BASE = (21.0, 29.0, 27.0)
COMPOUND = {"HARD": ((0.0, 0.0, 0.0), 0.035), "MEDIUM": ((-0.15, -0.20, -0.15), 0.05),
            "SOFT": ((-0.30, -0.40, -0.30), 0.065)}
FUEL_S_PER_LAP = (-0.015, -0.025, -0.020)
TRAFFIC = ((-0.02, 0.15, 0.07), (0.0, 0.02, 0.0))  # under 1 s, 1 to 2 s
NOISE_S = 0.15
LAPS = 60
TOLERANCE_S = 0.06


def race(seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for k, (car, gaps) in enumerate(CARS.items()):
        stops = sorted(rng.choice(np.arange(15, LAPS - 10), 2, replace=False))
        stints = np.searchsorted(stops, np.arange(1, LAPS + 1), side="left")
        compounds = rng.permutation(list(COMPOUND))
        for lap in range(1, LAPS + 1):
            stint = int(stints[lap - 1])
            compound = compounds[stint % 3]
            age = lap - (0 if stint == 0 else stops[stint - 1])
            gap = float(rng.exponential(3.0))
            offsets, slope = COMPOUND[compound]
            band = 0 if gap < pace.TRAFFIC_BANDS_S[0] else 1 if gap < pace.TRAFFIC_BANDS_S[1] else None
            times = []
            for s in range(3):
                t = BASE[s] + gaps[s] + offsets[s] + slope * age / 3 + FUEL_S_PER_LAP[s] * lap
                t += TRAFFIC[band][s] if band is not None else 0.0
                t += rng.normal(0, NOISE_S)
                times.append(t)
            if rng.random() < 0.03:
                times[int(rng.integers(0, 3))] += float(rng.uniform(1.5, 4.0))  # a lock-up or a backmarker
            rows.append({"driver": car, "driver_number": k + 1, "team": f"Team {car}", "lap_number": lap,
                         "compound": compound, "tyre_age": age, "s1": times[0], "s2": times[1], "s3": times[2],
                         "gap_ahead": gap, "green": True})
    return pd.DataFrame(rows)


def recovery(seed: int = 3) -> pd.DataFrame:
    """True and recovered gap to the fastest car, per car and sector [s]."""
    p = pace.sector_pace(race(seed), n_boot=60)
    ref = p.reference
    out = []
    for r in p.cars.itertuples():
        for s in range(3):
            truth = CARS[r.driver][s] - CARS[ref][s]
            got = getattr(r, f"s{s + 1}")
            out.append({"car": r.driver, "sector": s + 1, "true_s": truth, "recovered_s": got,
                        "error_s": got - truth, "se_s": getattr(r, f"s{s + 1}_se")})
    return pd.DataFrame(out)
