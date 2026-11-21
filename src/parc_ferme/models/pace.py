"""Race pace per car, sector by sector, against the session's fastest car.

Each green lap's three sector times are fitted, one sector at a time, with an effect per car and shared terms for
what changes from lap to lap but isn't the car: tyre compound, tyre age (a slope per compound), lap number (fuel burn
and track evolution) and traffic. Traffic is the smallest gap to the car ahead during the lap, in three bands: under
1 s, 1 to 2 s, and clear. The car effects, less the fastest car's, are the time each car lost per lap in each sector.

Pace is per car rather than per team: two drivers of one team can have very different races, and pooling them
would rank the team on its average.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

SECTORS = ("s1", "s2", "s3")
MIN_LAPS = 10
TRAFFIC_BANDS_S = (1.0, 2.0)
OUTLIER_MADS = 4.0


def gap_ahead(laps: pd.DataFrame, intervals: pd.DataFrame) -> np.ndarray:
    """Smallest interval to the car ahead [s] during each lap, from the timing feed's interval table (about one
    reading every 5 s per car). NaN where the feed has no reading inside the lap."""
    by = {d: g.sort_values("date") for d, g in intervals.groupby("driver_number")}
    out = np.full(len(laps), np.nan)
    for i, r in enumerate(laps.itertuples()):
        g = by.get(r.driver_number)
        if g is None or pd.isna(r.lap_time):
            continue
        end = r.date_start + pd.Timedelta(seconds=r.lap_time)
        inside = g.interval[(g.date >= r.date_start) & (g.date <= end)]
        if len(inside):
            out[i] = float(inside.min())
    return out


def _design(laps: pd.DataFrame, cars: list, comps: list) -> np.ndarray:
    lo, hi = TRAFFIC_BANDS_S
    cols = [np.column_stack([laps.driver == c for c in cars]).astype(float)]
    if len(comps) > 1:
        cols.append(np.column_stack([laps.compound == c for c in comps[1:]]).astype(float))
    cols.append(np.column_stack([(laps.compound == c) * laps.tyre_age for c in comps]).astype(float))
    cols.append(laps.lap_number.to_numpy(float)[:, None])
    cols.append(np.column_stack([laps.gap_ahead < lo, (laps.gap_ahead >= lo) & (laps.gap_ahead < hi)]).astype(float))
    return np.hstack(cols)


def _robust_lstsq(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Least squares, refitted once without rows more than OUTLIER_MADS robust deviations out (a lock-up, a slow
    lap behind a lapped car)."""
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    r = y - x @ coef
    keep = np.abs(r - np.median(r)) <= OUTLIER_MADS * 1.4826 * np.median(np.abs(r - np.median(r)))
    coef, *_ = np.linalg.lstsq(x[keep], y[keep], rcond=None)
    return coef


def _fit(laps: pd.DataFrame, cars: list, comps: list) -> tuple[np.ndarray, np.ndarray]:
    """Per sector: car effects [n_cars, 3] and the two traffic terms [3, 2]."""
    x = _design(laps, cars, comps)
    coefs = [_robust_lstsq(x, laps[sector].to_numpy(float)) for sector in SECTORS]
    return np.array([c[:len(cars)] for c in coefs]).T, np.array([c[-2:] for c in coefs])


@dataclass
class Pace:
    cars: pd.DataFrame
    reference: str
    traffic: pd.DataFrame
    holdout: dict
    excluded: list


def sector_pace(laps: pd.DataFrame, n_boot: int = 200, seed: int = 0) -> Pace:
    """`laps` is the lap table (warmup.laps) with a gap_ahead column. Uses green laps with all three sector
    times and a gap reading; cars with fewer than MIN_LAPS such laps are left out and listed. Standard errors are a
    bootstrap over laps."""
    use = laps[laps.green & laps[list(SECTORS)].notna().all(axis=1) & laps.gap_ahead.notna()].copy()
    counts = use.groupby("driver").size()
    cars = sorted(counts[counts >= MIN_LAPS].index)
    excluded = sorted(counts[counts < MIN_LAPS].index)
    use = use[use.driver.isin(cars)]
    comps = sorted(use.compound.unique())

    effects, traffic = _fit(use, cars, comps)
    ref = int(np.argmin(effects.sum(1)))
    rng = np.random.default_rng(seed)
    boot_eff, boot_tr = [], []
    for _ in range(n_boot):
        b = use.iloc[rng.integers(0, len(use), len(use))]
        if b.driver.nunique() < len(cars):
            continue
        if b.compound.nunique() < len(comps):
            continue
        e, tr = _fit(b, cars, comps)
        boot_eff.append(e - e[ref])
        boot_tr.append(tr)
    boot_eff, boot_tr = np.array(boot_eff), np.array(boot_tr)

    delta = effects - effects[ref]
    first = use.drop_duplicates("driver").set_index("driver")
    table = pd.DataFrame({"driver": cars, "driver_number": [int(first.driver_number[c]) for c in cars],
                          "team": [first.team[c] for c in cars], "laps": [int(counts[c]) for c in cars]})
    for k, sector in enumerate(SECTORS):
        table[sector] = delta[:, k]
        table[sector + "_se"] = boot_eff[:, :, k].std(0)
    table["lap"] = delta.sum(1)
    table["lap_se"] = boot_eff.sum(2).std(0)
    table = table.sort_values("lap").reset_index(drop=True)

    names = [f"under {TRAFFIC_BANDS_S[0]:g} s", f"{TRAFFIC_BANDS_S[0]:g} to {TRAFFIC_BANDS_S[1]:g} s"]
    tr = pd.DataFrame({"gap": names})
    for k, sector in enumerate(SECTORS):
        tr[sector] = traffic[k]
        tr[sector + "_se"] = boot_tr[:, k, :].std(0)
    tr["lap"] = traffic.sum(0)
    tr["lap_se"] = boot_tr.sum(1).std(0)
    tr["laps"] = [int((use.gap_ahead < TRAFFIC_BANDS_S[0]).sum()),
                  int(((use.gap_ahead >= TRAFFIC_BANDS_S[0]) & (use.gap_ahead < TRAFFIC_BANDS_S[1])).sum())]
    return Pace(table, cars[ref], tr, holdout(use, cars, comps), excluded)


def holdout(laps: pd.DataFrame, cars: list, comps: list) -> dict:
    """Fit on odd-numbered laps, predict the lap times of the even-numbered ones. The baseline predicts each car's
    median odd-lap time. Errors are median absolute errors [s]: the model has to beat the baseline to earn its terms."""
    train = laps[laps.lap_number % 2 == 1]
    test = laps[(laps.lap_number % 2 == 0) & laps.driver.isin(train.driver.unique())]
    x_tr, x_te = _design(train, cars, comps), _design(test, cars, comps)
    pred = sum(x_te @ _robust_lstsq(x_tr, train[sector].to_numpy(float)) for sector in SECTORS)
    actual = test[list(SECTORS)].sum(axis=1).to_numpy()
    base = test.driver.map(train[list(SECTORS)].sum(axis=1).groupby(train.driver).median()).to_numpy()
    return {"laps": int(len(test)), "model_err_s": float(np.median(np.abs(actual - pred))),
            "baseline_err_s": float(np.median(np.abs(actual - base)))}
