import numpy as np
import pytest

from parc_ferme.bench import grip as bench
from parc_ferme.core.car import Car, air_density
from parc_ferme.models import grip


@pytest.fixture(scope="module")
def run():
    b = bench.run()
    assert grip.grip_limited(b.minima).corner.nunique() == len(bench.RADII)
    return b


def test_air_density_matches_the_standard_atmosphere():
    assert air_density(1013.25, 15.0, 0.0) == pytest.approx(1.225, abs=0.001)
    assert air_density(1000.5, 30.5, 29.0) == pytest.approx(1.142, abs=0.002)


def test_fit_car_recovers_mu_and_downforce_on_the_true_line(run):
    a_mu, a_cla = bench.TEAMS["A"]
    target = run.minima[run.minima.team == "A"].groupby("corner").v.median()
    fit = grip.fit_car(run.track, np.zeros(len(run.track.s), bool),
                       Car(fuel_kg=grip.FUEL_AVG_KG, rho=bench.RHO), run.corner_fraction, target)
    assert fit.car.mu == pytest.approx(a_mu, rel=0.02)
    assert fit.car.cla_corner == pytest.approx(a_cla, rel=0.04)
    assert fit.rms_kph < 1.0


def test_relative_grip_recovers_each_team(run):
    r = bench.recovery(run)
    assert np.all(np.abs(r.mech_err) <= bench.TOLERANCE_PCT["mech"])
    assert np.all(np.abs(r.downforce_err) <= bench.TOLERANCE_PCT["downforce"])
