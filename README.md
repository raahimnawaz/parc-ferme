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

## Quick start

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/bin/parc-ferme ingest 11307     # 2026 Barcelona GP race, from OpenF1
.venv/bin/parc-ferme check 11307      # data checks + warm-up analyses, written to reports/11307/
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
  cli.py        `parc-ferme ingest` / `parc-ferme check`
```

## License

MIT
