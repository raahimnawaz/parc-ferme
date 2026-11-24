import numpy as np
import pytest
from scipy.integrate import trapezoid

from parc_ferme.bench import state as bench
from parc_ferme.models.state import estimate_fuel, fuel, gap_bridges, interval, smooth


def test_fuel_clips_timing_lines_and_obeys_rpm_ceiling():
    t = np.arange(-.25, 3.5, .25)
    for rpm, cap in ((8000, 2325.), (11500, 3000.)):
        kg, covered = fuel(t, np.full(len(t), 100), np.full(len(t), rpm), 3.)
        assert covered == pytest.approx(1.)
        assert kg[1] == pytest.approx(.95 * cap * 3/3600/39.5)
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
    checks = result["profile_checks"]
    assert checks["flow"]["mae"] < 3. and checks["used"]["mae"] < .15
    assert checks["gap_g"]["n"] > 0 and checks["gap_g"]["mae"] < checks["linear_g"]["mae"]
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

def test_fuel_bins_integrate_a_ramp_at_the_lines_and_keep_the_partial_second():
    t = np.arange(-.25, 3., .25)
    duration = 2.35
    kg, coverage, p = estimate_fuel(t, 30+10*t, np.full(len(t), 11000.), duration, with_profile=True)
    edges = np.array([0., 1., 2., duration])
    primitive = 3000/3600/39.5*((.015+.935*.30)*edges + .5*.935*.1*edges**2)
    assert coverage == pytest.approx(1.)
    assert p["missing"] == []
    assert np.cumsum(p["mg"])/1e6 == pytest.approx(primitive[1:], abs=.5e-6)
    assert sum(p["mg"])/1e6 == pytest.approx(kg[1], abs=.5e-6)


def test_fuel_profile_masks_missing_flow_and_keeps_supported_lap_total():
    t = np.arange(0, 20.25, .25)
    pedal = np.full(len(t), 80)
    pedal[t == 8.] = 104
    kg, _, p = estimate_fuel(t, pedal, np.full(len(t), 9820.), 20., with_profile=True)
    assert p["missing"] == [7, 8]
    assert sum(p["mg"])/1e6 == pytest.approx(kg[1], abs=.5e-6)
    assert min(p["mg"]) >= 0
    pedal[(t > 9) & (t < 12)] = 104
    assert estimate_fuel(t, pedal, np.full(len(t), 9820.), 20., with_profile=True)[2] is None


def test_short_gap_curve_meets_both_flanks_and_integrates_to_measured_speed_change():
    t = np.array([0., .25, .5, 1., 2.25, 2.5, 5., 5.25, 5.5])
    speed = np.array([180., 177., 176., 135., 110., 109., 100., 100., 100.])
    # A 2 s gap, a longer gap and open lap ends. Only the first has eligible endpoints.
    accel = np.array([np.nan, .1, np.nan, np.nan, -.1, np.nan, np.nan, -.2, np.nan])
    ((i, j, c),) = gap_bridges(t, speed, accel)
    assert (i, j) == (1, 4)
    q = np.linspace(0, 1, 1001)
    curve = (1-q)**2*accel[i] + 2*q*(1-q)*c + q**2*accel[j]
    assert curve[[0, -1]] == pytest.approx(accel[[i, j]])
    assert trapezoid(curve, q)*(t[j]-t[i])*9.81*3.6 == pytest.approx(speed[j]-speed[i], abs=.001)
