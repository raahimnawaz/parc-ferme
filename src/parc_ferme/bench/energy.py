"""Blind S4 recovery from sampled speeds. Calibration cars and audit cars use disjoint seeds."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.car import Car, G
from ..core.track import Track
from ..models.energy import windows
from ..models.energy_fit import profile
from . import coverage as cv

RESULTS = Path(__file__).with_name("energy_coverage.json")


def fingerprint():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for name in ("bench/energy.py", "bench/coverage.py", "models/energy.py", "models/energy_fit.py",
                 "core/car.py", "core/rules_2026.toml"):
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


def experiment(seed, strategy):
    rng = np.random.default_rng(seed)
    car = Car(fuel_kg=20, rho=1.142)
    laps = int(rng.integers(8, 46))
    n = laps * 4
    lap = np.repeat(np.arange(1, laps + 1), 4)
    zone = np.tile(np.arange(4), laps)
    cda = rng.uniform(.55, 1.25)
    ice = rng.uniform(370, 420) + rng.normal(0, 4, n)
    mass = car.mass - car.fuel_kg + (72 - 68*lap/laps) + rng.uniform(-2, 2)
    grade = rng.uniform(-.012, .016, 4)[zone]
    wind = rng.normal(0, 2., 4)[zone] + rng.normal(0, .8, n)
    tow = 1 - rng.uniform(.04, .16, n) * (rng.random(n) < .30)
    knee = rng.uniform(2, 8, 4)[zone] + rng.normal(0, 1.2, n)
    strength = rng.uniform(.65, 1, n)
    harvest = rng.uniform(70, 260, n)
    lift = rng.uniform(8, 12, n)
    dt = .05
    t = np.arange(201) * dt
    v = np.empty((len(t), n))
    v[0] = rng.uniform(54, 64, n)
    s = np.zeros_like(v)
    energy = np.zeros_like(v)  # shaft kJ
    mode = rng.choice(STRATEGIES, size=n) if strategy == "switching" else np.full(n, strategy)
    for i, time in enumerate(t[:-1]):
        speed = v[i]
        cap = car.mguk_limit_w(speed) / 1000
        k = np.select([mode == "clip", mode == "early_taper", mode == "harvest"],
                      [strength * cap * (time < knee), strength * cap * np.clip(1 - (time-knee)/3, 0, 1),
                       np.where(time < knee, strength * cap, -harvest)],
                      default=cap * (.35 + .18 * np.sin((time-knee)/2)))
        coast = time >= lift
        k = np.where(coast, -harvest, k)
        shift = (speed > 70) & (speed < 70.8)
        power = car.driveline_eff * (ice * ~coast * (1 - .35*shift) + k) * 1000
        force = power / speed - .5*car.rho*cda*tow*(speed+wind)**2 - mass*G*(grade + car.crr)
        v[i+1] = speed + dt * force/mass
        s[i+1] = s[i] + .5*dt*(speed+v[i+1])
        energy[i+1] = energy[i] + dt*k

    x = np.arange(1400.)
    ref = Track("bench", x, x, x*0, x*0, x*0, x*0, 1.)
    mask = np.ones(len(x), int)
    records, truth = [], {k: [] for k in range(4)}
    for j in range(n):
        tick = np.arange(2, len(t)-1, 5) + rng.integers(-1, 2, len(t[2:-1:5]))
        tick = tick[rng.random(len(tick)) > .035]
        sample = pd.DataFrame(dict(s=np.rint(s[tick, j]), t=t[tick], v=np.rint(v[tick, j]*3.6)/3.6,
                                   brake=0, throttle=100*(t[tick] < lift[j])))

        for row in windows(sample, replace(ref, z=grade[j]*x), mask, car):
            if row["phase"] != "full throttle":
                continue
            row.update(zone=int(zone[j]), lap=int(lap[j]))
            records.append(row)
            start, end = np.rint(np.array([row["start_s"], row["end_s"]])/dt).astype(int)
            truth[zone[j]].append([energy[end, j]-energy[start, j], t[end]-t[start]])
    _, _, quantities = profile(pd.DataFrame(records), car)
    for q in quantities:
        actual = cda
        if q["quantity"] == "deployment_kw":
            total, duration = np.sum(truth[q["zone"]], axis=0)
            actual = total / duration
        delta = actual - q["estimate"]
        half = q["high"] - q["estimate"] if delta >= 0 else q["estimate"] - q["low"]
        q.update(seed=seed, strategy=strategy, truth=actual, score=abs(delta)/max(half, 1e-9))
    return quantities


def trials(start, per_strategy, strategies):
    records = []
    failures = []
    for i in range(per_strategy):
        for j, strategy in enumerate(strategies):
            seed = start + len(strategies)*i + j
            try:
                records.extend(experiment(seed, strategy))
            except ValueError as err:
                failures.append(dict(seed=seed, strategy=strategy, reason=str(err)))
    return pd.DataFrame(records), failures


def run(quick=False):
    """Split-conformal 95% intervals. Use the largest per-strategy calibration quantile so
    the estimator need not know the strategy. A car is the independent unit, including
    for deployment where its worst zone sets its calibration score."""
    n_cal, n_audit = (20, 4) if quick else (40, 60)
    cal, cal_fail = trials(10000, n_cal, STRATEGIES)
    audit_strategies = (*STRATEGIES, "switching")
    audit, audit_fail = trials(20000, n_audit, audit_strategies)
    scales, results = {}, {}
    for quantity, group in cal.groupby("quantity"):
        worst = group.groupby(["strategy", "seed"]).score.max()
        factors = []
        for strategy in STRATEGIES:
            sample = np.sort(worst.loc[strategy])
            rank = int(np.ceil(.95 * (len(sample)+1)))
            if rank > len(sample):
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
