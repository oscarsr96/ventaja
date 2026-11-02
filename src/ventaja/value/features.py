"""Per-option features: the shot taken and the four pass alternatives at the decision frame."""

import math
from typing import Any

import polars as pl

from ventaja.decision.align import Aligner
from ventaja.errors import VentajaError
from ventaja.geometry.court import HOOP, distance_to_hoop
from ventaja.model.snapshot import PlayerPos, Snapshot
from ventaja.value.params import (
    BETWEEN_WIDTH,
    FLIGHT_MAX,
    FLIGHT_MIN,
    LANE_END_MARGIN,
    LANE_WIDTH,
    PASS_SPEED,
    PROJECTION_CAP,
    SHOT_CLOCK_LOW,
)
from ventaja.value.priors import Priors
from ventaja.value.zones import Zone, is_three, points, region_to_zone, zone_of

__all__ = ["OPTION_FEATURES", "option_rows", "shot_kwargs", "shot_rows"]

OPTION_FEATURES: tuple[str, ...] = (
    "dist_hoop",
    "dist_hoop_sq",
    "angle_abs",
    "is_three",
    "nearest_def_dist",
    "def_between",
    "closing_speed",
    "moving_to_hoop",
    "prior_zone",
    "shot_clock_low",
    "shot_clock",
)


def _segment_position(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> tuple[float, float, float]:
    """(perpendicular distance, projection along a->b in feet, length) of p against a->b."""
    length = math.hypot(bx - ax, by - ay)
    if length == 0:
        return math.hypot(px - ax, py - ay), 0.0, 0.0
    ux, uy = (bx - ax) / length, (by - ay) / length
    along = (px - ax) * ux + (py - ay) * uy
    perp = abs((px - ax) * uy - (py - ay) * ux)
    return perp, along, length


def _projected_displacement(mate: PlayerPos, pass_distance: float) -> tuple[float, float]:
    """Displacement of the receiver during the pass flight, capped at ``PROJECTION_CAP``."""
    if mate.vx is None or mate.vy is None:
        return 0.0, 0.0
    t = min(max(pass_distance / PASS_SPEED, FLIGHT_MIN), FLIGHT_MAX)
    dx, dy = mate.vx * t, mate.vy * t
    norm = math.hypot(dx, dy)
    if norm > PROJECTION_CAP:
        dx, dy = dx * PROJECTION_CAP / norm, dy * PROJECTION_CAP / norm
    return dx, dy


def _lane_blocked(shooter: PlayerPos, x: float, y: float, defense: list[PlayerPos]) -> bool:
    for d in defense:
        perp, along, length = _segment_position(d.x, d.y, shooter.x, shooter.y, x, y)
        if perp < LANE_WIDTH and LANE_END_MARGIN < along < length - LANE_END_MARGIN:
            return True
    return False


def _def_between(x: float, y: float, defense: list[PlayerPos]) -> int:
    for d in defense:
        perp, along, length = _segment_position(d.x, d.y, x, y, HOOP[0], HOOP[1])
        if perp < BETWEEN_WIDTH and 0.0 < along < length:
            return 1
    return 0


def _closing_speed(x: float, y: float, nearest: PlayerPos) -> float:
    """Velocity of the defender along the defender->player unit vector (positive if closing)."""
    if nearest.vx is None or nearest.vy is None:
        return 0.0
    dist = math.hypot(x - nearest.x, y - nearest.y)
    if dist == 0:
        return 0.0
    return (nearest.vx * (x - nearest.x) + nearest.vy * (y - nearest.y)) / dist


def _moving_to_hoop(player: PlayerPos, x: float, y: float) -> float:
    if player.vx is None or player.vy is None:
        return 0.0
    dist = distance_to_hoop(x, y)
    if dist == 0:
        return 0.0
    return (player.vx * (HOOP[0] - x) + player.vy * (HOOP[1] - y)) / dist


def _option(
    snapshot: Snapshot,
    option: PlayerPos,
    shooter: PlayerPos,
    priors: Priors,
    *,
    is_shot: bool,
    shot_zone: Zone | None = None,
    shot_three: bool | None = None,
) -> dict[str, Any]:
    pass_distance = 0.0 if is_shot else math.hypot(option.x - shooter.x, option.y - shooter.y)
    dx, dy = (0.0, 0.0) if is_shot else _projected_displacement(option, pass_distance)
    x, y = option.x + dx, option.y + dy
    zone = shot_zone or zone_of(x, y)
    if shot_three is None:
        option_points, option_three = points(zone), is_three(x, y)
    else:
        option_points, option_three = (3 if shot_three else 2), shot_three
    dist = distance_to_hoop(x, y)
    nearest = min(snapshot.defense, key=lambda d: math.hypot(x - d.x, y - d.y))
    clock = snapshot.shot_clock
    return {
        "option_player_id": option.player_id,
        "option_type": "shot" if is_shot else "pass",
        "zone": zone,
        "points": option_points,
        "x": x,
        "y": y,
        "pass_distance": pass_distance,
        "lane_blocked": False if is_shot else _lane_blocked(shooter, x, y, snapshot.defense),
        "projected_dx": dx,
        "projected_dy": dy,
        "dist_hoop": dist,
        "dist_hoop_sq": dist * dist,
        "angle_abs": math.atan2(abs(y - HOOP[1]), x - HOOP[0]),
        "is_three": option_three,
        "nearest_def_dist": math.hypot(x - nearest.x, y - nearest.y),
        "def_between": _def_between(x, y, snapshot.defense),
        "closing_speed": _closing_speed(x, y, nearest),
        "moving_to_hoop": _moving_to_hoop(option, x, y),
        "prior_zone": priors.player_rate(option.player_id, zone),
        "shot_clock_low": int(clock is not None and clock < SHOT_CLOCK_LOW),
        "shot_clock": clock,
    }


_OPTION_SCHEMA: dict[str, Any] = {
    "option_player_id": pl.Int64,
    "option_type": pl.String,
    "zone": pl.String,
    "points": pl.Int64,
    "x": pl.Float64,
    "y": pl.Float64,
    "pass_distance": pl.Float64,
    "lane_blocked": pl.Boolean,
    "projected_dx": pl.Float64,
    "projected_dy": pl.Float64,
    "dist_hoop": pl.Float64,
    "dist_hoop_sq": pl.Float64,
    "angle_abs": pl.Float64,
    "is_three": pl.Boolean,
    "nearest_def_dist": pl.Float64,
    "def_between": pl.Int64,
    "closing_speed": pl.Float64,
    "moving_to_hoop": pl.Float64,
    "prior_zone": pl.Float64,
    "shot_clock_low": pl.Int64,
    "shot_clock": pl.Float64,
}


def option_rows(
    snapshot: Snapshot,
    shooter_id: int,
    priors: Priors,
    *,
    shot_zone: Zone | None = None,
    shot_three: bool | None = None,
) -> pl.DataFrame:
    """The shot and the four pass options of ``shooter_id``, one row each.

    The shot row describes the shot actually attempted: ``shot_zone`` (the event's zone) and
    ``shot_three`` (the event's ``three`` flag) set its ``zone``, ``points``, ``is_three`` and
    ``prior_zone`` when given; otherwise they come from the shooter's position. Every other
    feature of the shot row is read from the decision-frame state. Pass options describe a
    catch-and-shoot at the receiver's projected position (see ``params``).
    """
    try:
        shooter = snapshot.player(shooter_id)
    except KeyError:
        raise VentajaError(
            f"shooter {shooter_id} is not on court in frame {snapshot.frame_idx}"
        ) from None
    if not snapshot.defense:
        raise VentajaError(f"no defenders in frame {snapshot.frame_idx}")
    rows = [
        _option(
            snapshot,
            shooter,
            shooter,
            priors,
            is_shot=True,
            shot_zone=shot_zone,
            shot_three=shot_three,
        )
    ]
    rows += [
        _option(snapshot, mate, shooter, priors, is_shot=False)
        for mate in snapshot.teammates_of(shooter_id)
    ]
    return pl.DataFrame(rows, schema=_OPTION_SCHEMA)


def shot_kwargs(shot: dict[str, Any]) -> dict[str, Any]:
    """``option_rows`` keywords that describe the attempted shot from its ``shots`` event.

    The zone comes from the event ``region`` (``None`` when unknown, so ``option_rows`` falls
    back to the shooter's position); the points from the event ``three`` flag.
    """
    three = shot.get("three")
    return {
        "shot_zone": region_to_zone(shot.get("region")),
        "shot_three": None if three is None else bool(three),
    }


def shot_rows(aligner: Aligner, priors: Priors) -> pl.DataFrame:
    """Option rows of every shot of the game whose decision frame is not excluded.

    Adds ``shot_id, game_id, decision_frame, rule, shooter_id`` and the labels ``outcome``,
    ``three`` and ``shot_quality`` (SkillCorner xFG, 0-100), set on the shooter row only.
    """
    frames: list[pl.DataFrame] = []
    for shot in aligner._shots.iter_rows(named=True):
        decision = aligner.decision_frame(shot["id"])
        if decision.rule == "excluded" or decision.frame_idx is None:
            continue
        snapshot = aligner.snapshot_for_shot(shot["id"], decision=True)
        rows = option_rows(snapshot, shot["shooter_id"], priors, **shot_kwargs(shot))
        is_shot = pl.col("option_type") == "shot"
        frames.append(
            rows.with_columns(
                pl.lit(shot["id"]).alias("shot_id"),
                pl.lit(aligner.game_id).alias("game_id"),
                pl.lit(decision.frame_idx).alias("decision_frame"),
                pl.lit(decision.rule).alias("rule"),
                pl.lit(shot["shooter_id"]).alias("shooter_id"),
                pl.when(is_shot).then(pl.lit(shot["outcome"])).otherwise(None).alias("outcome"),
                pl.when(is_shot).then(pl.lit(shot["three"])).otherwise(None).alias("three"),
                pl.when(is_shot)
                .then(pl.lit(shot["shot_quality"], dtype=pl.Float64))
                .otherwise(None)
                .alias("shot_quality"),
            )
        )
    if not frames:
        return pl.DataFrame()
    first = ["shot_id", "game_id", "decision_frame", "rule", "shooter_id"]
    return pl.concat(frames).select(*first, pl.exclude(first))
