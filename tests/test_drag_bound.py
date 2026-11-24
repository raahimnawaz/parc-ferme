import numpy as np

from parc_ferme.core.car import G
from parc_ferme.models.drag_bound import LIMITS, bound, road_gaps

RHO = 1.14


def drive(cda, power_w, eta, mass, crr, wind, v0, rng, duration=1.6, step_kph=None):
    """Integrate a straight-line run finely, then sample it like the car-data feed (about 3.7 Hz, whole km/h)."""
    dt, t, v = 0.002, [0.0], [v0]
    while t[-1] < duration:
        u = v[-1]
        a = (eta * power_w / u - RHO / 2 * cda * (u - wind) ** 2 - mass * G * crr) / mass
        v.append(u + a * dt)
        t.append(t[-1] + dt)
    t, v = np.array(t), np.array(v)
    ticks = np.cumsum(np.r_[0.0, rng.uniform(0.22, 0.32, 8)])
    ticks = ticks[ticks <= duration]
    speed = np.interp(ticks, t, v)
    if step_kph:
        speed = np.round(speed * 3.6 / step_kph) * step_kph / 3.6
    return ticks, speed


def test_bound_holds_whatever_the_car_does():
    rng = np.random.default_rng(3)
    margins = []
    for _ in range(300):
        cda = rng.uniform(0.4, 1.0)
        power = 1e3 * (LIMITS["ice_kw"] * rng.uniform(0.85, 1.0) - rng.uniform(0, 150))  # part load and harvest
        t, v = drive(cda, power, rng.uniform(0.90, 0.97), 768 + rng.uniform(0, 70), rng.uniform(0.008, 0.015),
                     rng.uniform(-5, 5), rng.uniform(345.5, 352) / 3.6, rng, step_kph=1.0)
        margins.append(bound(t, v, np.zeros(len(t)), 5.0, RHO) / cda)
    assert min(margins) >= 1.0


def test_bound_is_tight_when_every_unknown_sits_at_its_limit():
    rng = np.random.default_rng(4)
    exact = dict(LIMITS, speed_step_kph=0.0)
    for cda in (0.5, 0.7, 0.9):
        t, v = drive(cda, 1e3 * LIMITS["ice_kw"], LIMITS["driveline_eff"], LIMITS["mass_kg"][0], LIMITS["crr"], 4.0,
                     348 / 3.6, rng)
        assert bound(t, v, np.zeros(len(t)), 4.0, RHO, limits=exact) / cda < 1.02


def test_overtake_allows_more_power_so_a_looser_bound():
    t = np.arange(6) * 0.27
    v = np.linspace(346, 350, 6) / 3.6
    assert bound(t, v, np.zeros(6), 0.0, RHO, overtake=True) > bound(t, v, np.zeros(6), 0.0, RHO)


def test_road_gap_is_the_time_since_the_car_ahead_passed_whatever_its_lap():
    length, speed = 1000.0, 50.0
    clock = np.linspace(0, 100, 2001)
    tracks = {1: (clock, speed * clock), 2: (clock, speed * clock + 100.0), 3: (clock, speed * clock + length + 300)}
    t = np.array([20.0, 40.0])
    s = np.mod(speed * t, length)
    assert np.allclose(road_gaps(tracks, 1, t, s, length), 100.0 / speed)
    assert np.allclose(road_gaps({1: tracks[1], 3: tracks[3]}, 1, t, s, length), 300.0 / speed)
