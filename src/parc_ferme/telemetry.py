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


def placed_samples(car_data: pd.DataFrame, location: pd.DataFrame, laps: pd.DataFrame, ref) -> pd.DataFrame:
    """Every car-data sample of the given laps, placed on the reference line through the position feed.

    The feed snaps positions onto one line, so this gives where a car is around the lap (`s` on `ref`, and `f`
    as a lap fraction) but not across the track. `laps` needs driver_number, lap_number, date_start and lap_time;
    any of driver, team, compound and tyre_age it carries are copied onto the samples. `a` is the central
    difference of speed [m/s^2].
    """
    from scipy.spatial import cKDTree

    from .core.track import FEED_UNITS_PER_M

    tree = cKDTree(np.c_[ref.x, ref.y])
    cd_by = {d: g.sort_values("date") for d, g in car_data.groupby("driver_number")}
    loc = location[(location.x != 0) | (location.y != 0)]
    lo_by = {d: g.sort_values("date") for d, g in loc.groupby("driver_number")}
    keep = [c for c in ("driver", "team", "compound", "tyre_age") if c in laps]
    parts = []
    for w in laps.itertuples():
        cd, lo = cd_by.get(w.driver_number), lo_by.get(w.driver_number)
        if cd is None or lo is None:
            continue
        t0 = w.date_start - pd.Timedelta(seconds=1)
        t1 = w.date_start + pd.Timedelta(seconds=w.lap_time + 1)
        c = cd[(cd.date > t0) & (cd.date < t1)]
        p = lo[(lo.date > t0) & (lo.date < t1)]
        if len(c) < 100 or len(p) < 100:
            continue
        tc = (c.date - w.date_start).dt.total_seconds().to_numpy()
        tp = (p.date - w.date_start).dt.total_seconds().to_numpy()
        _, j = tree.query(np.c_[p.x / FEED_UNITS_PER_M, p.y / FEED_UNITS_PER_M])
        sp = np.unwrap(ref.s[j] * 2 * np.pi / ref.length) * ref.length / (2 * np.pi)
        sp -= ref.length * np.round(np.interp(0.0, tp, sp) / ref.length)
        v = c.speed.to_numpy(float) / 3.6
        a = np.full(len(v), np.nan)
        a[1:-1] = (v[2:] - v[:-2]) / (tc[2:] - tc[:-2])
        s = np.mod(np.interp(tc, tp, sp), ref.length)
        inside = (tc >= 0) & (tc <= w.lap_time)
        part = pd.DataFrame({"driver_number": w.driver_number, "lap_number": w.lap_number, "t": tc, "v": v, "a": a,
                             "throttle": c.throttle.to_numpy(), "brake": c.brake.to_numpy(), "s": s,
                             "f": s / ref.length})[inside]
        for col in keep:
            part[col] = getattr(w, col)
        parts.append(part)
    return pd.concat(parts, ignore_index=True)
