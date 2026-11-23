# Limits and identifiability

What the public feed can and can't separate, and how each model handles it. Written in response to a review that
raised four concerns: parameter coupling in S3–S6, the limits of a quasi-steady point-mass sim, inferring brake loads
from an on/off brake signal, and scope. All four are real. Numbers below are from the 2026 Barcelona race (OpenF1
session 11307) unless stated, and estimates are marked as such.

## Rules for every number on the page

1. **Fit only what the data constrains.** Reparameterise into combinations the data can see, and report a split as
   "not resolved" when its interval is as wide as the differences between teams.
2. **Physics fixes what physics knows.** Mass, the power-unit limits, air density and the lap-time cost of fuel come
   from the rules, the weather and the lap sim, not from a fit.
3. **Compare like with like, so shared unknowns cancel.** Teams against the field at the same corner (the corner
   radius cancels); drag only within a power-unit family (the engine power cancels).
4. **Bench before page.** A parameter goes on the page only if the test bench recovers it and its stated interval
   covers the true value at the stated rate, with the confounders below switched on: deployment strategies,
   clipping, lift-and-coast, fuel, tyre wear, track evolution, traffic.
5. **Effective, not physical.** Fitted quantities are named for what they are (effective cornering grip, not tyre
   friction coefficient), and wide intervals are shown, not hidden.

## 1. Parameter coupling (S3–S6)

The feed has speed, throttle, rpm and gear at about 3.7 Hz, an on/off brake and positions snapped to one line. No
wheel speeds, ride heights, loads, brake pressure or battery state.

| Wanted | Confounded with | What separates it | What is reported |
|---|---|---|---|
| Tyre grip vs downforce (S3) | Each other | Speed dependence: slow corners mostly tyre grip, fast corners grip × downforce | Grip in slow and fast corners, about 1% (done). The split only where its interval excludes zero (Audi at Barcelona) |
| Drag (S4) | Deployed power, clipping, derating, and regen while coasting | Stretches with different power at the same drag: the clipping knee at constant throttle, ICE-only running after the battery empties, terminal speed. ICE power from the rules | Drag relative to teams with the same power unit. Across power units, drag-to-power ratio. Absolute drag only as a wide interval |
| Deployment (S4) | Drag | As above | Where each team deploys, harvests and clips, per straight. Total energy as an interval |
| Fuel effect (S5) | Track evolution | Nothing in the data: both follow race lap for every car | Fixed from physics, labelled a model estimate. What's left of the race-lap trend is track evolution |
| Tyre degradation (S6) | Fuel and evolution within a stint, where tyre age and race lap rise together | Pit stops reset tyre age while race lap keeps rising; cars on the same compound at different points of the race | Performance loss per compound per team, net of the physics fuel effect. Thermal and wear are not separated (no temperatures), so it is one curve |

**Power-unit families in 2026.** Mercedes: Mercedes, McLaren, Williams, Alpine. Ferrari: Ferrari, Haas, Cadillac. Red
Bull Ford: Red Bull Racing, Racing Bulls. Honda: Aston Martin. Audi: Audi. Customers receive the same power-unit
specification, so within a family the ICE power is taken as equal and relative drag becomes measurable. Fuel
suppliers can differ within a family, so that is an assumption, carried as an interval. Across families, drag and
engine power can't be told apart from speed traces.

**Evidence at Barcelona.**

- Full-throttle acceleration on the back straight falls from 7.4 to 2.3 m/s² between 250 and 295 km/h, below the
  290 km/h MGU-K taper. That is deployment management, so drag can't be fitted on a straight alone (S3 finding).
- Coasting phases don't isolate drag either. Before Turn 1 Hamilton coasts 63 m (0.72 s) with no throttle and no
  brake, losing 322 → 299 km/h: about 0.9 g, where drag alone would give about 0.5 g at a drag area of 1.0 m²
  (estimate). The rest is most likely the MGU-K harvesting. Leclerc coasts 35 m, Verstappen 18 m; Russell, Norris
  and Albon go straight from throttle to brake (median of 15 green laps each).
- Fuel against tyre wear (estimate). The lap sim's mass sensitivity is 0.028 s per kg (+1% mass costs 0.22 s on the
  fitted car). Burn per lap is 0.6–0.9 kg, from full-throttle time (35% of a green lap) and throttle-weighted time
  against the 3,000 MJ/h fuel-energy cap. So fuel is worth 0.016–0.026 s a lap, against a raw within-stint Hard
  slope of +0.066 s a lap: 25–40% of the raw slope, which is why it's fixed from physics rather than fitted.
- More circuits widen the spread of corner speeds, which helps separate tyre grip from downforce, but only under an
  assumption: teams change wing level from circuit to circuit, so downforce isn't constant across circuits. The
  split across circuits holds mechanical grip per team fixed within an upgrade window and lets downforce vary per
  circuit. The bench has to show that this recovers known values before it's used.

## 2. The quasi-steady point-mass sim

It ignores load transfer, yaw inertia, the differential, and aero sensitivity to pitch, roll and ride height,
including the switch between straight and corner mode.

**Evidence at Barcelona.** The fitted field car misses corner minimum speeds by 12 km/h rms, too fast where
transients and commitment matter most (the second half of sequences, Turn 2 +18 and Turn 8 +17; the blind Turn 9
+15). Straight-line braking plateaus at about 3.5 g above 250 km/h, consistent with the wings still closing from
straight mode.

**How it's handled.**

- Team comparisons are relative to the field at the same corner, so the sim's bias at a corner, which every car
  shares, cancels. A team-specific weakness, such as instability on brake release, doesn't cancel: it shows up as
  lower effective grip where it bites. So S3 reports effective cornering grip and says so.
- Corner phases. Each corner is split into entry (brake release to turn-in), apex (minimum speed) and exit
  (traction), from the corrected-distance traces already on the site. A car unstable on brake release loses on
  entry with a normal apex speed; a traction-limited car loses on exit.
- Model upgrades, each kept only if it measurably reduces the misfit: a g-g-v envelope from a quasi-steady
  two-track model (load transfer and aero balance) in place of the friction circle; the straight-to-corner mode
  change as a ramp fitted to the braking plateau, for the whole field; and a transient audit that drives
  engine-map-pinn's dynamic bicycle model with Pacejka tyres through Barcelona's corner types to measure the
  point mass's bias per corner type.
- Out of reach from this feed: kerb strikes, differential behaviour, detailed yaw dynamics. These stay inside the
  effective parameters and the learned correction (S12) and are never claimed as measured.

## 3. On/off brake signal (S7)

In racing laps the brake channel is 0 or 100. The value 104 appears in throttle and brake together at 0 km/h
(10% of all samples, mostly the four retired cars): a "car stopped" marker, treated as missing.

**How it's handled.**

- The brake flag only marks phases. No quantity is read from it.
- Braking energy per zone comes from an energy balance on robust endpoint speeds: ½m(v_in² − v_min²) minus drag,
  rolling resistance and grade. Nothing is differentiated from 4 Hz speed. The zone starts at the throttle lift,
  not at the brake flag, because 2026 cars coast and harvest before braking.
- Where a deceleration profile is needed, it comes from a model-based smoother (the S5 state estimator), checked on
  the bench at feed-like sampling.
- The split between friction brakes and MGU-K is bounded, not estimated. Turn 1, Hamilton's lap 44: 285 → 140 km/h
  in 132 m and 2.5 s, 1.9 MJ of kinetic energy. Drag takes 0.25–0.36 MJ (drag area 0.9–1.3 m²), leaving 1.5–1.6 MJ
  for brakes and MGU-K. The friction brakes take 0.6–1.6 MJ depending on whether the MGU-K absorbs 350 kW or
  nothing. The MGU-K share is the dominant unknown, not the brake signal. Friction energy is reported as that range,
  narrowed by S4's harvest estimate and the per-lap harvest cap.
- No absolute disc temperatures: brake cooling differs per team and circuit and isn't observable. Instead a brake
  load index (friction energy per zone, and the cooling time to the next zone), ranked against Brembo's published
  hardest corners and per-circuit difficulty.

## 4. Scope

S8 (CFD on a generic wing) and S11 (steering angle from onboard video) don't identify any team's parameters. A
team's downforce comes from the whole car, floor, wings and bodywork working together, so a generic wing can't
bound it. Both leave the
debrief roadmap and become side projects with no dependency either way. S8 comes back only if it measurably
narrows an interval on the bench. The debrief's critical path is S1–S7, then S9 (strategy, with apex-forecast's race
model), S10 and S12.

## The identifiability bench (built)

`parc-ferme bench` runs every reported quantity on synthetic races with the confounders switched on and checks how
often its stated 95% interval holds the true value, and how the errors compare with the stated uncertainty (1 is
honest). It passes at 90% coverage and 1.25 or less. The results go to `src/parc_ferme/bench/coverage.json`, stamped
with the commit they were measured on, and Model health shows them with what each session resolves. A short run is
in the tests.

**Grip (S3).** A synthetic 13-corner circuit whose downforce share at the limit spans 0.14–0.54, as Barcelona's
lifted corners do; 11 teams of two drivers; each driver's line differs by 1.5% in radius at every corner and 0.8%
from lap to lap, commitment by 0.7%; compounds, tyre wear that differs by team (25%), fuel from 70 kg, track
evolution, 6% of downforce lost within 1 s of the car ahead, and ~4 Hz samples with dropouts.

- Found: dirty air made fast-corner intervals too narrow (85% coverage), because teams that spend more laps in
  traffic read as having less downforce. Fixed with a shared dirty-air term that scales with the corner's downforce
  share. Real numbers barely moved (Ferrari fast corners 3.8 → 3.9%).
- Found: leave-one-corner-out can't see the estimator's own error (linearising the corner equation, minima from
  ~4 Hz samples), about 0.2 points, so on clean laps intervals were 1.6–3.7 times too narrow. That error, measured
  on clean synthetic laps, is now added in quadrature.
- Now: tyre grip, downforce, slow- and fast-corner grip all calibrated with every confounder on (errors 1.03–1.13
  times the stated uncertainty, 93% coverage) and on clean laps (0.83–0.97, 95–98%).
- Limit: if drivers took exactly the same line every time, corner-grip intervals would be about 1.3 times too
  narrow. Barcelona's own uncertainties (0.6–0.7 points) match the realistic bench (0.5–0.6), not that case
  (0.15–0.2).

**Race pace.** A 20-car field as close at the front as Barcelona's, with tyre wear that differs by car (30%) and an
offset that holds for a whole stint (0.07 s per sector), both measured at Barcelona: a wear slope per car improves
the fit decisively (F = 4.0, p = 9e-9, about 30% from car to car), and stint averages vary twice as much as
lap-to-lap noise explains.

- Found: the bootstrap over laps treated laps as independent, and every car was given the same wear rate. Intervals
  were 2.7–3.7 times too narrow; a 95% interval on a lap gap held the truth 28% of the time.
- Fixed: a wear slope per car, with gaps reported at the race's median tyre age on the reference compound (on new
  tyres they would be an extrapolation); generalised least squares with a random offset per stint, its variance by
  restricted maximum likelihood (estimated from residuals it came out far too small, because each car's own terms
  absorb most of what its two or three stints differ by); and the winner's curse taken off by parametric bootstrap,
  since gaps are measured from the car that looks fastest, which usually got lucky.
- Found, last: with those fixes lap gaps still read 0.45 standard errors too large. Measured from a fixed car the
  average error was zero but rose with the wear difference: one extra wear slope per car, shared across compounds,
  overstated a hard-wearing car's extra wear on the Hard the gaps are read on, and picking the fastest-looking car
  as reference turned that into a bias. A car hard on its tyres is now hard on every compound in proportion, fitted
  linearly in two stages from the compounds' relative steepness (Barcelona: Hard 0.81, Medium 1.00, Soft 1.20).
- Now: lap and sector gaps calibrated (errors 1.03–1.05 times the stated uncertainty, 93–95% coverage over 40
  races of 20 cars).
- Barcelona changed: Russell +0.03 ± 0.17 s a lap to Hamilton (was +0.16 ± 0.07), Antonelli +0.16, Norris +0.21,
  Verstappen +0.40, Leclerc +0.50, all ± 0.17 s, at a tyre age of 9 laps on the Hard. The stint offset is about
  0.19 s a lap and the winner's curse 81 ms. Hamilton and Russell had race pace the data can't tell apart.

## Order

1. Identifiability bench: built, as above, for S3 and race pace. Every new model joins it before it goes on the page.
2. S4: deployment and drag fitted together, reported as above.
3. S5 and S6: fuel from physics, degradation net of it, and corner phases.
4. S7: braking energy by energy balance, the friction share as a range, the brake load index.

### S4 straight-line diagnostic

`parc-ferme energy 11307 --fuel 20` writes `reports/11307/energy_windows.csv` for each
driver's fastest green lap. Each row gives two coefficients. For an assumed effective drag
area CdA in m², mean wheel power in kW is `base_kw + drag_kw_per_m2 × CdA`.
The intercept accounts for the change in kinetic and gravitational potential energy and
rolling loss. The slope integrates aerodynamic power at the session's air density in still
air. Fuel mass is an input shared across these laps. Wind, a tow and the actual wing state
can change the interpretation of the drag term.

Windows span at least 1.5 s inside a configured straight-mode zone, at continuous full
throttle or coast with the brake off. A pedal change, zone change or sample gap over
0.55 s breaks a window. The 213 Barcelona windows were all at full throttle. Short lifts
and coasting outside these zones therefore contribute no harvest measurement here.
The CSV is a diagnostic for the joint fit. Its coefficients do not identify combustion
power, electric power or battery charge individually. Synthetic forward-dynamics tests
check reconstruction at known drag. The multi-lap fit uses the same window balance.

### Joint drag and deployment fit

`parc-ferme energy 11307 --fit` takes all full-throttle green-lap windows from the four
configured zones. One effective straight-mode CdA is shared across each car's training
laps. Each window has its own signed electric shaft power. The model assumes 400 kW of
combustion power, 95% driveline efficiency, 20 kg of fuel by default, a 350 kW harvest
limit and the speed-dependent deployment cap in the rules file. A 50 kW wheel-work
allowance and a 15% aero-work allowance represent sensitivity to fuel, shifts, wind,
traffic and the engine map. These allowances are modelling choices.

For each candidate CdA, the work balance determines the required signed electric power.
The electric limits bound the candidate area in each window. Take the tightest bounds
within a lap and trim the outer 5% of lap limits on each side. An empty range fails
the fit. The midpoint gives one admissible trade-off for prediction. The per-zone
quantity is time-weighted mean signed shaft kW over observed full-throttle training
windows. The battery balance constrains those windows using the rest of the lap.

### Full-lap battery balance

The ledger covers the timing line to the timing line. At each segment the store gains
85% of harvested shaft work or spends deployed shaft work (unit discharge efficiency).
Charge stays within the configured 4 MJ window and recovered energy within the configured
8.5 MJ per lap. Both are model inputs from the project's rules file. The independent-lap control has free start and end charges on every lap. The linked fit has
free endpoints only at the ends of a consecutive sequence. Inside it, the end charge of
one lap is the start charge of the next. The recovery budget resets at every timing line.

The signed work balance admits harvesting at full throttle. At a lift with both pedals
off, or during braking, the available kinetic and elevation loss bounds recovery. The
lower bound is zero because engine and friction braking are unobserved. Elsewhere on
throttle, the maximum assumed combustion power and the measured work give a lower bound
on electric power. A missing sample span or pedal transition can exchange energy within
the machine's power limits. Its full duration stays in the ledger.

A backward pass finds feasible charge ranges. A forward pass returns a minimum-harvest
trajectory. A candidate drag must admit a trajectory on at least 95% of the car's training
laps. Within the surviving drag range a linear programme bounds zone-average signed power
when a proposed extreme violates the battery balance. Allowing different windows to use
different points within that drag range makes these outer bounds conservative.
Separate optimisations at the representative CdA give upper limits on recovery in each
phase. These limits can correspond to different trajectories.

In the original independent-lap study at `bf8c778`, on Hamilton's lap 44 (80.122 s), the upper limits at the representative CdA were **1.09 MJ**
during the measured full-throttle straight windows, **0.45 MJ** during 2.12 s of lift-and-coast,
and **3.53 MJ** under braking. These are store-side model limits. The public feed does
not measure how Hamilton divided recovery between those phases.

`parc-ferme bench --energy-only` calibrates the intervals from 160 independent simulated
cars with hidden strategies (clipping, early taper, full-throttle harvest or partial
deployment). Each drives 8–45 synthetic laps with a hidden store carried through four
successive straights, lifts, braking zones and exits and across the timing line into the next lap. The generator clips its policy
at an empty or full store and at the recovery cap. Combustion power,
fuel burn, wind, tow, shifts, lift points and deployment vary. The estimator sees sampled,
rounded speeds with timing jitter and dropouts. Scoring uses the true shaft work over
the exact time windows accepted by the estimator. For each quantity the interval scales
by the largest finite-sample 95% calibration quantile across the four strategies. For
deployment the calibration score is the worst of the car's four zone errors.

A disjoint 300-car audit includes 60 cars that switch strategy between straights and laps.
The independent and linked fits each covered drag on **287/300** cars (95.7%) and all
four deployment zones on **293/300** cars (97.7%). Each has its own calibration on the
same cars. The truth for zone power is evaluated only over the windows used for the fit.
Per-strategy coverage, interval widths and signed errors are in
`src/parc_ferme/bench/energy_coverage.json`.

### Linked-lap test at Barcelona

Laps **7–9, 22–24, 37–39 and 52–54** were reserved for every car before fitting the
reference geometry, drag or deployment. A driver’s training sequence breaks at a missing
lap, a non-green lap (including pit-in and pit-out) or a held-out block. Within a
sequence the solver enforces the 4 MJ store continuously and the 8.5 MJ recovery cap
separately on each lap. A sequence counts as feasible only if every lap admits the same
trajectory; the drag fit requires feasible sequences covering at least 95% of the
training laps. The known-answer test includes three laps whose upper drag endpoint
would exhaust the store despite being feasible on each isolated lap.

21 cars supplied 839 training car-laps. All 143 sequences admitted a feasible trajectory
at their car’s representative drag, across **696 timing-line crossings**, with up to 12
laps in one sequence. Stroll had fewer than five training laps.

| Median calibrated 95% interval width | Independent laps | Linked laps | Intervals narrowed |
| --- | ---: | ---: | ---: |
| Effective drag area | 0.532 m² | 0.532 m² | 0/21 |
| Zone-average signed electric power | 229.0 kW | 229.0 kW | 0/84 |

All drag intervals share an overlap. In 77 of 84 driver-zone intervals, both harvest and
deployment remain plausible. Raw widths also agreed to numerical precision. Compare the
two columns on this split: the earlier individual-lap holdout at `bf8c778` used a different
training sample and calibration.

| Held-out exit-speed check | Linked fit MAE | Local speed-gain MAE |
| --- | ---: | ---: |
| 1,928 window endpoints across 210 car-laps | 1.97 km/h | 2.05 km/h |
| 588 uninterrupted runs of two or more windows | 3.16 km/h | 3.37 km/h |

The independent-lap model also scored 1.97 km/h on the same endpoints. The prediction
starts from measured speed at entry and uses the observed full-throttle duration. The
speed test holds out blocks of laps; its prediction horizon is the straight-line window
or uninterrupted run.

Model health shows median 95% widths, the number narrowed, blind coverage and held-out
speed error. `parc-ferme energy 11307 --fit` writes the matched intervals, held-out
endpoints and rollouts to `reports/11307/`. In `energy_linked_balance.csv`, each row
records the sequence, start and end charge, and recovered and spent energy for **one
feasible history**. `energy_lap_balance.csv` retains the independent-lap phase limits at
the representative drag. The fit, split and exclusions are in `energy_fit.json`.
