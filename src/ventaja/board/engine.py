"""Whiteboard engine: move players of a decision frame and value the shot again.

The engine works on the packaged decision frames (``artifacts/frames/``), so it needs no
tracking data. A ``BoardState`` is immutable; ``move`` returns a new one and ``evaluate`` values
it with the same code path as layer 1 (``decide_snapshot``).
"""

from typing import Any

import polars as pl

from ventaja.config import Settings
from ventaja.data.load import (
    curve_files,
    decision_files,
    frame_files,
    load_decision_options,
    load_frames,
)
from ventaja.data.people import load_people
from ventaja.decision.cost import decide_snapshot, decision_from_tables
from ventaja.decision.frames import snapshot_from_frame
from ventaja.errors import DataNotFoundError
from ventaja.geometry.court import (
    CORNER_X_MAX,
    CORNER_Y,
    COURT_WIDTH,
    HALF_LENGTH,
    HOOP,
    KEY_HALF_WIDTH,
    KEY_X_MAX,
    RA_RADIUS,
    THREE_POINT_RADIUS,
)
from ventaja.model.core import _Frozen
from ventaja.model.decision import Decision, Rule
from ventaja.model.snapshot import PlayerPos, Snapshot
from ventaja.value.model import ValueModel
from ventaja.value.params import BOARD_MOVED_VELOCITY
from ventaja.value.priors import Priors
from ventaja.value.zones import Zone

__all__ = ["Board", "BoardState", "court_payload"]

_SHOT_COLUMNS = [
    "shot_id",
    "game_id",
    "shooter_id",
    "shooter",
    "team",
    "period",
    "shot_clock",
    "cost",
    "good_read",
    "headline_es",
    "headline_en",
]


def court_payload() -> dict[str, Any]:
    """Court constants (feet, offense orientation) the front end draws the half court with."""
    return {
        "half_length": HALF_LENGTH,
        "width": COURT_WIDTH,
        "hoop": [HOOP[0], HOOP[1]],
        "three_point_radius": THREE_POINT_RADIUS,
        "ra_radius": RA_RADIUS,
        "key_half_width": KEY_HALF_WIDTH,
        "key_x_max": KEY_X_MAX,
        "corner_y": CORNER_Y,
        "corner_x_max": CORNER_X_MAX,
    }


class BoardState(_Frozen):
    """A shot's decision frame with the moves applied so far.

    ``original`` is the stored decision (no moves); ``snapshot`` already has the moves.
    ``shot`` holds the ``id``, ``game_id``, ``shooter_id`` and ``start_frame`` that
    ``decide_snapshot`` needs; ``shot_zone`` and ``shot_three`` describe the shot actually
    taken (read from the stored decision), used while the shooter has not been moved.
    """

    shot_id: str
    game_id: int
    shooter_id: int
    decision_frame: int
    release_frame: int
    rule: Rule
    shot_clock: float | None
    original: Decision
    snapshot: Snapshot
    moves: dict[int, tuple[float, float]]
    shot: dict[str, Any]
    shot_zone: Zone
    shot_three: bool


def _read_all(paths: list[Any]) -> pl.DataFrame:
    return pl.concat([pl.read_parquet(p) for p in paths], how="vertical_relaxed")


def _priors_for(settings: Settings) -> Priors:
    """Priors from the build's aggregates, else the ones packaged next to the model."""
    try:
        return Priors.from_settings(settings)
    except DataNotFoundError:
        return Priors.default()


class Board:
    """Loads shots, moves players and values the result."""

    def __init__(
        self,
        settings: Settings,
        *,
        model: ValueModel | None = None,
        priors: Priors | None = None,
    ) -> None:
        self.settings = settings
        self.model = model or ValueModel.default()
        self.priors = priors or _priors_for(settings)
        decision_paths, _ = decision_files(settings)
        self._decisions = _read_all(decision_paths) if decision_paths else pl.DataFrame()
        self._game_of: dict[str, int] = (
            dict(zip(self._decisions["shot_id"], self._decisions["game_id"], strict=True))
            if self._decisions.height
            else {}
        )
        _, summary_paths = curve_files(settings)
        self._headlines = (
            _read_all(summary_paths).select("shot_id", "headline_es", "headline_en")
            if summary_paths
            else pl.DataFrame(
                schema={"shot_id": pl.String, "headline_es": pl.String, "headline_en": pl.String}
            )
        )
        people = load_people(settings)
        self._names, self._jerseys, self._team_names = people.names, people.jerseys, people.teams
        self._frames: dict[int, pl.DataFrame] = {}
        self._options: dict[int, pl.DataFrame] = {}

    def _game_frames(self, game_id: int) -> pl.DataFrame:
        if game_id not in self._frames:
            self._frames[game_id] = load_frames(game_id, self.settings)
        return self._frames[game_id]

    def _game_options(self, game_id: int) -> pl.DataFrame:
        if game_id not in self._options:
            self._options[game_id] = load_decision_options(game_id, self.settings)
        return self._options[game_id]

    def shots(self, game_id: int | None = None) -> pl.DataFrame:
        """The valued shots (optionally of one game) with who took them and what they cost."""
        if self._decisions.height == 0:
            return pl.DataFrame(schema=dict.fromkeys(_SHOT_COLUMNS, pl.Null))
        # Only the games with a frames table are listed; ``load`` still 404s on the others.
        with_frames = {int(p.stem) for p in frame_files(self.settings)}
        valued = self._decisions.filter(
            (pl.col("rule") != "excluded") & pl.col("game_id").is_in(sorted(with_frames))
        )
        if game_id is not None:
            valued = valued.filter(pl.col("game_id") == game_id)
        game_ids = valued["game_id"].unique().to_list()
        context = (
            pl.concat(
                [
                    self._game_frames(g)
                    .filter(pl.col("side") == "ball")
                    .select("shot_id", "period", "off_team_id")
                    for g in game_ids
                ]
            )
            if game_ids
            else pl.DataFrame(
                schema={"shot_id": pl.String, "period": pl.Int64, "off_team_id": pl.Int64}
            )
        )
        return (
            valued.join(context, on="shot_id", how="left")
            .join(self._headlines, on="shot_id", how="left")
            .with_columns(
                shooter=pl.col("shooter_id").replace_strict(self._names, default=None),
                team=pl.col("off_team_id").replace_strict(self._team_names, default=None),
            )
            .select(_SHOT_COLUMNS)
            .sort("shot_id")
        )

    def load(self, shot_id: str) -> BoardState:
        """The decision frame of a valued shot, with no moves."""
        game_id = self._game_of.get(shot_id)
        if game_id is None:
            raise DataNotFoundError(f"shot {shot_id} not found in the decisions tables")
        frames = self._game_frames(game_id).filter(pl.col("shot_id") == shot_id)
        if frames.height == 0:
            raise DataNotFoundError(f"shot {shot_id} has no decision frame (excluded shot?)")
        snapshot = snapshot_from_frame(frames)
        decisions = self._decisions.filter(pl.col("game_id") == game_id)
        original = decision_from_tables(shot_id, decisions, self._game_options(game_id))
        shot_option = original.options[0]
        return BoardState(
            shot_id=shot_id,
            game_id=game_id,
            shooter_id=original.shooter_id,
            decision_frame=original.decision_frame,
            release_frame=original.release_frame,
            rule=original.rule,
            shot_clock=original.shot_clock,
            original=original,
            snapshot=snapshot,
            moves={},
            shot={
                "id": shot_id,
                "game_id": game_id,
                "shooter_id": original.shooter_id,
                "start_frame": original.release_frame,
            },
            shot_zone=shot_option.zone,  # type: ignore[arg-type]
            # Layer 1 derives is_three by geometry when the event's ``three`` is null; the stored
            # option's points equal it (0 mismatches over the 1 351 shots) unless a future
            # decisions table stores points from the event flag against the geometry.
            shot_three=shot_option.points == 3,
        )

    def move(self, state: BoardState, player_id: int, x: float, y: float) -> BoardState:
        """Place a player at ``(x, y)``, clamped to the offensive half court."""
        x = min(max(x, -HALF_LENGTH), 0.0)
        y = min(max(y, -COURT_WIDTH / 2), COURT_WIDTH / 2)
        snap = state.snapshot
        old = snap.player(player_id)  # KeyError if not on court
        new = old.model_copy(
            update={
                "x": x,
                "y": y,
                "vx": BOARD_MOVED_VELOCITY,
                "vy": BOARD_MOVED_VELOCITY,
                "speed": 0.0,
            }
        )

        def swap(side: list[PlayerPos]) -> list[PlayerPos]:
            return [new if p.player_id == player_id else p for p in side]

        update: dict[str, Any] = {"offense": swap(snap.offense), "defense": swap(snap.defense)}
        if player_id == state.shooter_id:
            update["ball"] = snap.ball.model_copy(update={"x": x, "y": y})
        return state.model_copy(
            update={
                "snapshot": snap.model_copy(update=update),
                "moves": {**state.moves, player_id: (x, y)},
            }
        )

    def evaluate(self, state: BoardState) -> Decision:
        """Value the (moved) snapshot; a moved shooter is valued from his new position."""
        from_position = state.shooter_id in state.moves
        return decide_snapshot(
            state.snapshot,
            state.shot,
            self.priors,
            self.model,
            decision_frame=state.decision_frame,
            rule=state.rule,
            shot_zone=None if from_position else state.shot_zone,
            shot_three=None if from_position else state.shot_three,
        )

    def payload(self, state: BoardState, evaluated: Decision) -> dict[str, Any]:
        """JSON-serializable view of the board: court, players, ball, options and the cost."""
        snap = state.snapshot
        players = [
            {
                "player_id": int(p.player_id),
                "team_id": int(p.team_id),
                "side": side,
                "x": float(p.x),
                "y": float(p.y),
                "jersey": self._jerseys.get(p.player_id),
                "name": self._names.get(p.player_id),
                "is_shooter": bool(p.player_id == state.shooter_id),
                "moved": bool(p.player_id in state.moves),
            }
            for side, group in (("offense", snap.offense), ("defense", snap.defense))
            for p in group
        ]
        best = evaluated.best_alt_player_id
        options = [
            {
                "player_id": int(o.player_id),
                "option_type": o.option_type,
                "zone": o.zone,
                "proba": float(o.proba),
                "value": float(o.value),
                "viability": float(o.viability),
                "adjusted_value": float(o.adjusted_value),
                "alternative_type": o.alternative_type,
                "points": int(o.points),
                "x": float(o.x),
                "y": float(o.y),
                "pass_distance": float(o.pass_distance),
                "lane_blocked": bool(o.lane_blocked),
                "is_shooter": bool(o.option_type == "shot"),
                "best_alt": bool(o.option_type == "pass" and o.player_id == best),
            }
            for o in evaluated.options
        ]
        return {
            "shot_id": state.shot_id,
            "game_id": int(state.game_id),
            "shooter_id": int(state.shooter_id),
            "period": int(snap.period),
            "shot_clock": None if state.shot_clock is None else float(state.shot_clock),
            "rule": state.rule,
            "court": court_payload(),
            "players": players,
            "ball": {"x": float(snap.ball.x), "y": float(snap.ball.y), "z": float(snap.ball.z)},
            "moves": [
                {"player_id": int(pid), "x": float(x), "y": float(y)}
                for pid, (x, y) in state.moves.items()
            ],
            "options": options,
            "shot_value": float(evaluated.shot_value),
            "best_alt_player_id": None if best is None else int(best),
            "best_alt_value": (
                None if evaluated.best_alt_value is None else float(evaluated.best_alt_value)
            ),
            "cost": float(evaluated.cost),
            "good_read": None if evaluated.good_read is None else bool(evaluated.good_read),
            "original_cost": float(state.original.cost),
            "delta_cost": float(evaluated.cost - state.original.cost),
        }
