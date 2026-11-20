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
| Car | 2026 rules from `core/rules_2026.toml` (768 kg, 400 kW ICE, 350 kW MGU-K with its taper above 290 km/h, 8.5 MJ harvest per lap), straight mode only in the FIA zones, road grade. Aero and grip are nominal values until S3 fits them. |
| Lap sim | Quasi-steady point mass, compiled with Numba (0.3 ms per lap). The MGU-K deploys below a threshold speed chosen so the lap spends exactly what it harvests. |

Against Hamilton's fastest race lap (lap 44, 80.122 s) the nominal car runs 74.17 s with a speed-trace correlation
of 0.94. The gap is expected before S3: the nominal grip is too high (corner minimum speeds 5.6 km/h above his), and
the car harvests only under braking (4.0 MJ of the 8.5 MJ allowed), so it cannot deploy at high speed and is 7 km/h
down at the end of the main straight.

Open items found here:

- **Speed channel scale.** Speed integrated over a lap gives 4,633 m (median of 22 cars), but no line that fits the
  track is longer than about 4,550 m and still fast. The speed channel probably reads about 2% high. Drag fitted in
  S3 scales with speed squared, so this has to be settled first.
- **Lateral position.** The feed places every car on one reference line (Hamilton's positions sit within 6 cm of
  it), so it says where a car is around the lap, not across the track. The racing line cannot be checked against
  real lines directly; it is checked through speed traces once the car is fitted.

## Quick start

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/bin/parc-ferme ingest 11307     # 2026 Barcelona GP race, from OpenF1
.venv/bin/parc-ferme check 11307      # data checks + warm-up analyses, written to reports/11307/
.venv/bin/parc-ferme sim 11307        # nominal 2026 car on the minimum-time line vs Hamilton's best lap
.venv/bin/python -m pytest
```

`check` exits non-zero if any gating check fails.

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
  telemetry.py  car data cut to a lap and placed on distance
  warmup.py     tyre wear, long-run pace, pit-stop pace, fastest-lap overlay
  checks.py     the data checks
  cli.py        `parc-ferme ingest` / `check` / `sim`
  core/
    rules_2026.toml  2026 rules, each value with its source
    track.py    S1: layout from the feed, registration, widths, minimum-curvature line
    car.py      S2: the digital car and its gearing (fitted from telemetry)
  sim/
    lapsim.py   S2: quasi-steady lap sim with energy budget and straight-mode zones
    raceline.py minimum-time line search
    model.py    assembles S1 + S2 for a session and compares with a real lap
  bench/
    fake.py     simulated lap rendered as OpenF1-shaped car data and positions
```

Track geometry and the lap sim are ported from [engine-map-pinn](https://github.com/raahimnawaz/engine-map-pinn)
and extended for 2026.

## License

MIT
