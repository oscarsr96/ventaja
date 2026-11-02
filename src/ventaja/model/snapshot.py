"""Offense-oriented snapshot of one tracking frame: ten players plus the ball.

All coordinates are in feet in the offense-oriented frame (offensive hoop at ``(-40.7, 0.0)``),
see ADR-0001. Snapshots are built by ``ventaja.decision.align.Aligner``.
"""

import math

from ventaja.model.core import _Frozen


def _hypot(vx: float | None, vy: float | None) -> float | None:
    return None if vx is None or vy is None else math.hypot(vx, vy)


class PlayerPos(_Frozen):
    """Position and kinematics of one player in one frame.

    ``vx``/``vy`` are in ft/s, offense-oriented, by finite difference of tracked positions.
    """

    player_id: int
    team_id: int
    x: float
    y: float
    speed: float
    is_detected: bool
    pred_error: float
    vx: float | None = None
    vy: float | None = None

    @property
    def speed_vec(self) -> float | None:
        """Speed in ft/s from the finite-difference velocity, or None if unavailable."""
        return _hypot(self.vx, self.vy)


class BallPos(_Frozen):
    """Position and kinematics of the ball in one frame."""

    x: float
    y: float
    z: float
    speed: float
    is_detected: bool
    vx: float | None = None
    vy: float | None = None

    @property
    def speed_vec(self) -> float | None:
        """Speed in ft/s from the finite-difference velocity, or None if unavailable."""
        return _hypot(self.vx, self.vy)


class Snapshot(_Frozen):
    """One tracking frame aligned with its possession, split into offense and defense."""

    game_id: int
    frame_idx: int
    wall_clock: int
    period: int
    game_clock: float
    shot_clock: float | None
    possession_id: str
    chance_id: str | None
    off_team_id: int
    def_team_id: int
    offense: list[PlayerPos]
    defense: list[PlayerPos]
    ball: BallPos

    def player(self, player_id: int) -> PlayerPos:
        """The player with ``player_id``; raises KeyError if not on court in this frame."""
        for p in (*self.offense, *self.defense):
            if p.player_id == player_id:
                return p
        raise KeyError(player_id)

    def teammates_of(self, player_id: int) -> list[PlayerPos]:
        """The other players on ``player_id``'s side (offense or defense)."""
        for side in (self.offense, self.defense):
            if any(p.player_id == player_id for p in side):
                return [p for p in side if p.player_id != player_id]
        raise KeyError(player_id)
