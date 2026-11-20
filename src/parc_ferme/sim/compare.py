"""Simulated lap against a real one, on lap fraction so the two lines' different lengths don't misalign them."""

import numpy as np
import pandas as pd

WINDOW = 0.012


def on_fraction(distance: np.ndarray, values: np.ndarray, n: int = 2000) -> tuple[np.ndarray, np.ndarray]:
    f = np.linspace(0, 1, n, endpoint=False)
    return f, np.interp(f, np.asarray(distance) / distance[-1], values)


def compare(real: pd.DataFrame, sim: pd.DataFrame, corner_fraction: dict[int, float],
            real_time: float, sim_time: float) -> tuple[dict, pd.DataFrame]:
    """`real` and `sim` have distance [m] and speed [km/h] columns. Returns summary numbers and per-corner minima."""
    f, vr = on_fraction(real.distance.to_numpy(), real.speed.to_numpy(float))
    _, vs = on_fraction(sim.distance.to_numpy(), sim.speed.to_numpy(float))
    rows = []
    for n, fc in corner_fraction.items():
        near = np.abs(((f - fc + 0.5) % 1.0) - 0.5) < WINDOW
        rows.append({"corner": n, "real_min_kph": vr[near].min(), "sim_min_kph": vs[near].min()})
    corners = pd.DataFrame(rows)
    corners["diff_kph"] = corners.sim_min_kph - corners.real_min_kph
    summary = {
        "real_lap_s": real_time,
        "sim_lap_s": sim_time,
        "lap_diff_pct": 100 * (sim_time - real_time) / real_time,
        "real_length_m": float(real.distance.iloc[-1]),
        "sim_length_m": float(sim.distance.iloc[-1]),
        "real_top_kph": float(vr.max()),
        "sim_top_kph": float(vs.max()),
        "speed_rms_kph": float(np.sqrt(np.mean((vs - vr) ** 2))),
        "speed_corr": float(np.corrcoef(vs, vr)[0, 1]),
        "corner_min_bias_kph": float(corners.diff_kph.mean()),
    }
    return summary, corners
