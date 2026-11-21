"""Telemetry dashboard prototype, page step: ATLAS-style lap analysis workspace plus race pace, car model and model
health workspaces. Reads reports/11307/dashboard.json, writes _site/prototype/dashboard/index.html."""

import json
from html import escape
from pathlib import Path

from parc_ferme.paths import REPORTS, SITE

HERE = Path(__file__).parent
D = json.loads((REPORTS / "11307" / "dashboard.json").read_text())
TEAM_SHORT = {"Haas F1 Team": "Haas", "Red Bull Racing": "Red Bull"}


def e(x):
    return escape(str(x), quote=True)


def team(n):
    return TEAM_SHORT.get(n, n)


def signed(x, nd=2):
    return f"{'+' if x > 0 else '−' if x < 0 else ''}{abs(x):.{nd}f}"


cars = D["cars"]
sess = D["session"]
cond = D["conditions"]

# ---------------- race pace workspace (server-rendered) ----------------
rows = D["pace"]["cars"]
ref = rows[0]
sec_names = [f"S{s['k']} · T{s['corners'][0]}–{s['corners'][-1]}" for s in D["sectors"]]


def bars(group, lo, hi):
    out = []
    for pos, r in group:
        c = cars[r["driver"]]
        if r["driver"] == ref["driver"]:
            out.append(f'<div class="pb-row"><span class="rk">{pos}</span><i class="chip" style="background:{c["colour"]}"></i>'
                       f'<span class="nm">{e(c["last"])}<small>{e(team(r["team"]))}</small></span><div class="pb-bar">'
                       f'<div class="z" style="left:{100 * -lo / (hi - lo):.2f}%"></div><span class="reftag" '
                       f'style="left:{100 * -lo / (hi - lo):.2f}%">reference</span></div><span class="vv">—</span></div>')
            continue
        segs, neg, posv = [], 0.0, 0.0
        for k in range(1, 4):
            v = r[f"s{k}"]
            a, b = (neg + v, neg) if v < 0 else (posv, posv + v)
            neg, posv = (neg + v, posv) if v < 0 else (neg, posv + v)
            left, right = 100 * (a - lo) / (hi - lo), min(100 * (b - lo) / (hi - lo), 100)
            if right > left:
                segs.append(f'<i class="sg s{k}" style="left:{left:.2f}%;width:{right - left:.2f}%" '
                            f'data-v="{signed(v)} s" data-l="{e(c["last"])} · sector {k} vs {e(cars[ref["driver"]]["last"])}"></i>')
        net = r["lap"]
        segs.append(f'<i class="nt" style="left:{min(100 * (net - lo) / (hi - lo), 99.5):.2f}%"></i>')
        out.append(f'<div class="pb-row"><span class="rk">{pos}</span><i class="chip" style="background:{c["colour"]}"></i>'
                   f'<span class="nm">{e(c["last"])}<small>{e(team(r["team"]))}</small></span><div class="pb-bar">'
                   f'<div class="z" style="left:{100 * -lo / (hi - lo):.2f}%"></div>{"".join(segs)}</div>'
                   f'<span class="vv">{signed(net)} <small>± {r["lap_se"]:.2f}</small></span></div>')
    return "".join(out)


ranked = list(enumerate(rows, start=1))
front_hi = round(1.05 * max(sum(max(r[f"s{k}"], 0) for k in range(1, 4)) for _, r in ranked[:8]) + 0.05, 1)
pace_front = bars(ranked[:8], -0.25, front_hi)
pace_rest = bars(ranked[8:], -0.25, 4.5)
tr = D["pace"]["traffic"]
traffic_rows = "".join(
    f'<tr><td>{e(x["gap"])}</td>' + "".join(f'<td class="n">{signed(x[f"s{k}"])} <small>± {x[f"s{k}_se"]:.2f}</small></td>'
                                          for k in (1, 2, 3))
    + f'<td class="n"><b>{signed(x["lap"])}</b> <small>± {x["lap_se"]:.2f}</small></td><td class="n">{x["laps"]}</td></tr>'
    for x in tr)

# ---------------- car model workspace ----------------
badge = {"Rules": "rules", "Fitted": "fit", "Measured": "meas", "Nominal": "nom"}
eff_max = max(abs(p["effect_s"]) for p in D["params"])
param_rows = []
for p in D["params"]:
    w = 50 * abs(p["effect_s"]) / eff_max
    side = f"left:50%;width:{w:.1f}%" if p["effect_s"] > 0 else f"left:{50 - w:.1f}%;width:{w:.1f}%"
    cls = "slower" if p["effect_s"] > 0 else "faster"
    note = ""
    if p["name"].startswith("Energy harvest"):
        note = '<small class="warnnote">not reached: the sim harvests only under braking (S4)</small>'
    param_rows.append(
        f'<tr><td>{e(p["name"])}<small class="sym">{e(p["sym"])}</small>{note}</td>'
        f'<td class="n">{p["value"]:,.3f}'.rstrip("0").rstrip(".") + f' <small>{e(p["unit"])}</small></td>'
        f'<td><span class="badge {badge[p["source"]]}">{e(p["source"])}</span></td>'
        f'<td class="n">{signed(p["effect_s"], 3)} s</td><td class="effcell"><div class="eff"><i class="mid"></i>'
        f'<i class="bar {cls}" style="{side}"></i></div></td></tr>')

grip_rows = sorted(D["grip"]["teams"], key=lambda r: -r["fast_corner_pct"])
vals = [r[k] + s * r[k.replace("pct", "se")] for r in grip_rows for k in ("slow_corner_pct", "fast_corner_pct") for s in (-1, 1)]
g_lo, g_hi = min(vals + [0]) - 0.5, max(vals + [0]) + 0.5


def gx(v):
    return 100 * (v - g_lo) / (g_hi - g_lo)


team_colour = {c["team"]: c["colour"] for c in cars.values()}
grip_html = []
for r in grip_rows:
    marks = []
    for key, cls, dy, label in (("slow_corner_pct", "gs", -5, "slow corners"), ("fast_corner_pct", "gf", 5, "fast corners")):
        v, se = r[key], r[key.replace("pct", "se")]
        marks.append(f'<i class="wh {cls}" style="left:{gx(v - se):.2f}%;width:{gx(v + se) - gx(v - se):.2f}%;'
                     f'top:calc(50% + {dy - 1}px)"></i><i class="dt {cls}" style="left:{gx(v):.2f}%;top:calc(50% + {dy}px)" '
                     f'data-v="{signed(v, 1)} ± {se:.1f}%" data-l="{e(team(r["team"]))} · {label}" tabindex="0"></i>')
    grip_html.append(f'<div class="gr-row"><span class="nm"><i class="chip" style="background:{team_colour.get(r["team"], "#888")}">'
                     f'</i>{e(team(r["team"]))}</span><div class="gr-plot"><div class="z" style="left:{gx(0):.2f}%"></div>'
                     f'{"".join(marks)}</div></div>')
ticks = [t for t in range(int(g_lo) - 1, int(g_hi) + 2) if g_lo <= t <= g_hi and t % 2 == 0]
grip_axis = "".join(f'<span style="left:{gx(t):.2f}%">{"avg" if t == 0 else f"{t:+d}%"}</span>' for t in ticks)
corners_used = D["grip"]["corners"]
slow_c = min(corners_used, key=lambda c: c["w"])
fast_c = max(corners_used, key=lambda c: c["w"])

# ---------------- model health workspace ----------------
gating = [c for c in D["checks"] if c["gating"]]
health = []


def tile(status, name, value, detail):
    icon = {"ok": "✓", "warn": "!", "bad": "✕"}[status]
    health.append(f'<div class="ht {status}"><div class="hh"><i>{icon}</i>{e(name)}</div><div class="hv">{value}</div>'
                  f'<div class="hd">{e(detail)}</div></div>')


tile("ok" if all(c["passed"] for c in gating) else "bad", "Data checks", f'{sum(c["passed"] for c in gating)}/{len(gating)}',
     "Gating checks on the session's timing data")
sc = next(c for c in D["checks"] if c["name"] == "speed_scale")
tile("ok" if sc["passed"] else "bad", "Speed channel", sc["detail"].split("median ")[1].split(" ")[0],
     "Speed from positions ÷ speed channel, on straights (target 1.000 ± 1%)")
cr = next(c for c in D["checks"] if c["name"] == "car_data_rate")
tile("ok" if cr["passed"] else "bad", "Telemetry rate", cr["detail"].split("(")[1].split(")")[0], "Median car-data sample rate")
b = D["bench"]
tile("ok" if b["passed"] else "bad", "Grip model bench",
     f'{max(abs(r["mech_err"]) for r in b["rows"]):.2f} / {max(abs(r["downforce_err"]) for r in b["rows"]):.2f}',
     f'Largest error on tyre grip / downforce, points (limits {b["tolerance_pct"]["mech"]:g} / {b["tolerance_pct"]["downforce"]:g})')
pb = D["pace_bench"]
tile("ok" if pb["passed"] else "bad", "Pace model bench", f'{pb["max_error_s"]:.3f} s',
     f'Largest sector-gap error on a synthetic race (limit {pb["tolerance_s"]:.2f} s)')
h = D["pace"]["holdout"]
tile("ok" if h["model_err_s"] < h["baseline_err_s"] else "bad", "Pace model, held-out laps", f'{h["model_err_s"]:.2f} s',
     f'Median lap-time error on unseen laps; a car\'s own median lap gives {h["baseline_err_s"]:.2f} s')
tile("warn", "Lap sim corner fit", f'{D["grip"]["field"]["rms_kph"]:.0f} km/h',
     "RMS miss on corner minimum speeds; the racing line is the main error")
short = sum(x["line_short_m"] for x in D["grip"]["sections"] if x["line_short_m"] is not None)
tile("warn", "Racing line length", f"−{short:.0f} m", "Modelled line against the distance the cars drove, per lap")
tile("warn", "Drag & energy", "not fitted", "Needs the energy model (S4); straight-line speed is not used")
check_rows = "".join(
    f'<tr><td><span class="st {"ok" if c["passed"] else ("bad" if c["gating"] else "warn")}">'
    f'{"✓" if c["passed"] else ("✕" if c["gating"] else "!")}</span></td><td>{e(c["name"].replace("_", " "))}</td>'
    f'<td class="dim">{e(c["detail"])}</td></tr>' for c in D["checks"])

order = [r["driver"] for r in rows] + [c for c in cars if c not in {r["driver"] for r in rows}]
options = "".join(f'<option value="{c}">{e(cars[c]["last"])} · {e(team(cars[c]["team"]))}</option>' for c in order)
podium = " · ".join(f'P{p["position"]} {e(cars[p["driver"]]["last"])}' for p in D["podium"])

CSS = (HERE / "dash.css").read_text()
JS = (HERE / "dash.js").read_text()
html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Barcelona Grand Prix · telemetry · parc-ferme</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Saira:wdth,wght@100..125,300..500&family=Martian+Mono:wdth,wght@75..112.5,300..400&display=swap">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/uplot@1.6.32/dist/uPlot.min.css">
<script src="https://cdn.jsdelivr.net/npm/uplot@1.6.32/dist/uPlot.iife.min.js"></script>
<style>{CSS}</style></head><body>
<header class="top">
  <a class="logo" href="#"><i></i>Parc fermé</a>
  <div class="sess"><b>R{sess['round']} · Barcelona · Race</b><span>14 Jun 2026 · {sess['laps']} laps · {"wet" if cond['rain'] else "dry"} · air {cond['air_c']:.0f} °C · track {cond['track_c']:.0f} °C · {podium}</span></div>
  <nav class="ws-tabs" role="tablist">
    <button role="tab" data-ws="lap" aria-selected="true">Lap analysis</button>
    <button role="tab" data-ws="pace">Race pace</button>
    <button role="tab" data-ws="car">Car model</button>
    <button role="tab" data-ws="health">Model health</button>
  </nav>
</header>
<main>
<section class="ws" id="ws-lap">
  <div class="toolbar">
    <label class="sel a"><i class="sw" id="swA"></i><span>Car A</span><select id="selA">{options}</select></label>
    <span class="vs">vs</span>
    <label class="sel b"><i class="sw" id="swB"></i><span>Car B</span><select id="selB">{options}</select></label>
    <div class="seg" role="group" aria-label="Lap"><button data-lap="fastest" class="on">Fastest lap</button><button data-lap="typical">Typical lap</button></div>
    <label class="tog"><input type="checkbox" id="simOn"><span>Lap sim</span></label>
    <div class="zoom" id="zoom"></div>
  </div>
  <div class="lap-grid">
    <div class="traces card" id="traces"></div>
    <aside class="side">
      <div class="card map-card"><div class="card-h"><span>Track</span><div class="seg sm" role="group"><button data-map="gain" class="on">Who's faster</button><button data-map="sectors">Sectors</button></div></div>
        <svg id="map" role="img" aria-label="Track map"></svg><div class="map-legend" id="mapLegend"></div></div>
      <div class="card"><div class="card-h"><span>Lap summary</span><span class="dim" id="lapNote"></span></div><table class="sum" id="summary"></table>
        <div class="sum-legend" id="sumLegend"><span><i class="pp"></i>fastest of the race</span><span><i class="pg"></i>driver's best</span></div><div class="sum-note" id="sumNote" hidden></div></div>
      <div class="card" id="windowCard"><div class="card-h"><span>Selected stretch</span><button class="link" id="clearRef" hidden>clear</button></div><div id="window" class="dim">Click the traces to set a reference cursor; the stretch between it and the cursor is analysed here.</div></div>
    </aside>
  </div>
</section>

<section class="ws" id="ws-pace" hidden>
  <div class="ws-grid">
    <div class="card span2"><div class="card-h"><span>Time lost per lap to {e(cars[ref['driver']]['last'])}'s {e(team(ref['team']))}, by sector</span><span class="dim">all green laps · tyres, fuel and traffic taken out</span></div>
      <div class="pb-legend"><span><i class="s1"></i>{sec_names[0]}</span><span><i class="s2"></i>{sec_names[1]}</span><span><i class="s3"></i>{sec_names[2]}</span><span><i class="t"></i>net gap</span><span class="dim">left of the line = faster than the reference in that sector</span></div>
      {pace_front}
      <details class="more"><summary>Show the other {len(rows) - 8} cars <span class="dim">(wider scale)</span></summary>{pace_rest}</details>
    </div>
    <div class="card"><div class="card-h"><span>Cost of following, per lap</span><span class="dim">smallest gap to the car ahead during the lap</span></div>
      <table class="tbl"><thead><tr><th>Gap ahead</th><th class="n">S1</th><th class="n">S2</th><th class="n">S3</th><th class="n">Lap</th><th class="n">Laps</th></tr></thead><tbody>{traffic_rows}</tbody></table></div>
    <div class="card"><div class="card-h"><span>Pace model</span></div><p class="dim">Each green lap's sector times, fitted with one effect per car plus tyre compound and age, lap number and traffic. Fitted on odd laps it predicts even ones to {h['model_err_s']:.2f} s (a car's own median lap: {h['baseline_err_s']:.2f} s). ± is one standard error.</p></div>
  </div>
</section>

<section class="ws" id="ws-car" hidden>
  <div class="ws-grid">
    <div class="card span2"><div class="card-h"><span>Car model parameters</span><span class="dim">the simulator's 2026 car · lap-time effect of +1% on each, at Barcelona</span></div>
      <table class="tbl params"><thead><tr><th>Parameter</th><th class="n">Value</th><th>Source</th><th class="n">+1% →</th><th>faster ← → slower</th></tr></thead><tbody>{''.join(param_rows)}</tbody></table>
      <div class="badges dim"><span class="badge rules">Rules</span> 2026 regulations · <span class="badge meas">Measured</span> from this session · <span class="badge fit">Fitted</span> to this session's corner speeds · <span class="badge nom">Nominal</span> not fitted yet</div></div>
    <div class="card span2"><div class="card-h"><span>Cornering grip by team</span><span class="dim">against the average car · whiskers ± one standard error</span></div>
      <div class="gr-legend"><span><i class="gs"></i>Slow corners (Turn {slow_c['corner']}, {slow_c['real_kph']:.0f} km/h)</span><span><i class="gf"></i>Fast corners (Turn {fast_c['corner']}, {fast_c['real_kph']:.0f} km/h)</span></div>
      <div class="gr">{''.join(grip_html)}<div class="gr-row axis"><span></span><div class="gr-axis">{grip_axis}</div></div></div></div>
  </div>
</section>

<section class="ws" id="ws-health" hidden>
  <div class="ht-grid">{''.join(health)}</div>
  <div class="card"><div class="card-h"><span>Data checks</span><span class="dim">build {e(D['code']['commit'])}</span></div><table class="tbl">{check_rows}</table></div>
</section>
</main>
<div class="tip" id="tip" hidden></div>
<script id="data" type="application/json">{json.dumps({**{k: D[k] for k in ("L", "dx", "n", "sectors", "corners", "zones", "map", "cars", "best", "sims")}, "adjusted": {r["driver"]: [r["lap"], r["lap_se"]] for r in D["pace"]["cars"]}}, separators=(",", ":"))}</script>
<script>{JS}</script>
</body></html>"""
out = SITE / "prototype" / "dashboard" / "index.html"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html)
print(out, len(html) // 1024, "KB")
