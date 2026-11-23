"""The static site: a telemetry workstation for each session, and an index of sessions.

Each page is rendered from its session's debrief document alone. The race pace, car model and model health
workspaces are rendered here; the lap traces, track map and read-outs are drawn in the browser by static/dash.js,
with uPlot, from the telemetry embedded in the page.
"""

import hashlib
import re
import shutil
from html import escape
from pathlib import Path

from ..debrief.build import to_json

REPO_URL = "https://github.com/raahimnawaz/parc-ferme"
STATIC = Path(__file__).parent / "static"
ASSETS = ("dash.css", "dash.js")
FONTS = ("https://fonts.googleapis.com/css2?family=Saira:wdth,wght@100..125,300..500"
         "&family=Martian+Mono:wdth,wght@75..112.5,300..400&display=swap")
UPLOT_CSS = ("https://cdn.jsdelivr.net/npm/uplot@1.6.32/dist/uPlot.min.css",
             "sha384-IfV0B7MIOYuO95kO9G5ySKPz/85zqFNOAs8iy4tkK5zd9izhJAB8b7lHrwYqqmYE")
UPLOT_JS = ("https://cdn.jsdelivr.net/npm/uplot@1.6.32/dist/uPlot.iife.min.js",
            "sha384-Gx3t0zdBAuQOuvvmaLZj7HKEiSgWTAs+VdtNY7wt19QDPTDQjFIwAuXDj0zeN00c")
WORKSPACES = (("lap", "Lap analysis"), ("pace", "Race pace"), ("car", "Car model"), ("health", "Model health"))
TEAM_SHORT = {"Haas F1 Team": "Haas", "Red Bull Racing": "Red Bull"}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
FRONT_ROWS = 8

DISCLAIMER = ("parc-ferme is an independent project and is not associated in any way with the Formula 1 companies. "
              "F1, FORMULA ONE, FORMULA 1, FIA FORMULA ONE WORLD CHAMPIONSHIP, GRAND PRIX and related marks are "
              "trade marks of Formula One Licensing B.V.")

SOURCES = ('Data: <a href="https://openf1.org">OpenF1</a> (timing, car data, positions, weather), the F1 '
           'circuit-info service (corner positions), the <a href="https://github.com/TUMFTM/racetrack-database">'
           'TUMFTM racetrack database</a> (track widths, LGPL-3.0) and <a href="https://github.com/jolpica/jolpica-f1">'
           'Jolpica</a> (official classification).')

DATA_CHECK_NAMES = {
    "drivers": "Drivers", "lap_count": "Race distance", "sectors_sum_to_lap": "Sector times",
    "stints_contiguous": "Tyre stints", "stints_agree_with_pit_log": "Stints against the pit log",
    "pit_stops_match_stints": "Pit stops", "car_data_rate": "Car data rate", "lap_distance": "Lap distance",
    "speed_scale": "Speed channel", "centreline_matches_layout": "Track layout",
    "results_match_official": "Official result", "green_laps": "Green laps", "degradation_fits": "Tyre wear fits",
    "long_runs": "Long runs",
}


def e(x) -> str:
    return escape(str(x), quote=True)


def signed(x: float, nd: int = 2) -> str:
    if abs(x) < 0.5 * 10 ** -nd:
        x = 0.0
    return f"{'+' if x > 0 else '−' if x < 0 else ''}{abs(x):.{nd}f}"


def team(name: str) -> str:
    return TEAM_SHORT.get(name, name)


def slug(d: dict) -> str:
    s = d["session"]
    name = re.sub(r"[^a-z0-9]+", "-", f"{s['name']} {s['session_name']}".lower()).strip("-")
    rnd = f"{s['round']:02d}-" if s.get("round") else ""
    return f"{s['year']}/{rnd}{name}"


def date_text(iso: str) -> str:
    y, m, dd = (int(x) for x in iso.split("-"))
    return f"{dd} {MONTHS[m - 1]} {y}"


def place(s: dict) -> str:
    """The event's short name: Barcelona for the Barcelona Grand Prix."""
    return re.sub(r"\s+Grand Prix$", "", s["name"])


def _asset(name: str, prefix: str) -> str:
    version = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:10]
    return f"{prefix}assets/{name}?v={version}"


def _head(title: str, description: str, prefix: str, plots: bool = False) -> str:
    uplot = (f'<link rel="stylesheet" href="{UPLOT_CSS[0]}" integrity="{UPLOT_CSS[1]}" crossorigin="anonymous">\n'
             f'<script src="{UPLOT_JS[0]}" integrity="{UPLOT_JS[1]}" crossorigin="anonymous"></script>\n'
             if plots else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{e(FONTS)}">
{uplot}<link rel="stylesheet" href="{_asset('dash.css', prefix)}">
</head>"""


def _footer(code: dict | None = None) -> str:
    built = ""
    if code:
        built = (f' Built from <a href="{REPO_URL}/commit/{e(code["commit"])}">{e(code["commit"])}</a>'
                 + (" with uncommitted changes" if code["dirty"] else "") + ".")
    return (f'<footer class="foot"><p>{SOURCES} Code, models and test benches: <a href="{REPO_URL}">parc-ferme on '
            f'GitHub</a>, MIT licence.{built}</p><p>{DISCLAIMER}</p></footer>')


# ---------------- lap analysis (drawn by dash.js) ----------------

def car_order(d: dict) -> list[str]:
    """Cars with telemetry, in race-pace order, then the rest by fastest lap."""
    laps = d["telemetry"]["laps"]
    ranked = [r["driver"] for r in d["pace"]["cars"] if r["driver"] in laps]
    return ranked + sorted((c for c in laps if c not in ranked), key=lambda c: laps[c]["fastest"]["time"])


def lap_workspace(d: dict) -> str:
    cars = d["cars"]
    options = "".join(f'<option value="{e(c)}">{e(cars[c]["last"])} · {e(team(cars[c]["team"]))}</option>'
                      for c in car_order(d))
    return f"""<section class="ws" id="ws-lap">
  <div class="toolbar">
    <label class="sel a"><i class="sw" id="swA"></i><span>Car A</span><select id="selA">{options}</select></label>
    <span class="vs">vs</span>
    <label class="sel b"><i class="sw" id="swB"></i><span>Car B</span><select id="selB">{options}</select></label>
    <div class="seg" role="group" aria-label="Lap">
      <button data-lap="fastest" class="on">Fastest lap</button><button data-lap="typical">Typical lap</button>
    </div>
    <label class="tog"><input type="checkbox" id="simOn"><span>Lap sim</span></label>
    <div class="zoom" id="zoom"></div>
  </div>
  <div class="lap-grid">
    <div class="traces card" id="traces"></div>
    <aside class="side">
      <div class="card map-card">
        <div class="card-h"><span>Track</span>
          <div class="seg sm" role="group">
            <button data-map="gain" class="on">Who's faster</button><button data-map="sectors">Sectors</button>
          </div>
        </div>
        <svg id="map" role="img" aria-label="Track map"></svg><div class="map-legend" id="mapLegend"></div>
      </div>
      <div class="card">
        <div class="card-h"><span>Lap summary</span><span class="dim" id="lapNote"></span></div>
        <table class="sum" id="summary"></table>
        <div class="sum-legend" id="sumLegend">
          <span><i class="pp"></i>fastest of the race</span><span><i class="pg"></i>driver's best</span>
        </div>
        <div class="sum-note" id="sumNote" hidden></div>
      </div>
      <div class="card" id="windowCard">
        <div class="card-h"><span>Selected stretch</span><button class="link" id="clearRef" hidden>clear</button></div>
        <div id="window" class="dim">Click the traces to drop a reference cursor (red); the stretch between it and the
          cursor is measured here.</div>
      </div>
    </aside>
  </div>
</section>"""


def page_data(d: dict) -> str:
    """The telemetry dash.js draws, as JSON safe to embed in a script element."""
    t = d["telemetry"]
    data = {"L": t["L"], "dx": t["dx"], "n": t["n"], "sectors": t["sectors"], "corners": t["corners"],
            "zones": t["zones"], "map": {k: d["track"][k] for k in ("x", "y", "corners", "lines")},
            "cars": {c: {**d["cars"][c], **t["laps"][c]} for c in car_order(d)},
            "best": t["best"], "sims": t["sims"],
            "adjusted": {r["driver"]: [r["lap"], r["lap_se"]] for r in d["pace"]["cars"]}}
    return to_json(data).replace("<", "\\u003c")


# ---------------- race pace ----------------

def _scale(rows: list[dict]) -> tuple[float, float]:
    neg = min([0.0] + [sum(min(r[f"s{k}"], 0.0) for k in (1, 2, 3)) for r in rows])
    pos = max([0.0] + [sum(max(r[f"s{k}"], 0.0) for k in (1, 2, 3)) for r in rows])
    return min(-0.25, round(1.05 * neg - 0.05, 1)), max(0.5, round(1.05 * pos + 0.05, 1))


def _pace_rows(rows: list[dict], first: int, d: dict) -> str:
    cars, ref = d["cars"], d["pace"]["reference"]
    lo, hi = _scale(rows)

    def at(v):
        return 100 * (v - lo) / (hi - lo)

    out = []
    for pos, r in enumerate(rows, start=first):
        c = cars[r["driver"]]
        head = (f'<div class="pb-row"><span class="rk">{pos}</span>'
                f'<i class="chip" style="background:{e(c["colour"])}"></i>'
                f'<span class="nm">{e(c["last"])}<small>{e(team(r["team"]))}</small></span><div class="pb-bar">'
                f'<div class="z" style="left:{at(0):.2f}%"></div>')
        if r["driver"] == ref:
            out.append(f'{head}<span class="reftag" style="left:{at(0):.2f}%">reference</span></div>'
                       '<span class="vv">—</span></div>')
            continue
        segs, neg, posv = [], 0.0, 0.0
        for k in (1, 2, 3):
            v = r[f"s{k}"]
            a, b = (neg + v, neg) if v < 0 else (posv, posv + v)
            neg, posv = (neg + v, posv) if v < 0 else (neg, posv + v)
            if at(b) > at(a):
                segs.append(f'<i class="sg s{k}" style="left:{at(a):.2f}%;width:{at(b) - at(a):.2f}%" '
                            f'data-v="{signed(v)} s" '
                            f'data-l="{e(c["last"])} · sector {k} vs {e(cars[ref]["last"])}"></i>')
        segs.append(f'<i class="nt" style="left:{min(at(r["lap"]), 99.5):.2f}%"></i>')
        out.append(f'{head}{"".join(segs)}</div><span class="vv">{signed(r["lap"])} '
                   f'<small>± {r["lap_se"]:.2f}</small></span></div>')
    return "".join(out)


def pace_workspace(d: dict) -> str:
    p, cars, s = d["pace"], d["cars"], d["session"]
    rows, ref = p["cars"], cars[p["reference"]]
    names = [f"S{x['sector']}" + (f" · T{x['corners'][0]}–{x['corners'][-1]}" if x["corners"] else "")
             for x in d["sectors"]]
    rest = rows[FRONT_ROWS:]
    more = (f'<details class="more"><summary>Show the other {len(rest)} cars <span class="dim">(own scale)</span>'
            f'</summary>{_pace_rows(rest, FRONT_ROWS + 1, d)}</details>' if rest else "")
    traffic = "".join(
        f'<tr><td>{e(x["gap"])}</td>'
        + "".join(f'<td class="n">{signed(x[f"s{k}"])} <small>± {x[f"s{k}_se"]:.2f}</small></td>' for k in (1, 2, 3))
        + f'<td class="n"><b>{signed(x["lap"])}</b> <small>± {x["lap_se"]:.2f}</small></td>'
        + f'<td class="n">{x["laps"]}</td></tr>'
        for x in p["traffic"])
    h = p["holdout"]
    excluded = ""
    if p["excluded"]:
        who = ", ".join(e(cars[c]["last"]) if c in cars else e(c) for c in p["excluded"])
        excluded = f" Not enough green laps for an estimate (fewer than {p['min_laps']}): {who}."
    return f"""<section class="ws" id="ws-pace" hidden>
  <div class="ws-grid">
    <div class="card span2">
      <div class="card-h"><span>Time lost per lap to {e(ref['last'])}'s {e(team(ref['team']))}, by sector</span>
        <span class="dim">all green laps · tyres, fuel and traffic taken out</span></div>
      <div class="pb-legend"><span><i class="s1"></i>{e(names[0])}</span><span><i class="s2"></i>{e(names[1])}</span>
        <span><i class="s3"></i>{e(names[2])}</span><span><i class="t"></i>net gap</span>
        <span class="dim">left of the line = faster than the reference in that sector</span></div>
      {_pace_rows(rows[:FRONT_ROWS], 1, d)}
      {more}
    </div>
    <div class="card">
      <div class="card-h"><span>Cost of following, per lap</span>
        <span class="dim">smallest gap to the car ahead during the lap</span></div>
      <table class="tbl"><thead><tr><th>Gap ahead</th><th class="n">S1</th><th class="n">S2</th><th class="n">S3</th>
        <th class="n">Lap</th><th class="n">Laps</th></tr></thead><tbody>{traffic}</tbody></table>
    </div>
    <div class="card">
      <div class="card-h"><span>Pace model</span></div>
      <p class="dim">Each green lap's sector times at the {e(place(s))} {e(s['session_name'].lower())}, fitted with one
        effect per car plus tyre compound and age, lap number and traffic. Fitted on odd laps it predicts even ones to
        {h['model_err_s']:.2f} s (a car's own median lap: {h['baseline_err_s']:.2f} s). ± is one standard
        error.{excluded}</p>
    </div>
  </div>
</section>"""


# ---------------- car model ----------------

def car_workspace(d: dict) -> str:
    cm, g, cars = d["car_model"], d["grip"], d["cars"]
    badge = {"Rules": "rules", "Fitted": "fit", "Measured": "meas", "Nominal": "nom"}
    biggest = max(abs(p["effect_s"]) for p in cm["params"]) or 1.0
    params = []
    for p in cm["params"]:
        w = 50 * abs(p["effect_s"]) / biggest
        side = f"left:50%;width:{w:.1f}%" if p["effect_s"] > 0 else f"left:{50 - w:.1f}%;width:{w:.1f}%"
        note = f'<small class="warnnote">{e(p["note"])}</small>' if p.get("note") else ""
        value = f'{p["value"]:,.3f}'.rstrip("0").rstrip(".")
        params.append(
            f'<tr><td>{e(p["name"])}<small class="sym">{e(p["sym"])}</small>{note}</td>'
            f'<td class="n">{value} <small>{e(p["unit"])}</small></td>'
            f'<td><span class="badge {badge[p["source"]]}">{e(p["source"])}</span></td>'
            f'<td class="n">{signed(p["effect_s"], 3)} s</td><td class="effcell"><div class="eff"><i class="mid"></i>'
            f'<i class="bar {"slower" if p["effect_s"] > 0 else "faster"}" style="{side}"></i></div></td></tr>')

    rows = sorted(g["teams"], key=lambda r: -r["fast_corner_pct"])
    ends = [r[k] + sign * r[k.replace("pct", "se")] for r in rows for k in ("slow_corner_pct", "fast_corner_pct")
            for sign in (-1, 1)]
    lo, hi = min(ends + [0]) - 0.5, max(ends + [0]) + 0.5

    def gx(v):
        return 100 * (v - lo) / (hi - lo)

    colour = {c["team"]: c["colour"] for c in cars.values()}
    grip = []
    for r in rows:
        marks = []
        for key, cls, dy, label in (("slow_corner_pct", "gs", -5, "slow corners"),
                                    ("fast_corner_pct", "gf", 5, "fast corners")):
            v, se = r[key], r[key.replace("pct", "se")]
            marks.append(f'<i class="wh {cls}" style="left:{gx(v - se):.2f}%;width:{gx(v + se) - gx(v - se):.2f}%;'
                         f'top:calc(50% + {dy - 1}px)"></i><i class="dt {cls}" style="left:{gx(v):.2f}%;'
                         f'top:calc(50% + {dy}px)" data-v="{signed(v, 1)} ± {se:.1f}%" '
                         f'data-l="{e(team(r["team"]))} · {label}" tabindex="0"></i>')
        grip.append(f'<div class="gr-row"><span class="nm"><i class="chip" '
                    f'style="background:{e(colour.get(r["team"], "#8a8a8a"))}"></i>{e(team(r["team"]))}</span>'
                    f'<div class="gr-plot"><div class="z" style="left:{gx(0):.2f}%"></div>{"".join(marks)}</div></div>')
    ticks = [t for t in range(int(lo) - 1, int(hi) + 2) if lo <= t <= hi and t % 2 == 0]
    axis = "".join(f'<span style="left:{gx(t):.2f}%">{"avg" if t == 0 else f"{t:+d}%"}</span>' for t in ticks)
    slow = min(g["corners"], key=lambda c: c["w"])
    fast = max(g["corners"], key=lambda c: c["w"])
    return f"""<section class="ws" id="ws-car" hidden>
  <div class="ws-grid">
    <div class="card span2">
      <div class="card-h"><span>Car model parameters</span>
        <span class="dim">the simulator's 2026 car with {cm['fuel_kg']:g} kg fuel · lap-time effect of +1% on each,
          at {e(place(d['session']))}</span></div>
      <table class="tbl params"><thead><tr><th>Parameter</th><th class="n">Value</th><th>Source</th>
        <th class="n">+1% →</th><th>faster ← → slower</th></tr></thead><tbody>{''.join(params)}</tbody></table>
      <div class="badges dim"><span class="badge rules">Rules</span> 2026 regulations ·
        <span class="badge meas">Measured</span> from this session ·
        <span class="badge fit">Fitted</span> to this session's corner speeds ·
        <span class="badge nom">Nominal</span> not fitted yet</div>
    </div>
    <div class="card span2">
      <div class="card-h"><span>Cornering grip by team</span>
        <span class="dim">against the average car · whiskers ± one standard error</span></div>
      <div class="gr-legend">
        <span><i class="gs"></i>Slow corners (Turn {slow['corner']}, {slow['real_kph']:.0f} km/h)</span>
        <span><i class="gf"></i>Fast corners (Turn {fast['corner']}, {fast['real_kph']:.0f} km/h)</span></div>
      <div class="gr">{''.join(grip)}
        <div class="gr-row axis"><span></span><div class="gr-axis">{axis}</div></div></div>
    </div>
  </div>
</section>"""


# ---------------- model health ----------------

def _tile(status: str, name: str, value: str, detail: str) -> str:
    icon = {"ok": "✓", "warn": "!", "bad": "✕"}[status]
    return (f'<div class="ht {status}"><div class="hh"><i>{icon}</i>{e(name)}</div><div class="hv">{e(value)}</div>'
            f'<div class="hd">{e(detail)}</div></div>')


def health_tiles(d: dict) -> list[str]:
    checks = {c["name"]: c for c in d["checks"]}
    gating = [c for c in d["checks"] if c["gating"]]
    tiles = [_tile("ok" if all(c["passed"] for c in gating) else "bad", "Data checks",
                   f'{sum(c["passed"] for c in gating)}/{len(gating)}', "Gating checks on the session's timing data")]
    for name, title, fmt, detail in (
            ("speed_scale", "Speed channel", "{:.4f}",
             "Speed from positions ÷ speed channel, on straights (target 1.000 ± 1%)"),
            ("car_data_rate", "Telemetry rate", "{:.1f} Hz", "Median car-data sample rate")):
        c = checks.get(name)
        if c:
            value = "—" if c.get("value") is None else fmt.format(c["value"])
            tiles.append(_tile("ok" if c["passed"] else "bad", title, value, detail))
    b, pb, h, g = d["bench"], d["pace_bench"], d["pace"]["holdout"], d["grip"]
    tiles.append(_tile("ok" if b["passed"] else "bad", "Grip model bench",
                       f'{max(abs(r["mech_err"]) for r in b["rows"]):.2f} / '
                       f'{max(abs(r["downforce_err"]) for r in b["rows"]):.2f}',
                       f'Largest error on tyre grip / downforce, points (limits {b["tolerance_pct"]["mech"]:g} / '
                       f'{b["tolerance_pct"]["downforce"]:g})'))
    tiles.append(_tile("ok" if pb["passed"] else "bad", "Pace model bench", f'{pb["max_error_s"]:.3f} s',
                       f'Largest sector-gap error on a synthetic race (limit {pb["tolerance_s"]:.2f} s)'))
    tiles.append(_tile("ok" if h["model_err_s"] < h["baseline_err_s"] else "bad", "Pace model, held-out laps",
                       f'{h["model_err_s"]:.2f} s',
                       "Median lap-time error on unseen laps; a car's own median lap gives "
                       f'{h["baseline_err_s"]:.2f} s'))
    ca = g.get("clean_air")
    if ca:
        fitted = {r["team"]: r for r in g["teams"]}
        moves = []
        for r in ca["teams"]:
            f = fitted[r["team"]]
            for key in ("slow", "fast"):
                delta = abs(r[key] - f[f"{key}_corner_pct"])
                moves.append((delta / max(f[f"{key}_corner_se"], 1e-9), delta, key, team(r["team"])))
        z, delta, key, who = max(moves)
        tiles.append(_tile("ok" if z <= 2 else "warn", "Grip in dirty air", f"{z:.1f} SE",
                           f"Largest change when refitted on laps with no car within {ca['gap_s']:g} s ahead: "
                           f"{who}, {key} corners, {delta:.1f} points"))
    tiles.append(_tile("warn", "Lap sim corner fit", f'{g["field"]["rms_kph"]:.0f} km/h',
                       "RMS miss on corner minimum speeds; the racing line is the main error"))
    short = sum(x["line_short_m"] for x in g["sections"] if x["line_short_m"] is not None)
    tiles.append(_tile("warn", "Racing line length", f"−{short:.0f} m",
                       "Modelled line against the distance the cars drove, per lap"))
    tiles.append(_tile("warn", "Drag & energy", "not fitted",
                       "Needs the energy model (S4); straight-line speed is not used"))
    return tiles


STATUS_TEXT = {"resolved": "resolved", "interval only": "interval only", "not resolved": "not resolved"}


def identifiability_card(d: dict) -> str:
    """What the bench says of each reported quantity's intervals, and what this session's estimates resolve."""
    idf = d.get("identifiability")
    if not idf:
        return ""
    rows = []
    for r in idf["rows"]:
        kind = "ok" if r["status"] == "resolved" else ("bad" if not r["calibrated"] else "warn")
        if r["unit"] == "s":
            def fmt(v):
                return f'{v:.2f}<small> s</small>'
        else:
            def fmt(v):
                return f'{v:.1f}<small> pts</small>'
        cover = "—" if r["bench_cover_95"] is None else f'{100 * r["bench_cover_95"]:.0f}<small> %</small>'
        ratio = "—" if r["bench_sd_z"] is None else f'{r["bench_sd_z"]:.2f}'
        rows.append(f'<tr><td><span class="st {kind}">{kind}</span></td><td>{e(r["label"])}</td>'
                    f'<td class="n">{cover}</td><td class="n">{ratio}</td><td class="n">± {fmt(r["median_se"])}</td>'
                    f'<td class="n">{fmt(r["spread"])}</td><td>{e(STATUS_TEXT[r["status"]])}</td></tr>')
    b = idf.get("bench")
    if b:
        commit = b["commit"].rstrip("+")
        note = (f'{b["grip_races"]} synthetic races for grip, {b["pace_races"]} for pace · measured on '
                f'<a href="{REPO_URL}/commit/{e(commit)}">{e(b["commit"])}</a>')
    else:
        note = "bench not run: intervals unchecked"
    pace = idf.get("pace", {})
    return f"""<div class="card"><div class="card-h"><span>Identifiability</span><span class="dim">{note}</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th></th><th>Quantity</th><th class="n">95% covers</th>
      <th class="n">Error ÷ ±</th><th class="n">Typical ±</th><th class="n">Spread</th>
      <th>This session</th></tr></thead>
      <tbody>{''.join(rows)}</tbody></table></div>
    <p class="dim">Each model is run on synthetic races with the confounders the feed carries switched on: different
      lines and commitment per driver, tyre wear that differs by team, fuel, track evolution, dirty air and ~4 Hz
      sampling for grip; car-specific wear and offsets that hold for a whole stint for pace. <b>95% covers</b>: how
      often the stated 95% interval held the true value (pass at 90% or more). <b>Error ÷ ±</b>: spread of the errors
      over the stated uncertainty (1 is honest; pass at 1.25 or less). A quantity is resolved when the bench backs its
      intervals and a typical ± is under a third of the spread between teams or cars; interval only when the
      differences are real but rankings are uncertain; not resolved when the data can't tell them apart. Pace gaps
      are at a tyre age of {pace.get("ref_age", "—")} laps on the {e(str(pace.get("ref_compound", "")).lower())}, with
      the fastest-looking car's flattering luck ({1000 * abs(pace.get("selection_bias_s", 0.0)):.0f} ms) taken off.</p>
  </div>"""


def health_workspace(d: dict) -> str:
    rows = []
    for c in d["checks"]:
        kind = "ok" if c["passed"] else ("bad" if c["gating"] else "warn")
        mark = {"ok": "✓", "bad": "✕", "warn": "!"}[kind]
        rows.append(f'<tr><td><span class="st {kind}">{mark}</span></td>'
                    f'<td>{e(DATA_CHECK_NAMES.get(c["name"], c["name"].replace("_", " ")))}</td>'
                    f'<td class="dim">{e(c["detail"])}</td></tr>')
    code = d["code"]
    build = (f'build <a href="{REPO_URL}/commit/{e(code["commit"])}">{e(code["commit"])}</a>'
             + (" with uncommitted changes" if code["dirty"] else ""))
    return f"""<section class="ws" id="ws-health" hidden>
  <div class="ht-grid">{''.join(health_tiles(d))}</div>
  {identifiability_card(d)}
  <div class="card"><div class="card-h"><span>Data checks</span><span class="dim">{build}</span></div>
    <table class="tbl">{''.join(rows)}</table></div>
</section>"""


# ---------------- pages ----------------

def page(d: dict) -> str:
    s, c, cars = d["session"], d["conditions"], d["cars"]
    prefix = "../" * (slug(d).count("/") + 1)
    rnd = f"R{s['round']} · " if s.get("round") else ""
    weather = f'{"wet" if c["rain"] else "dry"} · air {c["air_c"]:.0f} °C · track {c["track_c"]:.0f} °C'
    podium = " · ".join(f'P{p["position"]} {e(cars[p["driver"]]["last"])}' for p in d["podium"])
    tabs = "".join(f'<button role="tab" data-ws="{k}" aria-selected="{"true" if k == "lap" else "false"}">{name}'
                   '</button>' for k, name in WORKSPACES)
    head = _head(f"{s['name']} · {s['session_name']} · parc-ferme",
                 f"Telemetry and engineering debrief of the {s['year']} {s['name']} ({s['session_name'].lower()}): "
                 "every car's laps against distance, race pace by sector, the car model and its checks.",
                 prefix, plots=True)
    return f"""{head}<body>
<header class="top">
  <a class="logo" href="{prefix}"><i></i>Parc fermé</a>
  <div class="sess"><b>{rnd}{e(place(s))} · {e(s['session_name'])}</b>
    <span>{e(date_text(s['date']))} · {s['laps']} laps · {weather} · {podium}</span></div>
  <nav class="ws-tabs" role="tablist">{tabs}</nav>
</header>
<main>
{lap_workspace(d)}
{pace_workspace(d)}
{car_workspace(d)}
{health_workspace(d)}
</main>
{_footer(d["code"])}
<div class="tip" id="tip" hidden></div>
<script id="data" type="application/json">{page_data(d)}</script>
<script src="{_asset('dash.js', prefix)}"></script>
</body></html>
"""


def index(debriefs: list[dict]) -> str:
    rows = []
    for d in sorted(debriefs, key=lambda x: (x["session"]["date"], x["session"]["key"]), reverse=True):
        s = d["session"]
        first = next((p for p in d["podium"] if p["position"] == 1), None)
        rows.append(f'<tr><td class="n">{s["round"] or "—"}</td><td><a href="{e(slug(d))}/">{e(place(s))}</a></td>'
                    f'<td>{e(s["session_name"])}</td><td class="n">{e(date_text(s["date"]))}</td>'
                    f'<td class="opt">{e(s["circuit"])}</td>'
                    f'<td>{e(d["cars"][first["driver"]]["last"]) if first else "—"}</td>'
                    f'<td class="n opt">{s["laps"]}</td></tr>')
    seasons = " · ".join(str(y) for y in sorted({d["session"]["year"] for d in debriefs}, reverse=True))
    latest = max((d["session"]["date"] for d in debriefs), default=None)
    count = f'{len(debriefs)} session{"" if len(debriefs) == 1 else "s"}'
    head = _head(f"parc-ferme · {seasons} sessions".replace("  ", " "),
                 "Telemetry and engineering debriefs for 2026 Formula 1 sessions, from public timing data.", "")
    return f"""{head}<body>
<header class="top">
  <a class="logo" href="./"><i></i>Parc fermé</a>
  <div class="sess"><b>{seasons} season</b>
    <span>{count}{f" · latest {e(date_text(latest))}" if latest else ""}</span></div>
</header>
<main>
<p class="idx-note">After each session: every car's laps against distance, race pace by sector with tyres, fuel
and traffic taken out, and the 2026 car model behind it, each model checked against what the cars did.</p>
<table class="tbl sessions"><thead><tr><th class="n">Rd</th><th>Grand Prix</th><th>Session</th><th class="n">Date</th>
<th class="opt">Circuit</th><th>P1</th><th class="n opt">Laps</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</main>
{_footer()}
</body></html>
"""


def _clear(out: Path) -> None:
    """Empty a previous build out of `out`, refusing a directory that isn't one."""
    if not out.exists():
        return
    entries = list(out.iterdir())
    if entries and not ((out / "index.html").exists() or (out / ".nojekyll").exists()):
        raise RuntimeError(f"{out} doesn't look like a site build, so it isn't cleared")
    for p in entries:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()


def write(out: Path, debriefs: list[dict]) -> list[Path]:
    """Build the site into `out`, replacing the previous build: the index, one page per session with its debrief
    document beside it, and the shared stylesheet and script. Returns the pages written."""
    _clear(out)
    (out / "assets").mkdir(parents=True)
    for name in ASSETS:
        shutil.copyfile(STATIC / name, out / "assets" / name)
    written = []
    for d in debriefs:
        path = out / slug(d) / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page(d))
        (path.parent / "debrief.json").write_text(to_json(d))
        written.append(path)
    (out / "index.html").write_text(index(debriefs))
    (out / ".nojekyll").write_text("")
    return written
