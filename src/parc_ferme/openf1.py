"""OpenF1 REST client and session ingest to Parquet."""

import json
import time

import pandas as pd
import pyarrow as pa
import requests

from .paths import session_dir

BASE = "https://api.openf1.org/v1/"
USER_AGENT = "parc-ferme/0.1"

SESSION_TABLES = (
    "drivers",
    "laps",
    "stints",
    "pit",
    "race_control",
    "weather",
    "intervals",
    "position",
    "session_result",
    "starting_grid",
    "overtakes",
)
PER_DRIVER_TABLES = ("car_data", "location")
TIME_COLUMNS = ("date", "date_start")
GAP_COLUMNS = ("gap_to_leader", "interval")


class Client:
    def __init__(self, min_interval: float = 0.4, retries: int = 6, timeout: float = 120):
        self.min_interval = min_interval
        self.retries = retries
        self.timeout = timeout
        self._last = 0.0
        self._http = requests.Session()
        self._http.headers["User-Agent"] = USER_AGENT

    def get(self, endpoint: str, **params) -> list[dict]:
        for attempt in range(self.retries):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            r = self._http.get(BASE + endpoint, params=params, timeout=self.timeout)
            if r.status_code == 404:
                return []
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            r.raise_for_status()
            body = r.json()
            return body if isinstance(body, list) else []
        raise RuntimeError(f"OpenF1 {endpoint} {params}: gave up after {self.retries} attempts")


def _split_gap(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    """'+1 LAP' style gaps become (NaN seconds, 1 lap); numeric gaps become (seconds, 0 laps)."""
    text = values.astype("string")
    laps = text.str.extract(r"\+?(\d+)\s*LAP", expand=False).astype("Int64")
    secs = pd.to_numeric(values.where(laps.isna()), errors="coerce")
    return secs, laps.fillna(0)


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in TIME_COLUMNS:
        if col in df:
            df[col] = pd.to_datetime(df[col], utc=True, format="ISO8601")
    for col in GAP_COLUMNS:
        if col in df and pd.api.types.is_object_dtype(df[col]):
            df[col], df[f"{col}_laps"] = _split_gap(df[col])
    for col in df.select_dtypes(include="object").columns:
        try:
            pa.array(df[col], from_pandas=True)
        except (pa.ArrowInvalid, pa.ArrowTypeError):
            df[col] = df[col].map(lambda v: None if v is None else json.dumps(v))
    return df


def fetch_session(session_key: int, client: Client | None = None, refresh: bool = False,
                  log=print) -> dict:
    """Download every table for one session into data/sessions/<key>/. Returns its metadata.

    Tables already on disk are kept unless `refresh`, so an interrupted ingest resumes.
    """
    client = client or Client()
    out = session_dir(session_key)
    out.mkdir(parents=True, exist_ok=True)

    def have(name: str) -> bool:
        return not refresh and (out / f"{name}.parquet").exists()

    sessions = client.get("sessions", session_key=session_key)
    if not sessions:
        raise ValueError(f"OpenF1 has no session {session_key}")
    meta = sessions[0]
    meeting = client.get("meetings", meeting_key=meta["meeting_key"])
    meta["meeting"] = meeting[0] if meeting else {}

    for name in SESSION_TABLES:
        if have(name):
            continue
        df = _frame(client.get(name, session_key=session_key))
        df.to_parquet(out / f"{name}.parquet", index=False)
        log(f"  {name:15} {len(df):>8} rows")

    drivers = sorted(pd.read_parquet(out / "drivers.parquet")["driver_number"].unique())
    for name in PER_DRIVER_TABLES:
        if have(name):
            continue
        parts = [
            _frame(client.get(name, session_key=session_key, driver_number=int(d)))
            for d in drivers
        ]
        df = pd.concat([p for p in parts if not p.empty], ignore_index=True)
        df.to_parquet(out / f"{name}.parquet", index=False)
        log(f"  {name:15} {len(df):>8} rows")

    meta["fetched_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta
