"""Test bench for S3: synthetic teams with known grip and downforce, driven by the lap sim on a test track,
rendered as OpenF1-shaped telemetry and put through the same estimator as real sessions.

`run` and `recovery` check that the estimator recovers known values on clean laps. `race` and `coverage` are the
identifiability bench: a full synthetic race with the confounders the real feed carries, repeated over seeds, to
check that the stated uncertainties cover the truth as often as they claim."""

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from ..core import track as T
from ..core.car import Car, Gearing
from ..models import grip
from ..sim.lapsim import deploy_threshold, simulate
from ..telemetry import placed_samples
from .circuit import bench_circuit
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


FIELD_MU, FIELD_CLA = 1.45, 4.9
TEAM_SPREAD = {"mu": 0.025, "cla": 0.04}
GEARING = Gearing((40.0, 52.0, 63.0, 72.0, 81.0, 90.0, 98.0, 106.0), 11500.0)
INTERVALS = np.array([0.20, 0.22, 0.24, 0.26, 0.28, 0.30])
PARAMS = ("mech", "downforce", "slow_corner", "fast_corner")


@dataclass(frozen=True)
class Confounders:
    """What the feed mixes into corner speeds besides the car. Grip terms are logarithmic (0.01 is about 1%)."""

    line_sd: float = 0.015  # each driver's radius at each corner, held through the race
    lap_line_sd: float = 0.008  # lap-to-lap radius scatter
    commitment_sd: float = 0.007  # each driver's share of the car's grip
    lap_grip_sd: float = 0.003  # lap-to-lap grip scatter
    compounds: tuple = (("SOFT", 0.020, 0.0010), ("MEDIUM", 0.010, 0.0006), ("HARD", 0.0, 0.0004))
    team_wear_sd: float = 0.25  # team-to-team spread in wear rate, relative
    fuel_start_kg: float = 70.0
    fuel_per_lap_kg: float = 1.3
    evolution: float = 0.01  # grip the track gains over the race
    dirty_air: float = 0.06  # downforce lost within 1 s of the car ahead (assumed)
    traffic: tuple = (0.2, 0.5)  # share of laps within 1 s, fastest team to slowest
    dropout: float = 0.01  # car-data samples lost


CLEAN = Confounders(0.0, 0.0, 0.0, 0.0, (("HARD", 0.0, 0.0),), 0.0, grip.FUEL_AVG_KG, 0.0, 0.0, 0.0, (0.0, 0.0), 0.0)


@dataclass
class Race:
    circuit: object
    laps: pd.DataFrame
    minima: pd.DataFrame
    truth: pd.DataFrame


def race(seed: int, conf: Confounders = Confounders(), teams: int = 11, laps: int = 50) -> Race:
    """A synthetic race on the bench circuit: two cars per team over laps 2 to `laps`, with known grip and downforce
    per team, rendered as OpenF1-shaped telemetry. Truth is each team's effective grip on fresh tyres in clean air:
    its tyre grip times its drivers' mean commitment, and its downforce, relative to the mean team [%]."""
    rng = np.random.default_rng(seed)
    c = bench_circuit()
    tr = c.track
    zones = np.zeros(len(tr.s), bool)
    mask = c.corner_mask().astype(float)
    v_star = deploy_threshold(tr, Car(fuel_kg=grip.FUEL_AVG_KG, mu=FIELD_MU, cla_corner=FIELD_CLA, rho=RHO), zones)
    mu = FIELD_MU * np.exp(rng.normal(0, TEAM_SPREAD["mu"], teams))
    cla = FIELD_CLA * np.exp(rng.normal(0, TEAM_SPREAD["cla"], teams))
    wear = np.exp(rng.normal(0, conf.team_wear_sd, teams))
    rank = np.argsort(np.argsort(-(np.log(mu) + 0.4 * np.log(cla))))
    traffic_share = np.interp(rank, [0, teams - 1], conf.traffic)
    names = [name for name, *_ in conf.compounds]
    compound = {name: (offset, loss) for name, offset, loss in conf.compounds}
    t0 = pd.Timestamp("2026-06-14 13:00", tz="UTC")
    car_data, locations, rows, mech = [], [], [], []
    for team in range(teams):
        code = f"T{team + 1:02d}"
        commitment = rng.normal(0, conf.commitment_sd, 2)
        mech.append(np.log(mu[team]) + commitment.mean())
        for d in range(2):
            number = 2 * team + d + 1
            line = rng.normal(0, conf.line_sd, len(c.apex))
            stops = np.sort(rng.choice(np.arange(12, laps - 8), len(names) - 1, replace=False))
            order = rng.permutation(names)
            start = t0 + pd.Timedelta(hours=number)
            for n in range(2, laps + 1):
                stint = int(np.searchsorted(stops, n, side="left"))
                age = n - (1 if stint == 0 else int(stops[stint - 1]))
                offset, loss = compound[order[stint]]
                g = offset - loss * wear[team] * age + conf.evolution * (n - 1) / (laps - 1)
                g += rng.normal(0, conf.lap_grip_sd)
                behind = bool(rng.random() < traffic_share[team])
                car = Car(fuel_kg=max(conf.fuel_start_kg - conf.fuel_per_lap_kg * (n - 1), 1.0),
                          mu=float(mu[team] * np.exp(commitment[d] + g)),
                          cla_corner=float(cla[team] * (1 - conf.dirty_air * behind)), rho=RHO)
                radius = line + rng.normal(0, conf.lap_line_sd, len(line))
                lap = simulate(replace(tr, kappa=tr.kappa * np.exp(-(radius @ mask))), car, zones, v_star)
                cd, pos = render(lap, GEARING, start, number, INTERVALS, rng, dropout=conf.dropout)
                car_data.append(cd)
                locations.append(pos)
                rows.append({"driver_number": number, "lap_number": n, "date_start": start,
                             "lap_time": lap.lap_time, "driver": f"{code}{d}", "team": code,
                             "compound": order[stint], "tyre_age": age,
                             "gap_ahead": rng.uniform(0.3, 0.99) if behind else rng.uniform(1.0, 8.0)})
                start += pd.Timedelta(seconds=lap.lap_time)
    lap_table = pd.DataFrame(rows)
    samples = placed_samples(pd.concat(car_data), pd.concat(locations), lap_table, tr)
    mech = np.array(mech)
    truth = pd.DataFrame({"team": [f"T{k + 1:02d}" for k in range(teams)],
                          "mech": 100 * (mech - mech.mean()),
                          "downforce": 100 * (np.log(cla) - np.log(cla).mean())})
    return Race(c, lap_table, grip.corner_minima(samples, c.apex), truth)


def estimate(r: Race) -> pd.DataFrame:
    """S3 on a synthetic race, as `grip.analyse` runs it on a session: lifted corners, field car fitted to the
    median corner speeds, downforce shares from it, then every team relative to the field."""
    minima = grip.with_dirty_air(grip.grip_limited(r.minima), r.laps)
    v_ref = minima.groupby("corner").v.median()
    base = Car(fuel_kg=grip.FUEL_AVG_KG, rho=RHO)
    zones = np.zeros(len(r.circuit.track.s), bool)
    field = grip.fit_car(r.circuit.track, zones, base, r.circuit.apex, v_ref).car
    w = pd.Series(grip.aero_share(v_ref, field.mu, field.cla_corner, base.mass, RHO), index=v_ref.index)
    return grip.relative_grip(minima, w)


def coverage(seeds, conf: Confounders = Confounders(), **race_kw) -> pd.DataFrame:
    """For every seed, team and reported quantity: estimate, stated standard error, truth and z = error / SE."""
    out = []
    for seed in seeds:
        r = race(seed, conf, **race_kw)
        rel = estimate(r).set_index("team")
        truth = r.truth.set_index("team")
        w = {"slow_corner": rel.attrs["w_slow"], "fast_corner": rel.attrs["w_fast"]}
        for team in truth.index:
            t = {"mech": truth.mech[team], "downforce": truth.downforce[team]}
            t |= {k: t["mech"] + wv * t["downforce"] for k, wv in w.items()}
            for p in PARAMS:
                col = "mech" if p == "mech" else "downforce" if p == "downforce" else p
                est, se = rel[f"{col}_pct"][team], rel[f"{col}_se"][team]
                out.append({"seed": seed, "team": team, "param": p, "est": est, "se": se, "truth": t[p],
                            "z": (est - t[p]) / se})
    return pd.DataFrame(out)
