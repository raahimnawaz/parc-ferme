# parc-ferme

Post-session engineering debriefs for 2026 Formula 1, worked out from public timing data by physics models that
are checked against what the cars actually did.

After every session the pipeline publishes the report a trackside performance engineer would want: each team's drag
and downforce, where it runs out of electric power, how its tyres wore, how its brakes were loaded, and a lap-by-lap
replay of the strategy calls. Each figure carries an uncertainty and the check it passed.

## Status

Step 1 of the build: the data layer. One race, the 2026 Barcelona Grand Prix (round 7), is ingested from OpenF1 and
passes every gating check below. Speed integrated over each car's fastest lap lands within 2% of the 4,650 m
centreline for all 22 cars (median 4,633 m), and the classification matches the official result.

One defect in the source data is corrected rather than trusted: OpenF1 places Bearman's second tyre change on lap 28,
while its own pit log and out-lap flag put it on lap 39. Stint boundaries are therefore rebuilt from the pit log, and
every correction is reported. Left in, that error put eleven Hard-tyre laps into the Soft wear fit and cut its slope
from +0.18 to +0.05 s/lap.

Step 2: the track model (S1) and the digital 2026 car with its lap simulator (S2). The simulated lap is rendered
as OpenF1-shaped telemetry and run through the same code as real laps.

| | |
|---|---|
| Track geometry | The 2026 layout from the timing feed: every car's green-lap positions (1,052 laps) averaged by lap fraction, with elevation (30 m range). The TUMFTM centreline is the pre-2021 layout at Turn 10 and the final sector, so it supplies track width only where it matches (67% of the lap). |
| Racing line | Minimum lap time, not minimum curvature. The offset from the reference is searched against the lap sim's own lap time, coarse to fine, from the minimum-curvature line. The gain is 2.0 s (2.6%) for the same car, concentrated at Turn 9 onto the back straight and the Turn 1–2 sequence. |
| Car | 2026 rules from `core/rules_2026.toml` (768 kg, 400 kW ICE, 350 kW MGU-K with its taper above 290 km/h, 8.5 MJ harvest per lap), straight mode only in the FIA zones, road grade, air density from the session's weather. Grip and corner downforce are fitted in S3; drag waits for S4. |
| Lap sim | Quasi-steady point mass, compiled with Numba (0.3 ms per lap). The MGU-K deploys below a threshold speed chosen so the lap spends exactly what it harvests. |

Against Hamilton's fastest race lap (lap 44, 80.122 s) the nominal car runs 74.17 s with a speed-trace correlation
of 0.94. The gap is expected before S3: the nominal grip is too high (corner minimum speeds 5.6 km/h above his), and
the car harvests only under braking (4.0 MJ of the 8.5 MJ allowed), so it cannot deploy at high speed and is 7 km/h
down at the end of the main straight.

Step 3: grip and downforce per team (S3), `parc-ferme grip`. Every team's grip in slow and fast corners relative
to the field, from the lowest speed of every green lap through every corner the drivers lift for (13 of 14; Turn 6
is flat out). Every car drives nearly the same radius, so comparing a team with the field at the same corner
cancels the radius, which the feed can't show. The test bench (synthetic teams with known grip and downforce, run
through the sim and rendered as OpenF1 telemetry) recovers mechanical grip to 0.3% and downforce to 1.5%.

| Team | Slow corners | Fast corners |
|---|---|---|
| Ferrari | +4.1 ± 1.2% | +3.8 ± 0.9% |
| Mercedes | +4.9 ± 1.0% | +3.5 ± 1.3% |
| McLaren | +2.1 ± 0.7% | +3.2 ± 0.8% |
| Red Bull Racing | +1.8 ± 0.6% | +2.8 ± 0.7% |
| Alpine | −0.7 ± 0.6% | +0.1 ± 0.3% |
| Audi | −3.7 ± 0.4% | −0.6 ± 0.5% |
| Racing Bulls | −0.8 ± 1.1% | −0.6 ± 0.7% |
| Haas | −0.8 ± 0.3% | −1.7 ± 0.3% |
| Williams | −1.1 ± 1.9% | −3.1 ± 1.3% |
| Aston Martin | −3.1 ± 0.6% | −3.3 ± 0.7% |
| Cadillac | −2.7 ± 0.8% | −4.1 ± 0.5% |

Grip here is lateral force capacity relative to the mean team, with compound, tyre age and lap number (fuel burn,
track evolution) taken out. Slow and fast are the field's slowest and fastest lifted corners, where 18% and 57% of
the grip comes from downforce. Uncertainties are leave-one-corner-out, so they include a team's drivers taking a
different line at one corner, not only lap-to-lap noise. The split into tyre grip and downforce is in
`grip_teams.csv` but is not resolved at one circuit: its uncertainty is 1–7% per team, and only Audi stands out
(downforce +8 ± 2%, mechanical grip −5 ± 1%). More circuits, with a wider spread of corner speeds, will separate them.

The field's absolute grip is fitted so the sim's corner minimum speeds match the real ones: mu 1.45 and ClA 4.94 m²
at the race's air density, on the minimum-time line re-searched for the fitted car. The misfit is 12 km/h rms and it
has a pattern. The sim is too fast where a corner is the second half of a sequence (Turn 2 +18 km/h, Turn 8 +17) and
at the fast, blind Turn 9 (+15), which is where a point mass driven at the limit is least like a driver. It is too
slow at every corner in the section rebuilt since the width survey (Turns 10, 12, 13, 14: −11 to −19 km/h), where the
widths are the database median.

Found here:

- **The speed channel is right.** Two independent checks: speed from the position feed on straights agrees within
  0.1% from 150 to 360 km/h (the feed's positions register onto the surveyed centreline at scale 1.000), and the
  speed trap agrees within 0.1% at 332 km/h. This is now the gating check `speed_scale`. The 4,633 m lap is real.
- **The racing line is too short, in known places.** With the speed channel trusted, the distance driven between
  two points on straights is a measurement. The minimum-time line is 31 m short through Turns 1–4, 13 m through
  Turns 5–8, 33 m through Turns 10–13 and 9 m through Turn 14, and within a metre through Turn 9
  (`path_lengths.csv`). Forcing the line to those lengths was tried and didn't make corner grip consistent, so it
  is not used.
- **Air density.** 1.142 kg/m³ on race day (1000.5 hPa, 30.5 °C, 29% humidity), 4.8% under the 1.20 assumed in step
  2. It now comes from the session's weather.
- **Drag can't be fitted from straights in 2026.** Full-throttle acceleration on the back straight collapses from
  7.4 to 2.3 m/s² between 250 and 295 km/h, below the 290 km/h point where the rules start tapering the MGU-K. That
  is teams cutting deployment to manage energy. Drag and deployed power trade off one for one, so drag is fitted
  together with the energy model (S4).
- **Straight-line braking is no clean grip measure either.** Peak deceleration flattens above 250 km/h (about
  3.5 g), consistent with the wings still closing from straight mode as the braking starts.
- **Lateral position.** The feed places every car on one reference line (Hamilton's positions sit within 6 cm of
  it), so it says where a car is around the lap, not across the track.

Step 4: the first debrief page, `parc-ferme debrief`. A static page per session with a summary of three findings,
race pace and grip, and the checks behind them, built into `_site/` from one JSON document (`debrief.json`) that
records every number, check and the code version. Plain HTML and CSS, light and dark, readable at phone width, with
a table view behind every chart. It is not published yet.

Race pace is compared car by car, sector by sector, against the fastest car. Each green lap's three sector times
are fitted with an effect per car and shared terms for tyre compound, tyre age (a slope per compound), lap number
(fuel burn and track evolution) and traffic (the smallest gap to the car ahead during the lap). Per car, not per
team: pooling both drivers put Mercedes ahead of Ferrari on pace in a race Hamilton won by 19.6 s, because Leclerc
had a much slower race.

| | |
|---|---|
| Barcelona | Hamilton's Ferrari fastest; Russell's Mercedes +0.16 ± 0.07 s a lap, Antonelli +0.23, Norris +0.29, Verstappen +0.43, Leclerc +0.62. Russell was 0.07 s quicker than Hamilton through sector 1 and lost 0.18 s in sector 2. |
| Traffic | Running within 1 s of the car ahead cost 0.20 ± 0.04 s a lap, 0.15 s of it in sector 2 (Turns 4–9); between 1 and 2 s it cost nothing measurable. 41% of green laps had a car within 1.5 s at some point, so the term is fitted rather than those laps dropped. |
| Held-out laps | Fitted on odd laps, the model predicts even-lap times to 0.29 s (median error), against 0.71 s for each car's own median lap. |
| Test bench | A synthetic race with known sector gaps, tyre, fuel and traffic effects, noise and wrecked laps: every car's gap in every sector recovered within 0.03 s (tolerance 0.06). |
| Grip in dirty air | Refitted on laps with no car within 1.5 s ahead, fast-corner grip moves at most 0.5 points; the largest move against its uncertainty is Haas in slow corners (0.9 points, 2.8 standard errors), shown as a warning. |

## Quick start

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/bin/parc-ferme ingest 11307     # 2026 Barcelona GP race, from OpenF1
.venv/bin/parc-ferme check 11307      # data checks + warm-up analyses, written to reports/11307/
.venv/bin/parc-ferme sim 11307        # nominal 2026 car on the minimum-time line vs Hamilton's best lap
.venv/bin/parc-ferme grip 11307       # S3: grip per team, the fitted field car, driven distance per section
.venv/bin/parc-ferme debrief 11307    # the debrief page, built into _site/ (refused if a gating check fails)
.venv/bin/parc-ferme site             # rebuild _site/ from every debrief already built
.venv/bin/python -m pytest
```

`check` exits non-zero if any gating check fails, and `debrief` won't build a page for a session that fails one.

## Data

| Source | Used for |
|---|---|
| [OpenF1](https://openf1.org) | Laps, sectors, speed traps, stints, pit stops, race control, weather, intervals, results, and car data and positions at about 4 Hz. No login. |
| Circuit info (the F1 timing feed's companion service) | Corner numbers and positions, marshal sectors, pit loss, track outline. |
| [TUMFTM racetrack-database](https://github.com/TUMFTM/racetrack-database) | Track centreline and width. LGPL-3.0; downloaded at ingest, not redistributed. |
| [Jolpica](https://github.com/jolpica/jolpica-f1) | Official classification, grid after penalties, retirement reasons. |

Everything is cached under `data/` (not committed) so a session loads offline after one ingest.

## Data checks

| Check | What it guards against |
|---|---|
| `drivers` | Missing cars or results without a driver entry. |
| `lap_count` | The winner's timed laps disagree with the classified race distance. |
| `sectors_sum_to_lap` | Sector times that don't add up to the lap time. |
| `stints_contiguous` | Tyre stints with gaps or overlaps, which would corrupt tyre age. |
| `pit_stops_match_stints` | Pit entries that don't line up with tyre changes. |
| `car_data_rate` | Telemetry that is too sparse or has long dropouts. |
| `lap_distance` | Speed integrated over each fastest lap must match the circuit length. |
| `speed_scale` | The speed channel must agree with speed from the position feed on straights within 1%. |
| `centreline_matches_layout` | The centreline file must be the layout actually raced. |
| `results_match_official` | OpenF1's classification must match the official one. |
| `green_laps`, `degradation_fits` | Enough clean racing laps, and tyre wear fits that are finite and tight. |

## Layout

```
src/parc_ferme/
  openf1.py     OpenF1 client and session ingest to Parquet
  circuit.py    corners, outline and centreline
  jolpica.py    official classification
  session.py    offline access to an ingested session
  laps.py       per-lap table: tyre state, pit and neutralisation flags, green-lap mask
  telemetry.py  car data cut to a lap, placed on distance or on the reference line
  warmup.py     tyre wear, long-run pace, pit-stop pace, fastest-lap overlay
  checks.py     the data checks
  cli.py        `parc-ferme ingest` / `check` / `sim` / `grip` / `debrief` / `site`
  core/
    rules_2026.toml  2026 rules, each value with its source
    track.py    S1: layout from the feed, registration, widths, minimum-curvature line
    car.py      S2: the digital car and its gearing (fitted from telemetry)
  sim/
    lapsim.py   S2: quasi-steady lap sim with energy budget and straight-mode zones
    raceline.py minimum-time line search
    model.py    assembles S1 + S2 for a session and compares with a real lap
  models/
    grip.py     S3: corner minimum speeds, grip per team relative to the field, the field car fitted to corners
    pace.py     race pace per car and sector, with tyre, fuel and traffic taken out
  bench/
    fake.py     simulated lap rendered as OpenF1-shaped car data and positions
    grip.py     S3 test bench: synthetic teams with known grip and downforce
    pace.py     pace test bench: a synthetic race with known gaps and effects
  debrief/
    build.py    everything one debrief page shows, as one JSON document
    summary.py  the three findings, worded only as strongly as the uncertainty allows
  site/
    render.py   the static site: one page per session and an index
```

Track geometry and the lap sim are ported from [engine-map-pinn](https://github.com/raahimnawaz/engine-map-pinn)
and extended for 2026.

## License

MIT
