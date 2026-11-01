"""Event-to-frame alignment: the single place where tracking is oriented to the offense.

``Aligner`` joins a tracking frame with the possession that contains it and returns a
``Snapshot`` whose coordinates are already offense-oriented (ADR-0001). Downstream code must
consume snapshots and never read ``left_hoop`` itself.
"""

from typing import Any

import polars as pl

from ventaja.config import Settings
from ventaja.data.load import load_events, load_game, load_tracking
from ventaja.errors import DataNotFoundError, NoTrackingError, VentajaError
from ventaja.geometry.court import orient_frame
from ventaja.model.snapshot import BallPos, PlayerPos, Snapshot


def _row_containing(df: pl.DataFrame, frame_idx: int) -> dict[str, Any] | None:
    """First row of an event table with ``start_frame <= frame_idx <= end_frame``."""
    hit = df.filter((pl.col("start_frame") <= frame_idx) & (pl.col("end_frame") >= frame_idx))
    return hit.row(0, named=True) if hit.height else None


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
        self._tracking = load_tracking(game_id, settings)

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
        rows = self._tracking.filter(pl.col("frame_idx") == frame_idx).collect()
        if rows.height == 0:
            raise NoTrackingError(f"game {self.game_id} has no tracking at frame {frame_idx}")
        possession = self.possession_at(frame_idx)
        if possession is None:
            raise VentajaError(
                f"game {self.game_id}: frame {frame_idx} is outside every possession, cannot orient"
            )
        return self._build(rows, possession)

    def shot(self, shot_id: str) -> dict[str, Any]:
        """The ``shots`` row with ``id == shot_id``; raises DataNotFoundError if absent."""
        hit = self._shots.filter(pl.col("id") == shot_id)
        if hit.height == 0:
            raise DataNotFoundError(f"shot {shot_id} not found in game {self.game_id}")
        return hit.row(0, named=True)

    def snapshot_for_shot(self, shot_id: str) -> Snapshot:
        """Snapshot at the shot's ``start_frame``."""
        return self.snapshot(int(self.shot(shot_id)["start_frame"]))

    def window(self, start: int, end: int) -> list[Snapshot]:
        """Snapshots of every tracked frame in ``[start, end]``, in order.

        Frames without tracking are absent; frames outside every possession are skipped.
        """
        rows = (
            self._tracking.filter(pl.col("frame_idx").is_between(start, end))
            .sort("frame_idx")
            .collect()
        )
        out: list[Snapshot] = []
        for (frame_idx,), frame in rows.group_by("frame_idx", maintain_order=True):
            possession = self.possession_at(int(frame_idx))
            if possession is not None:
                out.append(self._build(frame, possession))
        return out

    def _build(self, rows: pl.DataFrame, possession: dict[str, Any]) -> Snapshot:
        """Assemble a Snapshot from the 11 tracking rows of one frame."""
        oriented = orient_frame(rows, bool(possession["left_hoop"]))
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
                    x=r["x"], y=r["y"], z=r["z"], speed=r["speed"], is_detected=r["is_detected"]
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
            )
            (offense if player.team_id == off_team_id else defense).append(player)
        first = oriented.row(0, named=True)
        frame_idx = int(first["frame_idx"])
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
