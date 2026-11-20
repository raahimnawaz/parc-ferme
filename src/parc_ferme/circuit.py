"""Circuit geometry: corners and outline from the timing feed, centreline and width from TUMFTM."""

import json
from dataclasses import dataclass
from io import StringIO

import numpy as np
import pandas as pd
import requests

from .paths import centreline_path, circuit_path

CIRCUIT_INFO = "https://api.multiviewer.app/api/v1/circuits/{key}/{year}"
TUMFTM = "https://raw.githubusercontent.com/TUMFTM/racetrack-database/master/tracks/{name}.csv"
TUMFTM_NAMES = {15: "Catalunya"}
FEED_UNITS_PER_M = 10.0


def fetch_circuit(circuit_key: int, year: int) -> dict:
    path = circuit_path(circuit_key, year)
    if not path.exists():
        r = requests.get(CIRCUIT_INFO.format(key=circuit_key, year=year),
                         headers={"User-Agent": "parc-ferme/0.1"}, timeout=60)
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(r.text)
    return json.loads(path.read_text())


def fetch_centreline(circuit_key: int) -> pd.DataFrame:
    name = TUMFTM_NAMES[circuit_key]
    path = centreline_path(name)
    if not path.exists():
        r = requests.get(TUMFTM.format(name=name), timeout=60)
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(r.text)
    df = pd.read_csv(StringIO(path.read_text().lstrip("# ")))
    return df.rename(columns=str.strip)


def closed_length(x: np.ndarray, y: np.ndarray) -> float:
    dx = np.diff(np.append(x, x[0]))
    dy = np.diff(np.append(y, y[0]))
    return float(np.hypot(dx, dy).sum())


@dataclass(frozen=True)
class Circuit:
    key: int
    year: int
    name: str
    corners: pd.DataFrame
    outline: pd.DataFrame
    centreline: pd.DataFrame
    pit_loss: dict
    rotation: float

    @property
    def outline_length_m(self) -> float:
        o = self.outline
        return closed_length(o.x.to_numpy(), o.y.to_numpy())

    @property
    def centreline_length_m(self) -> float:
        c = self.centreline
        return closed_length(c.x_m.to_numpy(), c.y_m.to_numpy())


def load_circuit(circuit_key: int, year: int) -> Circuit:
    info = fetch_circuit(circuit_key, year)
    corners = pd.DataFrame(
        {
            "number": c["number"],
            "letter": c.get("letter", ""),
            "angle_deg": c["angle"],
            "x_m": c["trackPosition"]["x"] / FEED_UNITS_PER_M,
            "y_m": c["trackPosition"]["y"] / FEED_UNITS_PER_M,
        }
        for c in info["corners"]
    )
    outline = pd.DataFrame(
        {"x": np.asarray(info["x"]) / FEED_UNITS_PER_M, "y": np.asarray(info["y"]) / FEED_UNITS_PER_M}
    )
    return Circuit(
        key=circuit_key,
        year=year,
        name=info["circuitName"],
        corners=corners,
        outline=outline,
        centreline=fetch_centreline(circuit_key),
        pit_loss=info.get("pitLoss") or {},
        rotation=float(info.get("rotation", 0.0)),
    )
