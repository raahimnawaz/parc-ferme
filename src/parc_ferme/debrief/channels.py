"""Channels for the lap-analysis workspace: every car's fastest and typical lap on one distance axis, the lap sim's
channels for each team's car, and the sim car's parameters with the lap-time effect of each.

Distance is corrected distance, as MoTeC and ATLAS build it: speed integrated over the lap and scaled to the lap
length. The speed channel is right to 0.1% (the speed_scale check), while the position feed's timestamps jitter.
Channels are stored as integers: time in ms, speed in km/h, throttle and brake in %, gear, engine speed in 10 rpm.
"""

import copy
from dataclasses import replace

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from ..core.car import Car
from ..sim.lapsim import simulate

DX_M = 10.0
SIM_FUEL_KG = 20.0
CHANNELS = {"v": "speed", "thr": "throttle", "brk": "brake", "gear": "n_gear", "rpm": "rpm"}
SCALE = {"t": 1000, "rpm": 0.1}
MIN_SAMPLES = 100
EDGE_S = 1.0  # car data taken this far either side of the lap, so its ends interpolate


def _num(v) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def _pack(ch: dict) -> dict:
    return {k: np.rint(np.asarray(a) * SCALE.get(k, 1)).astype(int).tolist() for k, a in ch.items()}


def grid(length_m: float, dx: float = DX_M) -> np.ndarray:
    return np.arange(0.0, length_m, dx)


def distance_clock(t, speed_kph, duration):
    """Cumulative distance and elapsed time at the timing lines and interior speed samples."""
    inside = (t > 0) & (t < duration)
    tt = np.r_[0., t[inside], duration]
    v = np.interp(tt, t, speed_kph) / 3.6
    return np.r_[0., np.cumsum(.5*(v[1:] + v[:-1])*np.diff(tt))], tt


def lap_grid(car_data: pd.DataFrame, laps: pd.DataFrame, length_m: float, dx: float = DX_M) -> dict:
    """Every green lap's channels on the distance grid, keyed (driver, lap number), with its timing. `t` is the
    time into the lap [s]."""
    xg = grid(length_m, dx)
    by = {d: g.sort_values("date") for d, g in car_data.groupby("driver_number")}
    out = {}
    for w in laps[laps.green].itertuples():
        g = by.get(w.driver_number)
        if g is None or pd.isna(w.date_start) or not np.isfinite(w.lap_time):
            continue
        i0, i1 = g.date.searchsorted([w.date_start - pd.Timedelta(seconds=EDGE_S),
                                      w.date_start + pd.Timedelta(seconds=w.lap_time + EDGE_S)])
        c = g.iloc[i0:i1]
        if len(c) < MIN_SAMPLES:
            continue
        tc = (c.date - w.date_start).dt.total_seconds().to_numpy()
        dist, tt = distance_clock(tc, c.speed.to_numpy(float), w.lap_time)
        if dist[-1] <= 0:
            continue
        xx = dist / dist[-1] * length_m
        lap = {"t": np.interp(xg, xx, tt)}
        for k, col in CHANNELS.items():
            lap[k] = np.interp(xg, xx, np.interp(tt, tc, c[col].to_numpy(float)))
        lap |= {"lap_time": float(w.lap_time), "s": [_num(w.s1), _num(w.s2), _num(w.s3)], "st": _num(w.st_speed)}
        out[(w.driver, int(w.lap_number))] = lap
    return out


def car_laps(laps_on_grid: dict, length_m: float, dx: float = DX_M) -> dict:
    """Per driver: the fastest lap, the typical lap (every green lap's channels, median point by point) and the
    driver's best lap and sector times."""
    xg = grid(length_m, dx)
    by: dict[str, dict] = {}
    for (code, n), lap in laps_on_grid.items():
        by.setdefault(code, {})[n] = lap
    out = {}
    for code, laps in by.items():
        n_fast = min(laps, key=lambda n: laps[n]["lap_time"])
        fast = laps[n_fast]
        stack = {k: np.array([lap[k] for lap in laps.values()]) for k in CHANNELS}
        times = np.array([lap["lap_time"] for lap in laps.values()])
        sectors = np.array([[np.nan if x is None else x for x in lap["s"]] for lap in laps.values()])
        traps = [lap["st"] for lap in laps.values() if lap["st"] is not None]
        v = np.median(stack["v"], 0)
        # the median speed trace integrates to a time no lap took: scale it to the median lap from timing
        t = np.r_[0.0, np.cumsum(dx / (0.5 * (v[1:] + v[:-1]) / 3.6))]
        median_lap = float(np.median(times))
        t *= median_lap / (t[-1] + (length_m - xg[-1]) / (v[-1] / 3.6))
        out[code] = {
            "fastest": {"lap": n_fast, "time": fast["lap_time"], "s": fast["s"], "st": fast["st"],
                        "ch": _pack({k: fast[k] for k in ("t", *CHANNELS)})},
            "typical": {"laps": len(laps), "time": median_lap,
                        "s": [_num(x) for x in np.nanmedian(sectors, 0)],
                        "st": float(np.median(traps)) if traps else None,
                        "ch": _pack({"t": t, "v": v, "thr": np.median(stack["thr"], 0),
                                     "brk": 100 * np.mean(stack["brk"] > 50, 0), "gear": np.median(stack["gear"], 0),
                                     "rpm": np.median(stack["rpm"], 0)})},
            "pb": [_num(x) for x in np.nanmin(sectors, 0)],
            "pb_lap": float(times.min()),
        }
    return out


def zone_spans(mask: np.ndarray, frac: np.ndarray) -> list[list[float]]:
    """[start, end] lap fractions of each run of True in a closed-loop mask. A run across the line ends before it
    starts."""
    if mask.all():
        return [[0.0, 1.0]]
    starts = np.flatnonzero(mask & ~np.roll(mask, 1))
    ends = np.flatnonzero(mask & ~np.roll(mask, -1))
    return [[float(frac[i]), float(frac[ends[ends >= i][0] if (ends >= i).any() else ends[0]])] for i in starts]


def team_sims(model, teams: list[dict], field_car: Car, length_m: float, dx: float = DX_M) -> dict:
    """Each team's car in the lap sim, the field car with the team's grip and downforce, placed on the distance
    axis by position as the real cars are, so the corners line up."""
    xg = grid(length_m, dx)
    ref = model.reference
    tree = cKDTree(np.c_[ref.x, ref.y])
    out = {}
    for r in teams:
        car = replace(field_car, mu=field_car.mu * np.exp(r["mech_pct"] / 100),
                      cla_corner=field_car.cla_corner * np.exp(r["downforce_pct"] / 100))
        lap = simulate(model.line, car, model.zones)
        tr = lap.trace
        _, j = tree.query(np.c_[tr.x.to_numpy(), tr.y.to_numpy()])
        f = np.unwrap(ref.s[j] * 2 * np.pi / ref.length) / (2 * np.pi)
        f -= np.floor(f[0])
        x = np.clip(f, 0.0, 1.0) * length_m
        o = np.argsort(x, kind="stable")

        def on_grid(col, x=x[o], tr=tr.iloc[o]):
            return np.interp(xg, x, tr[col].to_numpy(float))

        ch = {"t": on_grid("t"), "v": on_grid("v_kph"), "thr": on_grid("throttle"), "brk": on_grid("brake"),
              "sm": on_grid("straight_mode"), "dep": on_grid("deploy_kw"), "reg": on_grid("regen_kw"),
              "soc": 100 * on_grid("soc_mj")}
        out[r["team"]] = {"time": lap.lap_time, "mu": car.mu, "cla": car.cla_corner, "deploy_mj": lap.deploy_mj,
                          "harvest_mj": lap.harvest_mj, "ch": _pack(ch)}
    return out


def _with_power_unit(car: Car, key: str, factor: float) -> Car:
    rules = copy.deepcopy(car.rules)
    rules["power_unit"][key] *= factor
    return replace(car, rules=rules)


def parameter_effects(line, zones: np.ndarray, car: Car) -> dict:
    """The sim car's parameters, where each value comes from, and the lap-time change for +1% on each."""
    base = simulate(line, car, zones)
    pu = car.rules["power_unit"]
    rows = [
        ("Tyre grip coefficient", "μ", car.mu, "", "Fitted", lambda c, k: replace(c, mu=c.mu * k)),
        ("Downforce, corner mode", "C_L·A", car.cla_corner, "m²", "Fitted",
         lambda c, k: replace(c, cla_corner=c.cla_corner * k)),
        ("Downforce, straight mode", "C_L·A", car.cla_straight, "m²", "Nominal",
         lambda c, k: replace(c, cla_straight=c.cla_straight * k)),
        ("Drag, corner mode", "C_D·A", car.cda_corner, "m²", "Nominal",
         lambda c, k: replace(c, cda_corner=c.cda_corner * k)),
        ("Drag, straight mode", "C_D·A", car.cda_straight, "m²", "Nominal",
         lambda c, k: replace(c, cda_straight=c.cda_straight * k)),
        (f"Mass with {car.fuel_kg:g} kg fuel", "m", car.mass, "kg", "Rules",
         lambda c, k: replace(c, fuel_kg=c.fuel_kg + (k - 1) * c.mass)),
        ("Combustion engine power", "P_ICE", pu["ice_kw"], "kW", "Rules",
         lambda c, k: _with_power_unit(c, "ice_kw", k)),
        ("MGU-K power", "P_K", pu["mgu_k_kw"], "kW", "Rules", lambda c, k: _with_power_unit(c, "mgu_k_kw", k)),
        ("Energy harvest per lap", "E", pu["harvest_per_lap_mj"], "MJ", "Rules",
         lambda c, k: _with_power_unit(c, "harvest_per_lap_mj", k)),
        ("Driveline efficiency", "η", car.driveline_eff, "", "Nominal",
         lambda c, k: replace(c, driveline_eff=c.driveline_eff * k)),
        ("Rolling resistance", "C_rr", car.crr, "", "Nominal", lambda c, k: replace(c, crr=c.crr * k)),
        ("Air density", "ρ", car.rho, "kg/m³", "Measured", lambda c, k: replace(c, rho=c.rho * k)),
    ]
    params = []
    for name, sym, value, unit, source, bump in rows:
        effect = simulate(line, bump(car, 1.01), zones).lap_time - base.lap_time
        params.append({"name": name, "sym": sym, "value": float(value), "unit": unit, "source": source,
                       "effect_s": float(effect), "note": None})
    if base.harvest_mj < pu["harvest_per_lap_mj"]:
        harvest = next(p for p in params if p["sym"] == "E")
        harvest["note"] = f"not reached: the sim harvests {base.harvest_mj:.1f} MJ, only under braking (S4)"
    return {"fuel_kg": car.fuel_kg, "base_lap_s": base.lap_time, "params": params}


def telemetry(car_data: pd.DataFrame, laps: pd.DataFrame, model, sectors: list[dict], teams: list[dict],
              field_car: Car, length_m: float, dx: float = DX_M) -> dict:
    """Everything the lap-analysis workspace draws, on one distance grid of `length_m` (the speed-integrated lap)."""
    on_grid = lap_grid(car_data, laps, length_m, dx)
    line = model.line
    sector_times = np.array([[np.nan if x is None else x for x in lap["s"]] for lap in on_grid.values()])
    return {
        "L": length_m, "dx": dx, "n": len(grid(length_m, dx)), "green_laps": len(on_grid),
        "sectors": [{"k": s["sector"], "x0": s["from"] * length_m, "x1": s["to"] * length_m,
                     "corners": s["corners"]} for s in sectors],
        "corners": [{"n": int(n), "x": f * length_m} for n, f in sorted(model.corner_fraction.items())],
        "zones": [[a * length_m, b * length_m] for a, b in zone_spans(model.zones, line.s / line.length)],
        "laps": car_laps(on_grid, length_m, dx),
        "best": {"s": [_num(x) for x in np.nanmin(sector_times, 0)],
                 "lap": min(lap["lap_time"] for lap in on_grid.values())},
        "sims": team_sims(model, teams, field_car, length_m, dx),
    }
