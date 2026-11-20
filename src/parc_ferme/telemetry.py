"""Car data cut to a lap and placed on distance."""

import numpy as np
import pandas as pd

CHANNELS = ("speed", "throttle", "brake", "n_gear", "rpm")


def lap_trace(car_data: pd.DataFrame, start: pd.Timestamp, duration: float) -> pd.DataFrame:
    """Samples of one driver's car data inside [start, start + duration], with the speed
    interpolated onto both ends, time in seconds from the line and distance in metres."""
    end = start + pd.to_timedelta(duration, unit="s")
    cd = car_data.sort_values("date")
    t_all = (cd["date"] - start).dt.total_seconds().to_numpy()
    inside = (t_all > 0) & (t_all < duration)
    if inside.sum() < 2:
        return pd.DataFrame(columns=["t", "distance", *CHANNELS])

    speed_all = cd["speed"].to_numpy(float)
    edges = np.interp([0.0, duration], t_all, speed_all)
    body = cd.loc[inside, list(CHANNELS)].reset_index(drop=True)
    first = body.iloc[[0]].assign(speed=edges[0])
    last = body.iloc[[-1]].assign(speed=edges[1])
    tr = pd.concat([first, body, last], ignore_index=True)
    tr.insert(0, "t", np.concatenate([[0.0], t_all[inside], [duration]]))

    v = tr["speed"].to_numpy(float) / 3.6
    dt = np.diff(tr["t"].to_numpy())
    tr.insert(1, "distance", np.concatenate([[0.0], np.cumsum(0.5 * (v[1:] + v[:-1]) * dt)]))
    tr.attrs["end"] = end
    return tr


def on_distance(trace: pd.DataFrame, grid: np.ndarray) -> pd.DataFrame:
    """Resample a lap trace onto a distance grid. Time is interpolated so deltas can be taken."""
    d = trace["distance"].to_numpy()
    out = {"distance": grid, "t": np.interp(grid, d, trace["t"].to_numpy())}
    for ch in CHANNELS:
        x = np.interp(grid, d, trace[ch].to_numpy(float))
        out[ch] = np.rint(x) if ch == "n_gear" else x
    return pd.DataFrame(out)
