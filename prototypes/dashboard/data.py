"""Telemetry dashboard prototype, data step: every car's fastest and typical lap as channels on one distance axis,
the lap sim's channels per team, the car-model parameter matrix with lap-time sensitivities, and session context.
Writes reports/11307/dashboard.json. Needs `parc-ferme debrief 11307` first."""

import json
import pickle
import warnings
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

warnings.filterwarnings("ignore")
from parc_ferme import warmup  # noqa: E402
from parc_ferme.core.car import Car, rules  # noqa: E402
from parc_ferme.core.track import FEED_UNITS_PER_M  # noqa: E402
from parc_ferme.paths import REPORTS  # noqa: E402
from parc_ferme.sim.model import circuit_model  # noqa: E402
from parc_ferme.session import Session  # noqa: E402
from parc_ferme.sim.lapsim import simulate, zone_mask  # noqa: E402

OUT = REPORTS / "11307"
D = json.loads((OUT / "debrief.json").read_text())
s = Session(11307)
t = warmup.laps(s)
model_cache = OUT / "dashboard_model.pkl"
if model_cache.exists():
    model = pickle.load(open(model_cache, "rb"))
else:
    model = circuit_model(s, Car(fuel_kg=20.0), t)
    pickle.dump(model, open(model_cache, "wb"))
ref = model.reference
L = float(np.median([c for c in [4633.0]]))  # median speed-integrated lap distance (lap_distance check)
DX = 10.0
XG = np.arange(0.0, L, DX)
N = len(XG)

# ---- every green lap placed on the reference line, all channels ----
cache = OUT / "dashboard_laps.pkl"
if cache.exists():
    grid = pickle.load(open(cache, "rb"))
else:
    tree = cKDTree(np.c_[ref.x, ref.y])
    loc = s.location[(s.location.x != 0) | (s.location.y != 0)]
    cd_by = {d: g.sort_values("date") for d, g in s.car_data.groupby("driver_number")}
    lo_by = {d: g.sort_values("date") for d, g in loc.groupby("driver_number")}
    grid = {}
    for w in t[t.green].itertuples():
        cd, lo = cd_by[w.driver_number], lo_by[w.driver_number]
        t0, t1 = w.date_start - pd.Timedelta(seconds=1), w.date_start + pd.Timedelta(seconds=w.lap_time + 1)
        c = cd[(cd.date > t0) & (cd.date < t1)]
        p = lo[(lo.date > t0) & (lo.date < t1)]
        if len(c) < 100 or len(p) < 100:
            continue
        tc = (c.date - w.date_start).dt.total_seconds().to_numpy()
        # corrected distance, as MoTeC and ATLAS build it: speed integrated over the lap, scaled to the lap length.
        # Smooth where position-feed timestamps jitter; the speed channel is right to 0.1% (speed_scale check).
        inside = (tc > 0) & (tc < w.lap_time)
        tt = np.r_[0.0, tc[inside], w.lap_time]
        vv = np.interp(tt, tc, c.speed.to_numpy(float)) / 3.6
        dist = np.r_[0.0, np.cumsum(0.5 * (vv[1:] + vv[:-1]) * np.diff(tt))]
        xx = dist / dist[-1] * L

        def ch(col, tt=tt, xx=xx, tc=tc, c=c):
            return np.interp(XG, xx, np.interp(tt, tc, c[col].to_numpy(float)))

        grid[(w.driver, int(w.lap_number))] = {
            "t": np.interp(XG, xx, tt), "v": ch("speed"), "thr": ch("throttle"), "brk": ch("brake"),
            "gear": ch("n_gear"), "rpm": ch("rpm"), "lap_time": float(w.lap_time),
            "s1": float(w.s1), "s2": float(w.s2), "s3": float(w.s3),
            "st": None if pd.isna(w.st_speed) else float(w.st_speed)}
    pickle.dump(grid, open(cache, "wb"))
print(len(grid), "green laps on the grid")


def num(v):
    return None if v is None or not np.isfinite(v) else float(v)


def q(a, scale=1.0):
    return [int(round(v * scale)) for v in a]


drivers = s.drivers.set_index("name_acronym")
cars = {}
for code in drivers.index:
    laps = {k: g for k, g in grid.items() if k[0] == code}
    if not laps:
        continue
    fast_key = min(laps, key=lambda k: laps[k]["lap_time"])
    fl = laps[fast_key]
    arr = {k: np.array([g[k] for g in laps.values()]) for k in ("v", "thr", "brk", "gear", "rpm")}
    v_med = np.median(arr["v"], 0)
    t_typ = np.r_[0.0, np.cumsum(DX / (0.5 * (v_med[1:] + v_med[:-1]) / 3.6))]
    t_end = t_typ[-1] + (L - XG[-1]) / (v_med[-1] / 3.6)
    # the median speed trace integrates to a time no lap actually took; scale it to the median lap from timing
    med_lap = float(np.median([g["lap_time"] for g in laps.values()]))
    t_typ = t_typ * med_lap / t_end
    t_end = med_lap
    secs = [np.nanmedian([g[k] for g in laps.values()]) for k in ("s1", "s2", "s3")]
    sts = [g["st"] for g in laps.values() if g["st"]]
    r = drivers.loc[code]
    cars[code] = {
        "name": f"{r.first_name} {r.last_name}", "last": r.last_name, "team": r.team_name,
        "colour": f"#{r.team_colour}", "number": int(r.driver_number),
        "fastest": {"lap": fast_key[1], "time": fl["lap_time"], "s": [num(fl[k]) for k in ("s1", "s2", "s3")], "st": fl["st"],
                    "ch": {"t": q(fl["t"], 1000), "v": q(fl["v"]), "thr": q(fl["thr"]), "brk": q(fl["brk"]),
                           "gear": q(fl["gear"]), "rpm": q(fl["rpm"], 0.1)}},
        "typical": {"laps": len(laps), "time": float(t_end), "s": [num(x) for x in secs],
                    "st": float(np.median(sts)) if sts else None,
                    "ch": {"t": q(t_typ, 1000), "v": q(v_med), "thr": q(np.median(arr["thr"], 0)),
                           "brk": q(np.mean(arr["brk"] > 50, 0) * 100), "gear": q(np.median(arr["gear"], 0)),
                           "rpm": q(np.median(arr["rpm"], 0), 0.1)}},
    }
best = {"s": [float(np.nanmin([g[k] for g in grid.values()])) for k in ("s1", "s2", "s3")],
        "lap": min(g["lap_time"] for g in grid.values())}
pb = {code: [num(np.nanmin([g[k] for kk, g in grid.items() if kk[0] == code])) for k in ("s1", "s2", "s3")]
      for code in cars}
for code in cars:
    cars[code]["pb"] = pb[code]
    cars[code]["pb_lap"] = min(g["lap_time"] for kk, g in grid.items() if kk[0] == code)

# ---- track: sectors, corners, straight-mode zones on the same distance axis ----
cf = model.corner_fraction
corner_s_ref = {n: f * ref.length for n, f in cf.items()}
zmask = zone_mask(ref, corner_s_ref, rules()["active_aero"]["zones"][str(s.meta["circuit_key"])])
fr = ref.s / ref.length
edges = np.flatnonzero(np.diff(np.r_[zmask[-1], zmask].astype(int)) != 0)
zones = []
on = bool(zmask[0])
starts = [i for i in range(len(zmask)) if zmask[i] and not zmask[i - 1]]
for i0 in starts:
    i1 = i0
    while zmask[(i1 + 1) % len(zmask)]:
        i1 = (i1 + 1) % len(zmask)
        if i1 == i0:
            break
    zones.append([float(fr[i0] * L), float(fr[i1] * L)])
sectors = [{"k": sec["sector"], "x0": sec["from"] * L, "x1": sec["to"] * L, "corners": sec["corners"]}
           for sec in D["sectors"]]
corners = [{"n": int(n), "x": float(f * L)} for n, f in sorted(cf.items())]

# ---- lap sim per team: field car scaled by each team's grip and downforce ----
field = D["grip"]["field"]
rho = D["conditions"]["air_density"]
sims = {}
ref_tree = cKDTree(np.c_[ref.x, ref.y])
for r in D["grip"]["teams"]:
    car = Car(fuel_kg=20.0, rho=rho, mu=field["mu"] * np.exp(r["mech_pct"] / 100),
              cla_corner=field["cla"] * np.exp(r["downforce_pct"] / 100))
    lap = simulate(model.line, car, model.zones)
    tr = lap.trace
    # place the sim lap on the reference line by position, as the real cars are placed, so corners line up
    _, j = ref_tree.query(np.c_[tr.x.to_numpy(), tr.y.to_numpy()])
    fsim = np.unwrap(ref.s[j] * 2 * np.pi / ref.length) * ref.length / (2 * np.pi) / ref.length
    fsim -= np.floor(fsim[0])
    x = np.clip(fsim, 0, 1) * L
    o = np.argsort(x)

    def g(col, scale=1.0, tr=tr, x=x, o=o):
        return q(np.interp(XG, x[o], tr[col].to_numpy(float)[o]), scale)

    tt = np.interp(XG, x[o], tr.t.to_numpy()[o])
    sims[r["team"]] = {"time": lap.lap_time, "mu": car.mu, "cla": car.cla_corner,
                       "deploy_mj": lap.deploy_mj, "harvest_mj": lap.harvest_mj,
                       "ch": {"t": q(tt, 1000), "v": g("v_kph"), "thr": g("throttle"), "brk": g("brake"),
                              "sm": g("straight_mode"), "dep": g("deploy_kw"), "reg": g("regen_kw"),
                              "soc": g("soc_mj", 100)}}

# ---- car model parameter matrix, with each parameter's lap-time effect for +1% ----
base = Car(fuel_kg=20.0, rho=rho, mu=field["mu"], cla_corner=field["cla"])
t_base = simulate(model.line, base, model.zones).lap_time
pu = base.rules["power_unit"]


def with_rule(car, key, factor):
    rr = json.loads(json.dumps(car.rules))
    rr["power_unit"][key] *= factor
    return replace(car, rules=rr)


matrix = [
    ("Tyre grip coefficient", "μ", base.mu, "", "Fitted", lambda c, k: replace(c, mu=c.mu * k)),
    ("Downforce, corner mode", "C_L·A", base.cla_corner, "m²", "Fitted", lambda c, k: replace(c, cla_corner=c.cla_corner * k)),
    ("Downforce, straight mode", "C_L·A", base.cla_straight, "m²", "Nominal", lambda c, k: replace(c, cla_straight=c.cla_straight * k)),
    ("Drag, corner mode", "C_D·A", base.cda_corner, "m²", "Nominal", lambda c, k: replace(c, cda_corner=c.cda_corner * k)),
    ("Drag, straight mode", "C_D·A", base.cda_straight, "m²", "Nominal", lambda c, k: replace(c, cda_straight=c.cda_straight * k)),
    ("Mass with 20 kg fuel", "m", base.mass, "kg", "Rules", lambda c, k: replace(c, fuel_kg=c.fuel_kg + (k - 1) * c.mass)),
    ("Combustion engine power", "P_ICE", pu["ice_kw"], "kW", "Rules", lambda c, k: with_rule(c, "ice_kw", k)),
    ("MGU-K power", "P_K", pu["mgu_k_kw"], "kW", "Rules", lambda c, k: with_rule(c, "mgu_k_kw", k)),
    ("Energy harvest per lap", "E", pu["harvest_per_lap_mj"], "MJ", "Rules", lambda c, k: with_rule(c, "harvest_per_lap_mj", k)),
    ("Driveline efficiency", "η", base.driveline_eff, "", "Nominal", lambda c, k: replace(c, driveline_eff=c.driveline_eff * k)),
    ("Rolling resistance", "C_rr", base.crr, "", "Nominal", lambda c, k: replace(c, crr=c.crr * k)),
    ("Air density", "ρ", rho, "kg/m³", "Measured", lambda c, k: replace(c, rho=c.rho * k)),
]
params = []
for name, sym, value, unit, source, bump in matrix:
    tl = simulate(model.line, bump(base, 1.01), model.zones).lap_time
    params.append({"name": name, "sym": sym, "value": float(value), "unit": unit, "source": source,
                   "effect_s": float(tl - t_base)})
    print(f"{name:28} {value:9.3f} {unit:6} {source:9} {tl - t_base:+.3f} s")

# ---- map in display coordinates (from the debrief), indexed by distance ----
mp = D["track"]
out = {
    "session": D["session"], "conditions": D["conditions"], "podium": D["podium"],
    "L": L, "dx": DX, "n": N, "sectors": sectors, "corners": corners, "zones": zones,
    "map": {"x": mp["x"], "y": mp["y"], "corners": mp["corners"], "lines": mp["lines"]},
    "cars": cars, "best": best, "sims": sims, "sim_base_time": t_base, "params": params,
    "pace": D["pace"], "grip": D["grip"], "checks": D["checks"], "bench": D["bench"],
    "pace_bench": D["pace_bench"], "code": D["code"],
}
def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, np.integer):
        return int(o)
    return o


(OUT / "dashboard.json").write_text(json.dumps(clean(out), separators=(",", ":"), allow_nan=False))
print("written", (OUT / "dashboard.json").stat().st_size // 1024, "KB;", len(cars), "cars")
