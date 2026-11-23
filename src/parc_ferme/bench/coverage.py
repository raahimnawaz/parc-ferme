"""Interval coverage: whether stated standard errors cover the truth as often as they claim, and what a session's
estimates can then be said to resolve.

For a calibrated estimator, z = (estimate - truth) / SE has a spread of 1 and |z| <= 1.96 about 95% of the time.
"""

import numpy as np
from scipy import stats

Z95 = 1.96
MIN_COVER_95 = 0.90
MAX_SD_Z = 1.25
RESOLVED_SE_SHARE = 1 / 3


def summary(z) -> dict:
    z = np.asarray(z, float)
    z = z[np.isfinite(z)]
    return {"n": int(len(z)), "mean_z": float(z.mean()), "sd_z": float(z.std(ddof=1)),
            "cover_68": float(np.mean(np.abs(z) <= 1.0)), "cover_95": float(np.mean(np.abs(z) <= Z95))}


def calibrated(s: dict) -> bool:
    """Intervals no narrower than they claim. Wider ones are conservative, and pass."""
    return s["cover_95"] >= MIN_COVER_95 and s["sd_z"] <= MAX_SD_Z


def resolution(est, se, bench_ok: bool) -> str:
    """What a session's estimates of one quantity, one per team or car relative to the field, can be said to show.

    "not resolved": the bench doesn't back the intervals, or the differences are no bigger than the noise (a
    chi-square test of all of them being zero passes at 5%). "interval only": the differences are real, but a
    typical uncertainty is more than a third of the spread between them, so rankings are uncertain. "resolved":
    otherwise.
    """
    est, se = np.asarray(est, float), np.asarray(se, float)
    ok = np.isfinite(est) & np.isfinite(se) & (se > 0)
    est, se = est[ok], se[ok]
    if not bench_ok or len(est) < 2:
        return "not resolved"
    chi2 = float(np.sum((est / se) ** 2))
    if stats.chi2.sf(chi2, len(est) - 1) >= 0.05:
        return "not resolved"
    return "resolved" if np.median(se) <= RESOLVED_SE_SHARE * np.std(est) else "interval only"
