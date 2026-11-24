"""S2 quasi-steady-state lap simulator for a 2026 car, with active aero zones and an electrical energy budget.

Ported from engine-map-pinn's QSS solver and extended for 2026: a power unit split into ICE and MGU-K with the
speed taper, braking-only harvesting capped by MGU-K power, a deployment threshold chosen so the lap is
energy-neutral, straight mode only inside FIA zones, and road grade.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numba import njit

from ..core.car import Car, G
from ..core.ers import deploy_fraction
from ..core.track import Track

VMAX = 120.0
VMIN = 5.0
BRAKE_FORCE_G = 0.1


def zone_mask(line: Track, corner_s: dict[int, float], zones: list, exit_m: float = 60.0,
              entry_m: float = 150.0) -> np.ndarray:
    """Straight-mode zones as a mask along the line. Each zone runs from `exit_m` past the first corner's apex
    to `entry_m` before the next one's; ["start_finish"] runs from the last corner to the first."""
    s = line.s
    mask = np.zeros(len(s), bool)
    numbers = sorted(corner_s)
    for z in zones:
        a, b = (numbers[-1], numbers[0]) if z == ["start_finish"] else z
        start, end = (corner_s[a] + exit_m) % line.length, (corner_s[b] - entry_m) % line.length
        mask |= (s >= start) & (s < end) if start < end else (s >= start) | (s < end)
    return mask


@dataclass
class Lap:
    trace: pd.DataFrame
    lap_time: float
    deploy_mj: float
    harvest_mj: float
    soc_swing_mj: float
    deploy_below_kph: float


@njit(cache=True)
def qss_speed(k, grade, ds, cla_c, cda_c, cla_z, cda_z, m, mu, roll, eff, ice_w, mguk_w,
              half_rho, v_star, n_iter=3):
    """Quasi-steady speed at each point of a closed path. Segment i runs from point i to i+1 with length ds[i].
    Forward passes are power- and grip-limited (straight-mode aero where zoned); backward passes are grip-limited
    braking in corner mode."""
    n = k.shape[0]
    v = np.empty(n)
    v_corner = np.empty(n)
    for i in range(n):
        denom = m * k[i] - mu * half_rho * cla_c[i]
        v_corner[i] = VMAX if denom <= 0 else min(np.sqrt(mu * m * G / denom), VMAX)
        v[i] = v_corner[i]
    for _ in range(n_iter):
        for i in range(n):
            j = i - 1 if i > 0 else n - 1
            vv = v[j]
            f_grip = mu * (m * G + half_rho * cla_z[j] * vv * vv)
            f_lat = m * vv * vv * k[j]
            f_long = np.sqrt(max(f_grip * f_grip - f_lat * f_lat, 0.0))
            p = ice_w
            if vv < v_star:
                p += mguk_w * deploy_fraction(vv)
            f = min(eff * p / max(vv, VMIN), f_long)
            a = (f - half_rho * cda_z[j] * vv * vv - roll - m * G * grade[j]) / m
            v[i] = min(v[i], np.sqrt(max(vv * vv + 2.0 * a * ds[j], VMIN * VMIN)), v_corner[i])
        for i in range(n - 1, -1, -1):
            j = i + 1 if i < n - 1 else 0
            vv = v[j]
            f_grip = mu * (m * G + half_rho * cla_c[j] * vv * vv)
            f_lat = m * vv * vv * k[j]
            f = np.sqrt(max(f_grip * f_grip - f_lat * f_lat, 0.0)) + half_rho * cda_c[j] * vv * vv + roll \
                + m * G * grade[j]
            v[i] = min(v[i], np.sqrt(vv * vv + 2.0 * f / m * ds[i]))
    return v


def kernel_args(car: Car, zones: np.ndarray) -> tuple:
    cda_c, cla_c = car.aero(np.zeros(len(zones), bool))
    cda_z, cla_z = car.aero(zones)
    return (cla_c.astype(float), cda_c.astype(float), cla_z.astype(float), cda_z.astype(float), car.mass, car.mu,
            car.crr * car.mass * G, car.driveline_eff, car.ice_w, car.mguk_w, 0.5 * car.rho)


def _speed_profile(line: Track, car: Car, zones: np.ndarray, v_star: float) -> np.ndarray:
    ds = np.full(len(line.s), line.ds)
    return qss_speed(np.abs(line.kappa), line.grade(), ds, *kernel_args(car, zones), v_star)


def _trace(line: Track, car: Car, zones: np.ndarray, v: np.ndarray, v_star: float) -> pd.DataFrame:
    m, ds = car.mass, line.ds
    v_next = np.roll(v, -1)
    v_mid = 0.5 * (v + v_next)
    dt = ds / v_mid
    accel = (v_next ** 2 - v ** 2) / (2 * ds)
    straight = zones & (accel > -0.5)
    cda, _ = car.aero(straight)
    resist = 0.5 * car.rho * cda * v_mid ** 2 + car.crr * m * G + m * G * line.grade()
    f_req = m * accel + resist
    p_wheel = np.maximum(f_req, 0.0) * v_mid
    p_avail = car.driveline_eff * (car.ice_w + np.where(v_mid < v_star, car.mguk_limit_w(v_mid), 0.0))
    deploy = np.maximum(p_wheel / car.driveline_eff - car.ice_w, 0.0)
    braking = np.maximum(-f_req, 0.0) * v_mid
    regen = car.regen_eff * np.minimum(braking, car.mguk_w)
    soc = np.cumsum((regen - deploy) * dt) / 1e6
    return pd.DataFrame({
        "s": line.s,
        "distance": line.lap_distance(line.s),
        "x": line.x, "y": line.y,
        "v_kph": v * 3.6,
        "t_step": dt,
        "throttle": np.clip(p_wheel / p_avail, 0.0, 1.0) * 100,
        "brake": np.where(-f_req > BRAKE_FORCE_G * m * G, 100, 0),
        "straight_mode": straight,
        "deploy_kw": deploy / 1e3,
        "regen_kw": regen / 1e3,
        "soc_mj": soc - soc.min(),
    })


def deploy_threshold(line: Track, car: Car, zones: np.ndarray, iterations: int = 18) -> float:
    """Speed below which the MGU-K deploys, chosen so the lap spends what it harvests (capped per lap)."""
    cap = car.rules["power_unit"]["harvest_per_lap_mj"]
    lo, hi = 0.0, VMAX
    for _ in range(iterations):
        v_star = 0.5 * (lo + hi)
        tr = _trace(line, car, zones, _speed_profile(line, car, zones, v_star), v_star)
        spent = float((tr.deploy_kw * tr.t_step).sum() / 1e3)
        budget = min(float((tr.regen_kw * tr.t_step).sum() / 1e3), cap)
        lo, hi = (v_star, hi) if spent < budget else (lo, v_star)
    return lo


def simulate(line: Track, car: Car, zones: np.ndarray, v_star: float | None = None) -> Lap:
    """Lap with an energy-neutral deployment threshold, or at a given one."""
    v_star = deploy_threshold(line, car, zones) if v_star is None else v_star
    tr = _trace(line, car, zones, _speed_profile(line, car, zones, v_star), v_star)
    tr = tr.iloc[np.argsort(tr.distance.to_numpy(), kind="stable")].reset_index(drop=True)
    tr["t"] = np.r_[0.0, np.cumsum(tr.t_step.to_numpy())[:-1]]
    return Lap(trace=tr,
               lap_time=float(tr.t_step.sum()),
               deploy_mj=float((tr.deploy_kw * tr.t_step).sum() / 1e3),
               harvest_mj=float((tr.regen_kw * tr.t_step).sum() / 1e3),
               soc_swing_mj=float(tr.soc_mj.max()),
               deploy_below_kph=v_star * 3.6)
