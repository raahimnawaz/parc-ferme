import numpy as np
import pandas as pd
import pytest

from parc_ferme.core.car import Car, G
from parc_ferme.core.track import Track
from parc_ferme.models.energy import power_balance, windows


def test_power_balance_on_feed_like_straights():
    """Integrate the forward dynamics at 1 ms, then estimate mean wheel power from rounded 4 Hz speeds."""
    rng = np.random.default_rng(44)
    errors = []
    short_errors = []
    for _ in range(80):
        car = Car(fuel_kg=rng.uniform(5, 65))
        cda = rng.uniform(0.7, 1.2)
        grade = rng.uniform(-0.02, 0.02)
        # The electric machine can taper early, abruptly clip or start harvesting at full throttle.
        t = np.arange(4001) / 1000
        electric_kw = np.maximum(0, rng.uniform(150, 320) - rng.uniform(10, 80) * t)
        electric_kw[t >= rng.uniform(1, 3)] = rng.uniform(-120, 30)
        wheel_kw = (400 + electric_kw) * car.driveline_eff
        speed = np.empty(len(t))
        height = np.zeros(len(t))
        speed[0] = rng.uniform(58, 77)
        for i, kw in enumerate(wheel_kw[:-1]):
            v = speed[i]
            resistance = car.rho * cda * v**2 / 2 + car.mass * G * (grade + car.crr)
            speed[i + 1] = v + 0.001 * (kw * 1000 / v - resistance) / car.mass
            height[i + 1] = height[i] + 0.001 * grade * v
        sample = np.r_[0, np.arange(250, 4000, 250) + rng.integers(-50, 51, 15), 4000]
        sample = np.delete(sample, rng.integers(1, len(sample) - 1))
        base, slope = power_balance(t[sample], np.rint(3.6 * speed[sample]) / 3.6, height[sample], car)
        errors.append(base + cda * slope - wheel_kw[:-1].mean())
        # Match the shortest production windows too, where endpoint quantisation matters most.
        end = np.searchsorted(sample, 1500)
        short = sample[:end + 1]
        base, slope = power_balance(t[short], np.rint(3.6 * speed[short]) / 3.6, height[short], car)
        short_errors.append(base + cda * slope - wheel_kw[:short[-1]].mean())
    assert np.percentile(np.abs(errors), 95) < 5
    assert np.percentile(np.abs(short_errors), 95) < 10


def test_drag_and_power_trade_at_terminal_speed():
    car = Car()
    v = 80.
    base, slope = power_balance(np.array([0., 2.]), np.full(2, v), np.zeros(2), car)
    assert base == pytest.approx(car.mass * G * car.crr * v / 1000)
    assert slope == pytest.approx(car.rho * v**3 / 2000)


def test_windows_exclude_invalid_pedals_and_gaps():
    x = np.arange(60.)
    ref = Track("straight", x, x, x*0, x*0, x*0, x*0, 1., z=x*0)
    tr = pd.DataFrame(dict(s=x, t=x/4, v=75., throttle=100, brake=0))
    tr.loc[10, "throttle"] = 104
    tr.loc[20, "brake"] = 104
    tr.loc[30:, "t"] += 1
    tr.loc[40:, "throttle"] = 0
    zones = np.ones(60, int)
    zones[51:] = 0
    rows = windows(tr, ref, zones, Car())
    assert {r["phase"] for r in rows} == {"full throttle", "coast"}
    for r in rows:
        assert r["end_s"] - r["start_s"] >= 1.5
        assert all(not r["start_s"] <= t <= r["end_s"] for t in [2.5, 5., 8., 13.75])


def test_joint_fit_holds_out_whole_laps_and_rolls_without_teacher_forcing():
    from parc_ferme.models.energy import held_out
    from parc_ferme.models.energy_fit import evaluate

    rows = []
    for lap in range(1, 13):
        for i in range(3):
            rows.append(dict(zone="main", driver="A", lap=lap, phase="full throttle",
                             start_s=1.6*i, end_s=1.6*(i+1), entry_kph=250+i*12+lap*.1,
                             exit_kph=262+i*12+lap*.1, entry_m=120*i, track_m=4600., grade=.003,
                             base_kw=190-i*60, drag_kw_per_m2=270+i*35, cap_kw=300-i*20))
    df = pd.DataFrame(rows)
    scales = dict(drag_m2=1, deployment_kw=1)
    p, held, runs, skipped = evaluate(df, scales, Car())
    assert not skipped and set(held.lap) == {7, 8, 9} and list(runs.windows) == [3, 3, 3]
    assert p.train_laps.eq(9).all()
    df.loc[held_out(df.lap), ["exit_kph", "cap_kw", "grade", "base_kw", "drag_kw_per_m2"]] = 999
    p2, h2, _, _ = evaluate(df, scales, Car())
    pd.testing.assert_frame_equal(p, p2)
    np.testing.assert_array_equal(held.predicted_kph, h2.predicted_kph)
    df.loc[(held_out(df.lap)) & (df.start_s > 0), ["entry_kph", "entry_m"]] = 320
    _, _, r2, _ = evaluate(df, scales, Car())
    np.testing.assert_array_equal(runs.predicted_kph, r2.predicted_kph)
    np.testing.assert_array_equal(runs.local_baseline_kph, r2.local_baseline_kph)


def test_joint_intervals_on_fresh_hidden_strategies():
    from parc_ferme.bench import energy

    study = energy.load()
    audit, failures = energy.trials(30000, 3, (*energy.STRATEGIES, "switching"), paired=True)
    assert not failures
    for (model, quantity), g in audit.groupby(["model", "quantity"]):
        scales = (study if model == "windows" else study[model])["scales"]
        assert (g.groupby("seed").score.max() <= scales[quantity]).mean() >= .8
