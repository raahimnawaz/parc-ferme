"""Data checks run on every ingested session. A session is usable only if all gating checks pass."""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from . import jolpica, warmup
from .laps import reconcile_stints
from .session import Session
from .telemetry import lap_trace

SECTOR_TOL_S = 0.01
DISTANCE_TOL = 0.02
LAYOUT_TOL = 0.015
SAMPLE_DT_RANGE = (0.15, 0.40)
MAX_GAP_S = 1.0


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    gating: bool = True

    def __post_init__(self):
        self.passed = bool(self.passed)

    def as_dict(self) -> dict:
        return asdict(self)


def drivers(s: Session) -> Check:
    n = s.drivers.driver_number.nunique()
    missing = set(s.session_result.driver_number) - set(s.drivers.driver_number)
    return Check("drivers", n == 22 and not missing, f"{n} drivers; {len(missing)} results without a driver entry")


def lap_count(s: Session) -> Check:
    winner = s.session_result.sort_values("position").iloc[0]
    laps_done = int(s.laps[s.laps.driver_number == winner.driver_number].lap_number.max())
    ok = laps_done == int(winner.number_of_laps)
    return Check("lap_count", ok,
                 f"winner #{winner.driver_number}: {laps_done} laps timed, {winner.number_of_laps} classified")


def sectors(s: Session) -> Check:
    lp = s.laps.dropna(subset=["duration_sector_1", "duration_sector_2", "duration_sector_3", "lap_duration"])
    err = (lp.duration_sector_1 + lp.duration_sector_2 + lp.duration_sector_3 - lp.lap_duration).abs()
    bad = int((err > SECTOR_TOL_S).sum())
    return Check("sectors_sum_to_lap", bad <= 0.01 * len(lp),
                 f"{len(lp)} complete laps, {bad} off by more than {SECTOR_TOL_S} s (max {err.max():.3f} s)")


def stints(s: Session) -> list[Check]:
    fixed, moved = reconcile_stints(s.stints, s.pit, s.laps)
    problems = []
    completed = s.laps.dropna(subset=["lap_duration"]).groupby("driver_number").lap_number.max()
    for drv, g in fixed.sort_values("stint_number").groupby("driver_number"):
        starts, ends = g.lap_start.to_numpy(), g.lap_end.to_numpy()
        if starts[0] != 1 or np.any(starts[1:] != ends[:-1] + 1) or ends[-1] < completed.get(drv, 0):
            problems.append(s.acronyms.get(drv, drv))
    listed = ", ".join(map(str, problems)) or "none"
    corrections = "; ".join(f"{s.acronyms.get(d, d)} stint ends {old} → {new}" for d, (old, new) in moved.items())
    return [
        Check("stints_contiguous", not problems,
              f"{fixed.driver_number.nunique()} drivers, after reconciling with the pit log; "
              f"gaps or overlaps: {listed}"),
        Check("stints_agree_with_pit_log", not moved,
              f"OpenF1 stint boundaries corrected from the pit log: {corrections or 'none'}", gating=False),
    ]


def pits(s: Session) -> Check:
    stops = s.pit.groupby("driver_number").size()
    changes = s.stints.groupby("driver_number").size() - 1
    diff = stops.reindex(changes.index, fill_value=0) - changes
    off = {s.acronyms.get(d, d): int(v) for d, v in diff.items() if v != 0}
    return Check("pit_stops_match_stints", not off,
                 f"{int(stops.sum())} pit entries, {int(changes.sum())} tyre changes; mismatched: {off or 'none'}")


def car_data_rate(s: Session) -> Check:
    start = pd.Timestamp(s.laps.date_start.min())
    end = start + pd.to_timedelta(float(s.session_result.duration.max()), unit="s")
    cd = s.car_data[(s.car_data.date >= start) & (s.car_data.date <= end)]
    dts, worst = [], ("", 0.0)
    for drv, g in cd.groupby("driver_number"):
        dt = g.date.sort_values().diff().dt.total_seconds().dropna()
        dts.append(dt.median())
        frac = float((dt > MAX_GAP_S).mean())
        if frac > worst[1]:
            worst = (s.acronyms.get(drv, drv), frac)
    med = float(np.median(dts))
    ok = SAMPLE_DT_RANGE[0] <= med <= SAMPLE_DT_RANGE[1] and worst[1] < 0.01
    return Check("car_data_rate", ok,
                 f"median sample interval {med:.3f} s ({1 / med:.1f} Hz); worst gaps >{MAX_GAP_S:.0f} s: "
                 f"{worst[0] or 'none'} {100 * worst[1]:.2f}% of samples")


def lap_distances(s: Session, t: pd.DataFrame) -> pd.Series:
    out = {}
    for drv, g in t[t.green].groupby("driver"):
        lap = g.loc[g.lap_time.idxmin()]
        cd = s.car_data[s.car_data.driver_number == lap.driver_number]
        tr = lap_trace(cd, lap.date_start, lap.lap_time)
        if len(tr):
            out[drv] = float(tr.distance.iloc[-1])
    return pd.Series(out, name="distance_m")


def lap_distance(s: Session, t: pd.DataFrame) -> Check:
    ref = s.circuit.centreline_length_m
    dist = lap_distances(s, t)
    rel = (dist - ref).abs() / ref
    ok = (rel <= DISTANCE_TOL).mean() >= 0.9
    return Check("lap_distance", ok,
                 f"speed integrated over each fastest lap: median {dist.median():.0f} m, "
                 f"range {dist.min():.0f}–{dist.max():.0f} m, vs centreline {ref:.0f} m; "
                 f"{int((rel <= DISTANCE_TOL).sum())}/{len(rel)} within {100 * DISTANCE_TOL:.0f}%")


def layout(s: Session, t: pd.DataFrame) -> Check:
    ref = s.circuit.centreline_length_m
    measured = lap_distances(s, t).median()
    rel = abs(ref - measured) / measured
    return Check("centreline_matches_layout", rel <= LAYOUT_TOL,
                 f"TUMFTM centreline {ref:.0f} m vs median driven lap {measured:.0f} m ({100 * rel:.1f}%)")


def results(s: Session) -> Check:
    rnd = jolpica.race_round(s.meta["year"], s.meta["date_start"][:10])
    off = jolpica.race_results(s.meta["year"], rnd).set_index("driver_number")
    ours = s.session_result.set_index("driver_number")
    classified = off[off.classified].index
    mism = [f"{off.code[d]} {ours.position.get(d)}≠{off.position[d]}"
            for d in classified if ours.position.get(d) != off.position[d]]
    return Check("results_match_official", not mism,
                 f"R{rnd}: {len(classified)} classified drivers compared with Jolpica; "
                 f"mismatches: {', '.join(mism) or 'none'}")


def warmups(t: pd.DataFrame) -> list[Check]:
    deg = warmup.degradation(t)
    used = deg[deg.green_laps >= 30]
    long_runs = warmup.best_long_run(t)
    return [
        Check("green_laps", t.green.mean() > 0.6,
              f"{int(t.green.sum())}/{len(t)} laps green ({100 * t.green.mean():.0f}%)"),
        Check("degradation_fits", bool(len(used)) and used.slope_s_per_lap.notna().all()
              and (used.stderr < 0.05).all(),
              "; ".join(f"{r.compound} {r.slope_s_per_lap:+.3f}±{r.stderr:.3f} s/lap (n={r.green_laps})"
                        for r in deg.itertuples())),
        Check("long_runs", len(long_runs) >= 10,
              f"{len(long_runs)} drivers with a {warmup.LONG_RUN}-lap green run", gating=False),
    ]


def run(s: Session) -> tuple[list[Check], pd.DataFrame]:
    t = warmup.laps(s)
    checks = [drivers(s), lap_count(s), sectors(s), *stints(s), pits(s), car_data_rate(s),
              lap_distance(s, t), layout(s, t), results(s), *warmups(t)]
    return checks, t
