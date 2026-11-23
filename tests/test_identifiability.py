import numpy as np
import pytest

from parc_ferme.bench import coverage as cv
from parc_ferme.bench import grip as grip_bench
from parc_ferme.bench import pace as pace_bench
from parc_ferme.bench.circuit import bench_circuit
from parc_ferme.models import pace

# Loose limits: a few seeds give a noisy view of coverage. The full study is `parc-ferme bench`.
MAX_SD_Z = 1.5
MIN_COVER_95 = 0.8


def test_bench_circuit_spans_slow_and_fast_corners():
    c = bench_circuit()
    apex = np.array(list(c.apex.values()))
    assert len(apex) == 13 and np.all(np.diff(apex) > 0) and 0 < apex[0] and apex[-1] < 1
    radii = 1 / np.array([np.abs(c.track.kappa[(c.track.s >= a * c.track.length) & (c.track.s <= b * c.track.length)])
                          .max() for a, b in c.spans.values()])
    assert radii.min() < 40 and radii.max() > 100


def test_resolution_says_what_the_estimates_can_show():
    est = np.array([-4.0, -2.0, 0.0, 2.0, 4.0])
    assert cv.resolution(est, np.full(5, 0.5), True) == "resolved"
    assert cv.resolution(est, np.full(5, 1.5), True) == "interval only"
    assert cv.resolution(est / 10, np.full(5, 1.0), True) == "not resolved"
    assert cv.resolution(est, np.full(5, 0.5), False) == "not resolved"


def test_gls_finds_the_stint_offset_the_fixed_effects_hide():
    rng = np.random.default_rng(0)
    cars, stints, laps = 20, 3, 15
    groups = np.repeat(np.arange(cars * stints), laps)
    car = groups // stints
    age = np.tile(np.arange(laps), cars * stints).astype(float)
    x = np.column_stack([np.eye(cars)[car], np.eye(cars)[car][:, 1:] * age[:, None]])
    y = x @ rng.normal(0, 0.5, x.shape[1]) + rng.normal(0, 0.15, cars * stints)[groups] + rng.normal(0, 0.3, len(age))
    _, _, var = pace.gls_random_groups(x, y, groups)
    assert np.sqrt(var["stint_var"]) == pytest.approx(0.15, rel=0.35)
    assert np.sqrt(var["lap_var"]) == pytest.approx(0.3, rel=0.1)


def test_selection_bias_is_the_expected_minimum_of_a_tie():
    tie = pace.selection_bias(np.zeros(2), np.eye(2) * 0.01, draws=20000)
    assert tie == pytest.approx(-0.1 / np.sqrt(np.pi), rel=0.05)
    clear = pace.selection_bias(np.array([0.0, 1.0]), np.eye(2) * 0.01, draws=20000)
    assert abs(clear) < 0.005


def _check(df, label):
    s = cv.summary(df.z)
    assert s["sd_z"] <= MAX_SD_Z, f"{label}: errors are {s['sd_z']:.2f} times the stated uncertainty"
    assert s["cover_95"] >= MIN_COVER_95, f"{label}: 95% intervals cover {s['cover_95']:.0%}"


@pytest.fixture(scope="module")
def grip_runs():
    return (grip_bench.coverage(range(100, 104), laps=25),
            grip_bench.coverage(range(200, 203), grip_bench.CLEAN, laps=25))


def test_grip_intervals_cover_the_truth_with_confounders(grip_runs):
    real, _ = grip_runs
    for param, g in real.groupby("param"):
        _check(g, f"grip {param}")


def test_grip_intervals_cover_the_truth_on_clean_laps(grip_runs):
    _, clean = grip_runs
    for param, g in clean.groupby("param"):
        _check(g, f"grip {param}, clean")


def test_pace_intervals_cover_the_truth_with_wear_and_stint_offsets():
    df = pace_bench.coverage(range(100, 112), cars=pace_bench.field())
    _check(df[df.param == "lap"], "pace lap")
    _check(df[df.param != "lap"], "pace sectors")
