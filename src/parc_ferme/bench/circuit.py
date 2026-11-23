"""Synthetic closed circuits for the test benches: left-hand corners of chosen radius and angle joined by straights.

All corners turn the same way, so the loop is convex and never crosses itself, which matters because positions are
placed on the nearest point of the line. Two of the straights are solved so the loop closes.
"""

from dataclasses import dataclass

import numpy as np

from ..core import track as T


@dataclass(frozen=True)
class Circuit:
    track: T.Track
    apex: dict[int, float]
    spans: dict[int, tuple[float, float]]

    def corner_mask(self, margin_m: float = 10.0) -> np.ndarray:
        """[corners, points] True where a track point lies within a corner's arc, plus a margin for smoothing."""
        s = self.track.s
        rows = []
        for a, b in self.spans.values():
            lo, hi = a * self.track.length - margin_m, b * self.track.length + margin_m
            rows.append((s >= lo) & (s <= hi))
        return np.array(rows)


def _close(radii: np.ndarray, angles: np.ndarray, straights: np.ndarray, a: int, b: int) -> np.ndarray:
    """Lengths for straights a and b that close the loop, the others held."""
    h = np.r_[0.0, np.cumsum(angles)[:-1]]
    chords = radii[:, None] * np.c_[np.sin(h + angles) - np.sin(h), np.cos(h) - np.cos(h + angles)]
    u = np.c_[np.cos(h), np.sin(h)]
    rest = np.delete(np.arange(len(radii)), [a, b])
    rhs = -(chords.sum(0) + (straights[rest, None] * u[rest]).sum(0))
    out = straights.copy()
    out[[a, b]] = np.linalg.solve(np.c_[u[a], u[b]], rhs)
    return out


def closed_circuit(radii, angles_deg, seed: int = 0, straight_m=(150.0, 450.0), step: float = 1.0,
                   smooth_m: float = 10.0, tries: int = 2000) -> Circuit:
    """Corner k has radius radii[k] and turns angles_deg[k]; the angles must add up to 360. Straights are drawn
    from `straight_m` until the two solved for closure also fall inside it."""
    radii = np.asarray(radii, float)
    th = np.radians(np.asarray(angles_deg, float))
    if not np.isclose(th.sum(), 2 * np.pi):
        raise ValueError("corner angles must add up to 360 degrees")
    h = np.r_[0.0, np.cumsum(th)[:-1]]
    a = 0
    b = int(np.argmin(np.abs(((h - h[a] - np.pi / 2) + np.pi) % (2 * np.pi) - np.pi)))
    rng = np.random.default_rng(seed)
    lo, hi = straight_m
    for _ in range(tries):
        straights = _close(radii, th, rng.uniform(lo, hi, len(radii)), a, b)
        if straights.min() >= lo and straights.max() <= 2 * hi:
            break
    else:
        raise ValueError("no closing set of straights found; widen straight_m")

    x, y, heading, pts, s = 0.0, 0.0, 0.0, [], 0.0
    apex, spans = {}, {}
    for k in range(len(radii)):
        n = max(1, int(straights[k] / step))
        for _ in range(n):
            x, y = x + np.cos(heading) * straights[k] / n, y + np.sin(heading) * straights[k] / n
            pts.append((x, y))
        s += straights[k]
        arc = radii[k] * th[k]
        n = max(2, int(arc / step))
        for _ in range(n):
            heading += th[k] / n
            x, y = x + np.cos(heading) * arc / n, y + np.sin(heading) * arc / n
            pts.append((x, y))
        apex[k + 1], spans[k + 1] = s + arc / 2, (s, s + arc)
        s += arc
    p = np.array(pts[:-1])
    track = T.build("bench circuit", p[:, 0], p[:, 1], ds=2.0, smooth_m=smooth_m)
    return Circuit(track, {k: v / s for k, v in apex.items()}, {k: (u / s, v / s) for k, (u, v) in spans.items()})


# Thirteen corners whose downforce share at the limit spans about 0.15 to 0.55, like Barcelona's lifted corners.
BENCH_RADII = (34.0, 88.0, 46.0, 104.0, 28.0, 72.0, 58.0, 112.0, 40.0, 80.0, 52.0, 96.0, 64.0)
BENCH_ANGLES = (30.0, 25.0, 35.0, 20.0, 35.0, 25.0, 30.0, 20.0, 35.0, 25.0, 30.0, 20.0, 30.0)


def bench_circuit() -> Circuit:
    return closed_circuit(BENCH_RADII, BENCH_ANGLES, seed=2026)
