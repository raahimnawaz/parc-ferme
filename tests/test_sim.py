import numpy as np
import pandas as pd
import pytest

from parc_ferme.bench.fake import render
from parc_ferme.core import track as T
from parc_ferme.core.car import RHO_AIR, Car, G, Gearing
from parc_ferme.sim.lapsim import simulate, zone_mask
from parc_ferme.telemetry import lap_trace


def circle(radius=150.0, n=1500):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return T.build("circle", radius * np.cos(a), radius * np.sin(a), ds=2.0)


def stadium(straight=1200.0, radius=120.0):
    a = np.linspace(-np.pi / 2, np.pi / 2, 400)
    right = np.c_[straight / 2 + radius * np.cos(a), radius * np.sin(a)]
    left = np.c_[-straight / 2 - radius * np.cos(a), -radius * np.sin(a)]
    top = np.c_[np.linspace(straight / 2, -straight / 2, 600), np.full(600, radius)]
    bottom = np.c_[np.linspace(-straight / 2, straight / 2, 600), np.full(600, -radius)]
    p = np.r_[right, top[1:-1], left, bottom[1:-1]]
    return T.build("stadium", p[:, 0], p[:, 1], ds=2.0)


def test_circle_speed_matches_friction_circle():
    r = 40.0
    tr, car = circle(radius=r, n=400), Car()
    lap = simulate(tr, car, np.zeros(len(tr.s), bool))
    m = car.mass
    v = np.sqrt(car.mu * m * G / (m / r - car.mu * 0.5 * RHO_AIR * car.cla_corner))
    assert lap.trace.v_kph.median() / 3.6 == pytest.approx(v, rel=0.01)


def test_lap_is_energy_neutral_and_within_caps():
    tr = stadium()
    car = Car()
    lap = simulate(tr, car, np.zeros(len(tr.s), bool))
    assert lap.deploy_mj <= lap.harvest_mj + 0.05
    assert lap.harvest_mj <= car.rules["power_unit"]["harvest_per_lap_mj"] + 1e-9
    assert lap.trace.regen_kw.max() <= car.rules["power_unit"]["mgu_k_kw"] + 1e-6


def test_top_speed_never_exceeds_power_drag_balance():
    tr, car = stadium(straight=3000.0), Car()
    lap = simulate(tr, car, np.zeros(len(tr.s), bool))
    p = car.driveline_eff * (car.ice_w + car.mguk_w)
    v_terminal = np.roots([0.5 * RHO_AIR * car.cda_corner, 0, car.crr * car.mass * G, -p]).real.max()
    assert lap.trace.v_kph.max() / 3.6 <= v_terminal + 0.5


def test_straight_mode_raises_top_speed():
    tr, car = stadium(straight=3000.0), Car()
    none = simulate(tr, car, np.zeros(len(tr.s), bool))
    straights = np.abs(tr.kappa) < 1e-3
    zoned = simulate(tr, car, straights)
    assert zoned.trace.v_kph.max() > none.trace.v_kph.max() + 5
    assert zoned.lap_time < none.lap_time


def test_zone_mask_wraps_through_the_line():
    tr = circle()
    corners = {1: 100.0, 2: 400.0, 3: 800.0}
    m = zone_mask(tr, corners, [["start_finish"]], exit_m=10.0, entry_m=10.0)
    assert m[int(850 / tr.ds)] and m[int(50 / tr.ds)] and not m[int(300 / tr.ds)]


@pytest.mark.parametrize("mirror", [False, True])
def test_registration_recovers_a_rigid_transform(mirror):
    tr = stadium()
    theta = np.radians(37.0)
    r = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    if mirror:
        r = r @ np.diag([1.0, -1.0])
    p = (np.c_[tr.x, tr.y] - [40.0, -25.0]) @ r * T.FEED_UNITS_PER_M
    reg = T.register(tr, p[::3, 0], p[::3, 1])
    x, y = reg.to_track(p[:, 0], p[:, 1])
    assert reg.rms_m < 0.2
    assert np.abs(x - tr.x).max() < 0.5 and np.abs(y - tr.y).max() < 0.5


def test_gearing_picks_the_lowest_gear_under_the_shift_point():
    g = Gearing((10.0, 15.0, 20.0), upshift_rpm=12000)
    assert list(g.gear(np.array([100.0, 150.0, 200.0, 260.0]))) == [1, 2, 3, 3]


def test_fake_telemetry_integrates_to_the_simulated_distance():
    tr, car = stadium(), Car()
    lap = simulate(tr, car, np.zeros(len(tr.s), bool))
    t0 = pd.Timestamp("2026-06-14T13:00:00Z")
    rng = np.random.default_rng(1)
    cd, loc = render(lap, Gearing((8.0, 12, 15, 18, 21, 24, 27, 30.0), 11500), t0, 0,
                     np.array([0.2, 0.24, 0.28]), rng)
    dt = cd.date.diff().dt.total_seconds().dropna()
    assert 0.2 <= dt.median() <= 0.28
    traced = lap_trace(cd, t0, lap.lap_time)
    assert traced.distance.iloc[-1] == pytest.approx(tr.length, rel=0.01)
    assert set(cd.brake.unique()) <= {0, 100} and cd.n_gear.between(1, 8).all()
