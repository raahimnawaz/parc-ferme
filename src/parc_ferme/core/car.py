"""S2 digital 2026 car: rules from rules_2026.toml, plus the parameters no rulebook gives (aero, grip, gearing).

The aero and grip values below are nominal starting points, not measurements. S3 replaces them with values
fitted per team from telemetry.
"""

import tomllib
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files

import numpy as np
import pandas as pd

RHO_AIR = 1.20
G = 9.81
KPH = 1 / 3.6
R_DRY = 287.05
R_VAPOUR = 461.5


def air_density(pressure_hpa: float, temperature_c: float, humidity_pct: float) -> float:
    """Moist-air density [kg/m^3] from station pressure, temperature and relative humidity (Tetens vapour
    pressure). At Barcelona on race day (1000.5 hPa, 30.5 C, 29%) this is 1.142, 4.8% below RHO_AIR."""
    t = temperature_c + 273.15
    p_sat = 610.78 * 10 ** (7.5 * temperature_c / (temperature_c + 237.3))
    p_v = humidity_pct / 100 * p_sat
    return (100 * pressure_hpa - p_v) / (R_DRY * t) + p_v / (R_VAPOUR * t)


@cache
def rules() -> dict:
    return tomllib.loads(files("parc_ferme.core").joinpath("rules_2026.toml").read_text())


@dataclass(frozen=True)
class Gearing:
    """Road speed per 1000 rpm in each gear, and the rpm at which the driver upshifts."""

    kph_per_krpm: tuple[float, ...]
    upshift_rpm: float

    def gear(self, v_kph: np.ndarray) -> np.ndarray:
        ratios = np.asarray(self.kph_per_krpm)
        rpm = 1000 * np.asarray(v_kph, float)[:, None] / ratios[None, :]
        fits = rpm <= self.upshift_rpm
        return np.where(fits.any(1), fits.argmax(1), len(ratios) - 1) + 1

    def rpm(self, v_kph: np.ndarray, gear: np.ndarray) -> np.ndarray:
        return 1000 * np.asarray(v_kph, float) / np.asarray(self.kph_per_krpm)[np.asarray(gear) - 1]

    @classmethod
    def fit(cls, car_data: pd.DataFrame) -> "Gearing":
        """Median speed/rpm per gear on driven samples, and the median rpm just before an upshift."""
        cd = car_data.sort_values("date")
        d = cd[(cd.speed > 30) & (cd.rpm > 5000) & (cd.n_gear > 0)]
        ratios = (1000 * d.speed / d.rpm).groupby(d.n_gear).median().sort_index()
        up = cd.n_gear.diff() == 1
        return cls(tuple(float(r) for r in ratios.to_numpy()), float(cd.rpm.shift(1)[up].median()))


@dataclass(frozen=True)
class Car:
    fuel_kg: float = 10.0
    cda_corner: float = 1.10
    cla_corner: float = 3.8
    cda_straight: float = 0.80
    cla_straight: float = 2.0
    mu: float = 1.75
    crr: float = 0.012
    driveline_eff: float = 0.95
    regen_eff: float = 0.85
    rho: float = RHO_AIR
    rules: dict = field(default_factory=rules, repr=False)

    @property
    def mass(self) -> float:
        return self.rules["mass"]["minimum_kg"] + self.fuel_kg

    @property
    def ice_w(self) -> float:
        return 1e3 * self.rules["power_unit"]["ice_kw"]

    @property
    def mguk_w(self) -> float:
        return 1e3 * self.rules["power_unit"]["mgu_k_kw"]

    def mguk_limit_w(self, v: np.ndarray) -> np.ndarray:
        """MGU-K deployment cap at speed v [m/s]: full power, then a linear taper to zero."""
        pu = self.rules["power_unit"]
        a, b = pu["mgu_k_taper_start_kph"] * KPH, pu["mgu_k_taper_end_kph"] * KPH
        return self.mguk_w * np.clip((b - np.asarray(v)) / (b - a), 0.0, 1.0)

    def aero(self, straight: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return (np.where(straight, self.cda_straight, self.cda_corner),
                np.where(straight, self.cla_straight, self.cla_corner))
