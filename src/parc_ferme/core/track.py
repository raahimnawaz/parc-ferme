"""S1 track model: centreline geometry, the feed-to-track registration, and positions along the lap.

Geometry and the minimum-curvature line are ported from engine-map-pinn, extended with per-point track width,
signed curvature and elevation.
"""

from dataclasses import dataclass, field, replace

import numpy as np
from scipy.optimize import minimize
from scipy.signal import savgol_filter
from scipy.spatial import cKDTree

FEED_UNITS_PER_M = 10.0


def periodic_smooth(a: np.ndarray, w: int) -> np.ndarray:
    k = np.ones(w) / w
    return np.convolve(np.r_[a[-w:], a, a[:w]], k, "same")[w:-w]


def periodic_savgol(a: np.ndarray, w: int, order: int = 3) -> np.ndarray:
    """Savitzky-Golay smoothing on a closed loop. Unlike a moving average it does not shrink tight corners."""
    return savgol_filter(a, w, order, mode="wrap")


def smoothed_geometry(x: np.ndarray, y: np.ndarray, step: float, smooth_m: float):
    """Smoothed closed path and its curvature. Linear in (x, y) up to the curvature formula, so small changes
    to the path change the result smoothly."""
    w = _window(step, smooth_m)
    xs, ys = periodic_savgol(x, w), periodic_savgol(y, w)
    return xs, ys, periodic_savgol(curvature(xs, ys), w, 2)


def curvature(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Signed curvature of a closed polyline, from periodic central differences (any regular parameterisation)."""
    dx = 0.5 * (np.roll(x, -1) - np.roll(x, 1))
    dy = 0.5 * (np.roll(y, -1) - np.roll(y, 1))
    ddx = np.roll(x, -1) - 2 * x + np.roll(x, 1)
    ddy = np.roll(y, -1) - 2 * y + np.roll(y, 1)
    return (dx * ddy - dy * ddx) / np.power(dx * dx + dy * dy, 1.5)


def _window(ds: float, smooth_m: float) -> int:
    return max(5, int(round(smooth_m / ds)) | 1)


@dataclass(frozen=True)
class Track:
    name: str
    s: np.ndarray
    x: np.ndarray
    y: np.ndarray
    kappa: np.ndarray
    width_left: np.ndarray
    width_right: np.ndarray
    ds: float
    z: np.ndarray = field(default=None)
    start_s: float = 0.0

    @property
    def length(self) -> float:
        return float(self.s[-1] + self.ds)

    def normals(self) -> tuple[np.ndarray, np.ndarray]:
        dx, dy = np.gradient(self.x), np.gradient(self.y)
        t = np.hypot(dx, dy)
        return -dy / t, dx / t

    def grade(self) -> np.ndarray:
        """Slope dz/ds along the lap; zero where elevation is unknown."""
        if self.z is None:
            return np.zeros_like(self.s)
        return np.gradient(np.r_[self.z, self.z[0]], self.ds)[:-1]

    def lap_distance(self, s: np.ndarray) -> np.ndarray:
        """Distance from the start/finish line for positions given as centreline s."""
        return np.mod(np.asarray(s) - self.start_s, self.length)


def resample_closed(x, y, n: int, *extra) -> tuple:
    """n points evenly spaced by arc length around a closed polyline, the step, and any `extra` per-point arrays
    interpolated to the same points."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    s_raw = np.r_[0.0, np.cumsum(np.hypot(np.diff(np.r_[x, x[0]]), np.diff(np.r_[y, y[0]])))]
    step = s_raw[-1] / n
    su = np.arange(n) * step
    out = [np.interp(su, s_raw, np.r_[a, a[0]]) for a in (x, y, *(np.asarray(e, float) for e in extra))]
    return step, *out


def build(name: str, x, y, width_left=None, width_right=None, ds: float = 2.0, smooth_m: float = 24.0) -> Track:
    """Resample a closed (x, y) polyline in metres to a uniform step and compute signed curvature."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    total = float(np.hypot(np.diff(np.r_[x, x[0]]), np.diff(np.r_[y, y[0]])).sum())
    n = int(round(total / ds))
    extra = [w for w in (width_left, width_right) if w is not None]
    step, xr, yr, *wr_ = resample_closed(x, y, n, *extra)
    su = np.arange(n) * step

    def resample(a):
        return wr_.pop(0) if a is not None else None

    xs, ys, kappa = smoothed_geometry(xr, yr, step, smooth_m)
    wl = resample(width_left)
    wr = resample(width_right)
    wl = np.full(n, 6.0) if wl is None else wl
    wr = np.full(n, 6.0) if wr is None else wr
    return Track(name, su, xs, ys, kappa, wl, wr, step)


def from_centreline(name: str, centreline, ds: float = 2.0) -> Track:
    c = centreline
    return build(name, c.x_m, c.y_m, c.w_tr_left_m, c.w_tr_right_m, ds=ds)


def offset_bounds(track: Track, car_width: float, margin: float = 0.3) -> tuple[np.ndarray, np.ndarray]:
    """Lateral offsets (left positive) that keep the car's half-width plus a margin inside each edge."""
    half = car_width / 2 + margin
    return np.minimum(-(track.width_right - half), 0.0), np.maximum(track.width_left - half, 0.0)


def min_curvature_offsets(track: Track, car_width: float, margin: float = 0.3) -> np.ndarray:
    """Offsets of the minimum-curvature path: the largest radius through every corner, ignoring the car."""
    x, y = track.x, track.y
    nx, ny = track.normals()
    lo, hi = offset_bounds(track, car_width, margin)
    cx = np.roll(x, 1) - 2 * x + np.roll(x, -1)
    cy = np.roll(y, 1) - 2 * y + np.roll(y, -1)

    def objective(a):
        px, py = a * nx, a * ny
        dx = cx + np.roll(px, 1) - 2 * px + np.roll(px, -1)
        dy = cy + np.roll(py, 1) - 2 * py + np.roll(py, -1)
        lx = np.roll(dx, 1) - 2 * dx + np.roll(dx, -1)
        ly = np.roll(dy, 1) - 2 * dy + np.roll(dy, -1)
        return float(np.sum(dx * dx + dy * dy)), 2.0 * (nx * lx + ny * ly)

    res = minimize(objective, np.zeros(len(x)), jac=True, method="L-BFGS-B",
                   bounds=list(zip(lo, hi, strict=True)), options={"maxiter": 5000})
    return res.x


LINE_SMOOTH_M = 16.0


def line_from_offsets(track: Track, a: np.ndarray, name: str, smooth_m: float = LINE_SMOOTH_M) -> Track:
    """The path at lateral offsets `a` from `track`, resampled, with widths, elevation and timing line carried over."""
    nx, ny = track.normals()
    line = build(name, track.x + a * nx, track.y + a * ny, track.width_left - a, track.width_right + a,
                 ds=track.ds, smooth_m=smooth_m)
    i0 = _index(track, track.start_s)
    start = Registration.identity().project(line, track.x[[i0]], track.y[[i0]])[0][0]
    z = None if track.z is None else np.interp(line.s / line.length, track.s / track.length, track.z, period=1.0)
    return replace(line, z=z, start_s=float(start))


def racing_line(track: Track, car_width: float, margin: float = 0.3) -> Track:
    """Minimum-curvature path inside the track edges."""
    return line_from_offsets(track, min_curvature_offsets(track, car_width, margin), f"{track.name} min-curvature")


def _index(track: Track, s: float) -> int:
    return int(round(s / track.ds)) % len(track.s)


@dataclass(frozen=True)
class Registration:
    """Rigid map from timing-feed coordinates (decimetres) to track metres: p_track = R @ (p_feed / 10) + t."""

    rotation: np.ndarray
    translation: np.ndarray
    rms_m: float = 0.0

    @classmethod
    def identity(cls) -> "Registration":
        return cls(np.eye(2), np.zeros(2))

    def to_track(self, x_feed, y_feed) -> tuple[np.ndarray, np.ndarray]:
        p = np.c_[x_feed, y_feed] / FEED_UNITS_PER_M @ self.rotation.T + self.translation
        return p[:, 0], p[:, 1]

    def to_feed(self, x, y) -> tuple[np.ndarray, np.ndarray]:
        p = (np.c_[x, y] - self.translation) @ self.rotation * FEED_UNITS_PER_M
        return p[:, 0], p[:, 1]

    def project(self, track: Track, x_feed, y_feed, feed: bool = False):
        """Centreline s and signed lateral offset (left positive) of each point."""
        x, y = self.to_track(x_feed, y_feed) if feed else (np.asarray(x_feed, float), np.asarray(y_feed, float))
        _, i = cKDTree(np.c_[track.x, track.y]).query(np.c_[x, y])
        nx, ny = track.normals()
        tx, ty = ny[i], -nx[i]
        along = (x - track.x[i]) * tx + (y - track.y[i]) * ty
        lateral = (x - track.x[i]) * nx[i] + (y - track.y[i]) * ny[i]
        return np.mod(track.s[i] + along, track.length), lateral


def _kabsch(src: np.ndarray, dst: np.ndarray, allow_reflection: bool) -> tuple[np.ndarray, np.ndarray]:
    ms, md = src.mean(0), dst.mean(0)
    u, _, vt = np.linalg.svd((src - ms).T @ (dst - md))
    d = np.eye(2)
    if not allow_reflection and np.linalg.det(vt.T @ u.T) < 0:
        d[1, 1] = -1
    r = vt.T @ d @ u.T
    return r, md - r @ ms


def register(track: Track, x_feed, y_feed, iterations: int = 60) -> Registration:
    """Fit the feed-to-track rigid transform by ICP from a coarse search over rotation and handedness."""
    src = np.c_[x_feed, y_feed] / FEED_UNITS_PER_M
    dst = np.c_[track.x, track.y]
    tree = cKDTree(dst)
    best = None
    for mirror in (False, True):
        m = np.diag([1.0, -1.0]) if mirror else np.eye(2)
        for theta in np.radians(np.arange(0, 360, 15)):
            c, s = np.cos(theta), np.sin(theta)
            r = np.array([[c, -s], [s, c]]) @ m
            t = dst.mean(0) - r @ src.mean(0)
            for _ in range(iterations):
                d, i = tree.query(src @ r.T + t)
                r, t = _kabsch(src, dst[i], allow_reflection=mirror)
            rms = float(np.sqrt(np.mean(tree.query(src @ r.T + t)[0] ** 2)))
            if best is None or rms < best.rms_m:
                best = Registration(r, t, rms)
    return best


def driven_line(name: str, location, windows, n_bins: int = 2400, ds: float = 2.0, smooth_m: float = 40.0,
                min_laps: int = 50) -> tuple[Track, dict]:
    """The line cars actually drove, from timing-feed positions: every lap in `windows` is cut at the timing
    line, parameterised by its own fraction of path length, and the median position and height taken per bin.

    `location` has driver_number, date, x, y, z in feed units; `windows` has driver_number, date_start,
    lap_time. Returns the track (start at the timing line, elevation attached) and fit statistics.
    """
    xs, ys, zs, fs = [], [], [], []
    by_driver = {d: g.sort_values("date") for d, g in location.groupby("driver_number")}
    used = 0
    for w in windows.itertuples():
        g = by_driver.get(w.driver_number)
        if g is None:
            continue
        t = (g.date - w.date_start).dt.total_seconds().to_numpy()
        inside = (t > 0) & (t < w.lap_time)
        if inside.sum() < 100:
            continue
        tt = np.r_[0.0, t[inside], w.lap_time]
        px = np.interp(tt, t, g.x.to_numpy(float))
        py = np.interp(tt, t, g.y.to_numpy(float))
        pz = np.interp(tt, t, g.z.to_numpy(float))
        d = np.r_[0.0, np.cumsum(np.hypot(np.diff(px), np.diff(py)))]
        fs.append(d / d[-1])
        xs.append(px)
        ys.append(py)
        zs.append(pz)
        used += 1
    if used < min_laps:
        raise ValueError(f"only {used} usable laps for the driven line")
    f, x, y, z = (np.concatenate(a) for a in (fs, xs, ys, zs))
    b = np.minimum((f * n_bins).astype(int), n_bins - 1)
    order = np.argsort(b, kind="stable")
    groups = np.split(order, np.flatnonzero(np.diff(b[order])) + 1)
    mx = np.array([np.median(x[g]) for g in groups]) / FEED_UNITS_PER_M
    my = np.array([np.median(y[g]) for g in groups]) / FEED_UNITS_PER_M
    mz = np.array([np.median(z[g]) for g in groups]) / FEED_UNITS_PER_M
    spread = np.array([np.median(np.hypot(x[g] / FEED_UNITS_PER_M - mx[k], y[g] / FEED_UNITS_PER_M - my[k]))
                       for k, g in enumerate(groups)])
    line = build(name, mx, my, ds=ds, smooth_m=smooth_m)
    zz = np.interp(line.s, np.linspace(0, line.length, len(mz), endpoint=False), mz, period=line.length)
    zz = periodic_smooth(zz, _window(line.ds, 60.0))
    stats = {"laps": used, "length_m": line.length, "median_spread_m": float(np.median(spread)),
             "p95_spread_m": float(np.percentile(spread, 95)), "elevation_range_m": float(np.ptp(zz))}
    return replace(line, z=zz - zz.mean()), stats


def transfer_widths(target: Track, source: Track, max_gap_m: float = 3.0,
                    smooth_m: float = 60.0) -> tuple[Track, float]:
    """Copy track widths from `source` (e.g. a centreline database) onto `target` where the two layouts coincide.

    `target` is registered onto `source` first. Points with no source point within `max_gap_m` (sections
    rebuilt since the source was surveyed) get the source's median widths. Returns the track and the share
    of points that matched.
    """
    reg = register(source, target.x * FEED_UNITS_PER_M, target.y * FEED_UNITS_PER_M)
    x, y = reg.to_track(target.x * FEED_UNITS_PER_M, target.y * FEED_UNITS_PER_M)
    gap, i = cKDTree(np.c_[source.x, source.y]).query(np.c_[x, y])
    ok = gap <= max_gap_m
    wl = np.where(ok, source.width_left[i], np.median(source.width_left))
    wr = np.where(ok, source.width_right[i], np.median(source.width_right))
    if np.linalg.det(reg.rotation) < 0:
        wl, wr = wr, wl
    w = _window(target.ds, smooth_m)
    return replace(target, width_left=periodic_smooth(wl, w), width_right=periodic_smooth(wr, w)), float(ok.mean())
