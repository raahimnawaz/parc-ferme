"""Drag from the shape of the speed trace along a full-throttle run.

The window balance in `energy` only sees each window's total work, so any drag area can be
balanced by some electric power. Along a run the two have different shapes: drag power grows
with the cube of speed, while the power unit holds a level, or a fraction of the rules'
deployment cap, and may change level once (the point where deployment ends or harvesting
starts). Each run's power profile is profiled out by least squares; the drag area is shared
by every run of a car. Cumulative work is fitted rather than acceleration, so nothing is
differentiated from 4 Hz speed. A gear change can cost a little work, so each one gets a
free step in the balance.
"""

import numpy as np
from scipy import stats

from ..core.car import G

GRID = np.arange(0.3, 1.8001, 0.0025)
MIN_SIDE = 3          # samples on each side of a power change
MIN_SAMPLES = 10
MIN_SECONDS = 3.0


def _cumulative(t, x):
    return np.r_[0., np.cumsum(np.diff(t) * (x[1:] + x[:-1]) / 2)]


def _basis(x):
    u, s, _ = np.linalg.svd(x, full_matrices=False)
    return u[:, s > s[0] * 1e-9]


def run_curve(t, v, z, car, gear=None, wind=0.):
    """Concentrated negative log-likelihood of each CdA on GRID for one run.

    Work balance from the first sample: kinetic + potential + rolling work + CdA × aero work
    equals a constant plus the work of the power profile. Profiles: a level plus a fraction
    of the deployment cap, or that until one change point and a new level after it.
    """
    m = car.mass
    work = m * v * v / 2 + m * G * (z - z[0]) + m * G * car.crr * _cumulative(t, v)
    aero = car.rho / 2 * _cumulative(t, (v + wind) ** 2 * v)
    elapsed = t - t[0]
    cap = _cumulative(t, car.mguk_limit_w(v) / car.mguk_w)
    ones = np.ones(len(t))
    shifts = [] if gear is None else [(t >= t[k]).astype(float) for k in np.flatnonzero(np.diff(gear)) + 1]
    designs = [np.column_stack([ones, elapsed, cap, *shifts])]
    for k in range(MIN_SIDE, len(t) - MIN_SIDE):
        designs.append(np.column_stack([ones, elapsed, np.minimum(cap, cap[k]), np.maximum(0., t - t[k]), *shifts]))
    best = np.full(len(GRID), np.inf)
    for x in designs:
        q = _basis(x)
        r0, ra = work - q @ (q.T @ work), aero - q @ (q.T @ aero)
        best = np.minimum(best, r0 @ r0 + 2 * GRID * (r0 @ ra) + GRID ** 2 * (ra @ ra))
    return len(t) / 2 * np.log(np.maximum(best, 1e-9))


def runs(samples, rows):
    """Merge consecutive full-throttle windows of one zone into runs; return their sample index ranges."""
    out, current = [], None
    for row in sorted((r for r in rows if r["phase"] == "full throttle"), key=lambda r: r["start_s"]):
        if current and row["zone"] == current["zone"] and np.isclose(row["start_s"], current["end_s"]):
            current["end_s"] = row["end_s"]
        else:
            current = dict(zone=row["zone"], start_s=row["start_s"], end_s=row["end_s"])
            out.append(current)
    t = samples.t.to_numpy()
    kept = []
    for run in out:
        idx = np.flatnonzero((t >= run["start_s"] - 1e-9) & (t <= run["end_s"] + 1e-9))
        if len(idx) >= MIN_SAMPLES and t[idx[-1]] - t[idx[0]] >= MIN_SECONDS:
            kept.append(run | dict(index=idx))
    return kept


def _argmin(curve):
    return GRID[np.argmin(curve)]


def fit(curves, laps, zones, draws=400, seed=0):
    """Pooled estimate. The half-width combines a lap-block bootstrap (noise) with a
    leave-one-zone-out jackknife at Student's t for the number of zones (a deployment pattern
    that differs by straight biases each straight differently). Clipped to GRID."""
    curves, laps, zones = np.asarray(curves), np.asarray(laps), np.asarray(zones)
    unique, inverse = np.unique(laps, return_inverse=True)
    per_lap = np.zeros((len(unique), len(GRID)))
    np.add.at(per_lap, inverse, curves)
    estimate = _argmin(per_lap.sum(axis=0))
    weights = np.random.default_rng(seed).multinomial(len(unique), np.full(len(unique), 1 / len(unique)), size=draws)
    boot = GRID[np.argmin(weights @ per_lap, axis=1)]
    half = 1.96 * np.std(boot)
    present = np.unique(zones)
    if len(present) > 1:
        loo = np.array([_argmin(curves[zones != zone].sum(axis=0)) for zone in present])
        jack = np.sqrt((len(loo) - 1) / len(loo) * np.sum((loo - loo.mean()) ** 2))
        half = np.hypot(half, stats.t.ppf(.975, len(loo) - 1) * jack)
    low, high = max(GRID[0], estimate - half), min(GRID[-1], estimate + half)
    if estimate in (GRID[0], GRID[-1]):
        low, high = GRID[0], GRID[-1]
    return float(estimate), float(low), float(high)
