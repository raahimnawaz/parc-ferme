"""Feasible full-lap store trajectories for the S4 work balance. Energies are store-side MJ."""

import numpy as np
from numba import njit
from scipy import sparse
from scipy.optimize import linprog

from ..core.car import G

UNKNOWN, STRAIGHT, COAST, BRAKING, OTHER = range(5)
PHASES = ("unknown", "straight", "lift_coast", "braking", "other")
# Segment columns: duration (s), phase, wheel intercept (kW), aero slope (kW/m²),
# shaft deployment ceiling (kW), shaft harvest ceiling (kW), straight identifier.


def segments(samples, ref, straight_windows, car, duration):
    """Partition [0, lap duration] exactly. Only measured uninterrupted windows constrain straight work."""
    t = samples.t.to_numpy()
    v = samples.v.to_numpy()
    z = np.interp(samples.s, ref.s, ref.z, period=ref.length)
    throttle, brake = samples.throttle.to_numpy(), samples.brake.to_numpy()
    valid = (throttle >= 0) & (throttle <= 100) & np.isin(brake, [0, 100])
    phase = np.select([~valid, brake == 100, throttle == 0], [UNKNOWN, BRAKING, COAST], default=OTHER)
    dt = np.diff(t)
    if np.any(dt <= 0) or t[0] < 0 or t[-1] > duration + 1e-6:
        raise ValueError("non-monotonic or out-of-lap battery samples")
    edge = np.where((dt <= .55) & (phase[:-1] == phase[1:]), phase[:-1], UNKNOWN)
    known = {}
    for w in straight_windows:
        if w["phase"] == "full throttle":
            i, j = np.searchsorted(t, [w["start_s"], w["end_s"]])
            known[i] = (j, w)
            edge[i:j] = STRAIGHT
    limit = car.mguk_w / 1000
    rows = []
    if t[0] > 0:
        rows.append((t[0], UNKNOWN, 0, 0, limit, limit, -1))
    stops = np.r_[np.flatnonzero(np.diff(edge)) + 1, len(edge)]
    i = 0
    while i < len(edge):
        if i in known:
            j, w = known[i]
            rows.append((t[j]-t[i], STRAIGHT, w["base_kw"], w["drag_kw_per_m2"], w["cap_kw"], limit, w["zone"]))
        else:
            j = stops[np.searchsorted(stops, i, side="right")]
            kind = edge[i]
            cap, recover = limit, limit
            if kind in (BRAKING, COAST):
                # Zero throttle (or braking) allows friction/engine losses. Ignore aero and rolling
                # losses for an upper bound on recovery. Allow for endpoint quantisation and work error.
                kinetic = car.mass * ((v[i]+.14)**2 - max(0, v[j]-.14)**2) / 2
                available = (kinetic + car.mass*G*(z[i]-z[j])) / (t[j]-t[i]) / 1000
                cap = 0.
                recover = np.clip((available + 50.) / car.driveline_eff, 0., limit)
            elif kind == OTHER:
                # Driven outside a measured straight window. The engine can supply at most
                # its assumed full power plus allowance. Aero, rolling and corner losses
                # are nonnegative, giving a lower bound on the required electric work.
                kinetic = car.mass * (max(0, v[j]-.14)**2 - (v[i]+.14)**2) / 2
                minimum = (kinetic + car.mass*G*(z[j]-z[i])) / (t[j]-t[i]) / 1000
                recover = np.clip(car.ice_w/1000 - (minimum-50.)/car.driveline_eff, -limit, limit)
            rows.append((t[j]-t[i], kind, 0, 0, cap, recover, -1))
        i = j
    if duration > t[-1]:
        rows.append((duration-t[-1], UNKNOWN, 0, 0, limit, limit, -1))
    return np.asarray(rows, float)


@njit(cache=True)
def shaft_bounds(parts, area_low, area_high, ice_kw, eta, allowance, aero_fraction):
    """Shaft MJ drawn (positive) in each segment over the candidate drag range."""
    low = np.empty(len(parts))
    high = np.empty(len(parts))
    for i in range(len(parts)):
        dt, phase, base, aero, deploy, harvest, _ = parts[i]
        kmin, kmax = -harvest, deploy
        if phase == STRAIGHT:
            kmin = min(deploy, max(-harvest, (base+aero*area_low*(1-aero_fraction)-allowance)/eta - ice_kw))
            kmax = min(deploy, max(-harvest, (base+aero*area_high*(1+aero_fraction)+allowance)/eta - ice_kw))
        low[i], high[i] = kmin*dt/1000, kmax*dt/1000
    return low, high


@njit(cache=True)
def path(kmin, kmax, regen_eff, capacity):
    """Least recovered MJ for given shaft-MJ bounds. Negative means no viable store path.

    Work backwards for the full range of viable charges, then start as full as viable
    and postpone optional charging. This minimises positive increments with free endpoints.
    """
    n = len(kmin)
    low = -kmax * np.where(kmax < 0, regen_eff, 1.)
    high = -kmin * np.where(kmin < 0, regen_eff, 1.)
    floor = np.zeros(n+1)
    ceiling = np.full(n+1, float(capacity))
    soc = np.full(n+1, np.nan)
    for i in range(n-1, -1, -1):
        floor[i] = max(0., floor[i+1]-high[i])
        ceiling[i] = min(capacity, ceiling[i+1]-low[i])
        if floor[i] > ceiling[i]+1e-10:
            return -1., soc
    soc[0] = ceiling[0]
    recovered = 0.
    for i in range(n):
        # Preserve charge whenever possible. Spending optional energy here could force
        # a needless refill later even when both paths meet the same endpoint limits.
        lower = max(floor[i+1], soc[i]+low[i])
        upper = min(ceiling[i+1], soc[i]+high[i])
        soc[i+1] = min(upper, max(lower, soc[i]))
        recovered += max(0., soc[i+1]-soc[i])
    return recovered, soc


def trajectory(parts, cda, ice, eta, regen, capacity, allowance, fraction):
    low, high = shaft_bounds(parts, cda, cda, ice, eta, allowance, fraction)
    return path(low, high, regen, capacity)


def constants(car):
    from .energy_fit import AERO_FRACTION, WHEEL_ALLOWANCE_KW

    return (car.ice_w/1000, car.driveline_eff, car.regen_eff, car.rules["power_unit"]["energy_store_mj"],
            WHEEL_ALLOWANCE_KW, AERO_FRACTION)


def drag_range(laps, low, high, car):
    """Hull of drag values with a feasible store on >=95% of training laps, allowing isolated bad laps."""
    args = constants(car)
    limit = car.rules["power_unit"]["harvest_per_lap_mj"]

    def feasible(area):
        count = sum(0 <= trajectory(lap, area, *args)[0] <= limit+1e-9 for lap in laps)
        return count >= .95 * len(laps)

    # If both endpoints pass, their hull already covers the input range.
    if feasible(low) and feasible(high):
        return low, high
    grid = np.linspace(low, high, 65)
    accepted = [i for i, value in enumerate(grid) if feasible(value)]
    if not accepted:
        raise ValueError("no feasible full-lap battery balance on drag grid")
    # Round outwards by one grid cell. Avoid claiming sub-grid precision.
    return grid[max(0, accepted[0]-1)], grid[min(len(grid)-1, accepted[-1]+1)]


def ledger(laps, cda, car):
    """One minimum-harvest witness per lap at the representative drag. Failed laps stay explicit."""
    data = []
    for lap, parts in laps.items():
        harvest, soc = trajectory(parts, cda, *constants(car))
        passed = 0 <= harvest <= car.rules["power_unit"]["harvest_per_lap_mj"] + 1e-9
        row = dict(lap=lap, feasible=passed, duration_s=parts[:, 0].sum(), cda_m2=cda)
        if passed:
            ice, eta, regen, capacity, allowance, frac = constants(car)
            low, high = shaft_bounds(parts, cda, cda, ice, eta, allowance, frac)
            budget = car.rules["power_unit"]["harvest_per_lap_mj"]
            for code, name in ((None, "total"), (STRAIGHT, "straight"), (COAST, "lift_coast"), (BRAKING, "braking")):
                sel = np.ones(len(parts), bool) if code is None else parts[:, 1] == code
                if code is not None:
                    row[name+"_duration_s"] = parts[sel, 0].sum()
                # Separate optima at this CdA. These phase maxima cannot in general be added.
                row[name+"_max_harvest_mj"] = -flow_optimum(
                    low, high, np.zeros(len(low)), -regen*sel.astype(float), regen, capacity, budget)
            change = np.diff(soc)
            row.update(start_mj=soc[0], end_mj=soc[-1], min_soc_mj=soc.min(), max_soc_mj=soc.max(),
                       harvested_mj=harvest, deployed_mj=-np.minimum(change, 0).sum())
            for code, name in enumerate(PHASES):
                row[name+"_harvest_mj"] = np.maximum(change[parts[:, 1] == code], 0).sum()
        data.append(row)
    return data


def zone_extreme(low, high, selected, sign, regen, capacity, budget):
    """Extremise selected shaft MJ with storage, per-lap recovery and phase power limits."""
    forced_low, forced_high = low.copy(), high.copy()
    if sign == 1:
        forced_high[selected] = low[selected]
    else:
        forced_low[selected] = high[selected]
    recovered, _ = path(forced_low, forced_high, regen, capacity)
    independent = (low if sign == 1 else high)[selected].sum()
    if 0 <= recovered <= budget + 1e-9:
        return independent
    weight = sign*selected.astype(float)
    result = flow_optimum(low, high, weight, -weight, regen, capacity, budget)
    return independent if np.isnan(result) else sign*result


def flow_optimum(low, high, weight_d, weight_h, regen, capacity, budget):
    """Minimise a linear work or charge objective over a complete lap."""
    # D, H are deployed and harvested shaft MJ; S is store MJ at all n+1 boundaries.
    # Sign-changing segments may time-share within their two power limits.
    n = len(low)
    eye = sparse.eye(n)
    delta = sparse.diags([-np.ones(n), np.ones(n)], [0, 1], shape=(n, n+1))
    balance = sparse.hstack([eye, -regen*eye, delta])
    max_d, max_h = np.maximum(high, 0), np.maximum(-low, 0)
    mixed = (max_d > 0) & (max_h > 0)
    sharing = sparse.hstack([sparse.diags(1/np.where(mixed, max_d, 1)),
                             sparse.diags(1/np.where(mixed, max_h, 1)), sparse.csr_matrix((n, n+1))]).tocsr()[mixed]
    cap = np.r_[np.zeros(n), np.full(n, regen), np.zeros(n+1)]
    objective = np.r_[weight_d, weight_h, np.zeros(n+1)]
    result = linprog(objective, A_eq=balance, b_eq=np.zeros(n), A_ub=sparse.vstack([sharing, cap[None, :]]),
                     b_ub=np.r_[np.ones(mixed.sum()), budget],
                     bounds=np.column_stack((np.r_[np.maximum(low, 0), np.maximum(-high, 0), np.zeros(n+1)],
                                             np.r_[max_d, max_h, np.full(n+1, capacity)])), method="highs")
    if result.status == 2:
        return np.nan  # empty feasible set
    if not result.success:
        raise RuntimeError(result.message)
    return result.fun


def zone_power_ranges(laps, low_area, high_area, car):
    """Outer bounds on each zone's time-weighted training mean after enforcing the lap balance."""
    ice, eta, regen, capacity, allowance, frac = constants(car)
    budget = car.rules["power_unit"]["harvest_per_lap_mj"]
    totals = {}
    for parts in laps.values():
        low, high = shaft_bounds(parts, low_area, high_area, ice, eta, allowance, frac)
        for zone in np.unique(parts[:, 6]):
            if zone < 0:
                continue
            sel = parts[:, 6] == zone
            acc = totals.setdefault(zone, np.zeros(3))
            acc += (parts[sel, 0].sum(), zone_extreme(low, high, sel, 1, regen, capacity, budget),
                    zone_extreme(low, high, sel, -1, regen, capacity, budget))
    return {zone: value[1:]*1000/value[0] for zone, value in totals.items()}
