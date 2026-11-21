import numpy as np
import pytest

from parc_ferme.core.car import Car
from parc_ferme.debrief import channels

FIELD = Car(fuel_kg=20.0, mu=1.48, cla_corner=3.6, rho=1.15)


def test_corrected_distance_puts_time_and_speed_where_the_lap_had_them(bench_session):
    """From samples at the feed's ~4 Hz, the grid recovers each simulated lap's time and speed at every distance."""
    b = bench_session
    grid = channels.lap_grid(b.car_data, b.laps, b.track.length)
    assert set(grid) == set(b.truth)
    x = channels.grid(b.track.length)
    for key, lap in b.truth.items():
        tr = lap.trace
        t_err = grid[key]["t"] - np.interp(x, tr.distance, tr.t)
        v_err = grid[key]["v"] - np.interp(x, tr.distance, tr.v_kph)
        assert np.all(np.diff(grid[key]["t"]) > 0)
        assert np.abs(t_err).max() < 0.03
        assert np.median(np.abs(v_err)) < 0.5


def test_typical_lap_runs_to_the_median_lap_and_bests_come_from_timing(bench_session):
    b = bench_session
    length = b.track.length
    cars = channels.car_laps(channels.lap_grid(b.car_data, b.laps, length), length)
    n = len(channels.grid(length))
    for code, g in b.laps.groupby("driver"):
        c = cars[code]
        assert c["fastest"]["lap"] == int(g.lap_number[g.lap_time.idxmin()])
        assert c["fastest"]["time"] == pytest.approx(g.lap_time.min())
        assert c["typical"]["time"] == pytest.approx(g.lap_time.median())
        assert c["typical"]["laps"] == len(g)
        assert c["typical"]["st"] == pytest.approx(g.st_speed.median())
        assert c["pb"] == pytest.approx([g.s1.min(), g.s2.min(), g.s3.min()])
        assert c["pb_lap"] == pytest.approx(g.lap_time.min())
        for lap in ("fastest", "typical"):
            assert all(len(a) == n for a in c[lap]["ch"].values())
            t = np.array(c[lap]["ch"]["t"]) / 1000
            assert t[0] == 0 and t[-1] < c[lap]["time"]


def test_zone_spans_keep_a_zone_across_the_line_whole():
    frac = np.arange(10) / 10
    mask = np.array([1, 1, 0, 0, 1, 1, 0, 0, 0, 1], bool)
    assert channels.zone_spans(mask, frac) == [[0.4, 0.5], [0.9, 0.1]]
    assert channels.zone_spans(np.ones(10, bool), frac) == [[0.0, 1.0]]


def test_team_sims_sit_on_the_distance_axis(bench_session):
    b = bench_session
    teams = [{"team": "Grippy", "mech_pct": 2.0, "downforce_pct": 0.0},
             {"team": "Slippy", "mech_pct": -2.0, "downforce_pct": 0.0}]
    sims = channels.team_sims(b.model, teams, FIELD, b.track.length)
    assert sims["Grippy"]["time"] < sims["Slippy"]["time"]
    x = channels.grid(b.track.length)
    for sim in sims.values():
        t = np.array(sim["ch"]["t"]) / 1000
        assert np.all(np.diff(t) > 0) and t[-1] < sim["time"]
        straight = np.array(sim["ch"]["sm"], bool)
        assert straight[x < 200].all() and not straight[(x > 400) & (x < b.track.length - 400)].any()


def test_parameter_effects_have_the_physical_sign(bench_session):
    b = bench_session
    effect = {p["name"]: p["effect_s"] for p in channels.parameter_effects(b.model.line, b.model.zones,
                                                                           FIELD)["params"]}
    assert effect["Tyre grip coefficient"] < 0 and effect["Downforce, corner mode"] < 0
    assert effect["Combustion engine power"] < 0
    assert effect["Mass with 20 kg fuel"] > 0 and effect["Drag, corner mode"] > 0
    assert effect["Drag, straight mode"] > 0
    no_zones = channels.parameter_effects(b.model.line, np.zeros_like(b.model.zones), FIELD)["params"]
    assert {p["name"]: p["effect_s"] for p in no_zones}["Drag, straight mode"] == 0.0
