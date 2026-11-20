"""Assemble the S1 track and S2 car for an ingested session, and run the simulated lap against a real one."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import warmup
from ..bench.fake import render
from ..checks import lap_distances
from ..core import track as T
from ..core.car import Car, Gearing, rules
from ..session import Session
from ..telemetry import lap_trace
from .compare import compare
from .lapsim import Lap, simulate, zone_mask
from .raceline import min_time_line


@dataclass
class CircuitModel:
    reference: T.Track
    line: T.Track
    min_curvature: T.Track
    corner_s: dict[int, float]
    corner_fraction: dict[int, float]
    zones: np.ndarray
    stats: dict


def _on_line(line: T.Track, ref: T.Track, mask_ref: np.ndarray) -> np.ndarray:
    return np.interp(line.s / line.length, ref.s / ref.length, mask_ref.astype(float), period=1.0) > 0.5


def circuit_model(s: Session, car: Car, laps: pd.DataFrame | None = None) -> CircuitModel:
    """S1 for this session (timing-feed layout, surveyed widths, elevation) and the minimum-time line for `car`."""
    laps = warmup.laps(s) if laps is None else laps
    loc = s.location[(s.location.x != 0) | (s.location.y != 0)]
    ref, stats = T.driven_line(s.circuit.name, loc, laps[laps.green])
    ref, matched = T.transfer_widths(ref, T.from_centreline("centreline database", s.circuit.centreline))
    c = s.circuit.corners
    ident = T.Registration.identity()
    s_ref, _ = ident.project(ref, c.x_m.to_numpy(), c.y_m.to_numpy())
    zones_ref = zone_mask(ref, dict(zip(c.number.astype(int), s_ref, strict=True)),
                          rules()["active_aero"]["zones"][str(s.meta["circuit_key"])])
    width = rules()["dimensions"]["width_m"]
    best = min_time_line(ref, car, zones_ref, width)
    mc = T.racing_line(ref, width)
    line = best.line
    s_line, _ = ident.project(line, c.x_m.to_numpy(), c.y_m.to_numpy())
    zones = _on_line(line, ref, zones_ref)
    stats |= {
        "width_matched_share": matched,
        "speed_integrated_lap_m": float(lap_distances(s, laps).median()),
        "min_curvature_line_m": mc.length,
        "min_curvature_lap_s": simulate(mc, car, _on_line(mc, ref, zones_ref)).lap_time,
        "racing_line_m": line.length,
        "line_search_evaluations": best.evaluations,
        "straight_mode_share": float(zones.mean()),
    }
    return CircuitModel(ref, line, mc, dict(zip(c.number.astype(int), s_line, strict=True)),
                        {int(n): float(ref.lap_distance(x) / ref.length) for n, x in zip(c.number, s_ref, strict=True)},
                        zones, stats)


@dataclass
class SimResult:
    lap: Lap
    summary: dict
    corners: pd.DataFrame
    fake_car_data: pd.DataFrame
    fake_location: pd.DataFrame
    real: pd.DataFrame
    fake: pd.DataFrame


def run(s: Session, driver: str, car: Car, seed: int = 0) -> tuple[CircuitModel, SimResult]:
    laps = warmup.laps(s)
    model = circuit_model(s, car, laps)
    lap = simulate(model.line, car, model.zones)

    best = warmup.fastest_lap(laps, driver)
    cd = s.car_data[s.car_data.driver_number == best.driver_number]
    real = lap_trace(cd, best.date_start, best.lap_time)
    intervals = cd.sort_values("date").date.diff().dt.total_seconds().dropna()
    intervals = intervals[(intervals > 0) & (intervals < 1.0)].to_numpy()

    rng = np.random.default_rng(seed)
    z = np.interp(lap.trace.s, model.line.s, model.line.z) if model.line.z is not None else None
    fake_cd, fake_loc = render(lap, Gearing.fit(cd), best.date_start, 0, intervals, rng, z=z)
    fake = lap_trace(fake_cd, best.date_start, lap.lap_time)

    summary, corners = compare(real, fake, model.corner_fraction, float(best.lap_time), lap.lap_time)
    summary |= {"driver": driver, "lap_number": int(best.lap_number), "compound": best.compound,
                "fuel_kg_assumed": car.fuel_kg, "deploy_mj": lap.deploy_mj, "harvest_mj": lap.harvest_mj,
                "soc_swing_mj": lap.soc_swing_mj, "deploy_below_kph": lap.deploy_below_kph}
    return model, SimResult(lap, summary, corners, fake_cd, fake_loc, real, fake)
