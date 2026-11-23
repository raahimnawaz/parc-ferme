"""Lap-by-lap S5 estimates and their validation for the session document."""

from dataclasses import replace

import numpy as np
import pandas as pd

from ..bench import state as bench
from ..models.state import MAX_BRIDGE_S, MAX_GAP_S, estimate_fuel, gap_bridges, interval, smooth
from ..sim.lapsim import simulate
from .channels import distance_clock


def held_speed_errors(t, v):
    """Remove every seventh observation; interpolate neighbouring fitted speeds at the withheld times."""
    omit = np.arange(3, len(t)-1, 7)
    keep = np.ones(len(t), bool)
    keep[omit] = False
    ts, vs = t[keep], v[keep]
    fit, _ = smooth(ts, vs)
    j = np.searchsorted(ts, t[omit])
    ok = (ts[j]-ts[j-1] <= MAX_GAP_S) & np.isfinite(fit[j]) & np.isfinite(fit[j-1])
    pred = np.interp(t[omit[ok]], ts, fit)
    baseline = np.interp(t[omit[ok]], ts, vs)
    return abs(3.6*pred-v[omit[ok]]), abs(baseline-v[omit[ok]])


def study(car_data, laps, model, car, car_model):
    audit = bench.run()
    mass = next(row for row in car_model["params"] if row["sym"] == "m")
    slope = mass["effect_s"] / (.01*mass["value"])
    def lap_time(load):
        return simulate(model.line, replace(car, fuel_kg=load), model.zones).lap_time

    effect = bench.mass_effect(lap_time, slope, audit["fuel_scale"])
    # Check the local mass response independently at light, mid-race and heavy loads.
    # A 5 kg finite difference is less sensitive to deployment-threshold kinks than a 1 kg bump.
    slopes = {}
    for kg in (5, 35, 60):
        slopes[kg] = (lap_time(kg+5)-lap_time(kg))/5

    sample_groups = {d: g.sort_values("date").drop_duplicates("date") for d, g in car_data.groupby("driver_number")}
    drivers, errors, baseline_errors, green = {}, [], [], []
    timed = estimated = 0
    for code, group in laps.groupby("driver"):
        g = sample_groups.get(group.driver_number.iloc[0])
        rows = []
        previous = 0
        cumulative = 0.
        for lap in group.sort_values("lap_number").itertuples():
            number = int(lap.lap_number)
            flags = ("pit in" if lap.pit_in else "pit out" if lap.pit_out else "green" if lap.green else "other")
            row = dict(lap=number, stint=int(lap.stint_number), compound=str(lap.compound), phase=flags,
                       burn=None, gain_ms=None, start_gain_s=None, trace=None)
            rows.append(row)
            if number != previous+1:
                cumulative = np.nan
            previous = number
            if pd.isna(lap.date_start) or not np.isfinite(lap.lap_time) or lap.lap_time <= 0:
                cumulative = np.nan
                row["status"] = "No complete timing"
                continue
            timed += 1
            row["duration_ms"] = round(float(lap.lap_time)*1000)
            if g is None:
                cumulative = np.nan
                row["status"] = "No car data"
                continue
            start, duration = lap.date_start, lap.lap_time
            left, right = g.date.searchsorted([start-pd.Timedelta(seconds=MAX_GAP_S),
                                               start+pd.Timedelta(microseconds=round(1e6*(duration+MAX_GAP_S)))])
            c = g.iloc[left:right]
            t = (c.date-start).dt.total_seconds().to_numpy()
            kg, coverage, profile = estimate_fuel(t, c.throttle.to_numpy(), c.rpm.to_numpy(), duration,
                                                  with_profile=True)
            row["coverage"] = coverage
            if kg is None:
                cumulative = np.nan
                row["status"] = "Insufficient throttle/RPM coverage"
            else:
                burn = interval(kg, audit["fuel_scale"])
                row.update(profile=profile, burn=burn, gain_ms=interval(np.asarray(burn)*1000*slope, effect["factor"]),
                           start_gain_s=None if not np.isfinite(cumulative) else slope*cumulative)
                cumulative += burn[1]
                estimated += 1
                if lap.green:
                    green.append(burn[1])
            inside = (t >= 0) & (t <= duration)
            ti, v = t[inside], c.speed.to_numpy(float)[inside]
            _, accel = smooth(ti, v)
            if np.any(np.isfinite(accel)):
                # Missing values at the ends of each observed segment break the displayed line.
                row["trace"] = dict(ms=np.rint(1000*ti).astype(int).tolist(),
                                    cg=[int(round(100*a)) if np.isfinite(a) else None for a in accel])
                row["trace"]["bridges"] = gap_bridges(ti, v, accel)
                if (lap.green and np.max(np.diff(t)) <= MAX_BRIDGE_S and t[0] <= MAX_GAP_S
                        and t[-1] >= duration-MAX_GAP_S and np.isfinite(c.speed).all()):
                    dist, times = distance_clock(t, c.speed.to_numpy(float), duration)
                    if dist[-1] > 0:
                        fractions = [f for _, f in sorted(model.corner_fraction.items())]
                        row["corner_ms"] = np.rint(1000*np.interp(fractions, dist/dist[-1], times)).astype(int).tolist()
                err, base = held_speed_errors(ti, v)
                errors.extend(err)
                baseline_errors.extend(base)
        drivers[code] = rows
    return dict(drivers=drivers, audit=audit, effect_audit=effect, timed_laps=timed, estimated_laps=estimated,
                green_laps=len(green),
                typical_green_kg=float(np.median(green)) if green else None, mass_s_per_kg=slope,
                mass_checks=slopes, held_speed_mae_kph=float(np.mean(errors)) if errors else None,
                held_speed_samples=len(errors), held_linear_mae_kph=float(np.mean(baseline_errors)) if errors else None)
