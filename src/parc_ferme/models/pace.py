"""Race pace per car, sector by sector, against the session's fastest car.

Each green lap's three sector times are fitted, one sector at a time, with an effect and a tyre-wear slope per car and
shared terms for what changes from lap to lap but isn't the car: tyre compound, tyre age (a slope per compound), lap
number (fuel burn and track evolution) and traffic. Traffic is the smallest gap to the car ahead during the lap, in
three bands: under 1 s, 1 to 2 s, and clear. Gaps are the time each car lost per lap to the fastest car, at the race's
median tyre age on the reference compound: cars wear their tyres at different rates, so a gap on new tyres would be an
extrapolation.

Laps within a stint share an offset the terms above don't explain (a tyre set, an engine mode): at Barcelona it is
about 0.13 s a lap, twice what lap-to-lap noise accounts for. Treating laps as independent understates every
uncertainty, so the fit is generalised least squares with a random offset per stint, whose size is estimated from the
residuals. The identifiability bench (bench/pace.py) checks that the resulting intervals cover the truth.

Gaps are measured from the car that looks fastest, which is usually the one whose estimate got lucky, so every gap
would come out too large (the winner's curse; at Barcelona-like closeness about half a standard error). The bias is
estimated by parametric bootstrap and taken off.

Pace is per car rather than per team: two drivers of one team can have very different races, and pooling them
would rank the team on its average.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

SECTORS = ("s1", "s2", "s3")
MIN_LAPS = 10
SELECTION_DRAWS = 4000
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


def _design(laps: pd.DataFrame, cars: list, comps: list, steepness: dict | None = None) -> np.ndarray:
    """Columns: an effect per car, a wear slope per car but the first, compound offsets, a wear slope per compound,
    lap number, and the two traffic bands. A car's own wear scales with each compound's `steepness` (its slope over
    the mean compound's): a car hard on its tyres is harder on every compound, in proportion."""
    lo, hi = TRAFFIC_BANDS_S
    age = laps.tyre_age.to_numpy(float)
    scaled = age * (laps.compound.map(steepness).to_numpy(float) if steepness else 1.0)
    cols = [np.column_stack([laps.driver == c for c in cars]).astype(float)]
    if len(cars) > 1:
        cols.append(np.column_stack([(laps.driver == c).to_numpy() * scaled for c in cars[1:]]))
    if len(comps) > 1:
        cols.append(np.column_stack([laps.compound == c for c in comps[1:]]).astype(float))
    cols.append(np.column_stack([(laps.compound == c).to_numpy() * age for c in comps]))
    cols.append(laps.lap_number.to_numpy(float)[:, None])
    cols.append(np.column_stack([laps.gap_ahead < lo, (laps.gap_ahead >= lo) & (laps.gap_ahead < hi)]).astype(float))
    return np.hstack(cols)


def compound_steepness(laps: pd.DataFrame, cars: list, comps: list) -> dict:
    """Each compound's wear slope over the mean compound's, from a first lap-time fit in which each car's extra wear
    is the same on every compound. Falls back to 1 where a slope isn't positive."""
    if len(comps) < 2:
        return {c: 1.0 for c in comps}
    coef = _robust_lstsq(_design(laps, cars, comps), laps[list(SECTORS)].sum(axis=1).to_numpy(float))
    start = len(cars) + max(len(cars) - 1, 0) + len(comps) - 1
    slopes = coef[start:start + len(comps)]
    mean = float(np.mean(slopes))
    return {c: (float(b) / mean if mean > 0 and b > 0 else 1.0) for c, b in zip(comps, slopes, strict=True)}


def _robust_keep(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Rows within OUTLIER_MADS robust deviations of a first least-squares fit (drops a lock-up, a slow lap behind
    a lapped car)."""
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    r = y - x @ coef
    return np.abs(r - np.median(r)) <= OUTLIER_MADS * 1.4826 * np.median(np.abs(r - np.median(r)))


def _robust_lstsq(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    keep = _robust_keep(x, y)
    coef, *_ = np.linalg.lstsq(x[keep], y[keep], rcond=None)
    return coef


def _gls_parts(x: np.ndarray, y: np.ndarray, inv: np.ndarray, n: np.ndarray, ratio: float):
    """Generalised least squares with group covariance s2 (I + ratio 11'), whose inverse is (I - a 11') / s2 with
    a = ratio / (1 + n ratio). Returns coefficients, X'WX (W = s2 V^-1) and the weighted residual sum r'Wr."""
    a = ratio / (1.0 + n * ratio)
    sx = np.zeros((len(n), x.shape[1]))
    np.add.at(sx, inv, x)
    sy = np.bincount(inv, y, minlength=len(n))
    xwx = x.T @ x - (sx.T * a) @ sx
    xwy = x.T @ y - (sx.T * a) @ sy
    coef = np.linalg.pinv(xwx) @ xwy
    r = y - x @ coef
    sr = np.bincount(inv, r, minlength=len(n))
    return coef, xwx, float(r @ r - np.sum(a * sr ** 2))


def gls_random_groups(x: np.ndarray, y: np.ndarray, groups: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    """Least squares with a random offset per group (a stint), after dropping outliers.

    The variances are restricted maximum likelihood: each car's own effect and wear slope absorb most of what its
    two or three stints differ by, so a variance read off the least-squares residuals comes out far too small.
    Returns the coefficients, their covariance and the lap and group variances."""
    from scipy.optimize import minimize_scalar

    keep = _robust_keep(x, y)
    x, y, groups = x[keep], y[keep], np.asarray(groups)[keep]
    _, inv = np.unique(groups, return_inverse=True)
    n = np.bincount(inv).astype(float)
    rank = np.linalg.matrix_rank(x)
    dof = len(y) - rank

    def neg_reml(log_ratio: float) -> float:
        ratio = float(np.exp(log_ratio))
        _, xwx, rwr = _gls_parts(x, y, inv, n, ratio)
        eig = np.linalg.eigvalsh(xwx)
        logdet = float(np.sum(np.log(eig[eig > eig.max() * 1e-10])))
        return 0.5 * (dof * np.log(rwr / dof) + np.sum(np.log1p(n * ratio)) + logdet)

    best = minimize_scalar(neg_reml, bounds=(np.log(1e-6), np.log(1e3)), method="bounded")
    ratio = float(np.exp(best.x)) if best.fun < neg_reml(np.log(1e-6)) else 0.0
    coef, xwx, rwr = _gls_parts(x, y, inv, n, ratio)
    s2 = rwr / dof
    return coef, s2 * np.linalg.pinv(xwx), {"lap_var": s2, "stint_var": s2 * ratio}


@dataclass
class Pace:
    cars: pd.DataFrame
    reference: str
    traffic: pd.DataFrame
    holdout: dict
    excluded: list
    ref_age: int = 0
    ref_compound: str = ""
    stint_sd_s: float = 0.0
    selection_bias_s: float = 0.0


def selection_bias(level: np.ndarray, cov: np.ndarray, draws: int = SELECTION_DRAWS, seed: int = 0) -> float:
    """How much the car that looks fastest flatters itself, on average [s, negative]: gaps measured from it come out
    too large by this much (the winner's curse). Parametric bootstrap: draw lap levels from their fitted
    uncertainty, take the fastest-looking car of each draw, and average how far its draw is below its fit."""
    rng = np.random.default_rng(seed)
    w, v = np.linalg.eigh((cov + cov.T) / 2)
    sims = level + (rng.standard_normal((draws, len(level))) * np.sqrt(np.clip(w, 0, None))) @ v.T
    pick = sims.argmin(1)
    return float(np.mean(sims[np.arange(draws), pick] - level[pick]))


def _gap_contrasts(k: int, p: int, ref: int, age: float) -> np.ndarray:
    """[k, p] rows that give each car's effect at tyre age `age`, less the reference car's."""
    out = np.zeros((k, p))
    for c in range(k):
        for car, sign in ((c, 1.0), (ref, -1.0)):
            out[c, car] += sign
            if car > 0:
                out[c, k + car - 1] += sign * age
    return out


def sector_pace(laps: pd.DataFrame) -> Pace:
    """`laps` is the lap table (warmup.laps) with a gap_ahead column. Uses green laps with all three sector
    times and a gap reading; cars with fewer than MIN_LAPS such laps are left out and listed."""
    use = laps[laps.green & laps[list(SECTORS)].notna().all(axis=1) & laps.gap_ahead.notna()].copy()
    counts = use.groupby("driver").size()
    cars = sorted(counts[counts >= MIN_LAPS].index)
    excluded = sorted(counts[counts < MIN_LAPS].index)
    use = use[use.driver.isin(cars)]
    comps = sorted(use.compound.unique())
    k = len(cars)
    age = float(np.median(use.tyre_age))
    steep = compound_steepness(use, cars, comps)
    x = _design(use, cars, comps, steep)
    stint = use.stint_number if "stint_number" in use else pd.Series(0, index=use.index)
    groups = (use.driver.astype(str) + "/" + stint.astype(str)).to_numpy()

    fits = {sector: gls_random_groups(x, use[sector].to_numpy(float), groups) for sector in SECTORS}
    lap_coef, lap_cov, lap_var = gls_random_groups(x, use[list(SECTORS)].sum(axis=1).to_numpy(float), groups)
    wear_age = age * steep[comps[0]]
    to_first = _gap_contrasts(k, x.shape[1], 0, wear_age)
    level = to_first @ lap_coef
    ref = int(np.argmin(level))
    contrast = _gap_contrasts(k, x.shape[1], ref, wear_age)
    flatter = selection_bias(level, to_first @ lap_cov @ to_first.T)

    first = use.drop_duplicates("driver").set_index("driver")
    table = pd.DataFrame({"driver": cars, "driver_number": [int(first.driver_number[c]) for c in cars],
                          "team": [first.team[c] for c in cars], "laps": [int(counts[c]) for c in cars]})
    ref_var = {sector: float(to_first[ref] @ cov @ to_first[ref]) for sector, (_, cov, _) in fits.items()}
    others = np.arange(k) != ref
    for sector, (coef, cov, _) in fits.items():
        share = ref_var[sector] / max(sum(ref_var.values()), 1e-12)
        table[sector] = contrast @ coef + others * flatter * share
        table[sector + "_se"] = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", contrast, cov, contrast), 0.0))
    table["lap"] = table[list(SECTORS)].sum(axis=1)
    table["lap_se"] = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", contrast, lap_cov, contrast), 0.0))
    table = table.sort_values("lap").reset_index(drop=True)

    names = [f"under {TRAFFIC_BANDS_S[0]:g} s", f"{TRAFFIC_BANDS_S[0]:g} to {TRAFFIC_BANDS_S[1]:g} s"]
    tr = pd.DataFrame({"gap": names})
    for sector, (coef, cov, _) in fits.items():
        tr[sector] = coef[-2:]
        tr[sector + "_se"] = np.sqrt(np.diag(cov)[-2:])
    tr["lap"] = lap_coef[-2:]
    tr["lap_se"] = np.sqrt(np.diag(lap_cov)[-2:])
    tr["laps"] = [int((use.gap_ahead < TRAFFIC_BANDS_S[0]).sum()),
                  int(((use.gap_ahead >= TRAFFIC_BANDS_S[0]) & (use.gap_ahead < TRAFFIC_BANDS_S[1])).sum())]
    return Pace(table, cars[ref], tr, holdout(use, cars, comps), excluded, int(round(age)), comps[0],
                float(np.sqrt(lap_var["stint_var"])), float(flatter))


def holdout(laps: pd.DataFrame, cars: list, comps: list) -> dict:
    """Fit on odd-numbered laps, predict the lap times of the even-numbered ones. The baseline predicts each car's
    median odd-lap time. Errors are median absolute errors [s]: the model has to beat the baseline to earn its terms."""
    train = laps[laps.lap_number % 2 == 1]
    test = laps[(laps.lap_number % 2 == 0) & laps.driver.isin(train.driver.unique())]
    steep = compound_steepness(train, cars, comps)
    x_tr, x_te = _design(train, cars, comps, steep), _design(test, cars, comps, steep)
    pred = sum(x_te @ _robust_lstsq(x_tr, train[sector].to_numpy(float)) for sector in SECTORS)
    actual = test[list(SECTORS)].sum(axis=1).to_numpy()
    base = test.driver.map(train[list(SECTORS)].sum(axis=1).groupby(train.driver).median()).to_numpy()
    return {"laps": int(len(test)), "model_err_s": float(np.median(np.abs(actual - pred))),
            "baseline_err_s": float(np.median(np.abs(actual - base)))}
