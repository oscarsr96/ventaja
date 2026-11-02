"""Advantage curve of a possession: the ball handler's best option, frame by frame.

Layer 1 values one shot against its best viable pass at a single decision frame. The curve
repeats that valuation every ``CURVE_STEP_FRAMES`` frames from the frontcourt entry to the
release, for whoever holds the ball, and the summary reads how long the advantage lasted and
whether the shot came while it was there.
"""

from typing import Any, Literal

import polars as pl

from ventaja.config import FPS
from ventaja.decision.align import Aligner
from ventaja.decision.cost import classify_alternative, viability
from ventaja.decision.handler import BallHandler
from ventaja.errors import VentajaError
from ventaja.model.decision import CurveSummary
from ventaja.model.snapshot import Snapshot
from ventaja.value.features import option_rows
from ventaja.value.model import ValueModel
from ventaja.value.params import ADVANTAGE_TOLERANCE, CURVE_MIN_ROWS, CURVE_STEP_FRAMES
from ventaja.value.priors import Priors

__all__ = ["CURVE_SCHEMA", "headline", "possession_curve", "summarize_curve"]

CURVE_SCHEMA: dict[str, Any] = {
    "shot_id": pl.String,
    "game_id": pl.Int64,
    "frame_idx": pl.Int64,
    "t_to_release": pl.Float64,  # s, <= 0
    "handler_id": pl.Int64,
    "shot_clock": pl.Float64,
    "handler_shot_value": pl.Float64,  # the handler's hypothetical shot from where he stands
    "best_value": pl.Float64,  # max adjusted value of the five options
    "best_player_id": pl.Int64,
    "best_option_type": pl.String,  # "shot" | "pass"
    "best_alt_type": pl.String,  # null when the best option is the shot
    "n_viable": pl.Int64,  # passes with viability > 0
}


def _frame_row(
    snapshot: Snapshot, handler_id: int, priors: Priors, model: ValueModel
) -> dict[str, Any]:
    """Best option of the handler in one snapshot; raises VentajaError if he is off court."""
    rows = option_rows(snapshot, handler_id, priors)
    probas = model.predict_proba(rows).to_list()
    best: tuple[float, dict[str, Any]] | None = None
    shot_value = 0.0
    n_viable = 0
    for row, proba in zip(rows.iter_rows(named=True), probas, strict=True):
        value = float(proba) * row["points"]
        if row["option_type"] == "shot":
            shot_value = adjusted = value
        else:
            via = viability(row["pass_distance"], row["lane_blocked"], snapshot.shot_clock)
            n_viable += via > 0
            adjusted = value * via
        if best is None or adjusted > best[0]:  # ties keep the earlier row (the shot first)
            best = (adjusted, row)
    assert best is not None  # option_rows always yields the shot row
    best_value, best_row = best
    is_shot = best_row["option_type"] == "shot"
    return {
        "handler_id": handler_id,
        "shot_clock": snapshot.shot_clock,
        "handler_shot_value": shot_value,
        "best_value": best_value,
        "best_player_id": best_row["option_player_id"],
        "best_option_type": best_row["option_type"],
        "best_alt_type": None if is_shot else classify_alternative(best_row),
        "n_viable": n_viable,
    }


def possession_curve(
    aligner: Aligner, shot_id: str, priors: Priors, model: ValueModel
) -> pl.DataFrame | None:
    """One row per sampled frame of the shot's chance, from frontcourt entry to release.

    The span runs from the chance's ``frontcourt_frame`` (its ``start_frame`` when null) to
    the shot's release, inclusive. Frames ``release - k * CURVE_STEP_FRAMES`` are sampled, so
    the release is always on the curve; a sampled frame is absent when it has no tracking,
    the ball is in flight (no handler) or the handler is not on court. Columns follow
    ``CURVE_SCHEMA``. Returns None when the shot's decision frame is excluded.
    """
    if aligner.decision_frame(shot_id).rule == "excluded":
        return None
    shot = aligner.shot(shot_id)
    chance = aligner.chance_of_shot(shot_id)
    release = int(shot["start_frame"])
    front = chance["frontcourt_frame"]
    span_start = int(front if front is not None else chance["start_frame"])
    handler = BallHandler(aligner.touches_of(shot["possession_id"]))
    snapshots = {s.frame_idx: s for s in aligner.window(span_start, release)}
    rows: list[dict[str, Any]] = []
    for frame_idx in range(release, span_start - 1, -CURVE_STEP_FRAMES):
        snapshot = snapshots.get(frame_idx)
        handler_id = handler.handler_at(frame_idx)
        if snapshot is None or handler_id is None:
            continue
        try:
            row = _frame_row(snapshot, handler_id, priors, model)
        except VentajaError:  # handler not tracked in this frame
            continue
        rows.append(
            {
                "shot_id": shot_id,
                "game_id": aligner.game_id,
                "frame_idx": frame_idx,
                "t_to_release": (frame_idx - release) / FPS,
                **row,
            }
        )
    return pl.DataFrame(rows[::-1], schema=CURVE_SCHEMA)


def summarize_curve(
    curve: pl.DataFrame, *, shot_id: str, game_id: int, decision_frame: int, shot_value: float
) -> CurveSummary:
    """Advantage window of a curve (sorted by ``frame_idx``) against the decision frame."""
    frames = [int(f) for f in curve["frame_idx"]]
    values = [float(v) for v in curve["best_value"]]
    base: dict[str, Any] = {
        "shot_id": shot_id,
        "game_id": game_id,
        "n_rows": len(frames),
        "span_start": frames[0] if frames else None,
        "span_end": frames[-1] if frames else None,
        "shot_value": shot_value,
    }
    if len(frames) < CURVE_MIN_ROWS:
        return CurveSummary(
            **base,
            peak_frame=None,
            peak_value=None,
            window_start=None,
            window_end=None,
            advantage_seconds=0.0,
            release_lag_seconds=None,
            value_at_decision=None,
            verdict="no_window",
        )
    peak = values.index(max(values))  # first maximum: ties take the earliest row
    floor = values[peak] - ADVANTAGE_TOLERANCE
    lo = hi = peak
    while lo > 0 and values[lo - 1] >= floor:
        lo -= 1
    while hi < len(values) - 1 and values[hi + 1] >= floor:
        hi += 1
    start, end = frames[lo], frames[hi]
    lag = 0.0
    verdict: Literal["on_time", "late", "early"] = "on_time"
    if decision_frame > end:
        lag, verdict = (decision_frame - end) / FPS, "late"
    elif decision_frame < start:
        lag, verdict = (decision_frame - start) / FPS, "early"
    closest = min(range(len(frames)), key=lambda i: abs(frames[i] - decision_frame))
    return CurveSummary(
        **base,
        peak_frame=frames[peak],
        peak_value=values[peak],
        window_start=start,
        window_end=end,
        advantage_seconds=(end - start + CURVE_STEP_FRAMES) / FPS,
        release_lag_seconds=lag,
        value_at_decision=values[closest],
        verdict=verdict,
    )


_HEADLINES = {
    "es": {
        "on_time": "La ventaja duró {a:.1f} s y el tiro llegó a tiempo",
        "late": "La ventaja duró {a:.1f} s; el tiro llegó {lag:.1f} s tarde",
        "early": "El tiro salió {early:.1f} s antes del pico de ventaja",
        "no_window": "Sin curva suficiente ({n} frames)",
    },
    "en": {
        "on_time": "The advantage lasted {a:.1f} s and the shot came on time",
        "late": "The advantage lasted {a:.1f} s; the shot came {lag:.1f} s late",
        "early": "The shot went up {early:.1f} s before the peak of advantage",
        "no_window": "Not enough curve ({n} frames)",
    },
}


def headline(summary: CurveSummary, lang: Literal["es", "en"] = "es") -> str:
    """One-sentence reading of a curve summary, in Spanish or English."""
    lag = summary.release_lag_seconds or 0.0
    return _HEADLINES[lang][summary.verdict].format(
        a=summary.advantage_seconds, lag=lag, early=-lag, n=summary.n_rows
    )
