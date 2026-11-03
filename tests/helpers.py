"""Builders for synthetic test objects."""

import shutil
from pathlib import Path
from typing import Any, Literal

import polars as pl

from ventaja.config import Settings
from ventaja.data.load import ARTIFACTS_DIR
from ventaja.model.decision import Decision, Option
from ventaja.model.snapshot import BallPos, PlayerPos, Snapshot

# (player_id, x, y) or (player_id, x, y, vx, vy)
PlayerSpec = tuple[int, float, float] | tuple[int, float, float, float | None, float | None]


def _pos(spec: PlayerSpec, team_id: int) -> PlayerPos:
    vx, vy = (spec[3], spec[4]) if len(spec) == 5 else (None, None)
    return PlayerPos(
        player_id=spec[0],
        team_id=team_id,
        x=spec[1],
        y=spec[2],
        speed=0.0,
        is_detected=True,
        pred_error=0.0,
        vx=vx,
        vy=vy,
    )


def make_snapshot(
    offense: list[PlayerSpec],
    defense: list[PlayerSpec],
    ball: tuple[float, float] | None = None,
    shot_clock: float | None = 12.0,
) -> Snapshot:
    """A synthetic snapshot; the ball defaults to the first offensive player's position."""
    bx, by = ball if ball is not None else (offense[0][1], offense[0][2])
    return Snapshot(
        game_id=1,
        frame_idx=100,
        wall_clock=0,
        period=1,
        game_clock=600.0,
        shot_clock=shot_clock,
        possession_id="p",
        chance_id=None,
        off_team_id=1,
        def_team_id=2,
        offense=[_pos(s, 1) for s in offense],
        defense=[_pos(s, 2) for s in defense],
        ball=BallPos(x=bx, y=by, z=0.0, speed=0.0, is_detected=True),
    )


def decision_with(**overrides: Any) -> Decision:
    """A valid synthetic ``Decision`` (shot plus four passes); ``overrides`` replace fields."""

    def option(
        player_id: int, option_type: Literal["shot", "pass"], value: float, via: float
    ) -> Option:
        return Option(
            player_id=player_id,
            option_type=option_type,
            zone="mid_range",
            points=2,
            x=15.0,
            y=0.0,
            pass_distance=0.0 if option_type == "shot" else 15.0,
            lane_blocked=False,
            proba=value / 2,
            value=value,
            viability=via,
            adjusted_value=value * via,
            alternative_type=None if option_type == "shot" else "other",
            features={},
        )

    fields: dict[str, Any] = {
        "shot_id": "shot-1-1-0",
        "game_id": 1,
        "shooter_id": 10,
        "decision_frame": 100,
        "release_frame": 110,
        "rule": "gather",
        "shot_clock": 12.0,
        "shot_value": 0.9,
        "best_alt_player_id": 11,
        "best_alt_type": "other",
        "best_alt_value": 1.0,
        "cost": 0.1,
        "good_read": False,
        "confidence": 1.0,
        "options": [
            option(10, "shot", 0.9, 1.0),
            option(11, "pass", 1.0, 1.0),
            option(12, "pass", 0.8, 1.0),
            option(13, "pass", 0.7, 1.0),
            option(14, "pass", 0.6, 1.0),
        ],
    }
    return Decision(**{**fields, **overrides})


def make_decisions(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """A layer-1 decisions frame from partial rows (defaults: a readable gather, cost 0.3)."""
    from ventaja.decision.cost import DECISION_SCHEMA

    base: dict[str, Any] = {
        "game_id": 1,
        "shooter_id": 10,
        "decision_frame": 500,
        "release_frame": 510,
        "rule": "gather",
        "reason": None,
        "shot_clock": 12.0,
        "shot_value": 0.9,
        "best_alt_player_id": 11,
        "best_alt_type": "open_corner",
        "best_alt_value": 1.2,
        "cost": 0.3,
        "good_read": False,
        "confidence": 1.0,
    }
    return pl.DataFrame([base | r for r in rows], schema=DECISION_SCHEMA)


def make_summaries(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """A layer-2 curve-summary frame from partial rows (defaults: verdict ``none``)."""
    from ventaja.decision.curve import SUMMARY_SCHEMA

    base: dict[str, Any] = {
        "game_id": 1,
        "verdict": "none",
        "advantage_seconds": 0.0,
        "held_to_decision": False,
        "shot_value": 0.9,
    }
    return pl.DataFrame([base | r for r in rows], schema=SUMMARY_SCHEMA)


def decisions_for_all_frames_for_one(tmp_path: Path) -> Settings:
    """Build dir with the ten packaged decision tables but the frames of one game only."""
    build = tmp_path / "build"
    shutil.copytree(ARTIFACTS_DIR / "decisions", build / "decisions")
    (build / "frames").mkdir(parents=True)
    shutil.copy(ARTIFACTS_DIR / "frames" / f"{114243}.parquet", build / "frames")
    shutil.copy(ARTIFACTS_DIR / "frames" / "roster.parquet", build / "frames")
    return Settings(data_dir=tmp_path / "raw", build_dir=build)
