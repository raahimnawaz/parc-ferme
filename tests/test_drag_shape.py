import numpy as np
import pytest
from scipy.integrate import solve_ivp

from parc_ferme.core.car import Car, G
from parc_ferme.models import drag_shape

CAR = Car(fuel_kg=20, rho=1.142)


def lap_run(cda, electric, dip=False, entry=58., seconds=9.4):
    """An exactly integrated full-throttle run sampled at 4 Hz: 400 kW engine plus `electric(t, v)`."""
    def accel(t, y):
        v = y[0]
        engine = 400e3 * (1 - .35 * (dip and 70 < v < 70.8))
        return [(CAR.driveline_eff * (engine + electric(t, v)) / v - .5 * CAR.rho * cda * v * v) / CAR.mass
                - G * CAR.crr]

    t = np.arange(0, seconds, .25)
    v = solve_ivp(accel, (0, seconds), [entry], t_eval=t, rtol=1e-9, atol=1e-9, max_step=.005).y[0]
    return t, v


def estimate(t, v, gear=None):
    return drag_shape.GRID[np.argmin(drag_shape.run_curve(t, v, np.zeros(len(t)), CAR, gear))]


@pytest.mark.parametrize("cda", [0.6, 0.9, 1.2])
def test_steady_deployment_under_the_rules_cap(cda):
    t, v = lap_run(cda, lambda t, v: .9 * CAR.mguk_limit_w(v))
    assert estimate(t, v) == pytest.approx(cda, rel=0.01)


def test_deployment_that_ends_partway_down_the_straight():
    t, v = lap_run(0.9, lambda t, v: .8 * CAR.mguk_limit_w(v) * (t < 5.))
    assert estimate(t, v) == pytest.approx(0.9, rel=0.02)


def test_a_shift_needs_the_gear_channel():
    t, v = lap_run(0.9, lambda t, v: .9 * CAR.mguk_limit_w(v), dip=True)
    gear = 7 + (v > 70.4)
    assert estimate(t, v, gear) == pytest.approx(0.9, rel=0.02)
    assert estimate(t, v) < 0.85    # without it the lost work reads as drag 10% low


def test_smooth_deployment_is_indistinguishable_from_drag():
    # Deployment falling smoothly along the straight biases the shape fit; the bench's 'partial' cars.
    t, v = lap_run(0.9, lambda t, v: CAR.mguk_limit_w(v) * (.53 - .04 * t))
    assert abs(estimate(t, v) - 0.9) > 0.1


def test_runs_merge_consecutive_windows_and_drop_short_ones():
    import pandas as pd
    samples = pd.DataFrame(dict(t=np.arange(0, 12, .25)))
    rows = [dict(phase="full throttle", zone=zone, start_s=start, end_s=end)
            for zone, start, end in [(1, 0., 1.5), (1, 1.5, 3.), (1, 3., 4.5), (2, 6., 7.5)]]
    runs = drag_shape.runs(samples, rows)
    assert len(runs) == 1 and runs[0]["start_s"] == 0. and runs[0]["end_s"] == 4.5
