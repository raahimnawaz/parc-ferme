"""Does the shape of each run identify drag where the window balance can't?

Runs the S4 bench's own synthetic cars (same seeds, strategies, sampling and held-out laps),
fits the shape model on the same full-throttle windows, and calibrates and audits its
intervals with the same split-conformal rule, so both estimators are scored on identical cars.

Two options change the synthetic cars, for both estimators alike: `fine` integrates the same
dynamics in 2.5 ms substeps instead of one 50 ms Euler step, and `gears` adds the gear channel
the real feed carries (the bench's shift is the power dip it already draws at 70–70.8 m/s).
"""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

from ..core.car import G
from ..models import drag_shape
from . import energy as bench


@njit(cache=True)
def drive_sector_fine(entry, soc, recovered, mass, ice, grade, aero, wind, strength, knee, harvest, lift, mode,
                      apex, dt, capacity, budget, eta, regen, machine, taper_start, taper_end):
    """`bench.energy.drive_sector` with its speed integrated in 20 substeps per step.

    Power-unit decisions and the store stay per 50 ms step, exactly as there; only the speed
    and distance integration is refined, including where the shift dip starts and ends."""
    v, s, energy = np.empty(341), np.zeros(341), np.zeros(341)
    v[0] = entry
    sub = 20
    h = dt / sub
    for i in range(340):
        time, speed = i*dt, v[i]
        cap = machine * min(1., max(0., (taper_end-speed)/(taper_end-taper_start)))
        if mode == 0:
            k = strength*cap*(time < knee)
        elif mode == 1:
            k = strength*cap*min(1., max(0., 1-(time-knee)/3))
        elif mode == 2:
            k = strength*cap if time < knee else -harvest
        else:
            k = cap*(.35+.18*np.sin((time-knee)/2))
        resistance = aero*(speed+wind)**2 + mass*G*grade
        engine = ice
        if time >= lift:
            k, engine = -harvest, 0.
        braking = 10.5 <= time < 14.
        decel = 0.
        if braking:
            decel = min(0., (apex-speed)/(14.-time))
            k = -min(machine, max(0., -(mass*decel+resistance)*speed/1000)/eta)
        if time >= 14.:
            k, engine = .22*cap, .75*ice
        k = min(soc*1000/dt, max(k, -max(0., min(budget-recovered, capacity-soc))*1000/(dt*regen)))
        gained = max(0., -k)*regen*dt/1000
        soc = max(0., soc+gained-max(k, 0.)*dt/1000)
        recovered += gained
        u, dist = speed, 0.
        for _ in range(sub):
            power = engine*(1-.35*(70 < u < 70.8)) if time < lift else engine
            accel = (eta*(power+k)*1000/u-(aero*(u+wind)**2 + mass*G*grade))/mass
            if braking:
                accel = min(accel, decel)
            nxt = u + h*accel
            dist += .5*h*(u+nxt)
            u = nxt
        v[i+1] = u
        s[i+1] = s[i]+dist
        energy[i+1] = energy[i]+dt*k
    return v, s, energy, soc, recovered


def _truth_cda(seed):
    rng = np.random.default_rng(seed)
    rng.integers(8, 46)
    return float(rng.uniform(.55, 1.25))


def car(job):
    """One synthetic car: the window-balance fit as the bench runs it, and the shape fit."""
    seed, strategy, fine, gears = job[:4]
    oracle = len(job) > 4 and job[4]
    captured, store, sectors = [], {}, []
    windows, profile, sector = bench.windows, bench.profile, bench.drive_sector

    def spy_windows(sample, ref, mask, car):
        if gears:
            sample = sample.assign(gear=7 + (sample.v > 70.4).astype(int))
        rows = windows(sample, ref, mask, car)
        captured.append((sample, ref, rows))
        return rows

    def spy_profile(data, car, parts, linked=False):
        store.update(data=data, car=car)
        return profile(data, car, parts, linked=linked)

    generator = drive_sector_fine if fine else sector

    def spy_sector(*args):
        sectors.append(dict(mass=args[3], aero=args[6], wind=args[7]))
        return generator(*args)

    bench.windows, bench.profile, bench.drive_sector = spy_windows, spy_profile, spy_sector
    try:
        baseline = bench.experiment(seed, strategy, paired=False)
    finally:
        bench.windows, bench.profile, bench.drive_sector = windows, profile, sector
    cda = _truth_cda(seed)
    vehicle = store["car"]
    curves, laps, zones = [], [], []
    known = [], [], []
    lap_ids = np.arange(1, len(sectors) // 4 + 1)
    trained = [dict(c, zone=k % 4) for k, c in enumerate(sectors) if not bench.held_out(lap_ids[k // 4])]
    still = .5 * vehicle.rho * cda
    zone_wind = pd.DataFrame(trained).groupby("zone").wind.mean() if trained else None
    for (sample, ref, rows), truth in zip(captured, trained, strict=True):
        full = [r for r in rows if r["phase"] == "full throttle"]
        if not full or "lap" not in full[0]:
            continue
        z = np.interp(sample.s.to_numpy(), ref.s, ref.z, period=ref.length)
        t, v = sample.t.to_numpy(), sample.v.to_numpy()
        gear = sample.gear.to_numpy() if gears else None
        for run in drag_shape.runs(sample, rows):
            i = run["index"]
            curves.append(drag_shape.run_curve(t[i], v[i], z[i], vehicle, None if gear is None else gear[i]))
            laps.append(full[0]["lap"])
            zones.append(full[0]["zone_id"])
            if oracle and truth["aero"] > still * .999:
                fuelled = replace(vehicle, fuel_kg=truth["mass"] - vehicle.mass + vehicle.fuel_kg)
                known[0].append(drag_shape.run_curve(t[i], v[i], z[i], fuelled, None if gear is None else gear[i],
                                                     wind=zone_wind[truth["zone"]]))
                known[1].append(laps[-1])
                known[2].append(zones[-1])
    records = [dict(r, model="window balance") for r in baseline if "failure" not in r]
    if curves:
        estimate, low, high = drag_shape.fit(curves, laps, zones, seed=seed)
        records.append(_scored(dict(quantity="drag_m2", zone="all", estimate=estimate, low=low, high=high),
                               cda, seed, strategy))
        records.extend(_deployment(store["data"], vehicle, (estimate, low, high), baseline, seed, strategy))
    if known[0]:
        estimate, low, high = drag_shape.fit(*known, seed=seed)
        records.append(_scored(dict(quantity="drag_m2", zone="all", estimate=estimate, low=low, high=high),
                               cda, seed, strategy) | dict(model="run shape, mass tow wind known"))
    return records


def _scored(q, truth, seed, strategy):
    delta = truth - q["estimate"]
    half = q["high"] - q["estimate"] if delta >= 0 else q["estimate"] - q["low"]
    return q | dict(seed=seed, strategy=strategy, model="run shape", truth=truth, score=abs(delta) / max(half, 1e-9))


def _deployment(rows, car, cdas, baseline, seed, strategy):
    """Zone-average signed shaft kW implied by the shape fit's drag, scored on the bench's truth."""
    truths = {r["zone"]: r["truth"] for r in baseline if r.get("quantity") == "deployment_kw"}
    eta, ice, limit = car.driveline_eff, car.ice_w / 1000, car.mguk_w / 1000
    out = []
    for zone, group in rows.groupby("zone"):
        if zone not in truths:
            continue
        weights = group.end_s - group.start_s
        estimate, low, high = (float(np.average(((group.base_kw + group.drag_kw_per_m2 * c) / eta - ice)
                                                .clip(-limit, group.cap_kw), weights=weights)) for c in cdas)
        out.append(_scored(dict(quantity="deployment_kw", zone=zone, estimate=estimate, low=low, high=high),
                           truths[zone], seed, strategy))
    return out


def trials(start, per_strategy, strategies, fine, gears, oracle=False):
    jobs = [(start + len(strategies) * i + j, s, fine, gears, oracle)
            for i in range(per_strategy) for j, s in enumerate(strategies)]
    return pd.DataFrame([row for job in jobs for row in car(job)])


def run(fine=False, gears=False, quick=False, oracle=False):
    n_cal, n_audit = (8, 4) if quick else (40, 60)
    cal = trials(10000, n_cal, bench.STRATEGIES, fine, gears, oracle)
    audit = trials(20000, n_audit, (*bench.STRATEGIES, "switching"), fine, gears, oracle)
    results = {model: bench.assess(cal[cal.model == model], audit[audit.model == model], n_cal, n_audit, [], [])
               for model in ("window balance", "run shape", "run shape, mass tow wind known")
               if (cal.model == model).any()}
    return results, cal, audit


RESULTS = Path(__file__).with_name("energy_shape.json")


def main():
    """The comparison as recorded: the bench's own generator, plus the gear channel."""
    results, _, audit = run(gears=True, oracle=True)
    drag = audit[audit.quantity == "drag_m2"].assign(error=lambda f: f.estimate - f.truth)
    errors = drag.groupby(["model", "strategy"]).error.agg(bias="mean", mae=lambda e: e.abs().mean())
    out = {model: dict(scales=r["scales"],
                       quantities={q: {lab: dict(cover_95=x["cover_95"], median_width=x["median_width"])
                                       for lab, x in br.items()} for q, br in r["quantities"].items()},
                       drag_error={s: dict(bias=float(e.bias), mae=float(e.mae))
                                   for (m, s), e in errors.iterrows() if m == model})
           for model, r in results.items()}
    RESULTS.write_text(json.dumps(out, indent=1) + "\n")
    for model, r in out.items():
        print(model)
        for q, br in r["quantities"].items():
            cells = (f"{lab} {x['cover_95']:.1%} / {x['median_width']:.3g}" for lab, x in br.items())
            print(f"  {q:14s}", "  ".join(cells))


if __name__ == "__main__":
    main()
