import numpy as np
import pandas as pd
import pytest

from parc_ferme.bench import pace as bench
from parc_ferme.models import pace


@pytest.fixture(scope="module")
def fitted():
    return pace.sector_pace(bench.race())


def test_bench_recovers_every_cars_sector_gaps():
    r = bench.recovery()
    assert r.error_s.abs().max() <= bench.TOLERANCE_S
    assert set(r.car) == set(bench.CARS)


def test_reference_is_the_fastest_car(fitted):
    assert fitted.reference == min(bench.CARS, key=lambda c: sum(bench.CARS[c]))
    assert fitted.cars.lap.iloc[0] == 0.0 and (fitted.cars.lap.iloc[1:] > 0).all()


def test_traffic_cost_is_recovered_where_it_was_put(fitted):
    near = fitted.traffic.iloc[0]
    assert near.s2 == pytest.approx(bench.TRAFFIC[0][1], abs=3 * near.s2_se)
    assert near.lap > 2 * near.lap_se


def test_held_out_laps_beat_each_cars_own_median(fitted):
    assert fitted.holdout["model_err_s"] < 0.5 * fitted.holdout["baseline_err_s"]


def test_cars_with_too_few_laps_are_left_out():
    laps = bench.race()
    few = laps[(laps.driver == "FFF") & (laps.lap_number <= pace.MIN_LAPS - 1)]
    p = pace.sector_pace(pd.concat([laps[laps.driver != "FFF"], few]))
    assert p.excluded == ["FFF"] and "FFF" not in set(p.cars.driver)


def test_gap_ahead_is_the_smallest_interval_inside_the_lap():
    t0 = pd.Timestamp("2026-06-14 13:00", tz="UTC")
    laps = pd.DataFrame({"driver_number": [7, 7], "date_start": [t0, t0 + pd.Timedelta(seconds=80)],
                         "lap_time": [80.0, 80.0]})
    iv = pd.DataFrame({"driver_number": 7, "date": [t0 + pd.Timedelta(seconds=s) for s in (5, 40, 90, 200)],
                       "interval": [2.5, 0.8, 1.7, 0.1]})
    gaps = pace.gap_ahead(laps, iv)
    assert gaps[0] == pytest.approx(0.8) and gaps[1] == pytest.approx(1.7)
    assert np.isnan(pace.gap_ahead(laps.assign(driver_number=9), iv)).all()
