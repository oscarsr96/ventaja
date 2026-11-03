import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ventaja.board.engine import Board, BoardState, court_payload
from ventaja.config import Settings
from ventaja.data.load import load_decision_options, load_decisions
from ventaja.decision.align import Aligner
from ventaja.decision.cost import decide, decision_from_tables
from ventaja.errors import DataNotFoundError
from ventaja.geometry.court import COURT_WIDTH, HALF_LENGTH
from ventaja.model.snapshot import PlayerPos
from ventaja.value.model import ValueModel
from ventaja.value.params import BOARD_MOVED_VELOCITY
from ventaja.value.priors import Priors

GAME_ID = 114243
SHOT_ID = "shot-114243-1-0"
VALUED_SHOTS = 17


@pytest.fixture(scope="module")
def board(
    fixture_frames_built: Settings, trained_fixture_model: ValueModel, fixture_priors: Priors
) -> Board:
    return Board(fixture_frames_built, model=trained_fixture_model, priors=fixture_priors)


def test_shots_lists_valued_only(board: Board) -> None:
    shots = board.shots()
    assert shots.height == VALUED_SHOTS
    assert shots.columns == [
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
    ]
    assert board.shots(GAME_ID).height == VALUED_SHOTS
    assert board.shots(1).height == 0
    assert shots["shooter"].null_count() == 0 and shots["team"].null_count() == 0


def test_load_unknown_shot_names_it(board: Board) -> None:
    with pytest.raises(DataNotFoundError, match="shot-114243-9-9"):
        board.load("shot-114243-9-9")
    excluded = load_decisions(GAME_ID, board.settings).filter(pl.col("rule") == "excluded")
    assert excluded.height > 0
    with pytest.raises(DataNotFoundError, match=excluded["shot_id"][0]):
        board.load(excluded["shot_id"][0])


def test_evaluate_without_moves_matches_decisions(board: Board) -> None:
    decisions = load_decisions(GAME_ID, board.settings)
    options = load_decision_options(GAME_ID, board.settings)
    for shot_id in board.shots()["shot_id"]:
        got = board.evaluate(board.load(shot_id))
        want = decision_from_tables(shot_id, decisions, options)
        assert got.shot_value == pytest.approx(want.shot_value, abs=1e-6)
        assert got.best_alt_value == pytest.approx(want.best_alt_value, abs=1e-6)
        assert got.cost == pytest.approx(want.cost, abs=1e-6)
        assert got.good_read == want.good_read
        assert len(got.options) == len(want.options)
        for g, w in zip(got.options, want.options, strict=True):
            assert g.player_id == w.player_id and g.zone == w.zone
            assert g.adjusted_value == pytest.approx(w.adjusted_value, abs=1e-6)


def test_decide_delegates(
    fixture_frames_built: Settings, trained_fixture_model: ValueModel, fixture_priors: Priors
) -> None:
    decisions = load_decisions(GAME_ID, fixture_frames_built)
    options = load_decision_options(GAME_ID, fixture_frames_built)
    aligner = Aligner(GAME_ID, fixture_frames_built)
    for shot_id in decisions.filter(pl.col("rule") != "excluded")["shot_id"]:
        d = decide(aligner, shot_id, fixture_priors, trained_fixture_model)
        want = decision_from_tables(shot_id, decisions, options)
        assert d is not None
        assert d.model_dump(exclude={"options"}) == pytest.approx(
            want.model_dump(exclude={"options"})
        )
        assert [o.adjusted_value for o in d.options] == pytest.approx(
            [o.adjusted_value for o in want.options]
        )


def test_move_clamps_to_court(board: Board) -> None:
    state = board.load(SHOT_ID)
    defender = state.snapshot.defense[0].player_id
    far = board.move(state, defender, 50.0, 99.0)
    p = far.snapshot.player(defender)
    assert (p.x, p.y) == (0.0, COURT_WIDTH / 2)
    far = board.move(state, defender, -99.0, -99.0)
    p = far.snapshot.player(defender)
    assert (p.x, p.y) == (-HALF_LENGTH, -COURT_WIDTH / 2)
    assert far.moves == {defender: (-HALF_LENGTH, -COURT_WIDTH / 2)}
    assert state.moves == {} and state.snapshot.player(defender) != p  # original untouched


def test_moved_player_has_zero_velocity(board: Board) -> None:
    state = board.load(SHOT_ID)
    mate = state.snapshot.teammates_of(state.shooter_id)[0]
    moved = board.move(state, mate.player_id, -30.0, 5.0)
    p = moved.snapshot.player(mate.player_id)
    assert p.vx == p.vy == BOARD_MOVED_VELOCITY
    assert p.speed == 0.0
    assert (p.is_detected, p.pred_error) == (mate.is_detected, mate.pred_error)
    assert moved.snapshot.ball == state.snapshot.ball  # a teammate does not carry the ball
    again = board.move(moved, mate.player_id, -20.0, 1.0)
    assert again.moves == {mate.player_id: (-20.0, 1.0)}


def test_move_shooter_revalues_from_position(board: Board) -> None:
    state = board.load(SHOT_ID)
    before = board.evaluate(state)
    moved = board.move(state, state.shooter_id, -41.0, 0.0)
    ball = moved.snapshot.ball
    assert (ball.x, ball.y) == (-41.0, 0.0)
    assert ball.z == state.snapshot.ball.z and ball.speed == state.snapshot.ball.speed
    after = board.evaluate(moved)
    assert after.options[0].zone == "restricted_area"
    assert after.shot_value > before.shot_value


def _open_pass_case(board: Board) -> tuple[BoardState, Any, PlayerPos] | None:
    """A shot with a viable, unblocked pass, its option and the receiver's nearest defender."""
    for shot_id in board.shots()["shot_id"]:
        state = board.load(shot_id)
        for o in board.evaluate(state).options[1:]:
            if o.adjusted_value <= 0.0 or o.lane_blocked:
                continue
            near = min(state.snapshot.defense, key=lambda d: (d.x - o.x) ** 2 + (d.y - o.y) ** 2)
            return state, o, near
    return None


def test_move_defender_changes_pass_value(board: Board) -> None:
    case = _open_pass_case(board)
    assert case is not None
    state, option, defender = case
    shooter = state.snapshot.player(state.shooter_id)
    middle = ((shooter.x + option.x) / 2, (shooter.y + option.y) / 2)
    moved = board.move(state, defender.player_id, *middle)
    after = next(
        o
        for o in board.evaluate(moved).options
        if o.option_type == "pass" and o.player_id == option.player_id
    )
    assert after.lane_blocked or after.adjusted_value < option.adjusted_value


def test_payload_is_json_serializable(board: Board) -> None:
    state = board.load(SHOT_ID)
    moved = board.move(state, state.shooter_id, -41.0, 0.0)
    evaluated = board.evaluate(moved)
    payload = board.payload(moved, evaluated)
    assert json.loads(json.dumps(payload)) == payload
    assert payload["court"] == court_payload()
    assert len(payload["players"]) == 10 and len(payload["options"]) == 5
    assert sum(p["moved"] for p in payload["players"]) == 1
    assert [p["is_shooter"] for p in payload["players"]].count(True) == 1
    assert payload["options"][0]["is_shooter"] is True
    assert payload["delta_cost"] == pytest.approx(evaluated.cost - state.original.cost)
    assert payload["moves"] == [{"player_id": state.shooter_id, "x": -41.0, "y": 0.0}]


def test_names_fall_back_to_player_cards(
    tmp_path: Path, trained_fixture_model: ValueModel, fixture_priors: Priors
) -> None:
    """A clean clone has no ``meta/``: names and teams come from the packaged cards."""
    clean = Settings(data_dir=tmp_path / "raw", build_dir=tmp_path / "build")
    clean_board = Board(clean, model=trained_fixture_model, priors=fixture_priors)
    shots = clean_board.shots()
    assert shots.height > 0
    assert shots["shooter"].null_count() == 0 and shots["team"].null_count() == 0
    state = clean_board.load(shots["shot_id"][0])
    payload = clean_board.payload(state, clean_board.evaluate(state))
    shooter = next(p for p in payload["players"] if p["is_shooter"])
    assert shooter["name"] == shots["shooter"][0]
    assert all(p["name"] for p in payload["players"])
    assert all(p["jersey"] is not None for p in payload["players"])  # from the packaged roster


def test_clean_clone_builds_priors_from_packaged_file(tmp_path: Path) -> None:
    """No build dir, no aggregates: the priors packaged next to the model are used."""
    clean = Settings(data_dir=tmp_path / "raw", build_dir=tmp_path / "build")
    packaged = Board(clean)
    shot_id = packaged.shots()["shot_id"][0]
    game_id = int(shot_id.split("-")[1])
    want = decision_from_tables(
        shot_id, load_decisions(game_id, clean), load_decision_options(game_id, clean)
    )
    got = packaged.evaluate(packaged.load(shot_id))
    assert got.cost == pytest.approx(want.cost, abs=1e-6)
    assert got.shot_value == pytest.approx(want.shot_value, abs=1e-6)
    assert got.best_alt_value == pytest.approx(want.best_alt_value, abs=1e-6)
