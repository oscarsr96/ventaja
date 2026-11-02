"""Event-to-frame alignment: the single place where tracking is oriented to the offense.

``Aligner`` joins a tracking frame with the possession that contains it and returns a
``Snapshot`` whose coordinates are already offense-oriented (ADR-0001). Downstream code must
consume snapshots and never read ``left_hoop`` itself.
"""

from typing import Any

import polars as pl

from ventaja.config import FPS, Settings
from ventaja.data.load import load_events, load_game, load_tracking
from ventaja.decision.frame import decision_frame
from ventaja.errors import DataNotFoundError, NoTrackingError, VentajaError
from ventaja.geometry.court import orient_frame
from ventaja.model.decision import DecisionFrame
from ventaja.model.snapshot import BallPos, PlayerPos, Snapshot


def _row_containing(df: pl.DataFrame, frame_idx: int) -> dict[str, Any] | None:
    """First row of an event table with ``start_frame <= frame_idx <= end_frame``."""
    hit = df.filter((pl.col("start_frame") <= frame_idx) & (pl.col("end_frame") >= frame_idx))
    return hit.row(0, named=True) if hit.height else None


_REACH = 2  # neighbour frames read on each side of a frame for velocity

Velocity = tuple[float | None, float | None]


def _velocities(
    context: pl.DataFrame, frame_idx: int, left_hoop: bool
) -> dict[int | str, Velocity]:
    """Finite-difference velocity (ft/s, offense-oriented) of each player and the ball.

    ``context`` holds raw tracking rows of frames around ``frame_idx`` (it must include the
    central one). Keys are ``player_id`` for players and ``"ball"`` for the ball. Central
    difference over ``frame_idx -/+ 2`` when both exist for that entity, else a one-sided
    difference with the nearest existing neighbour at distance 1 or 2, else ``(None, None)``.
    """
    oriented = orient_frame(context, left_hoop)
    pos: dict[int, dict[int | str, tuple[float, float]]] = {}
    for r in oriented.iter_rows(named=True):
        key: int | str = "ball" if r["side"] == "ball" else r["player_id"]
        pos.setdefault(r["frame_idx"], {})[key] = (r["x"], r["y"])

    def diff(key: int | str, a: int, b: int) -> Velocity:
        (xa, ya), (xb, yb) = pos[a][key], pos[b][key]
        scale = FPS / (b - a)
        return ((xb - xa) * scale, (yb - ya) * scale)

    out: dict[int | str, Velocity] = {}
    for key in pos.get(frame_idx, {}):

        def has(offset: int, key: int | str = key) -> bool:
            return key in pos.get(frame_idx + offset, {})

        if has(-_REACH) and has(_REACH):
            out[key] = diff(key, frame_idx - _REACH, frame_idx + _REACH)
            continue
        # nearest existing neighbour, distance 1 before 2; backward wins a tie
        nearest = next(
            (off for off in (-1, 1, -2, 2) if has(off)),
            None,
        )
        if nearest is None:
            out[key] = (None, None)
        elif nearest < 0:
            out[key] = diff(key, frame_idx + nearest, frame_idx)
        else:
            out[key] = diff(key, frame_idx, frame_idx + nearest)
    return out


class Aligner:
    """Builds offense-oriented snapshots of one game.

    Possessions, chances, shots and game metadata are loaded once; tracking stays lazy and
    each ``snapshot``/``window`` call runs a single filtered ``collect()``.
    """

    def __init__(self, game_id: int, settings: Settings) -> None:
        self.game_id = game_id
        self._possessions = load_events(game_id, "possessions", settings).sort("start_frame")
        self._chances = load_events(game_id, "chances", settings).sort("start_frame")
        self._shots = load_events(game_id, "shots", settings)
        game = load_game(game_id, settings)
        self._team_of_side = {"home": game.home.team_id, "away": game.away.team_id}
        self._touches = load_events(game_id, "touches", settings)
        self._dribbles = load_events(game_id, "dribbles", settings)
        self._tracking = load_tracking(game_id, settings)
        self._tracked_frames = frozenset(
            self._tracking.select("frame_idx").unique().collect()["frame_idx"].to_list()
        )

    def possession_at(self, frame_idx: int) -> dict[str, Any] | None:
        """The possession row containing ``frame_idx``, or None.

        Consecutive possessions share their boundary frame; there the earlier one wins.
        """
        return _row_containing(self._possessions, frame_idx)

    def chance_at(self, frame_idx: int) -> dict[str, Any] | None:
        """The chance row containing ``frame_idx``, or None (earlier chance at a boundary)."""
        return _row_containing(self._chances, frame_idx)

    def snapshot(self, frame_idx: int) -> Snapshot:
        """Offense-oriented snapshot of one frame.

        Raises NoTrackingError if the frame has no tracking rows and VentajaError if it lies
        outside every possession (so it cannot be oriented).
        """
        context = self._frame_rows(frame_idx)
        possession = self.possession_at(frame_idx)
        if possession is None:
            raise VentajaError(
                f"game {self.game_id}: frame {frame_idx} is outside every possession, cannot orient"
            )
        return self._build(context, frame_idx, possession)

    def _frame_rows(self, frame_idx: int) -> pl.DataFrame:
        """Tracking rows of ``[frame_idx - 2, frame_idx + 2]`` (one collect).

        Raises NoTrackingError if the central frame itself has no rows.
        """
        rows = self._tracking.filter(
            pl.col("frame_idx").is_between(frame_idx - _REACH, frame_idx + _REACH)
        ).collect()
        if not (rows["frame_idx"] == frame_idx).any():
            raise NoTrackingError(f"game {self.game_id} has no tracking at frame {frame_idx}")
        return rows

    def shot(self, shot_id: str) -> dict[str, Any]:
        """The ``shots`` row with ``id == shot_id``; raises DataNotFoundError if absent."""
        hit = self._shots.filter(pl.col("id") == shot_id)
        if hit.height == 0:
            raise DataNotFoundError(f"shot {shot_id} not found in game {self.game_id}")
        return hit.row(0, named=True)

    def decision_frame(self, shot_id: str) -> DecisionFrame:
        """The decision frame of a shot (ADR-0003), from its touch and dribbles."""
        shot = self.shot(shot_id)
        touch_id = shot.get("touch_id")
        touch: dict[str, Any] | None = None
        dribble_frames: list[int] = []
        if touch_id is not None:
            hit = self._touches.filter(pl.col("id") == touch_id)
            touch = hit.row(0, named=True) if hit.height else None
            dribble_frames = sorted(
                self._dribbles.filter(pl.col("touch_id") == touch_id)["frame"].to_list()
            )
        return decision_frame(shot, touch, dribble_frames, self._tracked_frames.__contains__)

    def snapshot_for_shot(self, shot_id: str, *, decision: bool = False) -> Snapshot:
        """Snapshot at the shot's ``start_frame``, oriented by the shot's own possession.

        With ``decision=True`` the snapshot is taken at the shot's decision frame instead
        (ADR-0003); an excluded shot raises VentajaError with the reason.

        The possession is looked up by the shot's ``possession_id``, not by frame: some shots
        fall outside their possession's frame span (e.g. end-of-period possessions with
        ``start_frame == end_frame``). Raises DataNotFoundError if that possession is missing.
        """
        shot = self.shot(shot_id)
        possession_id = shot["possession_id"]
        hit = self._possessions.filter(pl.col("id") == possession_id)
        if hit.height == 0:
            raise DataNotFoundError(
                f"game {self.game_id}: possession {possession_id} of shot {shot_id} not found"
            )
        frame_idx = int(shot["start_frame"])
        if decision:
            chosen = self.decision_frame(shot_id)
            if chosen.frame_idx is None:
                raise VentajaError(f"shot {shot_id} has no decision frame: {chosen.reason}")
            frame_idx = chosen.frame_idx
        return self._build(self._frame_rows(frame_idx), frame_idx, hit.row(0, named=True))

    def window(self, start: int, end: int) -> list[Snapshot]:
        """Snapshots of every tracked frame in ``[start, end]``, in order.

        Frames without tracking are absent; frames outside every possession are skipped.

        Each frame is oriented by its own possession (``possession_at``). A window that crosses
        a possession boundary therefore flips orientation by 180 degrees and swaps offense and
        defense at the boundary; consumers must split the result on ``possession_id``.
        """
        rows = (
            self._tracking.filter(pl.col("frame_idx").is_between(start - _REACH, end + _REACH))
            .sort("frame_idx")
            .collect()
        )
        out: list[Snapshot] = []
        parts = {int(k[0]): v for k, v in rows.partition_by("frame_idx", as_dict=True).items()}
        for frame_idx in sorted(f for f in parts if start <= f <= end):
            possession = self.possession_at(frame_idx)
            if possession is not None:
                near = pl.concat(
                    parts[f]
                    for f in range(frame_idx - _REACH, frame_idx + _REACH + 1)
                    if f in parts
                )
                out.append(self._build(near, frame_idx, possession))
        return out

    def _build(self, context: pl.DataFrame, frame_idx: int, possession: dict[str, Any]) -> Snapshot:
        """Assemble the Snapshot of ``frame_idx`` from tracking rows around it.

        ``context`` holds the rows of ``frame_idx`` and of its +/-2 neighbours; the neighbours
        only feed the velocities.
        """
        left_hoop = bool(possession["left_hoop"])
        rows = context.filter(pl.col("frame_idx") == frame_idx)
        velocity = _velocities(context, frame_idx, left_hoop)
        oriented = orient_frame(rows, left_hoop)
        off_team_id = int(possession["off_team_id"])
        def_team_id = int(possession["def_team_id"])
        if {off_team_id, def_team_id} != set(self._team_of_side.values()):
            raise VentajaError(
                f"game {self.game_id}: frame {int(rows['frame_idx'][0])} possession "
                f"{possession['id']} has teams off={off_team_id} def={def_team_id}, "
                f"expected {sorted(self._team_of_side.values())}"
            )
        offense: list[PlayerPos] = []
        defense: list[PlayerPos] = []
        ball: BallPos | None = None
        for r in oriented.iter_rows(named=True):
            if r["side"] == "ball":
                ball = BallPos(
                    x=r["x"],
                    y=r["y"],
                    z=r["z"],
                    speed=r["speed"],
                    is_detected=r["is_detected"],
                    vx=velocity.get("ball", (None, None))[0],
                    vy=velocity.get("ball", (None, None))[1],
                )
                continue
            player = PlayerPos(
                player_id=r["player_id"],
                team_id=self._team_of_side[r["side"]],
                x=r["x"],
                y=r["y"],
                speed=r["speed"],
                is_detected=r["is_detected"],
                pred_error=r["pred_error"],
                vx=velocity.get(r["player_id"], (None, None))[0],
                vy=velocity.get(r["player_id"], (None, None))[1],
            )
            (offense if player.team_id == off_team_id else defense).append(player)
        first = oriented.row(0, named=True)
        if ball is None:
            raise NoTrackingError(f"game {self.game_id} has no ball at frame {frame_idx}")
        chance = self.chance_at(frame_idx)
        return Snapshot(
            game_id=self.game_id,
            frame_idx=frame_idx,
            wall_clock=first["wall_clock"],
            period=first["period"],
            game_clock=first["game_clock"],
            shot_clock=first["shot_clock"],
            possession_id=possession["id"],
            chance_id=chance["id"] if chance else None,
            off_team_id=off_team_id,
            def_team_id=def_team_id,
            offense=offense,
            defense=defense,
            ball=ball,
        )
