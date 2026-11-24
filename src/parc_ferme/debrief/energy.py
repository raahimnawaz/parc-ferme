"""S4 session report shared by the workstation and the offline fit command."""

import json

import pandas as pd

from ..bench import energy as bench_energy
from ..core.car import Car
from ..models.battery import ledger, linked_ledger
from ..models.energy import analyse, held_out
from ..models.energy_fit import evaluate, scores


def study(session, fuel_kg, version, out=None):
    calibration = bench_energy.load()
    battery_laps = {}
    rows = analyse(session, fuel_kg, multi_lap=True, battery_laps=battery_laps)
    if rows.empty:
        raise ValueError("no usable straight-line windows")
    car = Car(fuel_kg=fuel_kg, rho=rows.rho_kg_m3.iloc[0])
    baseline, base_pred, _, baseline_skipped = evaluate(rows, calibration["battery"]["scales"], car, battery_laps)
    params, pred, runs, skipped = evaluate(rows, calibration["linked"]["scales"], car, battery_laps, linked=True)
    if pred.empty:
        raise ValueError("no held-out laps with sufficient training data")
    full = rows[rows.phase == "full throttle"]
    held = full[held_out(full.lap)]
    trained = full[~held_out(full.lap) & full.driver.isin(params.driver)]
    extended = runs[runs.windows >= 2]
    report = dict(version=version, fingerprint=calibration["fingerprint"], session=session.key,
                  assumed_fuel_kg=fuel_kg, rho_kg_m3=car.rho,
                  split="Hold out laps 7–9 and every 15 laps thereafter for all cars",
                  held_laps=sorted(map(int, held.lap.unique())),
                  fitted_cars=params.driver.nunique(), train_car_laps=len(trained.drop_duplicates(["driver", "lap"])),
                  training_windows=len(trained), available_holdout_windows=len(held), scored_windows=len(pred),
                  scored_cars=pred.driver.nunique(), scored_car_laps=len(pred.drop_duplicates(["driver", "lap"])),
                  median_window_s=float((pred.end_s - pred.start_s).median()), skipped_cars=skipped,
                  window_scores=scores(pred), by_zone={z: scores(g) for z, g in pred.groupby("zone")},
                  extended_runs=len(extended), extended_scores=scores(extended) if len(extended) else None,
                  extended_median_s=float((extended.end_s-extended.start_s).median()) if len(extended) else None)
    keys = ["driver", "zone", "quantity"]
    paired = baseline.merge(params, on=keys, how="outer", suffixes=("_per_lap", "_linked"),
                            indicator=True, validate="one_to_one")
    matched = paired[paired._merge == "both"].copy()
    widths = {}
    for quantity, group in matched.groupby("quantity"):
        before = group.sim95_high_per_lap - group.sim95_low_per_lap
        after = group.sim95_high_linked - group.sim95_low_linked
        raw_before = group.high_per_lap - group.low_per_lap
        raw_after = group.high_linked - group.low_linked
        widths[quantity] = dict(pairs=len(before), per_lap_median=float(before.median()),
                                linked_median=float(after.median()), narrower=int((after < before-1e-8).sum()),
                                wider=int((after > before+1e-8).sum()),
                                raw_narrower=int((raw_after < raw_before-1e-8).sum()),
                                max_raw_reduction=float((raw_before-raw_after).max()))
    budgets = []
    linked_budgets = []
    for q in params[params.quantity == "drag_m2"].itertuples():
        parts = {lap: data for (driver, lap), data in battery_laps.items() if driver == q.driver and not held_out(lap)}
        linked_budgets.extend(dict(driver=q.driver, **row) for row in linked_ledger(parts, q.estimate, car))
        if out is not None:
            budgets.extend(dict(driver=q.driver, **row) for row in ledger(parts, q.estimate, car))
    linked_budget = pd.DataFrame(linked_budgets)
    chains = linked_budget.drop_duplicates(["driver", "first_lap"])
    report.update(chains=len(chains), linked_boundaries=len(linked_budget)-len(chains),
                  longest_chain=int((chains.last_lap-chains.first_lap+1).max()),
                  feasible_chains=int(chains.feasible.sum()), per_lap_scores=scores(base_pred),
                  bench={q: groups["all"] for q, groups in calibration["linked"]["quantities"].items()})
    report.update(interval_comparison=widths, baseline_skipped_cars=baseline_skipped,
                  unmatched_intervals=int((paired._merge != "both").sum()),
                  feasible_training_laps=int(linked_budget.feasible.sum()))
    drag = params[params.quantity == "drag_m2"]
    power = params[params.quantity == "deployment_kw"]
    report.update(drag=[dict(driver=r.driver, estimate=float(r.estimate), sim95_low=float(r.sim95_low),
                             sim95_high=float(r.sim95_high)) for r in drag.itertuples()],
                  bench_family=calibration.get("family_pairs"))
    report.update(drag_common_overlap=bool(drag.sim95_low.max() <= drag.sim95_high.min()),
                  deployment_includes_zero=int(((power.sim95_low <= 0) & (power.sim95_high >= 0)).sum()),
                  deployment_intervals=len(power),
                  audit_passed=all(g["calibrated"] for group in calibration["linked"]["quantities"].values()
                                   for g in group.values()))
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        linked_budget.to_csv(out / "energy_linked_balance.csv", index=False)
        pd.DataFrame(budgets).to_csv(out / "energy_lap_balance.csv", index=False)
        paired.to_csv(out / "energy_paired_intervals.csv", index=False)
        params.to_csv(out / "energy_intervals.csv", index=False)
        pred.to_csv(out / "energy_heldout.csv", index=False)
        runs.to_csv(out / "energy_rollouts.csv", index=False)
        (out / "energy_fit.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
