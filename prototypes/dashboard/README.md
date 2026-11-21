# Telemetry dashboard prototype

A design probe for the debrief site: an ATLAS-style analysis workstation for one session (Barcelona, session 11307),
dark, with four workspaces.

- **Lap analysis**: two cars' laps overlaid against distance (speed, time gap, throttle, brake, gear, engine speed),
  a circuit stripe with sectors, corners and straight-mode zones, a track map coloured by who was faster in each of
  25 mini-sectors, a lap summary in F1 timing colours, and a reference cursor that measures any stretch. Fastest lap
  or typical lap (raw medians, labelled as unadjusted), and an optional lap-sim overlay with its ERS channels.
- **Race pace**: time lost per lap to the fastest car by sector, and the cost of running in traffic.
- **Car model**: the simulator's parameters with their source and each one's lap-time effect for +1%, and
  cornering grip by team.
- **Model health**: data checks, test benches and the known gaps, as status tiles.

The distance axis is corrected distance, as MoTeC and ATLAS build it: speed integrated over the lap and scaled to the
lap length.

```bash
.venv/bin/parc-ferme debrief 11307                 # the debrief document this reads
.venv/bin/python prototypes/dashboard/data.py      # channels for every car, lap sims, parameter matrix
.venv/bin/python prototypes/dashboard/build.py     # _site/prototype/dashboard/index.html
```
