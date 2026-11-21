"""The debrief's summary: three findings in plain sentences, generated from the numbers.

A finding only claims a difference the uncertainty supports: a gap smaller than twice its standard error is
reported as level, and teams the uncertainty can't separate are named as a group.
"""

import numpy as np

TEAM_SHORT = {"Haas F1 Team": "Haas"}
SIGNIFICANT = 2.0


def team(name: str) -> str:
    return TEAM_SHORT.get(name, name)


def possessive(name: str) -> str:
    return name + "'s"


def join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def car(row: dict, cars: dict) -> str:
    return f"{possessive(cars[row['driver']]['last'])} {team(row['team'])}"


def corners_text(sector: dict) -> str:
    c = sector["corners"]
    return f"Turn {c[0]}" if len(c) == 1 else f"Turns {c[0]}–{c[-1]}"


def pace_finding(d: dict) -> str:
    rows, cars = d["pace"]["cars"], d["cars"]
    ref, second = rows[0], rows[1]
    if second["lap"] < SIGNIFICANT * second["lap_se"]:
        return (f"{car(ref, cars)} and {car(second, cars)} had the same race pace within the uncertainty "
                f"({second['lap']:.2f} ± {second['lap_se']:.2f} s a lap), with tyre compound and age, fuel burn and "
                f"traffic taken out.")
    rest = [f"{car(r, cars)} {r['lap']:.2f} s" for r in rows[2:4]]
    return (f"{car(ref, cars)} had the fastest race pace. With tyre compound and age, fuel burn and traffic taken out, "
            f"{car(second, cars)} was {second['lap']:.2f} ± {second['lap_se']:.2f} s a lap slower"
            + (f", {join(rest)}." if rest else "."))


def sector_finding(d: dict) -> str:
    """Where the fastest car's lead over the best car of another team came from."""
    rows, cars, sectors = d["pace"]["cars"], d["cars"], d["sectors"]
    ref = rows[0]
    rival = next(r for r in rows[1:] if r["team"] != ref["team"])
    gained, lost = [], []
    for k, sec in enumerate(sectors, start=1):
        delta, se = rival[f"s{k}"], rival[f"s{k}_se"]
        if abs(delta) >= SIGNIFICANT * se:
            (gained if delta < 0 else lost).append((abs(delta), k, sec))
    who, against = car(rival, cars), car(ref, cars)
    if not lost:
        return f"{who} was not measurably slower than {against} in any sector."
    worst = max(lost)
    lost_text = f"lost {worst[0]:.2f} s a lap in sector {worst[1]} ({corners_text(worst[2])})"
    if gained:
        best = max(gained)
        return (f"{who} was quicker than {against} through sector {best[1]} ({corners_text(best[2])}, by "
                f"{best[0]:.2f} s a lap) but {lost_text}.")
    share = worst[0] / rival["lap"] if rival["lap"] > 0 else np.nan
    return f"{who} {lost_text}, {share:.0%} of its deficit to {against}."


def leading_group(rows: list[dict], key: str, lowest: bool = False) -> list[dict]:
    """The rows the uncertainty can't separate from the highest one (or the lowest)."""
    ordered = sorted(rows, key=lambda r: r[key], reverse=not lowest)
    top = ordered[0]
    se = key.replace("pct", "se")
    return [r for r in ordered
            if abs(top[key] - r[key]) < SIGNIFICANT * np.hypot(top[se], r[se])]


def span(group: list[dict], key: str) -> str:
    v = sorted(abs(r[key]) for r in group)
    return f"{v[0]:.1f}%" if len(v) == 1 or round(v[0], 1) == round(v[-1], 1) else f"{v[0]:.1f}–{v[-1]:.1f}%"


def grip_finding(d: dict) -> str:
    rows = d["grip"]["teams"]
    fast_top = leading_group(rows, "fast_corner_pct")
    fast_low = leading_group(rows, "fast_corner_pct", lowest=True)
    slow_top = leading_group(rows, "slow_corner_pct")
    names = [team(r["team"]) for r in fast_top]
    text = (f"{join(names)} had the most grip in fast corners, {span(fast_top, 'fast_corner_pct')} above the mean "
            f"team; {join([team(r['team']) for r in fast_low])} had the least, "
            f"{span(fast_low, 'fast_corner_pct')} below.")
    if {r["team"] for r in slow_top} != {r["team"] for r in fast_top}:
        text += (f" In slow corners {join([team(r['team']) for r in slow_top])} "
                 f"{'was' if len(slow_top) == 1 else 'were'} ahead, {span(slow_top, 'slow_corner_pct')} above.")
    return text


def findings(d: dict) -> list[dict]:
    return [{"text": pace_finding(d), "href": "#pace"},
            {"text": sector_finding(d), "href": "#pace"},
            {"text": grip_finding(d), "href": "#grip"}]
