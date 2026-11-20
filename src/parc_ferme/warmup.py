"""The warm-up analyses. Each one also serves as a sanity check on the ingested data."""

import numpy as np
import pandas as pd

from .laps import lap_table, within_stint_slope
from .session import Session
from .telemetry import lap_trace, on_distance

LONG_RUN = 15


def laps(s: Session) -> pd.DataFrame:
    t = lap_table(s.laps, s.stints, s.pit, s.race_control)
    t.insert(1, "driver", t.driver_number.map(s.acronyms))
    t.insert(2, "team", t.driver_number.map(s.teams))
    return t


def degradation(t: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for compound, g in t[t.green].groupby("compound"):
        slope, se, n = within_stint_slope(g)
        rows.append({"compound": compound, "slope_s_per_lap": slope, "stderr": se, "green_laps": n})
    return pd.DataFrame(rows)


def best_long_run(t: pd.DataFrame, window: int = LONG_RUN) -> pd.DataFrame:
    """Lowest mean over `window` consecutive green laps inside one stint, per driver."""
    rows = []
    for (drv, stint), g in t[t.green].groupby(["driver_number", "stint_number"]):
        g = g.sort_values("lap_number")
        run_id = (g.lap_number.diff() != 1).cumsum()
        for _, r in g.groupby(run_id):
            if len(r) < window:
                continue
            means = r.lap_time.rolling(window).mean()
            i = means.idxmin()
            rows.append({"driver_number": drv, "driver": r.driver.iloc[0], "team": r.team.iloc[0],
                         "stint_number": stint, "compound": r.compound.iloc[0],
                         "first_lap": int(r.lap_number.loc[i]) - window + 1,
                         "mean_lap_time": float(means.loc[i])})
    if not rows:
        return pd.DataFrame(columns=["driver", "team", "compound", "mean_lap_time"])
    best = pd.DataFrame(rows).sort_values("mean_lap_time").drop_duplicates("driver_number")
    return best.reset_index(drop=True)


def stop_pace(t: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    """Mean of the n green laps before each in-lap against the n green laps after the out-lap."""
    rows = []
    for _, g in t.groupby("driver_number"):
        g = g.set_index("lap_number")
        for in_lap in g.index[g.pit_in]:
            before = g.loc[: in_lap - 1]
            before = before[before.green].tail(n)
            after = g.loc[in_lap + 2:]
            after = after[after.green].head(n)
            if len(before) < n or len(after) < n:
                continue
            rows.append({"driver": g.driver.iloc[0], "in_lap": int(in_lap),
                         "compound_before": before.compound.iloc[-1],
                         "compound_after": after.compound.iloc[0],
                         "pace_before": before.lap_time.mean(), "pace_after": after.lap_time.mean(),
                         "gain": before.lap_time.mean() - after.lap_time.mean()})
    return pd.DataFrame(rows)


def compound_summary(t: pd.DataFrame) -> pd.DataFrame:
    g = t[t.green]
    fresh = g[g.tyre_age <= 5].groupby("compound").lap_time.median().rename("fresh_pace")
    laps_run = t.groupby("compound").size().rename("laps_run")
    return (degradation(t).set_index("compound").join([fresh, laps_run]).reset_index())


def fastest_lap(t: pd.DataFrame, driver: str) -> pd.Series:
    g = t[(t.driver == driver) & t.green]
    return g.loc[g.lap_time.idxmin()]


def overlay(s: Session, t: pd.DataFrame, a: str, b: str, step: float = 5.0) -> pd.DataFrame:
    """Two drivers' fastest green laps on one distance grid, with the time gap as it builds."""
    traces = {}
    for drv in (a, b):
        lap = fastest_lap(t, drv)
        cd = s.car_data[s.car_data.driver_number == lap.driver_number]
        traces[drv] = lap_trace(cd, lap.date_start, lap.lap_time)
    length = min(tr.distance.iloc[-1] for tr in traces.values())
    grid = np.arange(0.0, length, step)
    ra, rb = (on_distance(traces[d], grid) for d in (a, b))
    out = ra.add_prefix(f"{a}_").rename(columns={f"{a}_distance": "distance"})
    out = out.join(rb.drop(columns="distance").add_prefix(f"{b}_"))
    out["delta"] = out[f"{b}_t"] - out[f"{a}_t"]
    return out
