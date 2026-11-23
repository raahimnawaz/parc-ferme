import numpy as np
import pandas as pd
import pytest

from parc_ferme.core.car import Car
from parc_ferme.core.track import Track
from parc_ferme.models import battery as bat


def test_store_capacity_and_free_endpoints():
    k = np.array([1., 2., 1.])  # one full discharge, no recharge
    h, soc = bat.path(k, k, .85, 4.)
    assert h == 0
    np.testing.assert_allclose(soc, [4., 3., 1., 0.])
    assert bat.path(k+.1, k+.1, .85, 4.)[0] < 0


def test_preserves_charge_and_matches_linear_program_on_variable_power():
    # Optional discharge then optional harvest before an unavoidable 4 MJ deployment.
    low, high = np.array([0., -4., 4.]), np.array([4., 0., 4.])
    assert bat.path(low, high, 1., 4.)[0] == 0.
    rng = np.random.default_rng(11307)
    zeros = np.zeros(14)
    for _ in range(100):
        low = rng.uniform(-2, 2, len(zeros))
        high = low + rng.uniform(.05, 2, len(zeros))
        optimum = bat.flow_optimum(low, high, zeros, zeros+.85, .85, 4., 100.)
        h, soc = bat.path(low, high, .85, 4.)
        if np.isnan(optimum):
            assert h < 0
        else:
            assert h == pytest.approx(optimum, abs=1e-9)
            assert soc.min() >= -1e-9 and soc.max() <= 4.+1e-9


def test_zone_power_limited_by_store_and_resettable_harvest_budget():
    # Two long deployment windows separated by one recovery opportunity.
    low, high = np.array([0., -4., 0.]), np.array([4., 0., 4.])
    zone = np.array([True, False, True])
    assert bat.zone_extreme(low, high, zone, -1, 1., 4., 2.) == pytest.approx(6.)
    assert bat.zone_extreme(low, high, zone, -1, .5, 4., 8.5) == pytest.approx(6.)
    # Mandatory regen can exhaust the lap cap even with ample headroom at every instant.
    k = np.tile(np.array([-2., 2.]), 5)
    assert bat.path(k, k, 1., 4.)[0] == pytest.approx(10.)


def test_lift_brake_unknown_and_straight_segments_partition_entire_lap():
    x = np.arange(100.)
    ref = Track("level", x, x, x*0, x*0, x*0, x*0, 1., z=x*0)
    t = np.r_[np.arange(.2, 3., .25), 3.9, 4.15]
    tr = pd.DataFrame(dict(s=t*10, t=t, v=80-t, throttle=100, brake=0))
    tr.loc[5:8, "throttle"] = 0
    tr.loc[9:11, ["throttle", "brake"]] = [0, 100]
    tr.loc[12, "throttle"] = 104
    win = [dict(start_s=t[0], end_s=t[4], phase="full throttle", base_kw=10, drag_kw_per_m2=350,
                cap_kw=200, zone=1)]
    parts = bat.segments(tr, ref, win, Car(), 4.5)
    assert parts[:, 0].sum() == pytest.approx(4.5)
    assert {bat.UNKNOWN, bat.STRAIGHT, bat.COAST, bat.BRAKING} <= set(parts[:, 1])
    assert parts[parts[:, 1] == bat.COAST, 5].sum() > 0
    assert np.all(parts[parts[:, 1] == bat.COAST, 4] == 0)
    assert parts[parts[:, 1] == bat.UNKNOWN, 0].sum() >= 1.
    row, = bat.ledger({1: parts}, .8, Car())
    assert row["feasible"]
    assert row["end_mj"] == pytest.approx(row["start_mj"] + row["harvested_mj"] - row["deployed_mj"])
    assert row["lift_coast_max_harvest_mj"] > 0
    assert row["straight_max_harvest_mj"] > 0


def test_drag_endpoint_rejected_by_long_unbroken_deployment():
    # At high drag even the least required power drains more than 4 MJ in 20 s.
    parts = np.array([[20., bat.STRAIGHT, 470., 250., 350., 350., 1.]])
    low, high = bat.drag_range([parts], .1, 1.5, Car())
    assert low == .1 and .5 < high < 1.5


def test_charge_continuity_excludes_unsustainable_drag_and_breaks_at_missing_laps():
    # Each lap forces > 2 MJ deployment at high drag: two isolated laps are feasible.
    parts = np.array([[12., bat.STRAIGHT, 450., 220., 350., 350., 1.]])
    car = Car()
    consecutive = {1: parts, 2: parts, 3: parts}
    separate = {1: parts, 3: parts, 5: parts}
    low, high = .1, 1.2
    assert bat.drag_range(consecutive, low, high, car) == (low, high)
    assert bat.drag_range(separate, low, high, car, linked=True) == (low, high)
    assert bat.drag_range(consecutive, low, high, car, linked=True)[1] < high
    linked = bat.linked_ledger(consecutive, low, car)
    assert all(r["feasible"] for r in linked)
    assert linked[0]["end_mj"] == linked[1]["start_mj"]
    linked_power = bat.zone_power_ranges(consecutive, low, high, car, linked=True)
    assert linked_power[1][1] <= 4000/36 + 1e-9


def test_recovery_cap_resets_without_resetting_charge():
    # 2 MJ recovered on each lap, with a 2 MJ per-lap cap. Splitting 3+1 is illegal.
    ends = np.array([2, 4])
    work = np.array([-2., 2., -2., 2.])
    assert bat.block_path(work, work, 1., 4., 2., ends) is not None
    work = np.array([-3., 3., -1., 1.])
    assert bat.block_path(work, work, 1., 4., 2., ends) is None
