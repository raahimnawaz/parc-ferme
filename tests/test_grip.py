import numpy as np
import pandas as pd
import pytest

from parc_ferme.bench.fake import render
from parc_ferme.core import track as T
from parc_ferme.core.car import Car, Gearing, air_density
from parc_ferme.models import grip
from parc_ferme.sim.lapsim import simulate
from parc_ferme.telemetry import placed_samples

RADII = (40.0, 100.0, 70.0, 130.0)
RHO = 1.15
FUEL = grip.FUEL_AVG_KG
TEAMS = {"A": (1.50, 3.60), "B": (1.56, 3.60), "C": (1.46, 3.95), "D": (1.50, 3.30), "E": (1.53, 3.75)}


def rounded_rectangle(width=1400.0, height=900.0, radii=RADII, step=1.0):
    """Closed track: four 90-degree corners of the given radii joined by straights, anticlockwise from the
    middle of the bottom straight. Returns the track and each corner's lap fraction at its apex."""
    r1, r2, r3, r4 = radii
    legs = [(width / 2 - r1, None), (r1, 0), (height - r1 - r2, None), (r2, 1), (width - r2 - r3, None), (r3, 2),
            (height - r3 - r4, None), (r4, 3), (width / 2 - r4, None)]
    x, y, h, pts, apex_s, s = 0.0, 0.0, 0.0, [], {}, 0.0
    for length, corner in legs:
        if corner is None:
            n = max(1, int(length / step))
            for _ in range(n):
                x, y = x + np.cos(h) * length / n, y + np.sin(h) * length / n
                pts.append((x, y))
            s += length
        else:
            arc = length * np.pi / 2
            n = max(1, int(arc / step))
            for i in range(n):
                h += np.pi / 2 / n
                x, y = x + np.cos(h) * arc / n, y + np.sin(h) * arc / n
                pts.append((x, y))
                if i == n // 2:
                    apex_s[corner + 1] = s + arc / 2
            s += arc
    p = np.array(pts[:-1])
    tr = T.build("bench", p[:, 0], p[:, 1], ds=2.0, smooth_m=10.0)
    return tr, {n: v / s for n, v in apex_s.items()}


@pytest.fixture(scope="module")
def bench():
    tr, corner_fraction = rounded_rectangle()
    zones = np.zeros(len(tr.s), bool)
    gearing = Gearing((40.0, 52.0, 63.0, 72.0, 81.0, 90.0, 98.0, 106.0), 11500.0)
    intervals = np.array([0.20, 0.22, 0.24, 0.26, 0.28, 0.30])
    rng = np.random.default_rng(1)
    cd, loc, laps = [], [], []
    t0 = pd.Timestamp("2026-06-14 13:00", tz="UTC")
    for k, (team, (mu, cla)) in enumerate(TEAMS.items()):
        lap = simulate(tr, Car(fuel_kg=FUEL, mu=mu, cla_corner=cla, rho=RHO), zones)
        start = t0 + pd.Timedelta(hours=k)
        for n in range(1, 9):
            c, p = render(lap, gearing, start, k, intervals, rng)
            cd.append(c)
            loc.append(p)
            laps.append({"driver_number": k, "lap_number": n, "date_start": start, "lap_time": lap.lap_time,
                         "driver": team, "team": team, "compound": "HARD", "tyre_age": n})
            start += pd.Timedelta(seconds=lap.lap_time)
    samples = placed_samples(pd.concat(cd), pd.concat(loc), pd.DataFrame(laps), tr)
    minima = grip.corner_minima(samples, corner_fraction)
    assert grip.grip_limited(minima).corner.nunique() == len(RADII)
    return tr, corner_fraction, minima


def test_air_density_matches_the_standard_atmosphere():
    assert air_density(1013.25, 15.0, 0.0) == pytest.approx(1.225, abs=0.001)
    assert air_density(1000.5, 30.5, 29.0) == pytest.approx(1.142, abs=0.002)


def test_fit_car_recovers_mu_and_downforce_on_the_true_line(bench):
    tr, corner_fraction, minima = bench
    a_mu, a_cla = TEAMS["A"]
    target = minima[minima.team == "A"].groupby("corner").v.median()
    fit = grip.fit_car(tr, np.zeros(len(tr.s), bool), Car(fuel_kg=FUEL, rho=RHO), corner_fraction, target)
    assert fit.car.mu == pytest.approx(a_mu, rel=0.02)
    assert fit.car.cla_corner == pytest.approx(a_cla, rel=0.04)
    assert fit.rms_kph < 1.0


def test_relative_grip_recovers_each_team(bench):
    tr, corner_fraction, minima = bench
    v_ref = minima.groupby("corner").v.median()
    w = pd.Series(grip.aero_share(v_ref, 1.5, 3.6, Car(fuel_kg=FUEL).mass, RHO), index=v_ref.index)
    rel = grip.relative_grip(minima, w).set_index("team")
    log_mu = np.log([m for m, _ in TEAMS.values()])
    log_cla = np.log([c for _, c in TEAMS.values()])
    for i, team in enumerate(TEAMS):
        assert rel.mech_pct[team] == pytest.approx(100 * (log_mu[i] - log_mu.mean()), abs=0.6)
        assert rel.downforce_pct[team] == pytest.approx(100 * (log_cla[i] - log_cla.mean()), abs=2.0)
