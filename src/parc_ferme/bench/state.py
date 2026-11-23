"""S5 blind lap audit. Fit calibration widths on a separate bank of cars from the published check."""

import numpy as np
from scipy.integrate import cumulative_trapezoid, trapezoid

from ..core.car import G
from ..models.state import estimate_fuel, gap_bridges, interval, smooth


def trial(seed, *, profile_checks=False):
    rng = np.random.default_rng(seed)
    # Flat approaches, power-limited exits and short hard braking events, with smooth onset and release.
    steps = []
    start = 0.
    for _ in range(rng.integers(8, 13)):
        corner = rng.uniform(30, 50)
        top = rng.uniform(75, 92)
        straight, brake, dwell = rng.uniform(4, 9), rng.uniform(1.6, 3.5), rng.uniform(.5, 2.5)
        steps.append((start, corner, top, straight, brake, dwell))
        start += straight+brake+dwell
    t = np.arange(0, start, .01)
    speed, accel, throttle = (np.zeros_like(t) for _ in range(3))
    for k, (a, low, high, run, brake, dwell) in enumerate(steps):
        next_v = steps[(k+1) % len(steps)][1]
        for begin, span, v0, v1 in [(a, run, low, high), (a+run, brake, high, next_v),
                                     (a+run+brake, dwell, next_v, next_v)]:
            mask = (t >= begin) & (t < begin+span)
            x = (t[mask]-begin)/span
            speed[mask] = v0 + (v1-v0)*(.5-.5*np.cos(np.pi*x))
            accel[mask] = (v1-v0)*.5*np.pi*np.sin(np.pi*x)/span
            if v1 < v0 and rng.random() < .5:
                # Trapezoidal deceleration exposes brake onset, a sustained plateau and release.
                ramp = rng.uniform(.06, .28)
                area = np.where(x < ramp, x**2/(2*ramp),
                                np.where(x > 1-ramp, 1-ramp-(1-x)**2/(2*ramp), x-ramp/2))
                speed[mask] = v0 + (v1-v0)*area/(1-ramp)
                accel[mask] = (v1-v0)*np.minimum(1., np.minimum(x, 1-x)/ramp)/(span*(1-ramp))
            if v1 > v0:
                throttle[mask] = np.minimum(1., .22 + 1.7*np.sin(np.pi*x))
            elif v1 == v0:
                throttle[mask] = rng.uniform(.05, .38)
    rpm = 9000 + np.mod(speed*210, 3800)
    if seed % 5 == 0:
        # Short low-load/pit-like periods stress overrun and part-throttle fuel use.
        start_low = rng.uniform(5, t[-1]-15)
        low_load = (t >= start_low) & (t < start_low+8)
        throttle[low_load] *= .25
        rpm[low_load] *= .7
    # Hidden ECU demand, overrun fuel, shifts, part-load nonlinearity and car-specific energy density.
    exponent = rng.uniform(.45, 1.9)
    utilisation = rng.uniform(.75, 1.)
    idle = rng.uniform(0, .055)
    load = idle+(utilisation-idle)*throttle**exponent
    load *= np.where(rpm > 12550, rng.uniform(.65, 1.), 1.)
    true_flow = np.minimum(3000., 165+.27*rpm)*load/3600/rng.uniform(41, 45)
    actual = trapezoid(true_flow, t)
    ticks = np.cumsum(rng.uniform(.17, .32, int(start/.17)))
    ticks = ticks[(ticks < t[-1]) & (rng.random(len(ticks)) > .035)]
    hole = rng.uniform(1, start-3)
    ticks = ticks[(ticks < hole) | (ticks > hole+1.1)]
    v = np.round(3.6*np.interp(ticks, t, speed)+rng.normal(0, .45, len(ticks)))
    pedal = np.rint(100*np.interp(ticks, t, throttle))
    pedal[rng.random(len(ticks)) < .002] = 104
    kg, _, profile = estimate_fuel(ticks, pedal, np.round(np.interp(ticks, t, rpm)), t[-1],
                                   with_profile=profile_checks)
    score = np.nan
    err = np.nan
    if kg is not None:
        low, mid, high = kg
        err = mid-actual
        score = abs(err)/(mid-low if actual < mid else high-mid)
    _, fitted = smooth(ticks, v)
    valid = np.isfinite(fitted)
    truth = np.interp(ticks, t, accel)/G
    central = np.r_[np.nan, (v[2:]-v[:-2])/(ticks[2:]-ticks[:-2])/3.6/G, np.nan]
    checks = {}
    if profile_checks:
        q = (np.arange(20)+.5)/20
        checks["gap_g"] = []
        checks["linear_g"] = []
        for i, j, control in gap_bridges(ticks, v, fitted):
            g0, g1 = np.rint(100*fitted[[i, j]])/100
            true_g = np.interp(ticks[i]+q*(ticks[j]-ticks[i]), t, accel)/G
            curve = (1-q)**2*g0 + 2*q*(1-q)*control + q**2*g1
            checks["gap_g"].extend(np.abs(curve-true_g))
            checks["linear_g"].extend(np.abs((1-q)*g0+q*g1-true_g))
        if profile:
            edges = np.r_[np.arange(0., t[-1]), t[-1]]
            true_mass = np.interp(edges, t, cumulative_trapezoid(true_flow, t, initial=0))
            error_kg = np.array(profile["mg"])/1e6 - np.diff(true_mass)
            ok = np.ones(len(error_kg), dtype=bool)
            ok[profile["missing"]] = False
            checks["flow"] = np.abs(1000*error_kg[ok]/np.diff(edges)[ok])
            checks["used"] = np.abs(np.cumsum(error_kg))
    return (score, err, fitted[valid]-truth[valid], fitted[valid], truth[valid],
            central[valid]-truth[valid], checks, kg, actual)


def run(quick=False):
    n, m = (40, 60) if quick else (200, 300)
    cal = [trial(i+51000) for i in range(n)]
    raw = np.array([r[0] for r in cal])
    raw = np.sort(raw[np.isfinite(raw)])
    scale = float(raw[int(np.ceil(.95*(len(raw)+1)))-1])

    # Conditional pointwise bands: evaluate by phase of the estimate (available on real laps).
    def errors(runs, braking):
        return np.concatenate([r[2][(r[3] < 0) == braking] for r in runs])

    audit = [trial(i+72000, profile_checks=True) for i in range(m)]
    scored = [r for r in audit if np.isfinite(r[0])]
    phases = {}
    for braking, name in [(False, "acceleration"), (True, "deceleration")]:
        radius = float(np.quantile(np.abs(errors(cal, braking)), .95))
        e = errors(audit, braking)
        raw_e = np.concatenate([r[5][(r[3] < 0) == braking] for r in audit])
        phases[name] = dict(central_mae_g=float(np.mean(abs(raw_e))), sd_z=float(np.std(e*1.96/radius)),
                            radius_g=radius, mae_g=float(np.mean(abs(e))), n=len(e),
                            coverage=float(np.mean(abs(e) <= radius)))
    covered = sum(r[0] <= scale for r in scored)
    fuel_sd_z = float(np.std([np.sign(r[1])*1.96*r[0]/scale for r in scored], ddof=1))
    peak_errors = [np.min(r[3])-np.min(r[4]) for r in audit]
    def profile_error(key):
        values = np.concatenate([r[6][key] for r in audit if key in r[6]])
        return {"n": len(values), "mae": float(np.mean(values))}

    return dict(profile_checks={key: profile_error(key) for key in ("flow", "used", "gap_g", "linear_g")},
                calibration_laps=n, audit_laps=m, fuel_scale=scale, fuel_sd_z=fuel_sd_z,
                fuel_scored=len(scored), fuel_covered=int(covered),
                fuel_coverage=covered/len(scored), fuel_mae_kg=float(np.mean([abs(r[1]) for r in scored])),
                phases=phases, median_peak_braking_attenuation_g=float(np.median(peak_errors)),
                passed=bool(fuel_sd_z <= 1.25 and covered/len(scored) >= .90 and len(scored)/m >= .9 and
                            all(v["coverage"] >= .90 and v["sd_z"] <= 1.25 for v in phases.values())))

def mass_effect(lap_time, slope, fuel_scale, calibration=80, audit=160):
    """End-to-end gain: compare the linear estimate with two lap solves at hidden load and true burn."""
    def cases(start, count):
        rows = []
        for seed in range(start, start+count):
            *_, kg, truth = trial(seed)
            if kg is None:
                continue
            load = np.random.default_rng(seed+1_000_000).uniform(5., 65.)
            reference = lap_time(load)-lap_time(load-truth)
            lower, estimate, upper = slope*np.array(interval(kg, fuel_scale))
            error = estimate-reference
            half = estimate-lower if error >= 0 else upper-estimate
            rows.append((error/half, error, reference))
        return np.array(rows)

    cal = np.sort(abs(cases(81000, calibration)[:, 0]))
    factor = float(cal[int(np.ceil(.95*(len(cal)+1)))-1])
    scores, errors, references = cases(91000, audit).T
    covered = int(np.sum((abs(scores) <= factor) & (references >= 0)))
    sd_z = float(np.std(scores*1.96/factor, ddof=1))
    return dict(factor=factor, calibration=len(cal), audit=len(scores), covered=covered, sd_z=sd_z,
                min_sim_gain_ms=float(1000*references.min()), mae_ms=float(1000*np.mean(abs(errors))),
                passed=bool(covered/len(scores) >= .90 and len(scores) >= .9*audit and sd_z <= 1.25))
