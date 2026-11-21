from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from parc_ferme.bench.fake import render
from parc_ferme.bench.grip import rounded_rectangle
from parc_ferme.core.car import Car, Gearing
from parc_ferme.sim.lapsim import simulate

GEARING = Gearing((40.0, 52.0, 63.0, 72.0, 81.0, 90.0, 98.0, 106.0), 11500.0)
INTERVALS = np.array([0.20, 0.22, 0.24, 0.26, 0.28, 0.30])
SECTOR_ENDS = (0.3, 0.7)
CARS = {"AAA": 1.50, "BBB": 1.48, "CCC": 1.46}
GRIP_PER_LAP = (1.0, 0.99, 1.01)


@pytest.fixture(scope="session")
def bench_session():
    """Three cars on the bench track, three laps each with grip varying by 1%, rendered as OpenF1-shaped car data
    sampled like the real feed, with the lap table that goes with it and each lap's simulated truth."""
    track, corner_fraction = rounded_rectangle()
    zones = (track.s < 250) | (track.s > track.length - 250)  # one straight-mode zone, across the line
    model = SimpleNamespace(reference=track, line=track, zones=zones, corner_fraction=corner_fraction)
    rng = np.random.default_rng(7)
    start = pd.Timestamp("2026-03-01 14:00", tz="UTC")
    car_data, laps, truth = [], [], {}
    for number, (code, mu) in enumerate(CARS.items(), start=1):
        for n, k in enumerate(GRIP_PER_LAP, start=1):
            lap = simulate(track, Car(fuel_kg=20.0, mu=mu * k, cla_corner=3.6, rho=1.15), zones)
            cd, _ = render(lap, GEARING, start, number, INTERVALS, rng)
            tr = lap.trace
            ends = [float(np.interp(f * track.length, tr.distance, tr.t)) for f in SECTOR_ENDS]
            laps.append({"driver": code, "driver_number": number, "lap_number": n, "date_start": start,
                         "lap_time": lap.lap_time, "s1": ends[0], "s2": ends[1] - ends[0],
                         "s3": lap.lap_time - ends[1], "st_speed": np.nan if n == 2 else float(tr.v_kph.max()),
                         "green": True})
            car_data.append(cd)
            truth[(code, n)] = lap
            start += pd.Timedelta(seconds=lap.lap_time)
    return SimpleNamespace(track=track, model=model, car_data=pd.concat(car_data, ignore_index=True),
                           laps=pd.DataFrame(laps), truth=truth)
