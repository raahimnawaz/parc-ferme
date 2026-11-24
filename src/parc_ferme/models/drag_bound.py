"""Upper bound on each car's straight-mode drag area from untowed running where the MGU-K may not propel it.

From 345 km/h the ERS-K may not drive the car (FIA C5.2.8 i; from 355 km/h with Overtake active, C5.2.8 ii), so at
full throttle the wheels get at most eta * P_ICE plus whatever the curve still allows. Harvesting, part load, a weaker
engine or a heavier car only lower the drag a run implies, so over a run

    CdA <= (sum eta (P_ICE + P_K(v)) dt - m (dv^2/2 + g dz + g crr d)) / (rho/2 sum (v - w)^2 v dt)

holds with every unknown at its loosening value (LIMITS), wind w taken as a full tailwind at the station's highest
reading. A car closer than TOW_GAP_S behind another is left out: a tow lowers its drag below its own. Overtake is
active on a lap only if the car crossed the Detection Line less than the Detection Gap behind another car (Sporting
B7.2.3 c). The line's position isn't public, so a run counts as normal mode only when the car stayed more than
DETECTION_GAP_S behind every car for CLEAR_LAPS laps before it; otherwise the Overtake curve is allowed.
"""

import numpy as np
import pandas as pd

from .. import warmup
from ..core.car import G, air_density
from ..core.ers import LIMIT_KW, deploy_fraction_array
from ..core.track import driven_line
from ..telemetry import placed_samples

LIMITS = dict(
    ice_kw=430.0,         # estimate, not a rule: 51.6% brake efficiency on the 3000 MJ/h fuel flow (C5.2.3)
    driveline_eff=0.97,
    crr=0.008,
    mass_kg=(768.0, 848.0),  # minimum car (C4.1, press figure) to minimum plus more fuel than a race starts with
    speed_step_kph=1.0,   # the speed channel is whole km/h
)
MIN_KPH = 345.0
TOW_GAP_S = 3.0
DETECTION_GAP_S = 1.0     # secondary sources; the FIA sets it per circuit (Sporting B7.2.1 b vii)
CLEAR_LAPS = 1.5


def bound(t, v, z, wind_ms, rho, overtake=False, limits=LIMITS):
    """Loosest drag area [m²] consistent with one full-throttle run sampled at times t [s], speeds v [m/s]."""
    t, v, z = (np.asarray(x, float) for x in (t, v, z))
    q = limits["speed_step_kph"] / 3.6
    dt = np.diff(t)
    slow = np.maximum((v[1:] + v[:-1]) / 2 - q, 0.0)
    drive = limits["driveline_eff"] * 1e3 * (limits["ice_kw"] + LIMIT_KW * deploy_fraction_array(slow, overtake))
    v0, v1 = v[0] + q, max(v[-1] - q, 0.0)
    per_kg = (v1**2 - v0**2) / 2 + G * (z[-1] - z[0]) + G * limits["crr"] * np.sum(slow * dt)
    light, heavy = limits["mass_kg"]
    used = (light if per_kg > 0 else heavy) * per_kg
    air = rho / 2 * np.sum(np.maximum(slow - wind_ms, 0.0) ** 2 * slow * dt)
    return (np.sum(drive * dt) - used) / air


def road_gaps(tracks, driver, t, s, length):
    """Seconds since another car was last at the same point of the lap: the time gap to the car ahead on the road,
    whatever lap it is on. `tracks` maps each driver to (time, race distance) arrays, both increasing."""
    t, s = np.asarray(t, float), np.asarray(s, float)
    gap = np.full(len(t), np.inf)
    for other, (to, ro) in tracks.items():
        if other == driver:
            continue
        at = np.interp(t, to, ro)
        target = s + np.floor((at - s) / length) * length
        seen = (t >= to[0]) & (t <= to[-1]) & (target >= ro[0])
        gap = np.where(seen, np.minimum(gap, t - np.interp(target, ro, to)), gap)
    return gap


def runs(session, limits=LIMITS):
    """Every untowed full-throttle run above MIN_KPH, with its drag-area bound."""
    laps = warmup.laps(session)
    loc = session.location
    ref, _ = driven_line(session.circuit.name, loc[(loc.x != 0) | (loc.y != 0)], laps[laps.green])
    length = ref.length
    timed = laps[np.isfinite(laps.lap_time) & laps.date_start.notna()]
    samples = placed_samples(session.car_data, loc, timed, ref)
    samples = samples.merge(timed[["driver_number", "lap_number", "date_start"]], on=["driver_number", "lap_number"])
    origin = samples.date_start.min()
    samples["clock"] = (samples.date_start - origin).dt.total_seconds() + samples.t
    samples = samples[samples.t >= 0].sort_values(["driver_number", "clock"], ignore_index=True)
    samples["race_s"] = (samples.lap_number - 1) * length + samples.s
    tracks = {d: (g.clock.to_numpy(), np.maximum.accumulate(g.race_s.to_numpy()))
              for d, g in samples.groupby("driver_number")}
    lap_s = laps[laps.green].groupby("driver_number").lap_time.median()
    wx = session.weather
    rho = min(air_density(r.pressure, r.air_temperature, r.humidity) for r in wx.itertuples())
    wx_clock = (wx.date - origin).dt.total_seconds().to_numpy()
    rows = []
    for (number, lap), g in samples.groupby(["driver_number", "lap_number"]):
        fast = ((g.v * 3.6 >= MIN_KPH) & (g.throttle >= 99) & (g.brake == 0)).to_numpy()
        if fast.sum() < 2:
            continue
        gap = np.full(len(g), np.nan)
        gap[fast] = road_gaps(tracks, number, g.clock.to_numpy()[fast], g.s.to_numpy()[fast], length)
        idx = np.flatnonzero(fast & (gap > TOW_GAP_S))
        for run in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1):
            r = g.iloc[run]
            if len(run) < 2 or r.t.iloc[-1] - r.t.iloc[0] < 0.4:
                continue
            start = r.clock.iloc[0]
            since = start - CLEAR_LAPS * lap_s.get(number, lap_s.max())
            mine = samples[(samples.driver_number == number) & samples.clock.between(since, start)]
            clear = road_gaps(tracks, number, mine.clock, mine.s, length).min()
            near = np.abs(wx_clock - start) <= 180
            wind = float(wx.wind_speed[near].max() if near.any() else wx.wind_speed.max())
            overtake = not clear > DETECTION_GAP_S
            rows.append(dict(driver=r.driver.iloc[0], team=r.team.iloc[0], lap=int(lap), samples=len(run),
                             duration_s=float(r.t.iloc[-1] - r.t.iloc[0]), entry_kph=float(r.v.iloc[0] * 3.6),
                             exit_kph=float(r.v.iloc[-1] * 3.6), max_kph=float(r.v.max() * 3.6),
                             gap_s=float(gap[run].min()), clear_s=float(clear), overtake_possible=overtake,
                             wind_ms=wind, rho_kg_m3=rho,
                             bound_m2=float(bound(r.clock, r.v, np.interp(r.s, ref.s, ref.z, period=length), wind,
                                                    rho, overtake, limits))))
    return pd.DataFrame(rows)


def per_car(run_table):
    """The tightest bound each car reached, every run being a valid bound on its own."""
    if run_table.empty:
        return run_table
    best = run_table.loc[run_table.groupby("driver").bound_m2.idxmin()]
    counts = run_table.groupby("driver").size().rename("runs")
    return best.set_index("driver").join(counts).reset_index()
