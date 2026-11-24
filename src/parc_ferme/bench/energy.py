"""Blind S4 recovery from sampled speeds. Calibration cars and audit cars use disjoint seeds."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

from ..core.car import Car, G
from ..core.ers import deploy_fraction
from ..core.track import Track
from ..models.energy import held_out, windows
from ..models.energy_fit import profile
from . import coverage as cv

RESULTS = Path(__file__).with_name("energy_coverage.json")


def fingerprint():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for name in ("bench/energy.py", "bench/coverage.py", "models/energy.py", "models/energy_fit.py",
                 "models/battery.py", "core/car.py", "core/ers.py", "core/rules_2026.toml"):
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def save(result, version):
    RESULTS.write_text(json.dumps(dict(version=version, fingerprint=fingerprint(), **result), indent=2) + "\n")


def load():
    result = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    if result.get("fingerprint") != fingerprint():
        raise ValueError("S4 calibration missing or stale: run parc-ferme bench --energy-only")
    return result


STRATEGIES = ("clip", "early_taper", "harvest", "partial")


@njit(cache=True)
def drive_sector(entry, soc, recovered, mass, ice, grade, aero, wind, strength, knee, harvest, lift, mode, apex,
                 dt, capacity, budget, eta, regen, machine):
    """Forward dynamics. The caller carries speed and store charge across every timing line."""
    v, s, energy = np.empty(341), np.zeros(341), np.zeros(341)
    v[0] = entry
    for i in range(340):
        time, speed = i*dt, v[i]
        cap = machine * deploy_fraction(speed)
        if mode == 0:
            k = strength*cap*(time < knee)
        elif mode == 1:
            k = strength*cap*min(1., max(0., 1-(time-knee)/3))
        elif mode == 2:
            k = strength*cap if time < knee else -harvest
        else:
            k = cap*(.35+.18*np.sin((time-knee)/2))
        resistance = aero*(speed+wind)**2 + mass*G*grade
        engine = ice*(1-.35*(70 < speed < 70.8))
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
        accel = (eta*(engine+k)*1000/speed-resistance)/mass
        v[i+1] = speed + dt*(min(accel, decel) if braking else accel)
        s[i+1] = s[i]+.5*dt*(speed+v[i+1])
        energy[i+1] = energy[i]+dt*k
    return v, s, energy, soc, recovered


def experiment(seed, strategy, paired=False):
    """Four sequential straights, lifts, braking and exits per lap; carry the hidden store through all four."""
    from ..models.battery import segments

    rng = np.random.default_rng(seed)
    car = Car(fuel_kg=20, rho=1.142)
    laps = int(rng.integers(8, 46))
    lap_ids = np.arange(1, laps + 1)
    cda = rng.uniform(.55, 1.25)
    ice = rng.uniform(370, 420) + rng.normal(0, 4, laps)
    mass = car.mass - car.fuel_kg + (72 - 68*lap_ids/laps) + rng.uniform(-2, 2)
    capacity = car.rules["power_unit"]["energy_store_mj"]
    budget = car.rules["power_unit"]["harvest_per_lap_mj"]
    soc = rng.uniform(.1, capacity)
    dt = .05
    t = np.arange(341) * dt
    entry = rng.uniform(53, 62)
    x = np.arange(1800.)
    mask = np.ones(len(x), int)
    records, truth = [], {zone: [] for zone in range(4)}
    battery = {lap: [] for lap in lap_ids if not held_out(lap)}
    grades = rng.uniform(-.012, .016, 4)
    refs = [Track("bench", x, x, x*0, x*0, x*0, x*0, 1., z=x*g) for g in grades]
    winds = rng.normal(0, 2., 4)
    knees = rng.uniform(2, 9, 4)
    tick_grid = np.arange(2, len(t)-1, 5)
    for j, lap in enumerate(lap_ids):
        recovered = 0.
        for zone, ref in enumerate(refs):
            wind = winds[zone] + rng.normal(0, .8)
            tow = 1 - rng.uniform(.04, .16)*(rng.random() < .30)
            lift = rng.uniform(8, 10.3)
            mode = rng.integers(4) if strategy == "switching" else STRATEGIES.index(strategy)
            v, s, energy, soc, recovered = drive_sector(
                entry, soc, recovered, mass[j], ice[j], grades[zone]+car.crr, .5*car.rho*cda*tow, wind,
                rng.uniform(.65, 1), knees[zone]+rng.normal(0, 1.2), rng.uniform(70, 260), lift, mode,
                rng.uniform(42, 48), dt, capacity, budget, car.driveline_eff, car.regen_eff, car.mguk_w/1000)
            entry = v[-1]
            if held_out(lap):
                continue
            tick = tick_grid + rng.integers(-1, 2, len(tick_grid))
            tick = tick[rng.random(len(tick)) > .035]
            throttle = np.where(t[tick] >= 14., 75, 100*(t[tick] < lift))
            sample = pd.DataFrame(dict(s=np.rint(s[tick]), t=t[tick], v=np.rint(v[tick]*3.6)/3.6,
                                       brake=100*((t[tick] >= 10.5) & (t[tick] < 14.)), throttle=throttle))
            straight = windows(sample, ref, mask, car)
            for row in straight:
                row["zone"] = zone
            if paired:
                battery[lap].append(segments(sample, ref, straight, car, t[-1]))
            for row in straight:
                if row["phase"] == "full throttle":
                    row.update(zone_id=zone, lap=int(lap))
                    records.append(row)
                    start, end = np.rint(np.array([row["start_s"], row["end_s"]])/dt).astype(int)
                    truth[zone].append([energy[end]-energy[start], t[end]-t[start]])
    data = pd.DataFrame(records)
    fits = {"windows": None}
    if paired:
        fits["battery"] = {lap: np.concatenate(parts) for lap, parts in battery.items()}
        fits["linked"] = fits["battery"]
    results = []
    for name, parts in fits.items():
        try:
            _, _, quantities = profile(data, car, parts, linked=name == "linked")
        except ValueError as err:
            results.append(dict(seed=seed, strategy=strategy, model=name, failure=str(err)))
            continue
        for q in quantities:
            actual = cda
            if q["quantity"] == "deployment_kw":
                total, duration = np.sum(truth[q["zone"]], axis=0)
                actual = total/duration
            delta = actual - q["estimate"]
            half = q["high"]-q["estimate"] if delta >= 0 else q["estimate"]-q["low"]
            q.update(seed=seed, strategy=strategy, model=name, truth=actual, score=abs(delta)/max(half, 1e-9))
        results.extend(quantities)
    return results


def trials(start, per_strategy, strategies, paired=False):
    records = []
    failures = []
    for i in range(per_strategy):
        for j, strategy in enumerate(strategies):
            seed = start + len(strategies)*i + j
            for row in experiment(seed, strategy, paired):
                (failures if "failure" in row else records).append(row)
    return pd.DataFrame(records), failures


def run(quick=False):
    """Split-conformal 95% intervals. Use the largest per-strategy calibration quantile so
    the estimator need not know the strategy. A car is the independent unit, including
    for deployment where its worst zone sets its calibration score."""
    n_cal, n_audit = (20, 4) if quick else (40, 60)
    cal, cal_fail = trials(10000, n_cal, STRATEGIES, paired=True)
    audit_strategies = (*STRATEGIES, "switching")
    audit, audit_fail = trials(20000, n_audit, audit_strategies, paired=True)
    results = {}
    for model in ("windows", "battery", "linked"):
        results[model] = assess(cal[cal.model == model], audit[audit.model == model], n_cal, n_audit,
                                [r for r in cal_fail if r["model"] == model],
                                [r for r in audit_fail if r["model"] == model])
    return results["windows"] | {"battery": results["battery"], "linked": results["linked"]}


def assess(cal, audit, n_cal, n_audit, cal_fail, audit_fail):
    audit_strategies = (*STRATEGIES, "switching")
    scales, results = {}, {}
    for quantity, group in cal.groupby("quantity"):
        worst = group.groupby(["strategy", "seed"]).score.max()
        factors = []
        for strategy in STRATEGIES:
            sample = np.sort(np.r_[worst.loc[strategy], np.full(n_cal-len(worst.loc[strategy]), np.inf)])
            rank = int(np.ceil(.95 * (len(sample)+1)))
            if rank > len(sample) or not np.isfinite(sample[rank-1]):
                raise ValueError("insufficient independent calibration cars")
            factors.append(sample[rank-1])
        k = scales[quantity] = float(max(factors))
        rows = audit[audit.quantity == quantity]
        breakdown = {}
        for label, subset in [("all", rows), *rows.groupby("strategy")]:
            # Count failed fits as uncovered; the z diagnostic only exists for returned intervals.
            expected = n_audit * (len(audit_strategies) if label == "all" else 1)
            worst = subset.groupby("seed").score.max()
            covered = float((worst <= k).sum() / expected)
            z = cv.Z95 * np.sign(subset.estimate - subset.truth) * subset.score / k
            sm = cv.summary(z)
            breakdown[label] = dict(cars=expected, covered_cars=int((worst <= k).sum()), cover_95=covered,
                                    sd_z=sm["sd_z"], mean_z=sm["mean_z"],
                                    median_width=float(np.median(k * (subset.high-subset.low))),
                                    calibrated=cv.calibrated(sm | {"cover_95": covered}))
        results[quantity] = breakdown
    return dict(calibration_per_strategy=n_cal, audit_per_strategy=n_audit, scales=scales, quantities=results,
                failed_calibrations=cal_fail, failed_audits=audit_fail)
