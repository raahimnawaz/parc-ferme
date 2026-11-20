import numpy as np
import pandas as pd

from parc_ferme.laps import lap_table, neutralised_laps, reconcile_stints, within_stint_slope
from parc_ferme.openf1 import _split_gap
from parc_ferme.telemetry import lap_trace


def _race(n_laps=30, pit_lap=15):
    rows = []
    t0 = pd.Timestamp("2026-06-14T13:00:00Z")
    for drv, base in ((44, 80.0), (16, 80.5)):
        for lap in range(1, n_laps + 1):
            age = lap - 1 if lap <= pit_lap else lap - pit_lap - 1
            rows.append({"driver_number": drv, "lap_number": lap,
                         "date_start": t0 + pd.Timedelta(seconds=80 * (lap - 1)),
                         "lap_duration": base + 0.05 * age + (20.0 if lap == pit_lap else 0.0),
                         "duration_sector_1": 25.0, "duration_sector_2": 30.0,
                         "duration_sector_3": base - 55.0, "i1_speed": 300, "i2_speed": 250,
                         "st_speed": 320, "is_pit_out_lap": lap == pit_lap + 1})
    laps = pd.DataFrame(rows)
    stints = pd.DataFrame([
        {"driver_number": d, "stint_number": k, "lap_start": a, "lap_end": b,
         "compound": c, "tyre_age_at_start": 0}
        for d in (44, 16)
        for k, a, b, c in ((1, 1, pit_lap, "MEDIUM"), (2, pit_lap + 1, n_laps, "HARD"))
    ])
    pit = pd.DataFrame({"driver_number": [44, 16], "lap_number": [pit_lap, pit_lap]})
    return laps, stints, pit


def test_neutralised_laps_cover_sc_and_vsc():
    rc = pd.DataFrame({
        "date": pd.date_range("2026-06-14", periods=4, freq="min"),
        "lap_number": [5, 7, 20, 21],
        "message": ["SAFETY CAR DEPLOYED", "SAFETY CAR IN THIS LAP",
                    "VIRTUAL SAFETY CAR DEPLOYED", "VIRTUAL SAFETY CAR ENDING"],
        "flag": [None, None, None, None],
    })
    assert neutralised_laps(rc) == {5, 6, 7, 8, 20, 21}


def test_green_mask_drops_lap_one_and_pit_laps():
    laps, stints, pit = _race()
    t = lap_table(laps, stints, pit, pd.DataFrame())
    ham = t[t.driver_number == 44].set_index("lap_number")
    assert not ham.green[[1, 15, 16]].any()
    assert ham.green.drop([1, 15, 16]).all()
    assert ham.tyre_age[16] == 0 and ham.tyre_age[30] == 14


def test_within_stint_slope_recovers_known_degradation():
    laps, stints, pit = _race()
    t = lap_table(laps, stints, pit, pd.DataFrame())
    slope, se, n = within_stint_slope(t[t.green])
    assert abs(slope - 0.05) < 1e-9 and n == 2 * 27


def test_lap_trace_integrates_constant_speed():
    t0 = pd.Timestamp("2026-06-14T13:00:00Z")
    cd = pd.DataFrame({"date": t0 + pd.to_timedelta(np.arange(-1, 82, 0.27), unit="s"),
                       "speed": 216.0, "throttle": 100, "brake": 0, "n_gear": 8, "rpm": 11000})
    tr = lap_trace(cd, t0, 80.0)
    assert abs(tr.distance.iloc[-1] - 60.0 * 80.0) < 1e-6


def test_split_gap_separates_lapped_cars():
    secs, laps = _split_gap(pd.Series([1.5, "+1 LAP", None, "+2 LAPS"], dtype=object))
    assert secs.iloc[0] == 1.5 and np.isnan(secs.iloc[1])
    assert list(laps) == [0, 1, 0, 2]


def test_reconcile_stints_moves_boundary_to_pit_lap():
    laps, stints, pit = _race(pit_lap=15)
    wrong = stints.copy()
    wrong.loc[(wrong.driver_number == 44) & (wrong.stint_number == 1), "lap_end"] = 10
    wrong.loc[(wrong.driver_number == 44) & (wrong.stint_number == 2), "lap_start"] = 11
    fixed, moved = reconcile_stints(wrong, pit, laps)
    ham = fixed[fixed.driver_number == 44].sort_values("stint_number")
    assert list(ham.lap_end) == [15, 30] and list(ham.lap_start) == [1, 16]
    assert set(moved) == {44}
