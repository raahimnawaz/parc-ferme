import json
import re
from html.parser import HTMLParser

import numpy as np
import pandas as pd
import pytest

from parc_ferme.bench import grip as grip_bench
from parc_ferme.bench import pace as pace_bench
from parc_ferme.core.car import Car
from parc_ferme.debrief import channels, summary
from parc_ferme.debrief.build import SCHEMA, to_json
from parc_ferme.models import grip, pace
from parc_ferme.site import render


def _records(df):
    return json.loads(df.to_json(orient="records"))


@pytest.fixture(scope="module")
def debrief(bench_session):
    """A complete debrief document built from the test benches and the synthetic session, in the shape
    debrief.build writes and the site reads back."""
    p = pace.sector_pace(pace_bench.race(), n_boot=20)
    b = grip_bench.run()
    v_ref = b.minima.groupby("corner").v.median()
    w = pd.Series(grip.aero_share(v_ref, 1.5, 3.6, 803.0, 1.15), index=v_ref.index)
    rel = grip.relative_grip(b.minima, w)
    corners = [{"corner": int(c), "real_kph": 3.6 * v, "sim_kph": 3.6 * v + d, "diff_kph": d, "w": float(w[c])}
               for (c, v), d in zip(v_ref.items(), (6.0, -9.0, 2.0, -14.0), strict=True)]
    angle = np.linspace(0, 2 * np.pi, 200, endpoint=False)
    track = {"x": (600 * np.cos(angle)).round(1).tolist(), "y": (300 * np.sin(angle)).round(1).tolist(),
             "corners": [{"number": n, "label": str(n), "x": 600 * np.cos(a), "y": 300 * np.sin(a),
                          "lx": 660 * np.cos(a), "ly": 340 * np.sin(a), "kph": c["real_kph"], "w": c["w"],
                          "flat_out": False} for n, a, c in zip(range(1, 5), (0.5, 2.0, 3.5, 5.0), corners,
                                                                  strict=True)],
             "lines": [{"line": "start", "x": 600.0, "y": 0.0, "nx": 1.0, "ny": 0.0},
                       {"line": "S1/S2", "x": -300.0, "y": 260.0, "nx": -0.5, "ny": 0.87},
                       {"line": "S2/S3", "x": -300.0, "y": -260.0, "nx": -0.5, "ny": -0.87}]}
    rel = rel.assign(team=rel.team.map(lambda t: f"Team {t}"))
    sectors = [{"sector": 1, "from": 0.0, "to": 0.3, "corners": [1]},
               {"sector": 2, "from": 0.3, "to": 0.7, "corners": [2, 3]},
               {"sector": 3, "from": 0.7, "to": 1.0, "corners": [4]}]
    s = bench_session
    field = Car(fuel_kg=channels.SIM_FUEL_KG, mu=1.48, cla_corner=3.6, rho=1.15)
    d = {
        "schema": SCHEMA,
        "session": {"key": 1, "year": 2026, "round": 3, "name": "Test Grand Prix", "session_name": "Race",
                    "circuit": "Test Circuit", "date": "2026-03-01", "laps": 60},
        "conditions": {"air_c": 21.0, "track_c": 35.0, "humidity_pct": 40.0, "pressure_hpa": 1012.0,
                       "rain": False, "air_density": 1.19},
        "podium": [{"position": 1, "driver": "AAA", "team": "Team AAA", "grid": 2}],
        "cars": {c: {"name": f"Driver {c}", "last": c.title(), "team": f"Team {c}", "number": k,
                     "colour": "#e8002d"} for k, c in enumerate(pace_bench.CARS, start=1)},
        "sectors": sectors,
        "pace": {"reference": p.reference, "cars": _records(p.cars), "traffic": _records(p.traffic),
                 "holdout": p.holdout, "excluded": [], "min_laps": pace.MIN_LAPS},
        "grip": {"teams": _records(rel), "w_slow": rel.attrs["w_slow"], "w_fast": rel.attrs["w_fast"],
                 "laps": rel.attrs["laps"], "corners": corners, "flat_out": [],
                 "field": {"mu": 1.5, "cla": 3.6, "rms_kph": 9.4, "mass_kg": 803.0},
                 "clean_air": {"gap_s": 1.5, "laps": 30,
                               "teams": [{"team": r["team"], "slow": r["slow_corner_pct"] + 0.2,
                                          "fast": r["fast_corner_pct"] - 0.1} for r in _records(rel)]},
                 "sections": [{"from_m": 0.0, "to_m": 500.0, "driven_m": 510.0, "line_m": 500.0,
                               "line_short_m": 10.0},
                              {"from_m": 500.0, "to_m": 900.0, "driven_m": None, "line_m": 400.0,
                               "line_short_m": float("nan")}]},
        "track": track,
        "telemetry": channels.telemetry(s.car_data, s.laps, s.model, sectors, _records(rel), field, s.track.length),
        "car_model": channels.parameter_effects(s.model.line, s.model.zones, field),
        "bench": {"rows": _records(grip_bench.recovery(b)), "tolerance_pct": grip_bench.TOLERANCE_PCT,
                  "passed": True},
        "pace_bench": {"cars": 6, "laps": 60, "max_error_s": 0.03, "tolerance_s": 0.06, "passed": True},
        "checks": [{"name": "speed_scale", "passed": True, "gating": True, "detail": "median 1.0004",
                    "value": 1.0004},
                   {"name": "centreline_matches_layout", "passed": False, "gating": False, "detail": "67%",
                    "value": None}],
        "code": {"commit": "abc1234", "dirty": False},
        "generated_utc": "2026-03-01 18:00",
    }
    return json.loads(to_json(d))  # as the site reads it back from disk


class _Checker(HTMLParser):
    """Collects text and checks that every tag opened is closed in order."""

    VOID = {"meta", "br", "img", "input", "link", "path", "circle", "line"}

    def __init__(self):
        super().__init__()
        self.stack, self.text, self.errors = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"</{tag}> closes <{self.stack[-1] if self.stack else None}>")
        else:
            self.stack.pop()

    def handle_data(self, data):
        self.text.append(data)


def _embedded(html: str) -> dict:
    return json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1))


def test_summary_states_only_what_the_uncertainty_supports(debrief):
    texts = [f["text"] for f in summary.findings(debrief)]
    assert len(texts) == 3
    assert texts[0].startswith("Aaa's Team AAA had the fastest race pace")
    level = json.loads(json.dumps(debrief))
    level["pace"]["cars"][1]["lap"] = 0.01
    assert "same race pace within the uncertainty" in summary.pace_finding(level)


def test_leading_group_keeps_teams_the_uncertainty_cannot_separate():
    rows = [{"team": "A", "fast_corner_pct": 4.0, "fast_corner_se": 0.5},
            {"team": "B", "fast_corner_pct": 3.5, "fast_corner_se": 0.5},
            {"team": "C", "fast_corner_pct": 0.0, "fast_corner_se": 0.5}]
    assert [r["team"] for r in summary.leading_group(rows, "fast_corner_pct")] == ["A", "B"]
    assert [r["team"] for r in summary.leading_group(rows, "fast_corner_pct", lowest=True)] == ["C"]


def test_document_json_is_strict(debrief):
    assert to_json({"a": float("nan"), "b": [np.float64(1.5), np.int64(2)], "c": np.bool_(True)}) == \
        '{"a":null,"b":[1.5,2],"c":true}'
    json.loads(to_json(debrief), parse_constant=lambda c: pytest.fail(f"{c} in the document"))


def test_page_is_well_formed_and_carries_every_workspace(debrief):
    checker = _Checker()
    checker.feed(render.page(debrief))
    assert not checker.errors, checker.errors[:3]
    assert checker.stack == []
    text = " ".join(checker.text)
    for label in ("Lap analysis", "Race pace", "Car model", "Model health", "Cost of following, per lap",
                  "Car model parameters", "Cornering grip by team", "Data checks"):
        assert label in text
    for tile in ("Speed channel", "Grip model bench", "Pace model bench", "Grip in dirty air", "Racing line length"):
        assert tile in text
    assert "1.0004" in text and "−10 m" in text
    assert "not associated in any way with the Formula 1 companies" in text


def test_page_embeds_what_its_script_draws(debrief):
    html = render.page(debrief)
    data = _embedded(html)
    assert set(data) == {"L", "dx", "n", "sectors", "corners", "zones", "map", "cars", "best", "sims", "adjusted"}
    assert re.findall(r'<option value="([^"]+)">', html) == list(data["cars"]) * 2
    for car in data["cars"].values():
        assert car["colour"].startswith("#") and car["team"] and car["last"]
        for lap in ("fastest", "typical"):
            assert {len(a) for a in car[lap]["ch"].values()} == {data["n"]}
    for sim in data["sims"].values():
        assert {len(a) for a in sim["ch"].values()} == {data["n"]}
    assert data["adjusted"][debrief["pace"]["reference"]][0] == 0


def test_names_from_the_feed_cannot_break_out_of_the_page(debrief):
    hostile = json.loads(json.dumps(debrief))
    code = next(iter(hostile["telemetry"]["laps"]))
    hostile["cars"][code]["last"] = "</script><script>alert(1)</script>"
    html = render.page(hostile)
    assert "<script>alert(1)" not in html
    assert _embedded(html)["cars"][code]["last"] == "</script><script>alert(1)</script>"


def test_site_build_replaces_the_last_one(tmp_path, debrief):
    stale = tmp_path / "prototype" / "index.html"
    stale.parent.mkdir()
    stale.write_text("old")
    (tmp_path / "index.html").write_text("old index")
    pages = render.write(tmp_path, [debrief])
    assert pages == [tmp_path / "2026" / "03-test-grand-prix-race" / "index.html"]
    assert not stale.exists()
    for ref in re.findall(r'(?:href|src)="(\.\./[^"?]*)', pages[0].read_text()):
        assert (pages[0].parent / ref).resolve().exists(), ref
    assert 'href="2026/03-test-grand-prix-race/"' in (tmp_path / "index.html").read_text()
    assert json.loads((pages[0].parent / "debrief.json").read_text())["session"]["name"] == "Test Grand Prix"


def test_site_build_leaves_a_directory_that_is_not_a_site_alone(tmp_path, debrief):
    (tmp_path / "notes.txt").write_text("keep")
    with pytest.raises(RuntimeError, match="doesn't look like a site build"):
        render.write(tmp_path, [debrief])
    assert (tmp_path / "notes.txt").read_text() == "keep"
