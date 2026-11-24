"""2026 MGU-K deployment limit against car speed.

FIA 2026 F1 Regulations, Section C, Issue 20 (5 Aug 2026), Art. C5.2.8: the ERS-K power used to propel the car may
not exceed P = 1800 - 5 v (kW, v in km/h) below 340 km/h, 6900 - 20 v from 340 to 345 km/h and 0 from 345 km/h;
with Overtake active, 7100 - 20 v below 355 km/h and 0 from 355 km/h. C5.2.7 caps |P| at 350 kW. Harvesting is
limited only by C5.2.7, so the MGU-K may recover at any speed.
"""
import numpy as np
from numba import njit

LIMIT_KW = 350.0


@njit(cache=True)
def deploy_fraction(v_ms, overtake=False):
    """Fraction of the 350 kW limit that may propel the car at speed v [m/s]."""
    kph = 3.6 * v_ms
    if overtake:
        p = 7100.0 - 20.0 * kph if kph < 355.0 else 0.0
    elif kph < 340.0:
        p = 1800.0 - 5.0 * kph
    elif kph < 345.0:
        p = 6900.0 - 20.0 * kph
    else:
        p = 0.0
    return min(max(p / LIMIT_KW, 0.0), 1.0)


def deploy_fraction_array(v_ms, overtake: bool = False) -> np.ndarray:
    kph = 3.6 * np.asarray(v_ms, float)
    if overtake:
        p = np.where(kph < 355.0, 7100.0 - 20.0 * kph, 0.0)
    else:
        p = np.select([kph < 340.0, kph < 345.0], [1800.0 - 5.0 * kph, 6900.0 - 20.0 * kph], 0.0)
    return np.clip(p / LIMIT_KW, 0.0, 1.0)
