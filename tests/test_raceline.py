import numpy as np
import pytest

from parc_ferme.core import track as T
from parc_ferme.core.car import Car
from parc_ferme.sim.lapsim import deploy_threshold, simulate
from parc_ferme.sim.raceline import OffsetLapTime, min_time_line, pattern_search, periodic_basis


def short_stadium(straight=300.0, radius=40.0, width=6.0):
    a = np.linspace(-np.pi / 2, np.pi / 2, 120)
    right = np.c_[straight / 2 + radius * np.cos(a), radius * np.sin(a)]
    left = np.c_[-straight / 2 - radius * np.cos(a), -radius * np.sin(a)]
    top = np.c_[np.linspace(straight / 2, -straight / 2, 150), np.full(150, radius)]
    bottom = np.c_[np.linspace(-straight / 2, straight / 2, 150), np.full(150, -radius)]
    p = np.r_[right, top[1:-1], left, bottom[1:-1]]
    n = len(p)
    return T.build("short stadium", p[:, 0], p[:, 1], np.full(n, width), np.full(n, width), ds=2.0)


def test_basis_is_a_partition_of_unity():
    b = periodic_basis(400, 10)
    assert np.allclose(b.sum(1), 1.0)


def test_pattern_search_handles_kinks():
    p, f, _ = pattern_search(lambda q: abs(q[0] - 1.3) + abs(q[1] + 2.2), np.zeros(2))
    assert f < 0.15 and abs(p[0] - 1.3) < 0.15 and abs(p[1] + 2.2) < 0.15


def test_offset_objective_matches_the_built_line():
    ref, car = short_stadium(), Car()
    zones = np.zeros(len(ref.s), bool)
    a = T.min_curvature_offsets(ref, 1.9)
    line = T.line_from_offsets(ref, a, "line")
    v_star = deploy_threshold(line, car, np.zeros(len(line.s), bool))
    objective = OffsetLapTime(ref, car, zones, v_star, n=len(line.s))
    assert objective(a) == pytest.approx(simulate(line, car, np.zeros(len(line.s), bool), v_star).lap_time, rel=3e-3)


def test_min_time_line_is_no_slower_and_stays_on_track():
    ref, car = short_stadium(), Car()
    zones = np.zeros(len(ref.s), bool)
    r = min_time_line(ref, car, zones, 1.9, spacings_m=(40.0, 20.0))
    lo, hi = T.offset_bounds(ref, 1.9)
    assert r.lap_time_s <= r.start_lap_time_s + 1e-6
    assert np.all(r.offsets >= lo - 1e-9) and np.all(r.offsets <= hi + 1e-9)
