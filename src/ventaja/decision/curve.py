"""Advantage curve of a possession: the ball handler's best option, frame by frame.

Layer 1 values one shot against its best viable pass at a single decision frame. The curve
repeats that valuation every ``CURVE_STEP_FRAMES`` frames from the frontcourt entry to the
release, for whoever holds the ball, and the summary reads how long the advantage lasted and
whether the shot came while it was there.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import polars as pl

from ventaja.config import FPS, Settings
from ventaja.data.build import _write_parquet_atomic
from ventaja.data.load import load_decisions
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

__all__ = [
    "CURVE_SCHEMA",
    "SUMMARY_SCHEMA",
    "CurveResult",
    "build_curves",
    "headline",
    "possession_curve",
    "summarize_curve",
]

CURVE_SCHEMA: dict[str, Any] = {
    "shot_id": pl.String,
    "game_id": pl.Int64,
    "frame_idx": pl.Int64,
    "t_to_release": pl.Float64,  # s, <= 0
    "handler_id": pl.Int64,
    "shot_clock": pl.Float64,
    "handler_shot_value": pl.Float64,  # the handler's hypothetical shot from where he stands
    "best_value": pl.Float64,  # max adjusted value of the five options
    "best_pass_value": pl.Float64,  # max adjusted value of the passes; null when none is viable
    "best_player_id": pl.Int64,
    "best_option_type": pl.String,  # "shot" | "pass"
    "best_alt_type": pl.String,  # null when the best option is the shot
    "n_viable": pl.Int64,  # passes with viability > 0
}


@dataclass(frozen=True)
class CurveResult:
    """A possession curve and how many sampled frames were skipped (handler off court)."""

    curve: pl.DataFrame
    skipped_off_court: int


def _frame_row(
    snapshot: Snapshot, handler_id: int, priors: Priors, model: ValueModel
) -> dict[str, Any]:
    """Best option of the handler in one snapshot; raises VentajaError if he is off court."""
    rows = option_rows(snapshot, handler_id, priors)
    probas = model.predict_proba(rows).to_list()
    best: tuple[float, dict[str, Any]] | None = None
    best_pass: float | None = None
    shot_value = 0.0
    n_viable = 0
    for row, proba in zip(rows.iter_rows(named=True), probas, strict=True):
        value = float(proba) * row["points"]
        if row["option_type"] == "shot":
            shot_value = adjusted = value
        else:
            via = viability(row["pass_distance"], row["lane_blocked"], snapshot.shot_clock)
            adjusted = value * via
            if via > 0:
                n_viable += 1
                best_pass = adjusted if best_pass is None else max(best_pass, adjusted)
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
        "best_pass_value": best_pass,
        "best_player_id": best_row["option_player_id"],
        "best_option_type": best_row["option_type"],
        "best_alt_type": None if is_shot else classify_alternative(best_row),
        "n_viable": n_viable,
    }


def possession_curve(
    aligner: Aligner, shot_id: str, priors: Priors, model: ValueModel
) -> CurveResult | None:
    """One row per sampled frame of the shot's chance, from frontcourt entry to release.

    The span runs from the chance's ``frontcourt_frame`` (its ``start_frame`` when null) to
    the shot's release, inclusive. Frames ``release - k * CURVE_STEP_FRAMES`` are sampled, so
    the release is always on the curve; a sampled frame is absent when it has no tracking,
    the ball is in flight (no handler) or the handler is not on court (counted in
    ``skipped_off_court``). Columns follow ``CURVE_SCHEMA``. Returns None when the shot's
    decision frame is excluded.
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
    skipped = 0
    for frame_idx in range(release, span_start - 1, -CURVE_STEP_FRAMES):
        snapshot = snapshots.get(frame_idx)
        handler_id = handler.handler_at(frame_idx)
        if snapshot is None or handler_id is None:
            continue
        try:
            row = _frame_row(snapshot, handler_id, priors, model)
        except VentajaError:  # handler not tracked in this frame
            skipped += 1
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
    return CurveResult(pl.DataFrame(rows[::-1], schema=CURVE_SCHEMA), skipped)


def _runs(flags: list[bool], handlers: list[int]) -> list[tuple[int, int]]:
    """``(first, last)`` row indices of each run of consecutive True flags of one handler."""
    runs: list[tuple[int, int]] = []
    for i, flag in enumerate(flags):
        if not flag:
            continue
        if runs and runs[-1][1] == i - 1 and handlers[i - 1] == handlers[i]:
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((i, i))
    return runs


def summarize_curve(
    curve: pl.DataFrame, *, shot_id: str, game_id: int, decision_frame: int, shot_value: float
) -> CurveSummary:
    """Advantage window of a curve (sorted by ``frame_idx``), relative to the shot taken.

    Only passes count: a row is advantage when its ``best_pass_value`` (null: no viable pass)
    reaches ``shot_value + ADVANTAGE_TOLERANCE``; the handler's own hypothetical shot never
    does. A run is a maximal sequence of consecutive advantage rows with the same
    ``handler_id`` (frames absent from the curve do not break it); the last run starting at
    or before ``decision_frame`` is kept. See ``CurveSummary`` for the verdicts.
    """
    frames = [int(f) for f in curve["frame_idx"]]
    values = [float(v) for v in curve["best_value"]]
    handlers = [int(h) for h in curve["handler_id"]]
    passes: list[float | None] = curve["best_pass_value"].to_list()
    out: dict[str, Any] = {
        "shot_id": shot_id,
        "game_id": game_id,
        "n_rows": len(frames),
        "span_start": frames[0] if frames else None,
        "span_end": frames[-1] if frames else None,
        "shot_value": shot_value,
        "peak_frame": None,
        "peak_value": None,
        "window_start": None,
        "window_end": None,
        "window_handler_id": None,
        "window_peak_value": None,
        "advantage_seconds": 0.0,
        "release_lag_seconds": None,
        "value_at_decision": None,
        "verdict": "no_window",
    }
    if len(frames) < CURVE_MIN_ROWS:
        return CurveSummary(**out)
    peak = values.index(max(values))  # first maximum: ties take the earliest row
    closest = min(range(len(frames)), key=lambda i: abs(frames[i] - decision_frame))
    out |= {
        "peak_frame": frames[peak],
        "peak_value": values[peak],
        "value_at_decision": values[closest],
        "verdict": "none",
    }
    runs = [
        r
        for r in _runs(
            [p is not None and p >= shot_value + ADVANTAGE_TOLERANCE for p in passes], handlers
        )
        if frames[r[0]] <= decision_frame
    ]
    if not runs:
        return CurveSummary(**out)
    lo, hi = runs[-1]
    run_passes = [p for p in passes[lo : hi + 1] if p is not None]  # all set inside a run
    start, end = frames[lo], frames[hi]
    late = end < decision_frame
    out |= {
        "window_start": start,
        "window_end": end,
        "window_handler_id": handlers[lo],
        "window_peak_value": max(run_passes),
        "advantage_seconds": (end - start + CURVE_STEP_FRAMES) / FPS,
        "release_lag_seconds": (decision_frame - end) / FPS if late else 0.0,
        "verdict": "late" if late else "during",
    }
    return CurveSummary(**out)


_HEADLINES = {
    "es": {
        "late": "La ventaja duró {a:.1f} s y se esfumó {lag:.1f} s antes del tiro",
        "during": (
            "Había una opción mejor en el instante del tiro (+{d:.2f} pts, abierta {a:.1f} s)"
        ),
        "none": "No hubo mejor opción que el tiro en la posesión",
        "no_window": "Sin curva suficiente ({n} frames)",
    },
    "en": {
        "late": "The advantage lasted {a:.1f} s and vanished {lag:.1f} s before the shot",
        "during": "A better option was open at the shot (+{d:.2f} pts, open for {a:.1f} s)",
        "none": "Nothing beat the shot during the possession",
        "no_window": "Not enough curve ({n} frames)",
    },
}


def headline(summary: CurveSummary, lang: Literal["es", "en"] = "es") -> str:
    """One-sentence reading of a curve summary, in Spanish or English."""
    edge = (summary.window_peak_value or 0.0) - summary.shot_value
    return _HEADLINES[lang][summary.verdict].format(
        a=summary.advantage_seconds,
        lag=summary.release_lag_seconds or 0.0,
        d=edge,
        n=summary.n_rows,
    )


SUMMARY_SCHEMA: dict[str, Any] = {
    "shot_id": pl.String,
    "game_id": pl.Int64,
    "n_rows": pl.Int64,
    "span_start": pl.Int64,
    "span_end": pl.Int64,
    "peak_frame": pl.Int64,
    "peak_value": pl.Float64,
    "window_start": pl.Int64,
    "window_end": pl.Int64,
    "window_handler_id": pl.Int64,
    "window_peak_value": pl.Float64,
    "advantage_seconds": pl.Float64,
    "release_lag_seconds": pl.Float64,
    "value_at_decision": pl.Float64,
    "shot_value": pl.Float64,  # the real shot's value, from the decisions table
    "verdict": pl.String,  # Verdict
    "headline_es": pl.String,
    "headline_en": pl.String,
    "skipped_off_court": pl.Int64,
}


def build_curves(
    game_id: int,
    settings: Settings,
    *,
    model: ValueModel | None = None,
    priors: Priors | None = None,
    out_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Write the curve and its summary for every valued shot of a game.

    Valued shots are the rows of ``load_decisions`` with ``rule != "excluded"``; each summary
    is read against that row's ``decision_frame`` and ``shot_value``. Two files in ``out_dir``
    (default: the build's ``curves/``): ``{game_id}.parquet`` (``CURVE_SCHEMA``, one row per
    sampled frame) and ``{game_id}.summary.parquet`` (``SUMMARY_SCHEMA``, one row per shot).
    Returns ``(curves_path, summaries_path)``.
    """
    model = model or ValueModel.default()
    priors = priors or Priors.from_settings(settings)
    aligner = Aligner(game_id, settings)
    valued = load_decisions(game_id, settings).filter(pl.col("rule") != "excluded")
    curves: list[pl.DataFrame] = []
    summaries: list[dict[str, Any]] = []
    for row in valued.iter_rows(named=True):
        result = possession_curve(aligner, row["shot_id"], priors, model)
        if result is None:  # excluded by the aligner although valued: tables out of date
            continue
        summary = summarize_curve(
            result.curve,
            shot_id=row["shot_id"],
            game_id=game_id,
            decision_frame=row["decision_frame"],
            shot_value=row["shot_value"],
        )
        curves.append(result.curve)
        summaries.append(
            {
                **summary.model_dump(),
                "headline_es": headline(summary, "es"),
                "headline_en": headline(summary, "en"),
                "skipped_off_court": result.skipped_off_court,
            }
        )
    out = out_dir if out_dir is not None else settings.curves_parquet(game_id).parent
    curves_path, summaries_path = out / f"{game_id}.parquet", out / f"{game_id}.summary.parquet"
    curve_df = pl.concat(curves) if curves else pl.DataFrame(schema=CURVE_SCHEMA)
    _write_parquet_atomic(curve_df, curves_path)
    _write_parquet_atomic(pl.DataFrame(summaries, schema=SUMMARY_SCHEMA), summaries_path)
    return curves_path, summaries_path
