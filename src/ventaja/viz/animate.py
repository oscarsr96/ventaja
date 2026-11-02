"""Minimal possession animator: one GIF per shot around its decision frame.

pyplot is imported lazily (``Agg`` backend) so importing this module has no side effects.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ventaja.config import FPS
from ventaja.decision.align import Aligner
from ventaja.errors import NoTrackingError
from ventaja.model.decision import Decision, Option
from ventaja.model.snapshot import Snapshot
from ventaja.viz.court import draw_half_court

__all__ = ["VALUE_RANGE", "render_shot_gif", "select_frames"]

VALUE_RANGE = (0.6, 1.5)  # fixed colour scale of the options' adjusted value (points)
FIGSIZE = (6.0, 6.4)
DPI = 100


def select_frames(snapshots: list[Snapshot], decision_frame: int, fps: int) -> list[Snapshot]:
    """Snapshots of the decision frame's possession, every ``round(25 / fps)`` frames.

    The kept frames are those at a multiple of the step from ``decision_frame``, so the
    decision frame itself is always kept when tracked. Without it, the possession of the
    snapshot nearest to ``decision_frame`` is used.
    """
    if not snapshots:
        return []
    anchor = min(snapshots, key=lambda s: abs(s.frame_idx - decision_frame))
    step = max(1, round(FPS / fps))
    return [
        s
        for s in snapshots
        if s.possession_id == anchor.possession_id and (s.frame_idx - decision_frame) % step == 0
    ]


def _title(decision: Decision) -> str:
    clock = "—" if decision.shot_clock is None else f"{decision.shot_clock:.1f}"
    return f"{decision.shot_id} · {decision.rule} · clock {clock} · cost {decision.cost:.2f}"


def _draw_frame(
    ax: Any,
    snap: Snapshot,
    decision: Decision,
    labels: Mapping[int, str],
    *,
    at_decision: bool,
) -> list[Any]:
    """Draw the moving layer of one frame and return its artists (removed afterwards)."""
    from matplotlib import colormaps
    from matplotlib.colors import Normalize

    cmap, norm = colormaps["viridis"], Normalize(*VALUE_RANGE)
    by_player: dict[int, Option] = {o.player_id: o for o in decision.options}
    artists: list[Any] = []
    off = snap.offense
    colors = [
        cmap(norm(by_player[p.player_id].adjusted_value)) if p.player_id in by_player else "grey"
        for p in off
    ]
    shooter = [p.player_id == decision.shooter_id for p in off]
    artists.append(
        ax.scatter(
            [p.x for p in off],
            [p.y for p in off],
            s=140,
            c=colors,
            edgecolors=["black" if s else "white" for s in shooter],
            linewidths=[2.5 if s else 0.8 for s in shooter],
            zorder=4,
        )
    )
    d = snap.defense
    artists.append(
        ax.scatter(
            [p.x for p in d],
            [p.y for p in d],
            s=90,
            c="lightgrey",
            edgecolors="dimgrey",
            linewidths=0.8,
            zorder=3,
        )
    )
    artists.append(
        ax.scatter(
            [snap.ball.x],
            [snap.ball.y],
            s=45,
            c="darkorange",
            edgecolors="black",
            linewidths=0.6,
            zorder=6,
        )
    )
    for p in (*off, *d):
        label = labels.get(p.player_id, str(p.player_id))
        artists.append(ax.text(p.x, p.y + 1.3, label, fontsize=6, ha="center", zorder=7))
    clock = "—" if snap.shot_clock is None else f"{snap.shot_clock:.1f}"
    status = "  DECISION" if at_decision else ""
    artists.append(
        ax.text(-46.5, -24.5, f"frame {snap.frame_idx} · clock {clock}{status}", fontsize=7)
    )
    if at_decision:
        artists.extend(_draw_options(ax, snap, decision, by_player, cmap, norm))
    return artists


def _draw_options(
    ax: Any,
    snap: Snapshot,
    decision: Decision,
    by_player: Mapping[int, Option],
    cmap: Any,
    norm: Any,
) -> list[Any]:
    """Projected receiver positions of the passes and the arrow to the best alternative."""
    artists: list[Any] = []
    positions = {p.player_id: (p.x, p.y) for p in snap.offense}
    for o in by_player.values():
        if o.option_type != "pass" or o.player_id not in positions:
            continue
        x0, y0 = positions[o.player_id]
        artists.extend(ax.plot([x0, o.x], [y0, o.y], ls=":", lw=1, color="grey", zorder=2))
        artists.append(
            ax.scatter(
                [o.x],
                [o.y],
                s=110,
                facecolors="none",
                edgecolors=[cmap(norm(o.adjusted_value))],
                linewidths=1.5,
                zorder=3,
            )
        )
    best = by_player.get(decision.best_alt_player_id) if decision.best_alt_player_id else None
    if best is not None and decision.shooter_id in positions:
        artists.append(
            ax.annotate(
                "",
                xy=(best.x, best.y),
                xytext=positions[decision.shooter_id],
                arrowprops={"arrowstyle": "->", "color": "crimson", "lw": 2},
                zorder=8,
            )
        )
    return artists


def render_shot_gif(
    aligner: Aligner,
    decision: Decision,
    out: Path,
    *,
    before_s: float = 3.0,
    after_s: float = 1.0,
    fps: int = 12,
    labels: Mapping[int, str] | None = None,
) -> Path:
    """Animate a shot from ``before_s`` before its decision frame to ``after_s`` after release.

    Attackers are coloured by the adjusted value of their option (``viridis``, fixed scale
    ``VALUE_RANGE``), defenders grey, the ball orange and the shooter has a black edge. The
    decision frame is held for one second with the projected pass targets and an arrow to the
    best alternative. ``labels`` maps player ids to the text drawn next to each player (jersey
    numbers); the player id is used otherwise. Raises NoTrackingError if no frame is tracked.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import cm, colormaps
    from matplotlib.animation import PillowWriter
    from matplotlib.colors import Normalize

    window = aligner.window(
        decision.decision_frame - round(before_s * FPS),
        decision.release_frame + round(after_s * FPS),
    )
    frames = select_frames(window, decision.decision_frame, fps)
    if not frames:
        raise NoTrackingError(f"shot {decision.shot_id}: no tracked frame to animate")
    fig, ax = plt.subplots(figsize=FIGSIZE)
    draw_half_court(ax)
    ax.set_title(_title(decision), fontsize=9)
    mappable = cm.ScalarMappable(norm=Normalize(*VALUE_RANGE), cmap=colormaps["viridis"])
    fig.colorbar(
        mappable,
        ax=ax,
        orientation="horizontal",
        fraction=0.04,
        pad=0.02,
        label="adjusted value (pts)",
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    writer = PillowWriter(fps=fps)
    try:
        with writer.saving(fig, str(out), dpi=DPI):
            for snap in frames:
                at_decision = snap.frame_idx == decision.decision_frame
                artists = _draw_frame(ax, snap, decision, labels or {}, at_decision=at_decision)
                for _ in range(fps if at_decision else 1):
                    writer.grab_frame()
                for artist in artists:
                    artist.remove()
    finally:
        plt.close(fig)
    return out
