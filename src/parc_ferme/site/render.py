"""Static site: one page per session debrief, plus an index. Plain HTML and CSS with one small script for
tooltips; no build step and nothing loaded from elsewhere, so a page works from any static host or from disk.

Charts follow one rulebook: thin marks, hairline grid, a legend for two or more series, colours from a validated
palette chosen separately for light and dark, and a table view behind every chart.
"""

import json
import math
import re
from html import escape
from pathlib import Path

from ..debrief.summary import corners_text, possessive, team
from ..debrief.summary import findings as summary_findings

REPO_URL = "https://github.com/raahimnawaz/parc-ferme"
LIMIT_S = 0.5  # sector cells reach full colour at this many seconds
MAX_TINT = 0.72

CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11, 11, 11, 0.10); --link: #256abf;
  --s1: #2a78d6; --s2: #eb6834;
  --div-neg: #2a78d6; --div-pos: #e34948; --div-mid: #f0efec;
  --good: #0ca30c; --warn: #fab219; --bad: #d03b3b; --info: #898781;
  --track: #c3c2b7;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255, 255, 255, 0.10); --link: #86b6ef;
    --s1: #3987e5; --s2: #d95926;
    --div-neg: #3987e5; --div-pos: #e66767; --div-mid: #262625;
    --track: #52514e;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255, 255, 255, 0.10); --link: #86b6ef;
  --s1: #3987e5; --s2: #d95926;
  --div-neg: #3987e5; --div-pos: #e66767; --div-mid: #262625;
  --track: #52514e;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
a { color: var(--link); text-underline-offset: 2px; }
a:focus-visible, [tabindex]:focus-visible, summary:focus-visible {
  outline: 2px solid var(--link); outline-offset: 2px; }
.top { border-bottom: 1px solid var(--border); background: var(--surface); }
.top .in { max-width: 1080px; margin: 0 auto; padding: 12px 16px; display: flex; gap: 16px;
  align-items: baseline; justify-content: space-between; }
.brand { font-weight: 650; letter-spacing: -0.01em; color: var(--ink); text-decoration: none; }
.top nav a { color: var(--ink-2); text-decoration: none; font-size: 14px; }
main { max-width: 1080px; margin: 0 auto; padding: 32px 16px 56px; display: flex; flex-direction: column; gap: 48px; }
h1, h2, h3 { margin: 0; line-height: 1.15; letter-spacing: -0.01em; text-wrap: balance; }
h1 { font-size: clamp(30px, 5vw, 44px); font-weight: 650; }
h2 { font-size: 24px; font-weight: 650; }
h3 { font-size: 18px; font-weight: 600; }
p { margin: 0; max-width: 72ch; }
.eyebrow { font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); font-weight: 500; }
.meta { color: var(--ink-2); }
section { display: flex; flex-direction: column; gap: 18px; scroll-margin-top: 16px; }
.sec-head { display: flex; flex-direction: column; gap: 6px; border-top: 1px solid var(--axis); padding-top: 16px; }
.hero { gap: 12px; }
.podium { display: flex; flex-wrap: wrap; gap: 8px 24px; margin: 4px 0 0; padding: 0; list-style: none; }
.podium li { display: flex; gap: 8px; align-items: baseline; }
.podium .pos { font-weight: 650; font-size: 18px; min-width: 1.2em; }
.podium .who { font-weight: 600; }
.podium .sub { color: var(--ink-2); font-size: 14px; }
.findings { margin: 0; padding: 0; list-style: none; display: grid; gap: 12px; counter-reset: f; }
.findings li { counter-increment: f; display: grid; grid-template-columns: 28px minmax(0, 1fr); gap: 4px 12px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 14px 16px; }
.findings li::before { content: counter(f); font-weight: 650; color: var(--muted); font-size: 18px; line-height: 1.3; }
.findings p { font-size: 16px; }
.findings a { grid-column: 2; font-size: 14px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 16px; }
.two { display: grid; grid-template-columns: minmax(0, 1fr); gap: 24px; align-items: start; }
@media (min-width: 860px) { .two { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } }
figure { margin: 0; display: flex; flex-direction: column; gap: 12px; }
figcaption, .note { font-size: 13.5px; color: var(--ink-2); max-width: 80ch; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13.5px; color: var(--ink-2); }
.key { display: inline-flex; align-items: center; gap: 6px; }
.swatch { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex: none; }
.swatch.s1 { background: var(--s1); } .swatch.s2 { background: var(--s2); }
.swatch.sq { border-radius: 2px; width: 14px; }
.swatch.neg { background: var(--div-neg); } .swatch.pos { background: var(--div-pos); }
details { font-size: 14px; }
details summary { cursor: pointer; color: var(--ink-2); width: fit-content; }
details[open] summary { margin-bottom: 8px; }
.tablewrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { padding: 7px 10px; text-align: left; border-bottom: 1px solid var(--grid); vertical-align: top; }
th { font-size: 12px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr:last-child td { border-bottom: 0; }
.car b { font-weight: 600; } .car span { color: var(--ink-2); }
table.heat td.h { background: color-mix(in oklab, var(--div-mid), var(--div-pos) calc(var(--k) * 100%)); }
table.heat td.h.neg { background: color-mix(in oklab, var(--div-mid), var(--div-neg) calc(var(--k) * 100%)); }
table.heat td.h { border-bottom: 2px solid var(--surface); border-left: 2px solid var(--surface); }
table.heat td.ref { color: var(--muted); }
table.heat .se { color: var(--ink-2); font-size: 12.5px; margin-left: 4px; }
table.heat th small { display: block; text-transform: none; letter-spacing: 0; font-size: 11.5px; }
.scale { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--ink-2); flex-wrap: wrap; }
.scale .ramp { width: 160px; height: 10px; border-radius: 2px;
  background: linear-gradient(90deg, color-mix(in oklab, var(--div-mid), var(--div-neg) 72%), var(--div-mid),
  color-mix(in oklab, var(--div-mid), var(--div-pos) 72%)); }
/* dot plot and diverging bars, drawn in HTML so text stays legible at every width */
.dp { position: relative; display: grid; grid-template-columns: var(--lw, 8.5rem) minmax(0, 1fr); }
.dp-label { font-size: 14px; padding-right: 10px; display: flex; align-items: center; min-height: 32px;
  border-bottom: 1px solid transparent; }
.dp-label small { color: var(--ink-2); margin-left: 6px; }
.dp-plot { position: relative; min-height: 32px; }
.dp-grid { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--grid); }
.dp-grid.zero { background: var(--axis); }
.dp-axis { position: relative; height: 22px; font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.dp-axis span { position: absolute; top: 4px; transform: translateX(-50%); white-space: nowrap; }
.whisker { position: absolute; height: 2px; border-radius: 1px; }
.dot { position: absolute; width: 10px; height: 10px; border-radius: 50%; transform: translate(-50%, -50%);
  box-shadow: 0 0 0 2px var(--surface); }
.dot::after { content: ""; position: absolute; inset: -8px; border-radius: 50%; }
.dot:hover, .dot:focus-visible { transform: translate(-50%, -50%) scale(1.25); }
.s1 > .dot, .whisker.s1, .dot.s1 { background: var(--s1); }
.whisker.s2, .dot.s2 { background: var(--s2); }
.bar { position: absolute; top: 50%; height: 14px; transform: translateY(-50%); }
.bar.pos { background: var(--div-pos); border-radius: 0 4px 4px 0; }
.bar.neg { background: var(--div-neg); border-radius: 4px 0 0 4px; }
.bar-val { position: absolute; top: 50%; transform: translateY(-50%); font-size: 12.5px; color: var(--ink-2);
  font-variant-numeric: tabular-nums; white-space: nowrap; padding: 0 6px; }
/* track map */
.map svg { width: 100%; height: auto; display: block; }
.map text { font-size: calc(var(--fs) * 1px); }
.map .track { fill: none; stroke: var(--track); stroke-width: 14; stroke-linejoin: round; }
.map .sector-line { stroke: var(--ink); stroke-width: 5; }
.map .sector-label { fill: var(--ink); font-weight: 600; }
.map .arrow { fill: var(--ink); }
.map .corner { fill: var(--surface); stroke: var(--ink-2); stroke-width: 4; }
.map .corner.slow { fill: var(--s1); stroke: var(--surface); }
.map .corner.fast { fill: var(--s2); stroke: var(--surface); }
.map .corner.flat { fill: var(--surface); stroke: var(--muted); }
.map .corner-label { fill: var(--ink-2); font-variant-numeric: tabular-nums; }
.map .hit { fill: transparent; }
/* checks */
.status { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 500; white-space: nowrap; }
.status i { width: 18px; height: 18px; border-radius: 50%; display: inline-grid; place-items: center;
  font-style: normal; font-size: 11px; font-weight: 700; color: #ffffff; }
.status.pass i { background: var(--good); } .status.warn i { background: var(--warn); color: #0b0b0b; }
.status.fail i { background: var(--bad); } .status.info i { background: var(--info); }
.checks td:first-child { width: 1%; }
.checks td.what { color: var(--ink-2); }
.checks .name { font-weight: 600; display: block; color: var(--ink); }
.callout { border-left: 3px solid var(--axis); padding: 10px 14px; background: var(--surface);
  border-radius: 0 6px 6px 0; }
.callout p { font-size: 14px; color: var(--ink-2); }
.callout b { color: var(--ink); }
footer { border-top: 1px solid var(--border); background: var(--surface); }
footer .in { max-width: 1080px; margin: 0 auto; padding: 20px 16px 32px; font-size: 13px; color: var(--ink-2);
  display: flex; flex-direction: column; gap: 8px; }
footer p { max-width: 100ch; }
.tip { position: fixed; z-index: 10; pointer-events: none; background: var(--surface); color: var(--ink);
  border: 1px solid var(--border); border-radius: 6px; padding: 6px 9px; font-size: 13px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12); max-width: 280px; }
.tip b { display: block; font-variant-numeric: tabular-nums; }
.tip span { color: var(--ink-2); }
.sessions { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }
.sessions a { display: block; text-decoration: none; color: var(--ink); background: var(--surface);
  border: 1px solid var(--border); border-radius: 6px; padding: 16px; }
.sessions a:hover { border-color: var(--axis); }
.sessions .t { font-weight: 600; font-size: 17px; display: block; }
.sessions .m { color: var(--ink-2); font-size: 14px; }
@media (max-width: 600px) {
  .opt { display: none; }
  table.heat td, table.heat th { padding: 7px 6px; }
  table.heat .se { display: block; margin: 0; }
  .car span { display: block; font-size: 12.5px; }
  .dp { --lw: 6.8rem; }
  .dp-axis span.minor { display: none; }
  .map text { font-size: calc(var(--fs) * 1.35px); }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
"""

SCRIPT = """
(() => {
  const tip = document.createElement('div');
  tip.className = 'tip'; tip.setAttribute('role', 'tooltip'); tip.hidden = true;
  document.body.appendChild(tip);
  const place = (x, y) => {
    const r = tip.getBoundingClientRect();
    let left = x + 14, top = y + 14;
    if (left + r.width > innerWidth - 8) left = x - r.width - 14;
    if (top + r.height > innerHeight - 8) top = y - r.height - 14;
    tip.style.left = Math.max(8, left) + 'px'; tip.style.top = Math.max(8, top) + 'px';
  };
  const show = (el, x, y) => {
    tip.replaceChildren();
    const v = document.createElement('b'); v.textContent = el.dataset.v || '';
    const l = document.createElement('span'); l.textContent = el.dataset.l || '';
    tip.append(v, l); tip.hidden = false; place(x, y);
  };
  const hit = e => e.target.closest && e.target.closest('[data-v]');
  document.addEventListener('pointermove', e => {
    const el = hit(e); el ? show(el, e.clientX, e.clientY) : (tip.hidden = true);
  });
  document.addEventListener('pointerleave', () => { tip.hidden = true; });
  document.addEventListener('focusin', e => {
    const el = hit(e);
    if (el) { const r = el.getBoundingClientRect(); show(el, r.right, r.bottom); }
  });
  document.addEventListener('focusout', () => { tip.hidden = true; });
})();
"""

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


def signed(x: float, nd: int = 2, unit: str = "") -> str:
    if abs(x) < 0.5 * 10 ** -nd:
        x = 0.0
    return f"{'+' if x > 0 else '−' if x < 0 else ''}{abs(x):.{nd}f}{unit}"


def slug(d: dict) -> str:
    s = d["session"]
    name = re.sub(r"[^a-z0-9]+", "-", f"{s['name']} {s['session_name']}".lower()).strip("-")
    rnd = f"{s['round']:02d}-" if s.get("round") else ""
    return f"{s['year']}/{rnd}{name}"


def date_text(iso: str) -> str:
    y, m, dd = (int(x) for x in iso.split("-"))
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December"]
    return f"{dd} {months[m - 1]} {y}"


def ticks(lo: float, hi: float, target: int = 6) -> list[float]:
    raw = (hi - lo) / target
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return [round(v * step, 10) for v in range(math.floor(lo / step), math.ceil(hi / step) + 1)]


def tip(value: str, label: str, focus: bool = True) -> str:
    return f'data-v="{e(value)}" data-l="{e(label)}"' + (' tabindex="0"' if focus else "")


def status(kind: str) -> str:
    icon, label = {"pass": ("✓", "Pass"), "warn": ("!", "Warn"), "fail": ("✕", "Fail"),
                   "info": ("i", "Info")}[kind]
    return f'<span class="status {kind}"><i aria-hidden="true">{icon}</i>{label}</span>'


# ---- components ---------------------------------------------------------------------------------------------------

def track_map(d: dict) -> str:
    tr, grip = d["track"], d["grip"]
    xs, ys = tr["x"], tr["y"]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    font = round(span / 36, 1)

    # Each timing line gets its sector's name where that sector starts, on whichever side of the track leaves it
    # furthest from the corner labels and from the track itself.
    occupied = [(c["lx"], c["ly"]) for c in tr["corners"]] + [(c["x"], c["y"]) for c in tr["corners"]]
    sector_labels = []
    for k, m in enumerate(tr["lines"]):
        track_pts = [(x, y) for x, y in zip(xs, ys, strict=True) if math.hypot(x - m["x"], y - m["y"]) > 1.5 * font]
        best = None
        for sign in (1, -1):
            px, py = m["x"] + sign * 2.0 * font * m["nx"], m["y"] + sign * 2.0 * font * m["ny"]
            clear = min(math.hypot(px - x, py - y) for x, y in occupied + track_pts)
            if best is None or clear > best[0]:
                best = (clear, px, py)
        sector_labels.append((f"S{k + 1}", best[1], best[2]))
    label_x = [c["lx"] for c in tr["corners"]] + [x for _, x, _ in sector_labels]
    label_y = [c["ly"] for c in tr["corners"]] + [y for _, _, y in sector_labels]
    pad = 1.2 * font
    x0, x1 = min(xs + label_x) - pad, max(xs + label_x) + pad
    y0, y1 = min(ys + label_y) - pad, max(ys + label_y) + pad
    w, h = x1 - x0, y1 - y0
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True)) + " Z"
    used = {c["corner"]: c for c in grip["corners"]}
    w_slow = min(used.values(), key=lambda c: c["w"])["corner"] if used else None
    w_fast = max(used.values(), key=lambda c: c["w"])["corner"] if used else None
    parts = [f'<path class="track" d="{path}"/>']
    half = 0.75 * font
    for m in tr["lines"]:
        parts.append(f'<line class="sector-line" x1="{m["x"] - half * m["nx"]:.1f}" y1="{m["y"] - half * m["ny"]:.1f}" '
                     f'x2="{m["x"] + half * m["nx"]:.1f}" y2="{m["y"] + half * m["ny"]:.1f}"/>')
    for name, x, y in sector_labels:
        parts.append(f'<text class="sector-label" x="{x:.1f}" y="{y:.1f}" text-anchor="middle" '
                     f'dominant-baseline="middle">{name}</text>')
    # direction of travel: an arrowhead a little after the start line, pointing along the track
    i = max(2, int(0.012 * len(xs)))
    tx, ty = xs[i + 1] - xs[i - 1], ys[i + 1] - ys[i - 1]
    angle = math.degrees(math.atan2(ty, tx))
    a = 0.45 * font
    parts.append(f'<path class="arrow" d="M{a:.1f},0 L{-a:.1f},{-0.8 * a:.1f} L{-a:.1f},{0.8 * a:.1f} Z" '
                 f'transform="translate({xs[i]:.1f},{ys[i]:.1f}) rotate({angle:.1f})"/>')
    for c in tr["corners"]:
        cls = "corner" + (" flat" if c["flat_out"] else "") + (" slow" if c["number"] == w_slow else "") + \
            (" fast" if c["number"] == w_fast else "")
        speed = f"{c['kph']:.0f} km/h" if c["kph"] == c["kph"] else "no reading"
        if c["flat_out"]:
            label = "flat out, not used for grip"
        else:
            label = f"{100 * c['w']:.0f}% of grip from downforce"
        parts.append(f'<g {tip(f"Turn {c["label"]} · {speed}", label)}><circle class="hit" cx="{c["x"]:.1f}" '
                     f'cy="{c["y"]:.1f}" r="{font}"/><circle class="{cls}" cx="{c["x"]:.1f}" cy="{c["y"]:.1f}" '
                     f'r="{font * 0.32:.1f}"/></g>')
        parts.append(f'<text class="corner-label" x="{c["lx"]:.1f}" y="{c["ly"]:.1f}" '
                     f'text-anchor="middle" dominant-baseline="middle">{e(c["label"])}</text>')
    rows = "".join(
        f'<tr><td>Turn {e(c["label"])}</td><td class="num">{c["kph"]:.0f}</td>'
        f'<td class="num">{"flat out" if c["flat_out"] else f"{100 * c["w"]:.0f}%"}</td>'
        f'<td>{next(s["sector"] for s in d["sectors"] if c["number"] in s["corners"])}</td></tr>'
        for c in tr["corners"])
    return f"""<figure class="map card">
<svg viewBox="{x0:.0f} {y0:.0f} {w:.0f} {h:.0f}" style="--fs:{font}" role="img"
aria-label="Track map of {e(d['session']['circuit'])}
with the three timing sectors and the corners numbered">{''.join(parts)}</svg>
<div class="legend"><span class="key"><span class="swatch s1"></span>Slowest lifted corner</span>
<span class="key"><span class="swatch s2"></span>Fastest lifted corner</span></div>
<figcaption>Ticks are the timing lines, each labelled with the sector that starts there; the arrow shows the
direction of travel. The two coloured corners set the ends of the grip scale below.</figcaption>
<details><summary>Table: corners</summary><div class="tablewrap"><table><thead><tr><th>Corner</th>
<th class="num">Median minimum speed, km/h</th><th class="num">Grip from downforce</th><th>Sector</th></tr></thead>
<tbody>{rows}</tbody></table></div></details>
</figure>"""


def traffic_note(p: dict, sectors: list) -> str:
    near, mid = p["traffic"][0], p["traffic"][1]
    worst = max(range(1, 4), key=lambda k: near[f"s{k}"])
    quiet = [str(k) for k in range(1, 4) if abs(near[f"s{k}"]) < 2 * near[f"s{k}_se"]]
    text = (f"Traffic is taken out, not filtered out. Running within 1 s of the car ahead cost "
            f"{signed(near['lap'], 2)} ± {near['lap_se']:.2f} s a lap, {signed(near[f's{worst}'], 2)} s of it in "
            f"sector {worst} ({corners_text(sectors[worst - 1])}).")
    if quiet:
        text += f" In sector{'s' if len(quiet) > 1 else ''} {' and '.join(quiet)} it was too small to measure."
    measurable = abs(mid["lap"]) >= 2 * mid["lap_se"]
    text += (f" Between 1 and 2 s behind, the cost was {signed(mid['lap'], 2)} ± {mid['lap_se']:.2f} s"
             + ("." if measurable else ", too small to measure."))
    return f'<p class="note">{e(text)}</p>'


def pace_table(d: dict) -> str:
    p, cars, sectors = d["pace"], d["cars"], d["sectors"]
    ref = p["reference"]
    head = "".join(f'<th class="num">S{s["sector"]}<small>{e(corners_text(s))}</small></th>' for s in sectors)
    body = []
    for rank, r in enumerate(p["cars"], start=1):
        name = cars[r["driver"]]["last"]
        cells = []
        for k in range(1, 4):
            v, se = r[f"s{k}"], r[f"s{k}_se"]
            if r["driver"] == ref:
                cells.append('<td class="num ref">ref</td>')
                continue
            t = min(abs(v) / LIMIT_S, 1.0) * MAX_TINT
            cls = "h neg" if v < 0 else "h"
            hover = tip(f"{signed(v, 3)} ± {se:.3f} s", f"{name}, sector {k}, against {cars[ref]['last']}", False)
            cells.append(f'<td class="num {cls}" style="--k:{t:.3f}" {hover}>{signed(v, 2)}</td>')
        lap = ('<td class="num ref">ref</td>' if r["driver"] == ref else
               f'<td class="num"><b>{signed(r["lap"], 2)}</b><span class="se">± {r["lap_se"]:.2f}</span></td>')
        body.append(f'<tr><td class="num opt">{rank}</td><td class="car"><b>{e(name)}</b> <span>'
                    f'{e(team(r["team"]))}</span></td>{lap}{"".join(cells)}<td class="num opt">{r["laps"]}</td></tr>')
    se_rows = "".join(
        f'<tr><td>{e(cars[r["driver"]]["last"])}</td>'
        + f'<td class="num">{signed(r["lap"], 3)} ± {r["lap_se"]:.3f}</td>'
        + "".join(f'<td class="num">{signed(r[f"s{k}"], 3)} ± {r[f"s{k}_se"]:.3f}</td>' for k in range(1, 4))
        + "</tr>" for r in p["cars"])
    excluded = ""
    if p["excluded"]:
        names = ", ".join(e(cars[x]["last"]) for x in p["excluded"])
        excluded = (f'<p class="note">Not shown: {names}, with fewer than {p["min_laps"]} green laps.</p>')
    return f"""<div class="scale" aria-hidden="true"><span>Faster than {e(cars[ref]['last'])}</span>
<span class="ramp"></span><span>Slower</span><span>· full colour at {LIMIT_S:g} s a lap</span></div>
<div class="tablewrap card" style="padding:0"><table class="heat"><caption class="note" style="text-align:left;
padding:12px 12px 0">Seconds a lap against {e(possessive(cars[ref]['last']))} {e(team(cars[ref]['team']))}, the
fastest car, in total and by timing sector. ± is one standard error.</caption><thead><tr><th class="num opt">#</th>
<th>Car</th><th class="num">Lap</th>{head}<th class="num opt">Laps</th></tr></thead><tbody>{''.join(body)}</tbody>
</table></div>
<details><summary>Table: every gap with its standard error</summary><div class="tablewrap"><table><thead><tr>
<th>Car</th><th class="num">Lap, s</th><th class="num">S1, s</th><th class="num">S2, s</th><th class="num">S3, s</th>
</tr></thead><tbody>{se_rows}</tbody></table></div></details>
{excluded}
{traffic_note(p, sectors)}"""


def dot_plot(d: dict) -> str:
    g = d["grip"]
    rows = sorted(g["teams"], key=lambda r: r["fast_corner_pct"], reverse=True)
    vals = [r[k] + s * r[k.replace("pct", "se")] for r in rows for k in ("slow_corner_pct", "fast_corner_pct")
            for s in (-1, 1)]
    t = ticks(min(vals + [0]), max(vals + [0]))
    lo, hi = t[0], t[-1]

    def x(v):
        return 100 * (v - lo) / (hi - lo)

    grid = "".join(f'<div class="dp-grid{" zero" if v == 0 else ""}" style="left:{x(v):.2f}%"></div>' for v in t)
    used = {c["corner"]: c for c in g["corners"]}
    slow_c = min(used.values(), key=lambda c: c["w"])
    fast_c = max(used.values(), key=lambda c: c["w"])
    series = (("slow_corner_pct", "s1", -5, "slow corners"), ("fast_corner_pct", "s2", 5, "fast corners"))
    out = []
    for r in rows:
        marks = []
        for key, cls, dy, label in series:
            v, se = r[key], r[key.replace("pct", "se")]
            top = f"calc(50% + {dy}px)"
            marks.append(f'<div class="whisker {cls}" style="left:{x(v - se):.2f}%;width:{x(v + se) - x(v - se):.2f}%;'
                         f'top:calc(50% + {dy - 1}px)"></div>')
            marks.append(f'<div class="dot {cls}" style="left:{x(v):.2f}%;top:{top}" role="img" '
                         f'aria-label="{e(team(r["team"]))}, {label}: {signed(v, 1)} percent, plus or minus '
                         f'{se:.1f}" {tip(f"{signed(v, 1)} ± {se:.1f}%", f"{team(r["team"])}, {label}")}></div>')
        out.append(f'<div class="dp-label">{e(team(r["team"]))}</div><div class="dp-plot">{"".join(marks)}</div>')
    axis = "".join(f'<span class="{"minor" if (i - t.index(0)) % 2 else ""}" style="left:{x(v):.2f}%">'
                   f'{signed(v, 0, "%") if v else "field"}</span>' for i, v in enumerate(t))
    table = "".join(
        f'<tr><td>{e(team(r["team"]))}</td><td class="num">{signed(r["slow_corner_pct"], 1)} ± '
        f'{r["slow_corner_se"]:.1f}</td><td class="num">{signed(r["fast_corner_pct"], 1)} ± '
        f'{r["fast_corner_se"]:.1f}</td><td class="num">{signed(r["mech_pct"], 1)} ± {r["mech_se"]:.1f}</td>'
        f'<td class="num">{signed(r["downforce_pct"], 1)} ± {r["downforce_se"]:.1f}</td></tr>' for r in rows)
    n_rows = len(rows)
    return f"""<figure class="card">
<div class="legend"><span class="key"><span class="swatch s1"></span>Slow corners: Turn {slow_c['corner']},
{slow_c['real_kph']:.0f} km/h, {100 * slow_c['w']:.0f}% of grip from downforce</span>
<span class="key"><span class="swatch s2"></span>Fast corners: Turn {fast_c['corner']}, {fast_c['real_kph']:.0f} km/h,
{100 * fast_c['w']:.0f}%</span></div>
<div class="dp" role="group" aria-label="Grip relative to the mean team, slow and fast corners, {n_rows} teams">
<div class="dp-plot" style="position:absolute;left:var(--lw,8.5rem);right:0;top:0;bottom:22px"
aria-hidden="true">{grid}</div>
{''.join(out)}<div></div><div class="dp-axis" aria-hidden="true">{axis}</div></div>
<figcaption>Lateral grip against the mean team, in percent. Dots are the estimates; whiskers are ± one standard
error, from refitting with each corner left out in turn.</figcaption>
<details><summary>Table: grip by team</summary><div class="tablewrap"><table><thead><tr><th>Team</th>
<th class="num">Slow corners</th><th class="num">Fast corners</th><th class="num">Tyre grip</th>
<th class="num">Downforce</th></tr></thead><tbody>{table}</tbody></table></div></details>
</figure>"""


def corner_bars(d: dict) -> str:
    rows = sorted(d["grip"]["corners"], key=lambda c: c["corner"])
    m = max(abs(c["diff_kph"]) for c in rows)
    lim = ticks(0, m, 3)[-1]
    span_kph = 1.35 * lim  # room for the value at the end of the longest bar

    def x(v):
        return 50 + 50 * v / span_kph

    out = []
    for c in rows:
        v = c["diff_kph"]
        cls = "pos" if v > 0 else "neg"
        left, width = (x(0), x(v) - x(0)) if v > 0 else (x(v), x(0) - x(v))
        label_pos = f"left:{x(v):.2f}%" if v > 0 else f"right:{100 - x(v):.2f}%"
        hover = tip(f"{signed(v, 1)} km/h",
                    f"Turn {c['corner']}: sim {c['sim_kph']:.0f}, real {c['real_kph']:.0f} km/h")
        out.append(f'<div class="dp-label">Turn {c["corner"]} <small>{c["real_kph"]:.0f} km/h</small></div>'
                   f'<div class="dp-plot"><div class="bar {cls}" style="left:{left:.2f}%;width:{width:.2f}%" {hover}>'
                   f'</div><span class="bar-val" style="{label_pos}">{signed(v, 0)}</span></div>')
    t = [-lim, -lim / 2, 0, lim / 2, lim]
    grid = "".join(f'<div class="dp-grid{" zero" if v == 0 else ""}" style="left:{x(v):.2f}%"></div>' for v in t)
    axis = "".join(f'<span style="left:{x(v):.2f}%">{signed(v, 0)}</span>' for v in t)
    table = "".join(f'<tr><td>Turn {c["corner"]}</td><td class="num">{c["real_kph"]:.0f}</td>'
                    f'<td class="num">{c["sim_kph"]:.0f}</td><td class="num">{signed(c["diff_kph"], 1)}</td></tr>'
                    for c in rows)
    return f"""<figure>
<div class="legend"><span class="key"><span class="swatch sq neg"></span>Sim slower than the cars</span>
<span class="key"><span class="swatch sq pos"></span>Sim faster</span></div>
<div class="dp" style="--lw:9.5rem" role="group" aria-label="Simulated minus real corner minimum speed, km/h">
<div class="dp-plot" style="position:absolute;left:var(--lw);right:0;top:0;bottom:22px"
aria-hidden="true">{grid}</div>{''.join(out)}<div></div><div class="dp-axis" aria-hidden="true">{axis}</div></div>
<details><summary>Table: corner speeds</summary><div class="tablewrap"><table><thead><tr><th>Corner</th>
<th class="num">Real, km/h</th><th class="num">Sim, km/h</th><th class="num">Sim − real</th></tr></thead>
<tbody>{table}</tbody></table></div></details>
</figure>"""


def model_checks(d: dict) -> list[tuple[str, str, str, str]]:
    """(status, name, what it compares, result) for each model check."""
    g, p, b = d["grip"], d["pace"], d["bench"]
    rows = []
    worst_m = max(abs(r["mech_err"]) for r in b["rows"])
    worst_d = max(abs(r["downforce_err"]) for r in b["rows"])
    rows.append(("pass" if b["passed"] else "fail", "Grip · test bench",
                 f"{len(b['rows'])} synthetic teams with known grip and downforce, run through the lap sim and "
                 f"rendered as OpenF1-style telemetry, then measured like a real session",
                 f"Largest error {worst_m:.2f} points on tyre grip (tolerance {b['tolerance_pct']['mech']:g}) and "
                 f"{worst_d:.2f} on downforce (tolerance {b['tolerance_pct']['downforce']:g})"))
    ca = g["clean_air"]
    if ca:
        se = {r["team"]: r for r in g["teams"]}
        moves = []
        for r in ca["teams"]:
            s = se[r["team"]]
            for key, k_se, label in (("slow", "slow_corner_se", "slow"), ("fast", "fast_corner_se", "fast")):
                delta = r[key] - s[key + "_corner_pct"]
                moves.append((abs(delta) / max(s[k_se], 1e-9), abs(delta), label, team(r["team"])))
        worst = max(moves)
        fast_max = max((m for m in moves if m[2] == "fast"), key=lambda m: m[1])
        kind = "pass" if worst[0] <= 2 else "warn"
        rows.append((kind, "Grip · dirty air",
                     f"Refitted on the {ca['laps']} laps with no car within {ca['gap_s']:g} s ahead",
                     f"Fast-corner grip moved {fast_max[1]:.1f} points at most ({fast_max[3]}). The largest move "
                     f"against its uncertainty: {worst[3]}, {worst[2]} corners, {worst[1]:.1f} points "
                     f"({worst[0]:.1f} standard errors)"))
    pb = d.get("pace_bench")
    if pb:
        rows.append(("pass" if pb["passed"] else "fail", "Pace · test bench",
                     f"A synthetic race of {pb['cars']} cars over {pb['laps']} laps with known sector gaps, tyre, fuel "
                     f"and traffic effects, lap-to-lap noise and a few wrecked laps",
                     f"Every car's gap in every sector recovered to within {pb['max_error_s']:.3f} s "
                     f"(tolerance {pb['tolerance_s']:.2f} s)"))
    h = p["holdout"]
    rows.append(("pass" if h["model_err_s"] < h["baseline_err_s"] else "fail", "Pace · held-out laps",
                 f"Fitted on odd-numbered laps, asked for the lap times of the {h['laps']} even-numbered ones",
                 f"Median error {h['model_err_s']:.2f} s, against {h['baseline_err_s']:.2f} s for each car's own "
                 f"median lap"))
    f = g["field"]
    short = sum(s["line_short_m"] for s in g["sections"] if s["line_short_m"] == s["line_short_m"])
    rows.append(("warn", "Field car · corner speeds",
                 f"The sim's car, with grip and downforce fitted so its corner minimum speeds match the field's "
                 f"(μ {f['mu']:.2f}, CLA {f['cla']:.2f} m²)",
                 f"Misses by {f['rms_kph']:.0f} km/h rms, with a pattern: see below. The team comparisons above "
                 f"don't use it. The modelled line is also {short:.0f} m a lap shorter than the cars drove"))
    return rows


def checks_section(d: dict) -> str:
    data_rows = []
    for c in d["checks"]:
        kind = "pass" if c["passed"] else ("fail" if c["gating"] else "warn")
        data_rows.append(f'<tr><td>{status(kind)}</td><td><span class="name">'
                         f'{e(DATA_CHECK_NAMES.get(c["name"], c["name"]))}</span></td>'
                         f'<td class="what">{e(c["detail"])}</td></tr>')
    model_rows = "".join(
        f'<tr><td>{status(k)}</td><td><span class="name">{e(n)}</span></td><td class="what">{e(w)}. '
        f'<span style="color:var(--ink)">{e(r)}.</span></td></tr>' for k, n, w, r in model_checks(d))
    code = d["code"]
    version = (f'<a href="{REPO_URL}/commit/{e(code["commit"])}">{e(code["commit"])}</a>'
               + (" with uncommitted changes" if code["dirty"] else ""))
    return f"""<section id="checks"><div class="sec-head"><div class="eyebrow">How far to trust it</div>
<h2>Checks</h2></div>
<p>Each model behind the numbers above has to recover known answers on a test bench before it runs on a session,
and its output is then checked against what the session's own data can confirm. A session is only published if
every gating data check passes.</p>
<h3>Models</h3>
<div class="tablewrap card" style="padding:0"><table class="checks"><tbody>{model_rows}</tbody></table></div>
<h3>Field car against real corner speeds</h3>
<p class="note">Simulated minus real minimum speed at each corner the drivers lift for. It is too fast where a corner
is the second half of a sequence and at Turn 9, where drivers don't use the full limit, and too slow in the section
rebuilt since the track-width survey, where widths are a guess.</p>
{corner_bars(d)}
<h3>Data</h3>
<div class="tablewrap card" style="padding:0"><table class="checks"><tbody>{''.join(data_rows)}</tbody></table></div>
<p class="note">Built from parc-ferme {version} on {e(d['generated_utc'])} UTC.</p>
</section>"""


def page(d: dict, home: str = "../../") -> str:
    s, c = d["session"], d["conditions"]
    cars = d["cars"]
    rnd = f"Round {s['round']} · " if s.get("round") else ""
    weather = ("wet" if c["rain"] else "dry") + f", air {c['air_c']:.0f} °C, track {c['track_c']:.0f} °C"
    podium = "".join(
        f'<li><span class="pos">{p["position"]}</span><span><span class="who">{e(cars[p["driver"]]["name"])}</span> '
        f'<span class="sub">{e(team(p["team"]))}'
        + (f' · from P{p["grid"]}' if p.get("grid") else "") + "</span></span></li>" for p in d["podium"])
    findings = "".join(f'<li><p>{e(f["text"])}</p><a href="{e(f["href"])}">'
                       f'{"See pace by sector" if f["href"] == "#pace" else "See grip by team"}</a></li>'
                       for f in summary_findings(d))
    title = f"{s['name']} {s['session_name'].lower()} debrief"
    g = d["grip"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · parc-ferme</title>
<meta name="description" content="Engineering debrief of the {s['year']} {e(s['name'])}: race pace by sector and
grip by team, from public timing data, with every model checked.">
<style>{CSS}</style></head>
<body>
<header class="top"><div class="in"><a class="brand" href="{home}">parc-ferme</a>
<nav><a href="{home}">{s['year']} debriefs</a></nav></div></header>
<main>
<section class="hero">
<div class="eyebrow">{e(s['session_name'])} debrief · {rnd}{e(date_text(s['date']))}</div>
<h1>{e(s['name'])}</h1>
<p class="meta">{e(s['circuit'])} · {s['laps']} laps · {e(weather)}</p>
<ol class="podium" aria-label="Result">{podium}</ol>
</section>

<section id="summary"><div class="sec-head"><div class="eyebrow">Summary</div><h2>Three findings</h2></div>
<ol class="findings">{findings}</ol></section>

<section id="car"><div class="sec-head"><div class="eyebrow">Car performance</div><h2>Pace and grip</h2></div>
{track_map(d)}
<div class="two">
<div style="display:flex;flex-direction:column;gap:12px">
<p>Every green lap counts: no pit laps, no safety cars, nothing slower than 107% of the car's own median. Laps are
compared after taking out what isn't the car: tyre compound and age, fuel burn over the race, and traffic.</p>
<p>Pace is shown car by car, because two drivers of one team can have very different races. Grip is shown team by
team, from both cars, because it is a property of the car.</p>
</div>
<div class="callout"><p><b>Not measured yet: drag.</b> In 2026 how fast a car accelerates on a straight depends on
how much battery energy it deploys there, which the public data doesn't show. Drag will be fitted together with the
energy model.</p></div>
</div>

<h3 id="pace" style="scroll-margin-top:16px">Race pace by sector</h3>
{pace_table(d)}

<h3 id="grip" style="scroll-margin-top:16px">Grip in slow and fast corners</h3>
<p>From the lowest speed of every green lap through each corner the drivers lift for ({len(g['corners'])} of
{len(d['track']['corners'])}). Every car takes nearly the same radius through a corner, so comparing a team with
the field at the same corner cancels the radius out; the timing data doesn't show where a car is across the
track.</p>
{dot_plot(d)}
<p class="note">The gap between slow and fast corners is where downforce shows. Splitting each team's grip into tyre
grip and downforce needs more circuits than one: here the split is uncertain by
{min(r['downforce_se'] for r in g['teams']):.0f}–{max(r['downforce_se'] for r in g['teams']):.0f}% per team, and
only the largest differences stand out. Both are in the table.</p>
</section>

{checks_section(d)}
</main>
<footer><div class="in"><p>{SOURCES} Code, models and test benches: <a href="{REPO_URL}">parc-ferme on
GitHub</a>, MIT licence.</p><p>{DISCLAIMER}</p></div></footer>
<script>{SCRIPT}</script>
</body></html>
"""


def index(debriefs: list[dict]) -> str:
    items = []
    for d in sorted(debriefs, key=lambda x: x["session"]["date"], reverse=True):
        s = d["session"]
        rnd = f"Round {s['round']} · " if s.get("round") else ""
        items.append(f'<li><a href="{e(slug(d))}/"><span class="t">{e(s["name"])} · {e(s["session_name"])}</span>'
                     f'<span class="m">{rnd}{e(date_text(s["date"]))} · {e(s["circuit"])}</span></a></li>')
    year = debriefs[0]["session"]["year"] if debriefs else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>parc-ferme · {year} debriefs</title>
<meta name="description" content="Post-session engineering debriefs for {year} Formula 1, from public timing data.">
<style>{CSS}</style></head>
<body>
<header class="top"><div class="in"><a class="brand" href="./">parc-ferme</a></div></header>
<main>
<section class="hero"><div class="eyebrow">{year} season</div><h1>Engineering debriefs</h1>
<p class="meta">After each session: where every car gained and lost time, and why, worked out from public timing
data by physics models that are checked against what the cars actually did.</p></section>
<section><ol class="sessions">{''.join(items)}</ol></section>
</main>
<footer><div class="in"><p>{SOURCES} Code, models and test benches: <a href="{REPO_URL}">parc-ferme on
GitHub</a>, MIT licence.</p><p>{DISCLAIMER}</p></div></footer>
</body></html>
"""


def write(out: Path, debriefs: list[dict]) -> list[Path]:
    """Write the index and one page per debrief under `out`. Returns the pages written."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for d in debriefs:
        path = out / slug(d) / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page(d))
        (path.parent / "debrief.json").write_text(json.dumps(d, indent=1, default=float))
        written.append(path)
    (out / "index.html").write_text(index(debriefs))
    (out / ".nojekyll").write_text("")
    return written
