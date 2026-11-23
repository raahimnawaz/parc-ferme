"""Joint straight-mode fit with a shared CdA per car and a free signed MGU-K power per window.

Profile out each window's electric power using its feasible range. Repeated laps intersect
those constraints. Speed prediction uses a local deployment map learned on training laps.
"""

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from ..core.car import G
from .energy import held_out

# Sensitivity assumptions for window-mean wheel work: ICE map, fuel mass, shifts and
# endpoint error in kW, and fractional aero-work difference from still air (wind / tow).
WHEEL_ALLOWANCE_KW = 50.
AERO_FRACTION = 0.15


def profile(rows, car, battery_laps=None, linked=False):
    """Robust identification range and typical signed shaft kW (time weighted in sampled windows)."""
    eta = car.driveline_eff
    ice, limit = car.ice_w / 1000, car.mguk_w / 1000
    a, b = rows.drag_kw_per_m2, rows.base_kw
    lo = (eta * (ice - limit) - WHEEL_ALLOWANCE_KW - b) / (a * (1 + AERO_FRACTION))
    hi = (eta * (ice + rows.cap_kw) + WHEEL_ALLOWANCE_KW - b) / (a * (1 - AERO_FRACTION))
    # Enforce the most informative windows within each lap, trim isolated inconsistent laps.
    low = max(0., lo.groupby(rows.lap).max().quantile(.95))
    high = hi.groupby(rows.lap).min().quantile(.05)
    if low >= high:
        raise ValueError("incompatible drag constraints")
    power_ranges = {}
    if battery_laps is not None:
        from .battery import drag_range, zone_power_ranges

        low, high = drag_range(battery_laps, low, high, car, linked)
        power_ranges = zone_power_ranges(battery_laps, low, high, car, linked)
    cda = (low + high) / 2
    latent = rows.copy()
    latent["electric_kw"] = ((b + a*cda) / eta - ice).clip(-limit, rows.cap_kw)
    latent["low_kw"] = ((b + a*low*(1-AERO_FRACTION) - WHEEL_ALLOWANCE_KW) / eta - ice).clip(-limit, rows.cap_kw)
    latent["high_kw"] = ((b + a*high*(1+AERO_FRACTION) + WHEEL_ALLOWANCE_KW) / eta - ice).clip(-limit, rows.cap_kw)
    quantities = []
    for zone, group in latent.groupby("zone"):
        signed = group[["electric_kw", "low_kw", "high_kw"]]
        p, lower, upper = np.average(signed, axis=0, weights=group.end_s - group.start_s)
        if power_ranges:
            bound = power_ranges[group.zone_id.iloc[0]]
            lower, upper = max(lower, bound[0]), min(upper, bound[1])
            p = np.clip(p, lower, upper)
        quantities.append(dict(quantity="deployment_kw", zone=zone, estimate=p, low=lower, high=upper))
    quantities.append(dict(quantity="drag_m2", zone="all", estimate=cda, low=low, high=high))
    return cda, latent, quantities


def features(s, v, length):
    # Circular coordinate so both halves of the start/finish straight are neighbours.
    angle = np.asarray(s) * 2 * np.pi / length
    radius = length / (2 * np.pi * 55.)  # 55 m of position has the weight of 10 km/h at entry
    return np.column_stack((radius*np.cos(angle), radius*np.sin(angle), np.asarray(v)/10.))


def predict(train, test, cda, car):
    """Forward prediction from entry speed and elapsed time only, with a training-only local road grade."""
    length = train.track_m.iloc[0]
    tree = cKDTree(features(train.entry_m, train.entry_kph, length))
    dist, idx = tree.query(features(test.entry_m, test.entry_kph, length), k=list(range(1, min(20, len(train)) + 1)))
    weights = 1 / (0.25 + dist**2)
    weights /= weights.sum(axis=1, keepdims=True)

    def local(values):
        return (weights * np.asarray(values)[idx]).sum(axis=1)

    duration = (test.end_s - test.start_s).to_numpy()
    entry = test.entry_kph.to_numpy()
    raw_rate = (train.exit_kph - train.entry_kph) / (train.end_s - train.start_s)
    baseline = entry + duration * local(raw_rate)
    electric = local(train.electric_kw) * 1000
    road = G * (car.crr + local(train.grade))
    v = entry / 3.6
    # The inferred electric channel is a window average. Limit instantaneous power as speed rises.
    for _ in range(32):
        power = car.driveline_eff * (car.ice_w + np.minimum(electric, car.mguk_limit_w(v)))
        v = v + duration / 32 * ((power / v - .5*car.rho*cda*v*v) / car.mass - road)
    return v * 3.6, baseline


def rollouts(train, held, cda, car):
    """Run both models from the first sample of each contiguous run to its last window end."""
    held = held.sort_values(["lap", "start_s"])
    new = (held.lap != held.lap.shift()) | (held.start_s != held.end_s.shift())
    runs = held.assign(run=new.cumsum(), step=held.groupby(new.cumsum()).cumcount())
    state = {}
    records = []
    for step, batch in runs.groupby("step"):
        times = (batch.end_s - batch.start_s).to_numpy()
        state_rows = [state[k] for k in batch.run] if step else list(zip(
            batch.entry_m, batch.entry_kph, batch.entry_m, batch.entry_kph, batch.start_s, strict=True))
        s, v, sb, vb, start = np.array(state_rows).T
        pred, _ = predict(train, batch.assign(entry_m=s, entry_kph=v), cda, car)
        _, base = predict(train, batch.assign(entry_m=sb, entry_kph=vb), cda, car)
        length = train.track_m.iloc[0]
        s = (s + times*(v+pred)/7.2) % length
        sb = (sb + times*(vb+base)/7.2) % length
        for k, pos, vel, bp, bv, t in zip(batch.run, s, pred, sb, base, start, strict=True):
            state[k] = (pos, vel, bp, bv, t)
        records.append(batch[["run", "lap", "zone", "driver", "end_s", "entry_kph", "exit_kph"]].assign(
            start_s=start, predicted_kph=pred, local_baseline_kph=base, windows=int(step)+1))
    frame = pd.concat(records)
    # Persistence uses the same entry speed as the initial condition for the whole run.
    frame["entry_kph"] = frame.groupby("run").entry_kph.transform("first")
    return frame.groupby("run").tail(1).drop(columns="run")


def evaluate(rows, scales, car, battery_laps=None, linked=False):
    """Same race-lap holdout for every driver. No held-out speeds used in fit, map or baseline."""
    params, predictions, runs, skipped = [], [], [], {}
    full = rows[rows.phase == "full throttle"]
    for driver, group in full.groupby("driver"):
        train = group[~held_out(group.lap)]
        test = group[held_out(group.lap)]
        if train.lap.nunique() < 5:
            skipped[driver] = "fewer than five training laps"
            continue
        try:
            laps = None if battery_laps is None else {lap: parts for (drv, lap), parts in battery_laps.items()
                                                      if drv == driver and not held_out(lap)}
            cda, latent, quantities = profile(train, car, laps, linked)
        except ValueError as err:
            skipped[driver] = str(err)
            continue
        for q in quantities:
            k = scales[q["quantity"]]
            p = q["estimate"]
            params.append(dict(driver=driver, train_laps=train.lap.nunique(), **q,
                               sim95_low=p-k*(p-q["low"]), sim95_high=p+k*(q["high"]-p)))
        for zone, held in test.groupby("zone"):
            known = latent[latent.zone == zone]
            if known.lap.nunique() < 3:
                continue
            pred, baseline = predict(known, held, cda, car)
            # Ablation: keep the nominal S2 drag and refit exactly the same deployment map.
            shaft = ((known.base_kw + known.drag_kw_per_m2 * car.cda_straight) / car.driveline_eff
                     - car.ice_w / 1000)
            fixed = known.assign(electric_kw=shaft.clip(-car.mguk_w/1000, known.cap_kw))
            fixed_pred, _ = predict(fixed, held, car.cda_straight, car)
            runs.append(rollouts(known, held, cda, car))
            predictions.append(held[["driver", "lap", "zone", "start_s", "end_s", "entry_kph", "exit_kph"]].assign(
                predicted_kph=pred, local_baseline_kph=baseline, fixed_drag_kph=fixed_pred))
    return (pd.DataFrame(params), pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame(),
            pd.concat(runs, ignore_index=True) if runs else pd.DataFrame(), skipped)


def scores(rows):
    out = {}
    models = {"joint": "predicted_kph", "local_speed_gain": "local_baseline_kph", "entry": "entry_kph"}
    if "fixed_drag_kph" in rows:
        models["fixed_drag"] = "fixed_drag_kph"
    for label, col in models.items():
        err = rows[col] - rows.exit_kph
        out[label] = dict(mae_kph=float(err.abs().mean()), rmse_kph=float(np.sqrt(np.mean(err**2))),
                          bias_kph=float(err.mean()), p90_abs_kph=float(err.abs().quantile(.9)))
    return out
