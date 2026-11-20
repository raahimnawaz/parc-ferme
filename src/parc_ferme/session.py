"""Offline access to an ingested session."""

import json
from functools import cached_property

import pandas as pd

from .circuit import Circuit, load_circuit
from .paths import session_dir


class Session:
    def __init__(self, session_key: int):
        self.key = session_key
        self.dir = session_dir(session_key)
        if not (self.dir / "meta.json").exists():
            raise FileNotFoundError(f"session {session_key} is not ingested: run `parc-ferme ingest {session_key}`")
        self.meta = json.loads((self.dir / "meta.json").read_text())
        self._tables: dict[str, pd.DataFrame] = {}

    def table(self, name: str) -> pd.DataFrame:
        if name not in self._tables:
            self._tables[name] = pd.read_parquet(self.dir / f"{name}.parquet")
        return self._tables[name]

    def __getattr__(self, name: str) -> pd.DataFrame:
        if name.startswith("_") or not (self.dir / f"{name}.parquet").exists():
            raise AttributeError(name)
        return self.table(name)

    @property
    def name(self) -> str:
        meeting = self.meta["meeting"].get("meeting_name", self.meta["location"])
        return f"{self.meta['year']} {meeting} {self.meta['session_name']}"

    @cached_property
    def circuit(self) -> Circuit:
        return load_circuit(self.meta["circuit_key"], self.meta["year"])

    @cached_property
    def acronyms(self) -> dict[int, str]:
        d = self.table("drivers")
        return dict(zip(d.driver_number, d.name_acronym, strict=True))

    @cached_property
    def teams(self) -> dict[int, str]:
        d = self.table("drivers")
        return dict(zip(d.driver_number, d.team_name, strict=True))
