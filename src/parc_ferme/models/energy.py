"""S4 straight-line work balance. All powers are at the wheels, averaged over a window."""

import numpy as np
import pandas as pd
from scipy.integrate import trapezoid

from .. import warmup
from ..core.car import Car, G, air_density, rules
from ..core.track import Registration, driven_line
from ..sim.lapsim import zone_mask
from ..telemetry import placed_samples


def power_balance(t, v, z, car):
    """Return wheel kW before aero and extra kW per m² of effective drag area in still air."""
    dt = np.diff(t)
    duration = t[-1] - t[0]
    distance = np.sum(dt * (v[1:] + v[:-1]) / 2)
    kinetic = car.mass * (v[-1] ** 2 - v[0] ** 2) / 2
    road = car.mass * G * (z[-1] - z[0] + car.crr * distance)
    aero = car.rho / 2 * np.sum(dt * (v[1:] ** 3 + v[:-1] ** 3) / 2)
    return (kinetic + road) / duration / 1000, aero / duration / 1000


def windows(samples, ref, zones, car):
    """Disjoint stretches inside one zone and pedal phase. Skip transitions and feed gaps."""
    position = samples.s.to_numpy()
    zone = zones[np.rint(position / ref.ds).astype(int) % len(zones)]
    pedal = np.select([samples.throttle.between(99, 100), samples.throttle == 0], [1, 2])
    phase = np.where((samples.brake == 0) & (zone > 0), pedal, 0)
    t, v = samples.t.to_numpy(), samples.v.to_numpy()
    z = np.interp(position, ref.s, ref.z, period=ref.length)
    dt = np.diff(t)
    breaks = (np.diff(phase) != 0) | (np.diff(zone) != 0) | (dt > 0.55) | (dt <= 0)
    rows = []
    for group in np.split(np.arange(len(t)), np.flatnonzero(breaks) + 1):
        i, last = group[0], group[-1]
        if not phase[i]:
            continue
        while t[last] - t[i] >= 1.5:
            j = i + np.searchsorted(t[i:last + 1] - t[i], 1.5)
            base, slope = power_balance(t[i:j + 1], v[i:j + 1], z[i:j + 1], car)
            rows.append(dict(zone=int(zone[i]), phase="full throttle" if phase[i] == 1 else "coast",
                             start_s=t[i], end_s=t[j], entry_kph=v[i] * 3.6, exit_kph=v[j] * 3.6,
                             base_kw=base, drag_kw_per_m2=slope, entry_m=position[i],
                             track_m=ref.length, grade=(z[j] - z[i]) / trapezoid(v[i:j + 1], t[i:j + 1]),
                             cap_kw=trapezoid(car.mguk_limit_w(v[i:j + 1]), t[i:j + 1])
                             / (t[j] - t[i]) / 1000))
            i = j
    return rows


def held_out(lap):
    """Three consecutive race laps per 15, common to all cars, fixed before fitting."""
    return ((lap - 7) % 15) < 3


def analyse(session, fuel_kg, *, multi_lap=False, battery_laps=None):
    """Straight windows on fastest or all green laps. Reserve three-lap blocks for validation."""
    config = rules()["active_aero"]["zones"].get(str(session.meta["circuit_key"]))
    if not config:
        raise ValueError("no straight-mode zones configured for this circuit")
    if session.meta["year"] != 2026 or not np.isfinite(fuel_kg) or fuel_kg < 0:
        raise ValueError("S4 requires a 2026 session and a finite nonnegative fuel load")
    laps = warmup.laps(session)
    green = laps[laps.green]
    loc = session.location
    geometry_laps = green[~held_out(green.lap_number)] if multi_lap else green
    ref, _ = driven_line(session.circuit.name, loc[(loc.x != 0) | (loc.y != 0)], geometry_laps)
    corners = session.circuit.corners
    s, _ = Registration.identity().project(ref, corners.x_m.to_numpy(), corners.y_m.to_numpy())
    apex = dict(zip(corners.number, s, strict=True))
    zones = np.zeros(len(ref.s), int)
    for number, pair in enumerate(config, 1):
        zones[zone_mask(ref, apex, [pair])] = number
    wx = session.weather
    car = Car(fuel_kg=fuel_kg, rho=air_density(wx.pressure.median(), wx.air_temperature.median(), wx.humidity.median()))
    selected = green if multi_lap else green.loc[green.groupby("driver_number").lap_time.idxmin()]
    samples = placed_samples(session.car_data, loc, selected, ref)
    durations = selected.set_index(["driver", "lap_number"]).lap_time
    records = []
    for (driver, lap), group in samples.groupby(["driver", "lap_number"]):
        straight = windows(group, ref, zones, car)
        if battery_laps is not None:
            from .battery import segments

            battery_laps[driver, lap] = segments(group, ref, straight, car, durations.loc[driver, lap])
        for row in straight:
            row["zone_id"] = row["zone"]
            pair = config[row["zone"] - 1]
            row["zone"] = "–".join(map(str, pair))
            records.append(dict(driver=driver, lap=lap, fuel_kg=fuel_kg, rho_kg_m3=car.rho, crr=car.crr, **row))
    return pd.DataFrame(records)
