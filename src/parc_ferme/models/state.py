"""S5 fuel work and longitudinal state from irregular, quantised telemetry."""

import numpy as np
from numba import njit

from ..core.car import G, rules

MAX_GAP_S = .8
MIN_COVERAGE = .95
BANDWIDTH_S = .30


def fuel(t, throttle, rpm, duration):
    """Integrate assumed load maps against the FIA RPM ceiling, clipping segments at the timing lines."""
    mass = rules()["mass"]
    full = mass["fuel_energy_flow_mj_per_h"]
    lhv = mass["fuel_lhv_mj_per_kg"]
    pedal = np.asarray(throttle, float) / 100
    rpm = np.asarray(rpm, float)
    valid = (pedal >= 0) & (pedal <= 1) & (rpm >= 0) & (rpm <= rules()["power_unit"]["rev_limit_rpm"])
    pedal = np.clip(pedal, 0., 1.)
    cap = np.where(rpm > 0, np.minimum(full, .27*rpm + 165), 0.) / 3600
    # The ECU's actual fuel map is private. The centre and both limiting scenarios are assumed.
    rates = np.array([cap * .78 * pedal**1.5 / 45,
                      cap * (.015 + .935*pedal) / lhv,
                      cap * (.08 + .92*np.sqrt(pedal)) / 41])
    delta = np.diff(t)
    left, right = np.maximum(0., t[:-1]), np.minimum(duration, t[1:])
    ok = valid[:-1] & valid[1:] & (delta > 0) & (delta <= MAX_GAP_S) & (right > left)
    span = (right-left)[ok]
    covered = span.sum()
    if covered < MIN_COVERAGE*duration or covered == 0:
        return None, float(covered/duration)
    mid = ((left[ok]+right[ok])/2 - t[:-1][ok]) / delta[ok]
    kg = ((rates[:, :-1][:, ok] + np.diff(rates)[:, ok]*mid) * span).sum(axis=1)
    # Unobserved time permits zero to maximum flow. The centre uses the observed time average.
    kg[1] *= duration/covered
    kg[2] += max(0., duration-covered)*full/3600/41
    return kg, float(covered/duration)


@njit(cache=True)
def smooth(t, speed_kph):
    """Local constant-acceleration fit to speed. Return fitted speed [m/s] and signed acceleration [g].

    Gaussian weights use clock time. Require observations on both sides, never bridge a dropout.
    """
    n = len(t)
    speed = np.full(n, np.nan)
    accel = np.full(n, np.nan)
    for i in range(1, n-1):
        if not np.isfinite(speed_kph[i]) or speed_kph[i] < 0:
            continue
        a, b = i, i
        while a > 0 and 0 < t[a]-t[a-1] <= MAX_GAP_S and t[i]-t[a-1] <= 3*BANDWIDTH_S:
            if not np.isfinite(speed_kph[a-1]) or speed_kph[a-1] < 0:
                break
            a -= 1
        while b+1 < n and 0 < t[b+1]-t[b] <= MAX_GAP_S and t[b+1]-t[i] <= 3*BANDWIDTH_S:
            if not np.isfinite(speed_kph[b+1]) or speed_kph[b+1] < 0:
                break
            b += 1
        if a == i or b == i:
            continue
        # Shorten the fit through a transition if the residual exceeds feed quantisation/noise.
        for width in (BANDWIDTH_S, .16):
            sw = sx = sy = sxx = sxy = syy = 0.
            for j in range(a, b+1):
                x, y = t[j]-t[i], speed_kph[j]/3.6
                w = np.exp(-.5*(x/width)**2)
                sw += w
                sx += w*x
                sy += w*y
                sxx += w*x*x
                sxy += w*x*y
                syy += w*y*y
            slope = (sxy-sx*sy/sw)/(sxx-sx*sx/sw)
            residual_var = (syy-sy*sy/sw-slope*(sxy-sx*sy/sw))/sw
            if residual_var <= .20**2:
                break
        accel[i] = slope/G
        speed[i] = (sy-slope*sx)/sw
    return speed, accel


def interval(kg, scale):
    low, mid, high = kg
    return [max(0., mid-scale*(mid-low)), mid, mid+scale*(high-mid)]
