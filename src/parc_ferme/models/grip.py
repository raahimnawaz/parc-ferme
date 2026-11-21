"""S3 grip and downforce, team against team, from corner minimum speeds.

At the slowest point of a grip-limited corner, m v^2 kappa = mu (m g + q ClA v^2) with q = rho / 2. The feed has no
position across the track, so the radius each car drives is unknown, but every car drives nearly the same one. Taking
a team's corner speed relative to the field cancels it:

    (1 - w) * 2 ln(v_team / v_field) = dmu/mu + w * dClA/ClA,   w = q ClA v^2 / (m g + q ClA v^2)

where w is the share of the corner's grip that comes from downforce. Regressing that left side on w across slow and
fast corners gives each team's mechanical grip (the intercept) and downforce (the slope) relative to the field. The
field's absolute mu and ClA only set the weights w, so their uncertainty barely moves the team differences.

Straight-line speed is not used: in 2026 how fast a car accelerates depends on how much electrical energy it
deploys there, which the feed doesn't show, so drag needs the energy model (S4).
"""

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from ..core.car import Car, G
from ..core.track import Track
from ..sim.lapsim import deploy_threshold, simulate

WINDOW = 0.012
FLAT_OUT_THROTTLE = 95.0
FUEL_AVG_KG = 35.0  # assumed: about half a race fuel load, the average over a race; S5 replaces it
OUTLIER_MADS = 4.0


def lap_window(f: np.ndarray, centre: float, half_width: float = WINDOW) -> np.ndarray:
    return np.abs(((np.asarray(f) - centre + 0.5) % 1.0) - 0.5) < half_width


def corner_minima(samples: pd.DataFrame, corner_fraction: dict[int, float]) -> pd.DataFrame:
    """Lowest speed [m/s] of every lap through every corner, and the lowest throttle [%] around it: one row per
    driver, lap and corner."""
    keys = [c for c in ("driver_number", "lap_number", "driver", "team", "compound", "tyre_age") if c in samples]
    out = []
    for n, fc in corner_fraction.items():
        g = samples[lap_window(samples.f.to_numpy(), fc)].groupby(keys, dropna=False)
        m = g.agg(v=("v", "min"), throttle=("throttle", "min"))
        out.append(m.reset_index().assign(corner=n))
    return pd.concat(out, ignore_index=True)


def grip_limited(minima: pd.DataFrame) -> pd.DataFrame:
    """Only the corners drivers lift for. Where the median lap stays above FLAT_OUT_THROTTLE, the minimum speed
    is set by power and drag, not grip."""
    lifted = minima.groupby("corner").throttle.median() < FLAT_OUT_THROTTLE
    return minima[minima.corner.map(lifted)]


def aero_share(v, mu: float, cla: float, mass: float, rho: float) -> np.ndarray:
    """Share of cornering grip that comes from downforce at speed v [m/s]."""
    aero = 0.5 * rho * cla * np.asarray(v, float) ** 2
    return aero / (mass * G + aero)


def sim_corner_minima(line: Track, car: Car, zones: np.ndarray, corner_fraction: dict[int, float],
                      v_star: float | None = None) -> pd.Series:
    """The lap sim's lowest speed [m/s] through each corner."""
    lap = simulate(line, car, zones, v_star)
    f = lap.trace.distance.to_numpy() / line.length
    v = lap.trace.v_kph.to_numpy() / 3.6
    return pd.Series({n: float(v[lap_window(f, fc)].min()) for n, fc in corner_fraction.items()})


@dataclass
class FieldFit:
    car: Car
    corners: pd.DataFrame

    @property
    def rms_kph(self) -> float:
        return float(np.sqrt(np.mean(self.corners.diff_kph ** 2)))


def fit_car(line: Track, zones: np.ndarray, car: Car, corner_fraction: dict[int, float],
            v_target: pd.Series) -> FieldFit:
    """mu and ClA of `car` that make the lap sim's corner minimum speeds on `line` match `v_target` [m/s] in the
    least-squares sense. Every other parameter is held. The line's radii can't be checked against the feed,
    so the per-corner misfit is returned with the car."""
    v_star = deploy_threshold(line, car, zones)
    corners = {n: corner_fraction[n] for n in v_target.index}

    def misfit(p):
        c = replace(car, mu=float(np.exp(p[0])), cla_corner=float(np.exp(p[1])))
        return float(np.sum((sim_corner_minima(line, c, zones, corners, v_star) - v_target) ** 2))

    res = minimize(misfit, np.log([car.mu, car.cla_corner]), method="Nelder-Mead",
                   options={"xatol": 1e-4, "fatol": 1e-6, "maxiter": 400})
    fitted = replace(car, mu=float(np.exp(res.x[0])), cla_corner=float(np.exp(res.x[1])))
    v_sim = sim_corner_minima(line, fitted, zones, corners, v_star)
    table = pd.DataFrame({"corner": v_target.index, "real_kph": 3.6 * v_target.to_numpy(),
                          "sim_kph": 3.6 * v_sim.reindex(v_target.index).to_numpy()})
    table["diff_kph"] = table.sim_kph - table.real_kph
    return FieldFit(fitted, table)


def _design(minima: pd.DataFrame, w: pd.Series) -> tuple[np.ndarray, np.ndarray, list[str], np.ndarray]:
    ref = minima.groupby("corner").v.median()
    wc = minima.corner.map(w).to_numpy()
    y = (1 - wc) * 2 * np.log(minima.v.to_numpy() / minima.corner.map(ref).to_numpy())
    teams = sorted(minima.team.unique())
    ti = minima.team.map({t: i for i, t in enumerate(teams)}).to_numpy()
    k = len(teams)
    cols = [np.eye(k)[ti], np.eye(k)[ti] * wc[:, None]]
    if "compound" in minima and minima.compound.nunique() > 1:
        comps = sorted(minima.compound.unique())[1:]
        cols.append(np.column_stack([minima.compound.to_numpy() == c for c in comps]).astype(float))
    for col in ("lap_number", "tyre_age"):
        if col in minima and minima[col].nunique() > 1:
            x = minima[col].to_numpy(float)
            cols.append((x - x.mean())[:, None])
    return np.hstack(cols), y, teams, ti


def _fit(x: np.ndarray, y: np.ndarray, k: int) -> np.ndarray:
    """Least squares, refit once without rows more than OUTLIER_MADS robust deviations out (a lap with a lock-up
    or a track-limits run). Team effects are returned relative to the mean team."""
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    r = y - x @ coef
    keep = np.abs(r - np.median(r)) <= OUTLIER_MADS * 1.4826 * np.median(np.abs(r - np.median(r)))
    coef, *_ = np.linalg.lstsq(x[keep], y[keep], rcond=None)
    a, b = coef[:k], coef[k:2 * k]
    return np.c_[a - a.mean(), b - b.mean()]


def relative_grip(minima: pd.DataFrame, w: pd.Series) -> pd.DataFrame:
    """Per team, mechanical grip and downforce relative to the mean team [%]. Compound, tyre age and lap number
    (fuel burn, track evolution) enter as shared terms. Also reports the grip the two imply at the field's slowest
    and fastest corner, which sit inside the data range.

    Standard errors are leave-one-corner-out jackknife. A bootstrap over laps would only see lap-to-lap noise;
    this also sees how much a team's result rests on one corner, where its drivers may take a different line."""
    x, y, teams, _ = _design(minima, w)
    k = len(teams)
    est = _fit(x, y, k)
    corners = sorted(minima.corner.unique())
    jack = []
    for c in corners:
        keep = (minima.corner != c).to_numpy()
        jack.append(_fit(*_design(minima[keep], w)[:2], k))
    jack = np.array(jack)
    n = len(corners)

    def se(values):
        return np.sqrt((n - 1) / n * np.sum((values - values.mean(0)) ** 2, axis=0))

    w_lo, w_hi = float(w.reindex(corners).min()), float(w.reindex(corners).max())
    out = pd.DataFrame({"team": teams, "mech_pct": 100 * est[:, 0], "mech_se": 100 * se(jack[:, :, 0]),
                        "downforce_pct": 100 * est[:, 1], "downforce_se": 100 * se(jack[:, :, 1])})
    for name, wv in (("slow_corner_pct", w_lo), ("fast_corner_pct", w_hi)):
        out[name] = 100 * (est[:, 0] + wv * est[:, 1])
        out[name.replace("pct", "se")] = 100 * se(jack[:, :, 0] + wv * jack[:, :, 1])
    laps = minima.groupby(["driver_number", "lap_number"]).ngroups
    out.attrs |= {"w_slow": w_lo, "w_fast": w_hi, "laps": int(laps), "corners": n}
    return out.sort_values("fast_corner_pct", ascending=False).reset_index(drop=True)


def path_lengths(samples: pd.DataFrame, anchors_s: np.ndarray, lap_length: float) -> np.ndarray:
    """Median distance actually driven between consecutive anchor points on the reference line [m]: speed
    integrated between the times a car passes each anchor. Anchors belong on straights, where the feed's
    progress along the reference is exact."""
    out = []
    for _, g in samples.groupby(["driver_number", "lap_number"], sort=False):
        g = g.sort_values("t")
        t, v = g.t.to_numpy(), g.v.to_numpy()
        su = np.unwrap(g.s.to_numpy() * 2 * np.pi / lap_length) * lap_length / (2 * np.pi)
        if np.any(np.diff(su) < -5):
            continue
        d = np.r_[0.0, np.cumsum(0.5 * (v[1:] + v[:-1]) * np.diff(t))]
        ta = np.interp(anchors_s, su, t, left=np.nan, right=np.nan)
        out.append(np.diff(np.interp(ta, t, d)))
    return np.nanmedian(np.array(out), axis=0)


def straight_anchors(ref: Track, min_gap_m: float = 250.0, max_kappa: float = 1 / 1500) -> np.ndarray:
    """Indices of reference points on straights, at least `min_gap_m` apart, to measure driven distance between."""
    from ..core.track import periodic_smooth

    k = periodic_smooth(np.abs(ref.kappa), max(5, int(round(50 / ref.ds)) | 1))
    out: list[int] = []
    for i in np.flatnonzero(k < max_kappa):
        if not out or ref.s[i] - ref.s[out[-1]] >= min_gap_m:
            out.append(int(i))
    return np.asarray(out)


def line_lengths(line: Track, ref: Track, anchors: np.ndarray) -> np.ndarray:
    """Length of `line` between consecutive anchor points of `ref`."""
    from ..core.track import Registration

    s, _ = Registration.identity().project(line, ref.x[anchors], ref.y[anchors])
    return np.diff(line.lap_distance(s)) % line.length
