import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("PARC_FERME_DATA", ROOT / "data"))
REPORTS = ROOT / "reports"
SITE = ROOT / "_site"


def session_dir(session_key: int) -> Path:
    return DATA / "sessions" / str(session_key)


def circuit_path(circuit_key: int, year: int) -> Path:
    return DATA / "circuits" / f"{circuit_key}_{year}.json"


def centreline_path(name: str) -> Path:
    return DATA / "tracks" / f"{name}.csv"
