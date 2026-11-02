"""Possession clip (court on top, advantage curve below) and the standalone curve figure.

The court panel is the layer-1 animator's (``viz/animate.py``); the curve panel draws a
shot's advantage curve (ADR-0006) once and moves a marker along it with the clip. pyplot is
imported lazily (``Agg`` backend) so importing this module has no side effects.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from ventaja.config import FPS
from ventaja.decision.align import Aligner
from ventaja.decision.curve import advantage_runs, headline
from ventaja.errors import DataNotFoundError
from ventaja.model.decision import CurveSummary, Decision
from ventaja.model.snapshot import Snapshot
from ventaja.value.params import CLIP_AFTER_S, CLIP_BEFORE_S, CURVE_STEP_FRAMES
from ventaja.viz.animate import (
    add_value_colorbar,
    clip_frames,
    decision_title,
    draw_frame,
    write_gif,
)
from ventaja.viz.court import draw_half_court

__all__ = ["curve_figure", "curve_of_shot", "plot_curve", "render_clip"]

Y_RANGE = (0.0, 2.0)  # expected points, fixed so that curves of different shots compare
CLIP_FIGSIZE = (6.0, 8.8)  # court 6 x 6.4 on top, curve 6 x 2.2 below
FIGURE_FIGSIZE = (7.0, 3.0)
FIGURE_DPI = 150
_WINDOW_VERDICTS = ("late", "during")
_HALF_STEP = CURVE_STEP_FRAMES / 2  # spans cover each sampled row's interval: width = duration


def curve_of_shot(
    shot_id: str, curves: pl.DataFrame, summaries: pl.DataFrame
) -> tuple[pl.DataFrame, CurveSummary]:
    """A shot's curve (sorted by frame) and its summary, from the curve artifact tables.

    Raises DataNotFoundError if the shot has no summary (excluded shots have no curve).
    """
    hit = summaries.filter(pl.col("shot_id") == shot_id)
    if hit.height == 0:
        raise DataNotFoundError(
            f"shot {shot_id} not found in the curve summaries (excluded shots have no curve)"
        )
    row = hit.row(0, named=True)
    summary = CurveSummary(**{f: row[f] for f in CurveSummary.model_fields})
    return curves.filter(pl.col("shot_id") == shot_id).sort("frame_idx"), summary


def _release(curve: pl.DataFrame) -> int | None:
    """Release frame of a curve, from any of its rows (``t_to_release`` is in seconds)."""
    if curve.height == 0:
        return None
    return int(curve["frame_idx"][0]) - round(float(curve["t_to_release"][0]) * FPS)


def _broken(curve: pl.DataFrame, column: str) -> tuple[np.ndarray, np.ndarray]:
    """``(t, y)`` with a NaN inserted wherever sampled frames are missing (a line gap)."""
    t = curve["t_to_release"].to_numpy().astype(float)
    y = curve[column].to_numpy().astype(float)  # nulls become NaN: gaps too
    gaps = np.flatnonzero(np.diff(curve["frame_idx"].to_numpy()) > CURVE_STEP_FRAMES) + 1
    return np.insert(t, gaps, np.nan), np.insert(y, gaps, np.nan)


def _marker_xy(curve: pl.DataFrame, frame: int) -> tuple[float, float] | None:
    """Point of the ``best_value`` line at ``frame`` (interpolated, clamped at the ends)."""
    release = _release(curve)
    if release is None:
        return None
    t = (frame - release) / FPS
    xs = curve["t_to_release"].to_numpy().astype(float)
    ys = curve["best_value"].to_numpy().astype(float)
    return t, float(np.interp(t, xs, ys))


def _shade_other_runs(
    ax: Any, curve: pl.DataFrame, summary: CurveSummary, decision_frame: int, release: int
) -> None:
    """Shade in light grey the advantage runs that are not the summary's window.

    A run is shaded when its handler differs from the window's (without a window: from the
    handler at the row closest to the decision frame) or when it ends before the window.
    """
    if summary.window_handler_id is not None:
        ref = summary.window_handler_id
    else:
        frames = curve["frame_idx"].to_list()
        closest = min(range(len(frames)), key=lambda i: abs(frames[i] - decision_frame))
        ref = int(curve["handler_id"][closest])
    label: str | None = "advantage (other handler)"
    for start, end, handler in advantage_runs(curve, summary.shot_value):
        if (start, end) == (summary.window_start, summary.window_end):
            continue
        before = summary.window_start is not None and end < summary.window_start
        if handler == ref and not before:
            continue
        ax.axvspan(
            (start - release - _HALF_STEP) / FPS,
            (end - release + _HALF_STEP) / FPS,
            color="lightgrey",
            alpha=0.6,
            lw=0,
            label=label,
        )
        label = None


def plot_curve(
    ax: Any,
    curve: pl.DataFrame,
    summary: CurveSummary,
    *,
    decision_frame: int,
    marker_frame: int | None = None,
) -> None:
    """Draw a shot's advantage curve on ``ax`` against the seconds to release.

    Lines: the best option (solid), the handler's own shot from where he stands (dotted), the
    best viable pass (dashed, gaps where none is viable or frames are missing) and the value
    of the shot taken (horizontal). The advantage window is shaded orange when the verdict is
    ``late`` or ``during``; every other advantage run that belongs to another handler (or
    ends before the window) is shaded light grey; each span covers its rows' sampled interval.
    Vertical lines mark the decision frame and the release; a marker sits on the best-option
    line at ``marker_frame`` if given. Legend upper left. No title: the caller sets it.
    """
    ax.set_ylim(*Y_RANGE)
    ax.set_xlabel("seconds to release", fontsize=8)
    ax.set_ylabel("expected points", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(alpha=0.25, lw=0.5)
    release = _release(curve)
    if release is not None:
        ax.plot(*_broken(curve, "best_value"), color="navy", lw=1.8, label="best option")
        ax.plot(
            *_broken(curve, "handler_shot_value"),
            color="grey",
            ls=":",
            lw=1.3,
            label="shot from here",
        )
        ax.plot(
            *_broken(curve, "best_pass_value"), color="seagreen", ls="--", lw=1.3, label="best pass"
        )
    ax.axhline(summary.shot_value, color="crimson", lw=1.0, label="shot taken")
    if release is not None:
        _shade_other_runs(ax, curve, summary, decision_frame, release)
    if (
        release is not None
        and summary.verdict in _WINDOW_VERDICTS
        and summary.window_start is not None
        and summary.window_end is not None
    ):
        ax.axvspan(
            (summary.window_start - release - _HALF_STEP) / FPS,
            (summary.window_end - release + _HALF_STEP) / FPS,
            color="orange",
            alpha=0.25,
            lw=0,
            label="advantage window",
        )
    if release is not None:
        ax.axvline((decision_frame - release) / FPS, color="black", ls="--", lw=1.0)
        ax.axvline(0.0, color="dimgrey", lw=1.0)
        top = Y_RANGE[1] * 0.97
        ax.text(
            (decision_frame - release) / FPS, top, "decision ", fontsize=6, ha="right", va="top"
        )
        ax.text(0.0, top, " release", fontsize=6, va="top")
        ax.set_xlim(float(curve["t_to_release"].min()) - 0.1, 0.4)  # type: ignore[arg-type]
    if marker_frame is not None and (xy := _marker_xy(curve, marker_frame)) is not None:
        ax.plot(*xy, "o", color="crimson", ms=6, zorder=10)
    ax.legend(loc="upper left", fontsize=6, ncol=3, framealpha=0.8)


def render_clip(
    aligner: Aligner,
    decision: Decision,
    curve: pl.DataFrame,
    summary: CurveSummary,
    out: Path,
    *,
    before_s: float = CLIP_BEFORE_S,
    after_s: float = CLIP_AFTER_S,
    fps: int = 12,
    labels: Mapping[int, str] | None = None,
) -> Path:
    """Animate a shot's possession with its advantage curve underneath; returns ``out``.

    The court panel is ``render_shot_gif``'s (same frames, colours and one-second hold at the
    decision frame); the curve panel is ``plot_curve``, drawn once, with a marker that follows
    the clip's frame. The title is the Spanish headline plus the decision's
    ``shot_id · rule · clock · cost`` line. Raises NoTrackingError if no frame is tracked.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frames = clip_frames(aligner, decision, before_s, after_s, fps)
    fig, (ax_court, ax_curve) = plt.subplots(
        2, 1, figsize=CLIP_FIGSIZE, gridspec_kw={"height_ratios": [6.4, 2.2]}
    )
    draw_half_court(ax_court)
    add_value_colorbar(fig, ax_court)
    plot_curve(ax_curve, curve, summary, decision_frame=decision.decision_frame)
    release = _release(curve)
    if release is not None:  # widen the x axis to every frame of the clip
        lo, hi = ax_curve.get_xlim()
        first, last = (frames[0].frame_idx - release) / FPS, (frames[-1].frame_idx - release) / FPS
        ax_curve.set_xlim(min(lo, first - 0.1), max(hi, last + 0.2))
    (marker,) = ax_curve.plot([], [], "o", color="crimson", ms=7, zorder=10)
    fig.suptitle(f"{headline(summary, 'es')}\n{decision_title(decision)}", fontsize=9)
    fig.subplots_adjust(left=0.1, right=0.97, top=0.93, bottom=0.06, hspace=0.12)

    def draw(snap: Snapshot, at_decision: bool) -> list[Any]:
        xy = _marker_xy(curve, snap.frame_idx)
        marker.set_data(*(([xy[0]], [xy[1]]) if xy is not None else ([], [])))
        return draw_frame(ax_court, snap, decision, labels or {}, at_decision=at_decision)

    return write_gif(fig, out, frames, decision.decision_frame, fps, draw)


def curve_figure(
    curve: pl.DataFrame,
    summary: CurveSummary,
    decision_frame: int,
    out: Path,
    *,
    title: str | None = None,
) -> Path:
    """Save only the curve panel as an image (150 dpi); the title defaults to the headline."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=FIGURE_FIGSIZE)
    try:
        plot_curve(ax, curve, summary, decision_frame=decision_frame)
        ax.set_title(title if title is not None else headline(summary, "es"), fontsize=9)
        fig.tight_layout()
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=FIGURE_DPI)
    finally:
        plt.close(fig)
    return out
