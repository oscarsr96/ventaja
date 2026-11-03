"""Pass viability, decision cost and the per-game ``decisions`` tables (ADR-0004)."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import polars as pl

from ventaja.config import Settings
from ventaja.decision.align import Aligner
from ventaja.errors import DataNotFoundError, NoTrackingError, VentajaError
from ventaja.model.decision import AlternativeType, Decision, Option, Rule
from ventaja.model.snapshot import Snapshot
from ventaja.value.features import OPTION_FEATURES, option_rows, shot_kwargs
from ventaja.value.model import ValueModel
from ventaja.value.params import (
    CUT_SPEED,
    LANE_BLOCKED_FACTOR,
    OPEN_DEF_DIST,
    PASS_DISTANCE_HARD,
    PASS_DISTANCE_SOFT,
    SHOT_CLOCK_MIN_PASS,
)
from ventaja.value.priors import Priors
from ventaja.value.zones import Zone

__all__ = [
    "ShooterOffCourtError",
    "build_decisions",
    "classify_alternative",
    "decide",
    "decide_snapshot",
    "decision_from_tables",
    "viability",
]

_PLAYERS_ON_COURT = 10


class ShooterOffCourtError(VentajaError):
    """The shooter is not among the tracked players of the decision frame."""


def viability(pass_distance: float, lane_blocked: bool, shot_clock: float | None) -> float:
    """Share of a pass option's value that survives the pass (1.0 = fully viable).

    Zero under ``SHOT_CLOCK_MIN_PASS`` seconds of shot clock; otherwise a linear fall from
    ``PASS_DISTANCE_SOFT`` to ``PASS_DISTANCE_HARD`` feet, times ``LANE_BLOCKED_FACTOR`` if a
    defender sits in the lane. An unknown shot clock does not penalize.
    """
    if shot_clock is not None and shot_clock < SHOT_CLOCK_MIN_PASS:
        return 0.0
    span = PASS_DISTANCE_HARD - PASS_DISTANCE_SOFT
    d = 1.0 - min(max((pass_distance - PASS_DISTANCE_SOFT) / span, 0.0), 1.0)
    return d * LANE_BLOCKED_FACTOR if lane_blocked else d


def classify_alternative(row: Mapping[str, Any]) -> AlternativeType:
    """Kind of pass alternative, from its ``zone``, ``moving_to_hoop`` and ``nearest_def_dist``."""
    zone, moving, def_dist = row["zone"], row["moving_to_hoop"], row["nearest_def_dist"]
    if zone in ("restricted_area", "paint_non_ra") and moving >= CUT_SPEED:
        return "rim_cut"
    if zone == "corner_3" and def_dist >= OPEN_DEF_DIST:
        return "open_corner"
    if zone == "paint_non_ra" and moving < CUT_SPEED:
        return "post"
    if zone in ("above_break_3", "mid_range") and def_dist >= OPEN_DEF_DIST:
        return "extra_pass"
    return "other"


def _option(row: dict[str, Any], proba: float, shot_clock: float | None) -> Option:
    is_shot = row["option_type"] == "shot"
    value = proba * row["points"]
    via = 1.0 if is_shot else viability(row["pass_distance"], row["lane_blocked"], shot_clock)
    return Option(
        player_id=row["option_player_id"],
        option_type=row["option_type"],
        zone=row["zone"],
        points=row["points"],
        x=row["x"],
        y=row["y"],
        pass_distance=row["pass_distance"],
        lane_blocked=row["lane_blocked"],
        proba=proba,
        value=value,
        viability=via,
        adjusted_value=value * via,
        alternative_type=None if is_shot else classify_alternative(row),
        features={f: float(row[f]) for f in OPTION_FEATURES if row[f] is not None},
    )


def _confidence(snapshot: Snapshot) -> float:
    detected = sum(p.is_detected for p in (*snapshot.offense, *snapshot.defense))
    return detected / _PLAYERS_ON_COURT


def decide(aligner: Aligner, shot_id: str, priors: Priors, model: ValueModel) -> Decision | None:
    """Value the shot against its four pass options at the decision frame.

    When no pass is viable (best adjusted value 0.0) there is no alternative: the best-alt
    fields are None, ``cost`` is 0.0 and ``good_read`` is None (not a read at all).

    Returns None if the shot's decision frame is excluded (no snapshot is read then). Raises
    ShooterOffCourtError if the shooter is not tracked in the decision frame.
    """
    frame = aligner.decision_frame(shot_id)
    if frame.rule == "excluded" or frame.frame_idx is None:
        return None
    shot = aligner.shot(shot_id)
    snapshot = aligner.snapshot_for_shot(shot_id, decision=True)
    return decide_snapshot(
        snapshot,
        shot,
        priors,
        model,
        decision_frame=frame.frame_idx,
        rule=frame.rule,
        **shot_kwargs(shot),
    )


def decide_snapshot(
    snapshot: Snapshot,
    shot: Mapping[str, Any],
    priors: Priors,
    model: ValueModel,
    *,
    decision_frame: int,
    rule: Rule,
    shot_zone: Zone | None,
    shot_three: bool | None,
) -> Decision:
    """Value a shot against its four pass options on an already built snapshot.

    ``shot`` needs ``id``, ``game_id``, ``shooter_id`` and ``start_frame``. ``shot_zone`` and
    ``shot_three`` describe the attempted shot (see ``shot_kwargs``); None values the shot from
    the shooter's position, as the whiteboard does after moving him. Raises
    ShooterOffCourtError if the shooter is not tracked in the snapshot.
    """
    shot_id = shot["id"]
    try:
        rows = option_rows(
            snapshot, shot["shooter_id"], priors, shot_zone=shot_zone, shot_three=shot_three
        )
    except VentajaError as exc:
        raise ShooterOffCourtError(f"shot {shot_id}: {exc}") from exc
    probas = model.predict_proba(rows).to_list()
    options = [
        _option(row, float(p), snapshot.shot_clock)
        for row, p in zip(rows.iter_rows(named=True), probas, strict=True)
    ]
    shot_option = next(o for o in options if o.option_type == "shot")
    passes = sorted(
        (o for o in options if o.option_type == "pass"),
        key=lambda o: o.adjusted_value,
        reverse=True,
    )  # stable: ties keep row order, so the first maximal pass is the best
    best = passes[0] if passes else None
    best_value = best.adjusted_value if best else None
    good_read: bool | None = best_value is None or best_value <= shot_option.value
    if best_value == 0.0:  # no viable pass (e.g. shot clock under SHOT_CLOCK_MIN_PASS)
        best, best_value, good_read = None, None, None
    return Decision(
        shot_id=shot_id,
        game_id=shot["game_id"],
        shooter_id=shot["shooter_id"],
        decision_frame=decision_frame,
        release_frame=shot["start_frame"],
        rule=rule,
        shot_clock=snapshot.shot_clock,
        shot_value=shot_option.value,
        best_alt_player_id=best.player_id if best else None,
        best_alt_type=best.alternative_type if best else None,
        best_alt_value=best_value,
        cost=max(0.0, (best_value or 0.0) - shot_option.value),
        good_read=good_read,
        confidence=_confidence(snapshot),
        options=[shot_option, *passes],
    )


DECISION_SCHEMA: dict[str, Any] = {
    "shot_id": pl.String,
    "game_id": pl.Int64,
    "shooter_id": pl.Int64,
    "decision_frame": pl.Int64,
    "release_frame": pl.Int64,
    "rule": pl.String,
    "reason": pl.String,
    "shot_clock": pl.Float64,
    "shot_value": pl.Float64,
    "best_alt_player_id": pl.Int64,
    "best_alt_type": pl.String,
    "best_alt_value": pl.Float64,
    "cost": pl.Float64,
    "good_read": pl.Boolean,  # null when no pass is viable
    "confidence": pl.Float64,
}
OPTION_SCHEMA: dict[str, Any] = {
    "shot_id": pl.String,
    "game_id": pl.Int64,
    "player_id": pl.Int64,
    "option_type": pl.String,
    "zone": pl.String,
    "points": pl.Int64,
    "x": pl.Float64,
    "y": pl.Float64,
    "pass_distance": pl.Float64,
    "lane_blocked": pl.Boolean,
    "proba": pl.Float64,
    "value": pl.Float64,
    "viability": pl.Float64,
    "adjusted_value": pl.Float64,
    "alternative_type": pl.String,
    **{f: pl.Float64 for f in OPTION_FEATURES},
}


def _excluded_row(shot: dict[str, Any], game_id: int, reason: str | None) -> dict[str, Any]:
    return {
        "shot_id": shot["id"],
        "game_id": game_id,
        "shooter_id": shot["shooter_id"],
        "release_frame": shot["start_frame"],
        "rule": "excluded",
        "reason": reason,
    }


def _option_rows(d: Decision) -> list[dict[str, Any]]:
    return [
        {
            "shot_id": d.shot_id,
            "game_id": d.game_id,
            **o.model_dump(exclude={"features"}),
            **o.features,
        }
        for o in d.options
    ]


_OPTION_FIELDS = tuple(f for f in Option.model_fields if f != "features")
_DECISION_FIELDS = tuple(f for f in Decision.model_fields if f != "options")


def decision_from_tables(shot_id: str, decisions: pl.DataFrame, options: pl.DataFrame) -> Decision:
    """Rebuild a shot's ``Decision`` from the ``decisions`` and ``decision_options`` tables.

    The inverse of what ``build_decisions`` writes: the options keep the table order (the
    shot first, then the passes by ``adjusted_value`` descending) and ``features`` holds the
    option's non-null ``OPTION_FEATURES`` columns. Raises DataNotFoundError if the shot is
    not in ``decisions`` and VentajaError, with its reason, if the shot is excluded.
    """
    hit = decisions.filter(pl.col("shot_id") == shot_id)
    if hit.height == 0:
        raise DataNotFoundError(f"shot {shot_id} not found in the decisions table")
    row = hit.row(0, named=True)
    if row["rule"] == "excluded":
        raise VentajaError(f"shot {shot_id} is excluded: {row['reason']}")
    rows = options.filter(pl.col("shot_id") == shot_id).iter_rows(named=True)
    return Decision(
        **{f: row[f] for f in _DECISION_FIELDS},
        options=[
            Option(
                **{f: o[f] for f in _OPTION_FIELDS},
                features={f: float(o[f]) for f in OPTION_FEATURES if o[f] is not None},
            )
            for o in rows
        ],
    )


def build_decisions(
    game_id: int,
    settings: Settings,
    *,
    model: ValueModel | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Write every shot decision of a game; returns the decisions parquet path.

    Two files in ``out_dir`` (default: the build's ``decisions/``): ``{game_id}.parquet``
    (one row per shot, excluded shots with their ``reason`` and null values) and
    ``{game_id}.options.parquet`` (one row per option of valid shots).
    """
    model = model or ValueModel.default()
    aligner = Aligner(game_id, settings)
    priors = Priors.from_settings(settings)
    rows: list[dict[str, Any]] = []
    options: list[dict[str, Any]] = []
    for shot in aligner._shots.iter_rows(named=True):
        try:
            d = decide(aligner, shot["id"], priors, model)
        except ShooterOffCourtError:
            rows.append(_excluded_row(shot, game_id, "shooter_off_court"))
            continue
        except NoTrackingError:
            rows.append(_excluded_row(shot, game_id, "no_tracking"))
            continue
        if d is None:
            rows.append(_excluded_row(shot, game_id, aligner.decision_frame(shot["id"]).reason))
            continue
        rows.append({**d.model_dump(exclude={"options"}), "reason": None})
        options.extend(_option_rows(d))
    out = out_dir if out_dir is not None else settings.decisions_parquet(game_id).parent
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{game_id}.parquet"
    pl.DataFrame(rows, schema=DECISION_SCHEMA).write_parquet(path)
    pl.DataFrame(options, schema=OPTION_SCHEMA).write_parquet(out / f"{game_id}.options.parquet")
    return path
