"""One row per driver lap, with tyre state, pit and neutralisation flags, and a green-lap mask."""

import numpy as np
import pandas as pd

OUTLIER_FACTOR = 1.07


def neutralised_laps(race_control: pd.DataFrame) -> set[int]:
    """Laps run under a safety car, VSC or red flag, from race control messages."""
    if race_control.empty:
        return set()
    rc = race_control.dropna(subset=["lap_number"]).sort_values("date")
    msg = rc["message"].fillna("").str.upper()
    laps: set[int] = set()
    start: dict[str, int] = {}
    for lap, m, flag in zip(rc["lap_number"].astype(int), msg, rc.get("flag", pd.Series(index=rc.index)), strict=True):
        if "VIRTUAL SAFETY CAR DEPLOYED" in m:
            start["vsc"] = lap
        elif "VIRTUAL SAFETY CAR ENDING" in m and "vsc" in start:
            laps.update(range(start.pop("vsc"), lap + 1))
        elif "SAFETY CAR DEPLOYED" in m:
            start["sc"] = lap
        elif "SAFETY CAR IN THIS LAP" in m and "sc" in start:
            laps.update(range(start.pop("sc"), lap + 2))
        elif flag == "RED" or m.startswith("RED FLAG"):
            laps.update({lap, lap + 1})
    for lap in start.values():
        laps.update(range(lap, int(rc["lap_number"].max()) + 1))
    return laps


def reconcile_stints(stints: pd.DataFrame, pit: pd.DataFrame, laps: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Stint boundaries rebuilt from pit-in laps, compounds kept from the stints table.

    OpenF1's stint boundaries are occasionally wrong while its pit log agrees with the out-lap flag,
    so the pit log sets the boundaries. Returns the stints and {driver_number: (old_ends, new_ends)}
    for every driver whose boundaries moved. Drivers whose stop count disagrees are left unchanged.
    """
    completed = laps.dropna(subset=["lap_duration"]).groupby("driver_number").lap_number.max()
    out, moved = [], {}
    for drv, g in stints.sort_values("stint_number").groupby("driver_number"):
        g = g.copy()
        pit_laps = sorted(pit.loc[pit.driver_number == drv, "lap_number"].astype(int)) if not pit.empty else []
        if len(pit_laps) == len(g) - 1:
            ends = [*pit_laps, int(max(completed.get(drv, g.lap_end.max()), g.lap_end.max()))]
            starts = [1, *(p + 1 for p in pit_laps)]
            if list(g.lap_end) != ends[:-1] + [g.lap_end.iloc[-1]]:
                moved[drv] = (list(g.lap_end), ends)
            g["lap_start"], g["lap_end"] = starts, ends
        out.append(g)
    return pd.concat(out, ignore_index=True), moved


def lap_table(laps: pd.DataFrame, stints: pd.DataFrame, pit: pd.DataFrame,
              race_control: pd.DataFrame) -> pd.DataFrame:
    stints, _ = reconcile_stints(stints, pit, laps)
    t = laps.rename(columns={"lap_duration": "lap_time", "duration_sector_1": "s1",
                             "duration_sector_2": "s2", "duration_sector_3": "s3"})
    t = t[["driver_number", "lap_number", "date_start", "lap_time", "s1", "s2", "s3",
           "i1_speed", "i2_speed", "st_speed", "is_pit_out_lap"]].copy()

    st = stints[["driver_number", "stint_number", "lap_start", "lap_end", "compound", "tyre_age_at_start"]]
    t = t.merge(st, on="driver_number", how="left")
    t = t[(t.lap_number >= t.lap_start) & (t.lap_number <= t.lap_end)]
    t = t.drop_duplicates(["driver_number", "lap_number"], keep="last")
    t["tyre_age"] = t.tyre_age_at_start + t.lap_number - t.lap_start

    pit_in = set(zip(pit.driver_number, pit.lap_number, strict=True)) if not pit.empty else set()
    t["pit_in"] = [(d, n) in pit_in for d, n in zip(t.driver_number, t.lap_number, strict=True)]
    t["pit_out"] = t.is_pit_out_lap.fillna(False).astype(bool)
    t["neutralised"] = t.lap_number.isin(neutralised_laps(race_control))

    clean = (t.lap_number > 1) & ~t.pit_in & ~t.pit_out & ~t.neutralised & t.lap_time.notna()
    median = t[clean].groupby("driver_number").lap_time.transform("median")
    t["green"] = clean & (t.lap_time < OUTLIER_FACTOR * median.reindex(t.index))
    t["green"] = t["green"].fillna(False).astype(bool)
    cols = ["driver_number", "lap_number", "stint_number", "compound", "tyre_age", "lap_time",
            "s1", "s2", "s3", "i1_speed", "i2_speed", "st_speed", "date_start",
            "pit_in", "pit_out", "neutralised", "green"]
    return t[cols].sort_values(["driver_number", "lap_number"]).reset_index(drop=True)


def within_stint_slope(t: pd.DataFrame, x: str = "tyre_age", y: str = "lap_time") -> tuple[float, float, int]:
    """Slope of y on x with a separate intercept per driver stint. Returns (slope, stderr, n)."""
    g = t.groupby(["driver_number", "stint_number"])
    xc = t[x] - g[x].transform("mean")
    yc = t[y] - g[y].transform("mean")
    n, k = len(t), g.ngroups
    sxx = float((xc ** 2).sum())
    if n - k - 1 <= 0 or sxx == 0:
        return float("nan"), float("nan"), n
    slope = float((xc * yc).sum() / sxx)
    resid = yc - slope * xc
    stderr = float(np.sqrt((resid ** 2).sum() / (n - k - 1) / sxx))
    return slope, stderr, n
