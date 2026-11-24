import numpy as np

from parc_ferme.bench.coverage import resolution
from parc_ferme.bench.identifiability import _relative, drag_rows

FAMILIES = {"A": ["Red", "Blue"], "B": ["Green", "Grey"], "C": ["Solo"]}
TEAMS = {"R1": "Red", "R2": "Red", "B1": "Blue", "B2": "Blue", "G1": "Green", "G2": "Green", "Y1": "Grey",
         "Y2": "Grey", "S1": "Solo"}
BENCH = {"cover_95": .97, "sd_z": .5, "calibrated": True}


def intervals(estimates, half):
    return [dict(driver=d, estimate=p, sim95_low=p - half, sim95_high=p + half) for d, p in estimates.items()]


def test_relative_values_carry_the_reference_mean_uncertainty():
    rel, se = _relative(np.array([1., 2., 6.]), np.full(3, .3), np.zeros(3))
    assert np.allclose(rel, [-2., -1., 3.])
    # var(x_i - mean) = s^2 (1 - 1/n) for equal independent errors
    assert np.allclose(se, .3 * np.sqrt(2 / 3))


def test_wide_battery_intervals_leave_drag_unresolved_at_both_levels():
    est = dict(R1=.71, R2=.42, B1=.68, B2=.39, G1=.64, G2=.41, Y1=.50, Y2=.46, S1=.36)
    rows = drag_rows(intervals(est, .30), TEAMS, FAMILIES, BENCH, BENCH)
    assert [r["quantity"] for r in rows] == ["drag", "drag_family"]
    assert all(r["status"] == "not resolved" for r in rows)
    # The single-team family has nothing to compare with, so its car is left out of the second row.
    assert rows[1]["spread"] > 0


def test_tight_intervals_resolve_real_differences():
    est = dict(R1=.60, R2=.60, B1=.70, B2=.70, G1=.55, G2=.55, Y1=.65, Y2=.65, S1=.60)
    rows = drag_rows(intervals(est, .01), TEAMS, FAMILIES, BENCH, BENCH)
    assert [r["status"] for r in rows] == ["resolved", "resolved"]
    failed = drag_rows(intervals(est, .01), TEAMS, FAMILIES, BENCH, dict(BENCH, calibrated=False))
    assert failed[1]["status"] == "not resolved"


def test_group_means_cost_one_degree_of_freedom_each():
    # chi2 = 7.0 over four values: significant on 2 dof (two group means removed, p = 0.03), not on 3 (p = 0.07).
    x = np.sqrt(7.0 / 4) * 0.1
    est, se = np.array([-x, x, -x, x]), np.full(4, 0.1)
    assert resolution(est, se, True) == "not resolved"
    assert resolution(est, se, True, groups=np.array(["a", "a", "b", "b"])) == "interval only"
