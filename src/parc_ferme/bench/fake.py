"""Render a simulated lap as OpenF1-shaped car data and positions, with the feed's sampling and quantisation."""

import numpy as np
import pandas as pd

from ..core.car import Gearing
from ..core.track import FEED_UNITS_PER_M
from ..sim.lapsim import Lap


def sample_times(lap_time: float, intervals: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Sample instants inside the lap, spaced like the real feed (intervals drawn from an observed set)."""
    t = [rng.uniform(0, intervals.mean())]
    while t[-1] < lap_time:
        t.append(t[-1] + rng.choice(intervals))
    return np.asarray(t[:-1])


def render(lap: Lap, gearing: Gearing, start: pd.Timestamp, driver_number: int, intervals: np.ndarray,
           rng: np.random.Generator, speed_noise_kph: float = 0.0, dropout: float = 0.0,
           z: np.ndarray | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    tr = lap.trace
    t = sample_times(lap.lap_time, intervals, rng)
    t = t[rng.random(len(t)) >= dropout]
    tt = tr.t.to_numpy()

    def at(col):
        return np.interp(t, tt, tr[col].to_numpy(float))

    speed = at("v_kph") + rng.normal(0, speed_noise_kph, len(t)) if speed_noise_kph else at("v_kph")
    gear = gearing.gear(speed)
    dates = start + pd.to_timedelta(t, unit="s")
    car_data = pd.DataFrame({
        "date": dates,
        "driver_number": driver_number,
        "speed": np.rint(speed).astype(int),
        "rpm": np.rint(gearing.rpm(speed, gear)).astype(int),
        "n_gear": gear,
        "throttle": np.rint(at("throttle")).astype(int),
        "brake": np.where(at("brake") >= 50, 100, 0),
    })
    zz = np.zeros(len(t)) if z is None else np.interp(t, tt, z)
    location = pd.DataFrame({
        "date": dates,
        "driver_number": driver_number,
        "x": np.rint(at("x") * FEED_UNITS_PER_M).astype(int),
        "y": np.rint(at("y") * FEED_UNITS_PER_M).astype(int),
        "z": np.rint(zz * FEED_UNITS_PER_M).astype(int),
    })
    return car_data, location
