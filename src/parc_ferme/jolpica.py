"""Official classification from Jolpica (Ergast-compatible), used to cross-check OpenF1."""

import json

import pandas as pd
import requests

from .paths import DATA

BASE = "https://api.jolpi.ca/ergast/f1/"


def _get(path: str) -> dict:
    cache = DATA / "jolpica" / (path.replace("/", "_") + ".json")
    if not cache.exists():
        r = requests.get(BASE + path + ".json", params={"limit": 100}, timeout=60)
        r.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(r.text)
    return json.loads(cache.read_text())["MRData"]


def race_round(year: int, date: str) -> int:
    races = _get(f"{year}")["RaceTable"]["Races"]
    for race in races:
        if race["date"] == date:
            return int(race["round"])
    raise ValueError(f"no {year} race on {date}")


def race_results(year: int, rnd: int) -> pd.DataFrame:
    race = _get(f"{year}/{rnd}/results")["RaceTable"]["Races"][0]
    return pd.DataFrame(
        {
            "driver_number": int(r["number"]),
            "code": r["Driver"].get("code"),
            "grid": int(r["grid"]),
            "position": int(r["position"]),
            "classified": r["positionText"].isdigit(),
            "status": r["status"],
            "laps": int(r["laps"]),
        }
        for r in race["Results"]
    )
