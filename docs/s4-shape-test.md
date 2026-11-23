# Can the shape of the speed trace resolve S4's drag?

**Answer: not at one circuit.** The shape of the speed trace pins drag to 2–5% when deployment
changes in steps, but a deployment that varies smoothly along a straight is indistinguishable
from drag, and nothing in the feed says which a team is doing. Under the bench's rule that an
interval must hold for every strategy it considers plausible, drag and deployment stay
**not resolved**. Tested 23 Nov 2026 on branch `s4-shape-bench`.

## The question

S4's window balance uses each straight window's total work. For any drag area some electric
power balances that work, so the drag interval is set by the power limits alone. On the S4
bench its calibrated 95% interval is 0.70 m² wide, as wide as the whole range the bench draws
drag from (0.55–1.25 m²): it carries almost no information beyond the prior.

Along a full-throttle run, drag and electric power have different shapes. Drag power grows
with the cube of speed. The power unit holds a level, or a fraction of the rules' deployment cap
(which tapers above 290 km/h), and may change level once, where deployment ends or harvesting
starts.

## The method

`models/drag_shape.py` fits the cumulative work balance of each run, so nothing is
differentiated from 4 Hz speed:

    kinetic + potential + rolling work + CdA × aero work = constant + work of the power profile

- **Power profile:** a level plus a fraction of the deployment cap, optionally changing to a new
  level at one point, which is searched. It is profiled out of every run by least squares.
- **Drag area:** shared by every run of a car, from the summed concentrated likelihood.
- **Gear changes:** each one gets a free step in the balance, from the gear channel the real
  feed carries.
- **Interval:** a lap-block bootstrap for noise, combined with a leave-one-straight-out
  jackknife at Student's t. A deployment pattern that differs by straight biases each straight
  differently, and the jackknife widens the interval when the straights disagree.

On exactly integrated synthetic runs it recovers drag area within 1% (`tests/test_drag_shape.py`).

## How it was tested

`python -m parc_ferme.bench.energy_shape` runs the S4 bench's own cars: the same seeds, the same
four hidden strategies plus switching cars, the same sampling, rounding, jitter, dropouts, tow,
wind, varying engine power and fuel, and the same held-out laps. Both estimators are calibrated
with the same split-conformal rule (160 calibration cars, the largest per-strategy 95% quantile)
and audited on the same 300 disjoint cars. Results are in `src/parc_ferme/bench/energy_shape.json`.

The bench's cars carry one gear change, a 0.1 s power dip near 252 km/h. The shape fit is given
the gear channel the real feed has; the window balance doesn't need it.

## Results

Median calibrated 95% width of drag area, m², and the share of audit cars whose interval held
the true value:

| Strategy | Window balance (today) | Run shape | Run shape, mass, tow and wind known |
|---|---|---|---|
| All 300 cars | **0.70**, 95.7% | **0.53**, 95.3% | 0.78, 99.0% |
| Deployment ends partway (clip) | 0.90, 96.7% | 0.30, 100% | 0.46, 100% |
| Deployment tapers off (early taper) | 0.83, 90.0% | 0.46, 100% | 0.68, 100% |
| Harvesting at full throttle | 0.51, 96.7% | 0.39, 91.7% | 0.62, 100% |
| Smoothly varying deployment (partial) | 0.92, 100% | 2.96, 85.0% | 4.96, 95.0% |
| Switches strategy between straights | 0.57, 95.0% | 0.66, 100% | 1.00, 100% |

Mean absolute error of the drag area estimate, m²:

| Strategy | Window balance | Run shape | Mass, tow and wind known |
|---|---|---|---|
| Clip | 0.29 | 0.05 | **0.02** |
| Early taper | 0.29 | 0.05 | 0.03 |
| Harvest | 0.14 | 0.08 | 0.04 |
| Partial | 0.25 | 0.39 | 0.41 |
| Switching | 0.15 | 0.07 | 0.05 |

Zone-average deployment barely moves overall (326 kW wide against 329 kW), because the engine's
own power, 370–420 kW on the bench, is unknown. For clip cars it halves (186 kW against 379 kW).

## What it shows

1. **The physics is there when deployment changes in steps.** Knowing the fuel mass (from S5),
   which runs were towed (from the gap to the car ahead) and the wind (from the weather feed)
   takes the error to 0.02–0.05 m², about 2–5%. That would separate teams.
2. **Smooth deployment changes are indistinguishable from drag.** A deployment that falls
   along a straight looks exactly like drag that rises with speed. On the bench's 'partial' cars
   the shape fit is off by 0.4 m² on average, sometimes confidently.
3. **The calibration is set by the worst case.** The feed can't tell which strategy a car runs,
   so one interval scale has to cover them all, and the 'partial' cars set it. Removing the
   other errors only makes that clearer: with mass, tow and wind known, the calibrated interval
   grows to 0.78 m², because the leftover error is almost entirely the smooth case.
4. **The shift matters.** Without the gear channel, the bench's 0.1 s shift dip reads as drag
   10% low, and the shape fit ends up wider than today's estimator. Real 2026 cars shift three or
   four times on a long straight, so any shape method needs the gear channel.
5. **A bench note.** The S4 generator integrates speed in single 50 ms Euler steps. That is fine
   for window totals, but it biases shape fits about 4%. Integrated in 2.5 ms substeps
   (`drive_sector_fine`), the shape fit gives 0.62 m² at 97.7% coverage, so the conclusion holds.

## What would change the answer

- **Evidence that teams hold deployment in steps.** If the four straights' shape estimates agree
  car by car at Barcelona, that is consistent with stepwise deployment, though the bench shows
  some smooth cars agree too. With that assumption stated, the method gives drag to roughly
  ±0.15 m² today and about ±0.05 m² with mass, tow and wind in the fit: an explicitly
  conditional estimate.
- **Comparisons within a power-unit family**, where shared deployment software might make the
  pattern common to the teams compared. Not tested.
- **Other circuits** help less than they seem, because wing levels change between circuits.

## Decision

Report S4 drag and zone deployment as **not resolved** at Barcelona. The run-shape fit is
the better estimator: 25% narrower under the same rule, and three to five times more accurate
when deployment changes in steps. But it doesn't change that label. It is kept on this branch,
with its bench, for a conditional estimate if one is wanted.
