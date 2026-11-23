import numpy as np
import pytest

from parc_ferme.bench import state as bench
from parc_ferme.models.state import fuel, interval, smooth


def test_fuel_clips_timing_lines_and_obeys_rpm_ceiling():
    t = np.arange(-.25, 3.5, .25)
    for rpm, cap in ((8000, 2325.), (11500, 3000.)):
        kg, covered = fuel(t, np.full(len(t), 100), np.full(len(t), rpm), 3.)
        assert covered == pytest.approx(1.)
        assert kg[1] == pytest.approx(.95 * cap * 3/3600/43)
        assert kg[0] < kg[1] < kg[2]
        assert interval(kg, 1) == pytest.approx(kg)
    kg, _ = fuel(t, np.zeros(len(t)), np.zeros(len(t)), 3.)
    assert kg == pytest.approx([0, 0, 0])


def test_missing_pedal_is_unobserved_and_large_gap_is_not_filled():
    t = np.arange(0, 20.25, .25)
    throttle = np.full(len(t), 100)
    throttle[10] = 104
    kg, coverage = fuel(t, throttle, np.full(len(t), 11000), 20.)
    assert coverage == pytest.approx(.975)
    assert kg is not None
    keep = (t < 8) | (t > 10)
    kg, coverage = fuel(t[keep], throttle[keep], np.full(keep.sum(), 11000), 20.)
    assert kg is None and coverage < .95


def test_smoother_recovers_signed_acceleration_and_breaks_at_gaps():
    t = np.r_[np.arange(0, 2, .23), np.arange(4, 6, .25)]
    for accel in (-7., 3., 0.):
        v, a = smooth(t, 3.6*(60 + accel*t))
        valid = np.isfinite(a)
        assert valid.sum() == len(t)-4
        assert np.allclose(v[valid], 60 + accel*t[valid])
        assert np.allclose(a[valid], accel/9.81)
        assert not valid[t == 4]
        assert not valid[0] and not valid[-1]


def test_state_bench_covers_hidden_truth_and_reports_peak_bias():
    result = bench.run(quick=True)
    assert result["passed"] and result["fuel_scored"] >= .9*result["audit_laps"]
    for phase in result["phases"].values():
        assert phase["mae_g"] < phase["central_mae_g"]
    assert 0 < result["median_peak_braking_attenuation_g"] < .5


def test_gain_interval_covers_independent_fuel_loads_on_nonlinear_mass_curve():
    study = bench.mass_effect(lambda load: 78. + .025*load + .00002*load**2, .026, .85)
    assert study["passed"] and study["min_sim_gain_ms"] > 0


def test_held_speed_prediction_is_exact_at_constant_acceleration():
    from parc_ferme.debrief.state import held_speed_errors

    t = np.arange(50) * .24
    v = 220 - 12*t
    residuals, baseline = held_speed_errors(t, v)
    assert len(residuals) > 0 and np.allclose(residuals, 0) and np.allclose(baseline, 0)
