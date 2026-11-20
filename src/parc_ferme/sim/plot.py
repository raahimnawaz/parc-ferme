from pathlib import Path

import numpy as np


def plot(result, model, path: Path, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from .compare import on_fraction

    real, fake = result.real, result.fake
    length = real.distance.iloc[-1]
    f, vr = on_fraction(real.distance.to_numpy(), real.speed.to_numpy(float))
    _, vs = on_fraction(fake.distance.to_numpy(), fake.speed.to_numpy(float))
    tr = result.lap.trace
    _, zone = on_fraction(tr.distance.to_numpy(), tr.straight_mode.to_numpy(float))
    _, soc = on_fraction(tr.distance.to_numpy(), tr.soc_mj.to_numpy())

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(12, 6.5), sharex=True, height_ratios=[3, 1])
    x = f * length
    ax.fill_between(x, 0, 360, where=zone > 0.5, color="#7339e6", alpha=0.08, lw=0, label="straight-mode zone")
    ax.plot(x, vr, color="#141820", lw=1.4, label=f"{result.summary['driver']} lap {result.summary['lap_number']} "
            f"({result.summary['real_lap_s']:.3f} s)")
    ax.plot(x, vs, color="#d4462f", lw=1.2,
            label=f"nominal 2026 car, fake telemetry ({result.summary['sim_lap_s']:.3f} s)")
    for n, fc in model.corner_fraction.items():
        ax.text(fc * length, 352, f"T{n}", ha="center", fontsize=8, color="#586273")
    ax.set_ylim(60, 360)
    ax.set_ylabel("speed [km/h]")
    ax.legend(loc="lower right", fontsize=8, frameon=False)
    ax.set_title(title, loc="left", fontsize=11)
    ax.grid(alpha=0.2)
    ax2.plot(x, soc, color="#138a47", lw=1.2)
    ax2.set_ylabel("battery [MJ]")
    ax2.set_xlabel("distance from the line [m]")
    ax2.grid(alpha=0.2)
    ax2.set_xlim(0, length)
    ax2.set_ylim(0, max(1.0, float(np.max(soc)) * 1.15))
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_lines(model, path: Path, sections: tuple[tuple[float, float], ...]) -> None:
    """Where each line sits across the track, against distance, for selected stretches of the lap."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from ..core.track import Registration

    ref = model.reference
    dist = ref.lap_distance(ref.s)
    order = np.argsort(dist)
    fig, axes = plt.subplots(len(sections), 1, figsize=(12, 2.6 * len(sections)))
    for ax, (a, b) in zip(np.atleast_1d(axes), sections, strict=True):
        w = order[(dist[order] >= a) & (dist[order] <= b)]
        ax.fill_between(dist[w], -ref.width_right[w], ref.width_left[w], color="#d3d9e2", lw=0, label="track")
        for line, colour, label in ((model.min_curvature, "#7339e6", "minimum curvature"),
                                    (model.line, "#d4462f", "minimum time")):
            s_ref, lateral = Registration.identity().project(ref, line.x, line.y)
            d = ref.lap_distance(s_ref)
            k = np.argsort(d)
            keep = (d[k] >= a) & (d[k] <= b)
            ax.plot(d[k][keep], lateral[k][keep], color=colour, lw=1.4, label=label)
        for n, fc in model.corner_fraction.items():
            x = fc * ref.length
            if a <= x <= b:
                ax.axvline(x, color="#586273", lw=0.6, ls=":")
                ax.text(x, ref.width_left[w].max() + 0.4, f"T{n}", ha="center", fontsize=8, color="#586273")
        ax.set_xlim(a, b)
        ax.set_ylabel("left of reference [m]")
        ax.grid(alpha=0.2)
    np.atleast_1d(axes)[0].legend(fontsize=8, frameon=False, loc="lower right", ncol=3)
    np.atleast_1d(axes)[-1].set_xlabel("distance from the line [m]")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
