"""Test bench for the pace model: a synthetic race with known per-car sector gaps, tyre, fuel and traffic effects,
lap-to-lap noise and a few wrecked laps, put through the same estimator as a real session.

`coverage` is the identifiability bench: the race repeated over seeds with two effects the model doesn't carry,
wear that differs from car to car and an offset that holds for a whole stint (a tyre set, an engine mode), to check
that the stated uncertainties cover the truth as often as they claim."""

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


WEAR_SD = 0.3  # car-to-car spread in wear rate, relative
STINT_SD_S = 0.07  # per sector, held for a whole stint: Barcelona shows about 0.13 s a lap


# Barcelona's lap gaps to Hamilton (s): a field whose front runners are as close as a real one's, for coverage.
BARCELONA_GAPS = (0.0, 0.16, 0.23, 0.29, 0.43, 0.62, 0.68, 0.81, 0.95, 1.02, 1.10, 1.18, 1.25, 1.31, 1.40, 1.52, 1.60,
                  1.71, 1.85, 2.0)


def field(gaps=BARCELONA_GAPS, seed: int = 0) -> dict:
    """Cars with the given lap gaps, split unevenly across the three sectors."""
    rng = np.random.default_rng(seed)
    out = {}
    for k, g in enumerate(gaps):
        share = rng.dirichlet((4.0, 4.0, 4.0))
        out[f"C{k + 1:02d}"] = tuple(float(x) for x in g * share)
    return out


def race(seed: int = 3, wear_sd: float = 0.0, stint_sd: float = 0.0, cars: dict | None = None) -> pd.DataFrame:
    cars = CARS if cars is None else cars
    rng = np.random.default_rng(seed)
    rows, wears = [], {}
    for k, (car, gaps) in enumerate(cars.items()):
        stops = sorted(rng.choice(np.arange(15, LAPS - 10), 2, replace=False))
        stints = np.searchsorted(stops, np.arange(1, LAPS + 1), side="left")
        compounds = rng.permutation(list(COMPOUND))
        wear = float(np.exp(rng.normal(0, wear_sd))) if wear_sd else 1.0
        stint_offset = rng.normal(0, stint_sd, (3, 3)) if stint_sd else np.zeros((3, 3))
        for lap in range(1, LAPS + 1):
            stint = int(stints[lap - 1])
            compound = compounds[stint % 3]
            age = lap - (0 if stint == 0 else stops[stint - 1])
            gap = float(rng.exponential(3.0))
            offsets, slope = COMPOUND[compound]
            band = 0 if gap < pace.TRAFFIC_BANDS_S[0] else 1 if gap < pace.TRAFFIC_BANDS_S[1] else None
            times = []
            for s in range(3):
                t = BASE[s] + gaps[s] + offsets[s] + wear * slope * age / 3 + FUEL_S_PER_LAP[s] * lap
                t += stint_offset[stint, s]
                t += TRAFFIC[band][s] if band is not None else 0.0
                t += rng.normal(0, NOISE_S)
                times.append(t)
            if rng.random() < 0.03:
                times[int(rng.integers(0, 3))] += float(rng.uniform(1.5, 4.0))  # a lock-up or a backmarker
            rows.append({"driver": car, "driver_number": k + 1, "team": f"Team {car}", "lap_number": lap,
                         "stint_number": stint + 1, "compound": compound, "tyre_age": age,
                         "s1": times[0], "s2": times[1], "s3": times[2], "gap_ahead": gap, "green": True})
        wears[car] = wear
    out = pd.DataFrame(rows)
    out.attrs |= {"wear": wears, "cars": cars}
    return out


def truth(laps: pd.DataFrame, p: pace.Pace, car: str) -> dict:
    """True gap of `car` to the reference car, per sector and lap, at the model's reference tyre age and compound."""
    wear = laps.attrs.get("wear", {})
    cars = laps.attrs.get("cars", CARS)
    slope = COMPOUND[p.ref_compound][1] / 3
    out = {}
    for k in range(3):
        extra = (wear.get(car, 1.0) - wear.get(p.reference, 1.0)) * slope * p.ref_age
        out[f"s{k + 1}"] = cars[car][k] - cars[p.reference][k] + extra
    out["lap"] = sum(out.values())
    return out


def recovery(seed: int = 3) -> pd.DataFrame:
    """True and recovered gap to the fastest car, per car and sector [s]."""
    laps = race(seed)
    p = pace.sector_pace(laps)
    out = []
    for r in p.cars.itertuples():
        t = truth(laps, p, r.driver)
        for s in range(3):
            got = getattr(r, f"s{s + 1}")
            out.append({"car": r.driver, "sector": s + 1, "true_s": t[f"s{s + 1}"], "recovered_s": got,
                        "error_s": got - t[f"s{s + 1}"], "se_s": getattr(r, f"s{s + 1}_se")})
    return pd.DataFrame(out)


def coverage(seeds, wear_sd: float = WEAR_SD, stint_sd: float = STINT_SD_S, cars: dict | None = None) -> pd.DataFrame:
    """For every seed, car and gap (each sector and the lap): estimate, stated standard error, truth and
    z = error / SE. Gaps are to the car the model ranks fastest, whose own row is left out."""
    out = []
    for seed in seeds:
        laps = race(seed, wear_sd, stint_sd, cars)
        p = pace.sector_pace(laps)
        for r in p.cars.itertuples():
            if r.driver == p.reference:
                continue
            for param, t in truth(laps, p, r.driver).items():
                est, se = getattr(r, param), getattr(r, f"{param}_se")
                out.append({"seed": seed, "car": r.driver, "param": param, "est": est, "se": se, "truth": t,
                            "z": (est - t) / se})
    return pd.DataFrame(out)
