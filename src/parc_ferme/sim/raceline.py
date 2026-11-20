"""Minimum-time racing line: lateral offsets chosen to minimise the lap sim's own lap time.

A small penalty on steering activity (curvature rate) keeps the line from drifting where lap time is flat, as on a
straight; it is scaled to 0.02 s on the starting line, so it decides nothing that lap time decides.

The minimum-curvature line maximises the radius through every corner, which ignores that the car's acceleration
is limited. Where a corner leads onto a straight, the faster line gives up some minimum speed for a later apex and
an earlier, straighter exit. This optimises the offset directly against the QSS lap time, starting from the
minimum-curvature line, so it can only match or improve on it.
"""

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import CubicSpline

from ..core.car import Car
from ..core.track import (
    LINE_SMOOTH_M,
    Track,
    line_from_offsets,
    min_curvature_offsets,
    offset_bounds,
    resample_closed,
    smoothed_geometry,
)
from .lapsim import deploy_threshold, kernel_args, qss_speed

PENALTY_S_PER_M2 = 50.0
STEERING_WEIGHT_S = 0.02


@dataclass
class LineResult:
    line: Track
    offsets: np.ndarray
    lap_time_s: float
    start_lap_time_s: float
    evaluations: int


def periodic_basis(n: int, spacing_pts: int) -> np.ndarray:
    """n x m matrix mapping m control values to a periodic cubic spline sampled at n points."""
    knots = np.arange(0, n, spacing_pts, dtype=float)
    m = len(knots)
    eye = np.eye(m)
    t = np.arange(n, dtype=float)
    return np.column_stack([CubicSpline(np.r_[knots, n], np.r_[eye[j], eye[j][0]], bc_type="periodic")(t)
                            for j in range(m)])


class OffsetLapTime:
    """Lap time of the path at offsets `a` from a reference track, built exactly as `line_from_offsets` builds the
    final line (even arc-length resampling, then smoothing) but with a fixed point count so it varies smoothly."""

    def __init__(self, ref: Track, car: Car, zones: np.ndarray, v_star: float, n: int,
                 smooth_m: float = LINE_SMOOTH_M):
        self.ref, self.n, self.smooth_m, self.v_star = ref, n, smooth_m, v_star
        self.nx, self.ny = ref.normals()
        self.z = np.zeros(len(ref.s)) if ref.z is None else ref.z
        self.zones = zones.astype(float)
        self.car = car

    def speeds(self, a: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        step, xr, yr, zr, zone = resample_closed(self.ref.x + a * self.nx, self.ref.y + a * self.ny, self.n,
                                                 self.z, self.zones)
        _, _, kappa = smoothed_geometry(xr, yr, step, self.smooth_m)
        ds = np.full(self.n, step)
        grade = (np.roll(zr, -1) - zr) / step
        return qss_speed(np.abs(kappa), grade, ds, *kernel_args(self.car, zone > 0.5), self.v_star), ds, kappa

    def __call__(self, a: np.ndarray) -> float:
        v, ds, _ = self.speeds(a)
        return float(np.sum(2.0 * ds / (v + np.roll(v, -1))))

    def steering_rate(self, a: np.ndarray) -> float:
        """Integral of squared curvature rate along the path [1/m^3]: what a driver feels as steering activity."""
        _, ds, kappa = self.speeds(a)
        return float(np.sum((np.roll(kappa, -1) - kappa) ** 2 / ds))


def pattern_search(f, p: np.ndarray, steps=(2.0, 1.0, 0.5, 0.25, 0.1), max_sweeps: int = 8,
                   tol_s: float = 1e-4) -> tuple[np.ndarray, float, int]:
    """Coordinate pattern search: try each control +-h, keep any improvement, shrink h when a sweep stalls.
    Lap time has kinks wherever the speed profile switches between grip, power and braking limits, which stalls
    gradient methods; this needs only function values."""
    fp = f(p)
    evals = 1
    for h in steps:
        for _ in range(max_sweeps):
            improved = False
            for j in range(len(p)):
                for d in (h, -h):
                    q = p.copy()
                    q[j] += d
                    fq = f(q)
                    evals += 1
                    if fq < fp - tol_s:
                        p, fp, improved = q, fq, True
                        break
            if not improved:
                break
    return p, fp, evals


def min_time_line(ref: Track, car: Car, zones: np.ndarray, car_width: float, margin: float = 0.3,
                  spacings_m=(80.0, 40.0, 20.0)) -> LineResult:
    """Start from the minimum-curvature line and refine the offsets against lap time, coarse sections first.
    `zones` is the straight-mode mask on the reference track's points."""
    lo, hi = offset_bounds(ref, car_width, margin)
    a = min_curvature_offsets(ref, car_width, margin)
    start = line_from_offsets(ref, a, "start")
    v_star = deploy_threshold(start, car, np.interp(start.s / start.length, ref.s / ref.length,
                                                    zones.astype(float), period=1.0) > 0.5)
    lap_time = OffsetLapTime(ref, car, zones, v_star, n=len(start.s))
    t0 = lap_time(a)
    steer_w = STEERING_WEIGHT_S / lap_time.steering_rate(a)
    evals = 0
    for spacing in spacings_m:
        basis = periodic_basis(len(ref.s), max(2, int(round(spacing / ref.ds))))
        base = a.copy()

        def objective(p, base=base, basis=basis):
            x = base + basis @ p
            over = np.maximum(x - hi, 0.0) + np.maximum(lo - x, 0.0)
            return (lap_time(x) + steer_w * lap_time.steering_rate(x)
                    + PENALTY_S_PER_M2 * float(np.sum(over * over)))

        p, _, n = pattern_search(objective, np.zeros(basis.shape[1]))
        evals += n
        a = np.clip(base + basis @ p, lo, hi)
    line = line_from_offsets(ref, a, f"{ref.name} min-time")
    return LineResult(line, a, lap_time(a), t0, evals)
