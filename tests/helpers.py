"""Builders for synthetic test objects."""

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
