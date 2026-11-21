"""Test bench for S3: synthetic teams with known grip and downforce, driven by the lap sim on a test track,
rendered as OpenF1-shaped telemetry and put through the same estimator as real sessions."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..core import track as T
from ..core.car import Car, Gearing
from ..models import grip
from ..sim.lapsim import simulate
from ..telemetry import placed_samples
from .fake import render

RADII = (40.0, 100.0, 70.0, 130.0)
RHO = 1.15
TEAMS = {"A": (1.50, 3.60), "B": (1.56, 3.60), "C": (1.46, 3.95), "D": (1.50, 3.30), "E": (1.53, 3.75)}
LAPS_PER_TEAM = 8
TOLERANCE_PCT = {"mech": 0.6, "downforce": 2.0}


def rounded_rectangle(width=1400.0, height=900.0, radii=RADII, step=1.0) -> tuple[T.Track, dict[int, float]]:
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
    return T.build("bench", p[:, 0], p[:, 1], ds=2.0, smooth_m=10.0), {n: v / s for n, v in apex_s.items()}


@dataclass
class Bench:
    track: T.Track
    corner_fraction: dict[int, float]
    minima: pd.DataFrame


def run(seed: int = 1) -> Bench:
    """Every synthetic team's laps, through placement on the line and corner minima, exactly as for a session."""
    tr, corner_fraction = rounded_rectangle()
    zones = np.zeros(len(tr.s), bool)
    gearing = Gearing((40.0, 52.0, 63.0, 72.0, 81.0, 90.0, 98.0, 106.0), 11500.0)
    intervals = np.array([0.20, 0.22, 0.24, 0.26, 0.28, 0.30])
    rng = np.random.default_rng(seed)
    cd, loc, laps = [], [], []
    t0 = pd.Timestamp("2026-06-14 13:00", tz="UTC")
    for k, (team, (mu, cla)) in enumerate(TEAMS.items()):
        lap = simulate(tr, Car(fuel_kg=grip.FUEL_AVG_KG, mu=mu, cla_corner=cla, rho=RHO), zones)
        start = t0 + pd.Timedelta(hours=k)
        for n in range(1, LAPS_PER_TEAM + 1):
            c, p = render(lap, gearing, start, k, intervals, rng)
            cd.append(c)
            loc.append(p)
            laps.append({"driver_number": k, "lap_number": n, "date_start": start, "lap_time": lap.lap_time,
                         "driver": team, "team": team, "compound": "HARD", "tyre_age": n})
            start += pd.Timedelta(seconds=lap.lap_time)
    samples = placed_samples(pd.concat(cd), pd.concat(loc), pd.DataFrame(laps), tr)
    return Bench(tr, corner_fraction, grip.corner_minima(samples, corner_fraction))


def recovery(bench: Bench | None = None) -> pd.DataFrame:
    """True and recovered mechanical grip and downforce per synthetic team, relative to the mean team [%]."""
    bench = run() if bench is None else bench
    mass = Car(fuel_kg=grip.FUEL_AVG_KG).mass
    mus, clas = (np.array(v) for v in zip(*TEAMS.values(), strict=True))
    v_ref = bench.minima.groupby("corner").v.median()
    w = pd.Series(grip.aero_share(v_ref, np.median(mus), np.median(clas), mass, RHO), index=v_ref.index)
    rel = grip.relative_grip(bench.minima, w).set_index("team").loc[list(TEAMS)]
    out = pd.DataFrame({"team": list(TEAMS),
                        "mech_true": 100 * (np.log(mus) - np.log(mus).mean()), "mech": rel.mech_pct.to_numpy(),
                        "downforce_true": 100 * (np.log(clas) - np.log(clas).mean()),
                        "downforce": rel.downforce_pct.to_numpy()})
    out["mech_err"] = out.mech - out.mech_true
    out["downforce_err"] = out.downforce - out.downforce_true
    return out
