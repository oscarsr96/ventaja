import math

import polars as pl
import pytest
from typer.testing import CliRunner

from ventaja.cli import app
from ventaja.config import Settings
from ventaja.data.load import load_events, load_tracking
from ventaja.decision.align import Aligner
from ventaja.errors import DataNotFoundError, NoTrackingError, VentajaError

SHOT_ID = "shot-114243-1-0"
SHOT_FRAME = 3895
SHOOTER = 35028


def test_snapshot_for_shot_has_five_and_five_oriented(built_fixture: Settings) -> None:
    s = Aligner(114243, built_fixture).snapshot_for_shot(SHOT_ID)
    assert s.frame_idx == SHOT_FRAME
    assert len(s.offense) == 5 and len(s.defense) == 5
    assert s.off_team_id == 1319 and s.def_team_id == 1330
    assert all(p.team_id == 1319 for p in s.offense)
    assert all(p.team_id == 1330 for p in s.defense)
    assert s.possession_id == "possession-114243-1-2"
    assert s.chance_id == "chance-114243-1-3"
    shooter = s.player(SHOOTER)
    assert abs(shooter.x - (-23.53)) < 4 and abs(shooter.y - (-6.66)) < 4
    assert s.shot_clock == pytest.approx(13.88, abs=0.05)


def test_snapshot_on_empty_frame_raises_no_tracking(built_fixture: Settings) -> None:
    frames = (
        load_tracking(114243, built_fixture)
        .select(pl.col("frame_idx").unique().sort())
        .collect()["frame_idx"]
        .to_list()
    )
    present = set(frames)
    empty = next(f for f in range(frames[0], frames[-1] + 1) if f not in present)
    with pytest.raises(NoTrackingError, match=str(empty)):
        Aligner(114243, built_fixture).snapshot(empty)


def test_snapshot_outside_possession_raises(built_fixture: Settings) -> None:
    frames = (
        load_tracking(114243, built_fixture)
        .select(pl.col("frame_idx").unique())
        .collect()["frame_idx"]
        .to_list()
    )
    possessions = load_events(114243, "possessions", built_fixture)
    intervals = list(zip(possessions["start_frame"], possessions["end_frame"], strict=True))
    outside = [f for f in frames if not any(lo <= f <= hi for lo, hi in intervals)]
    if not outside:
        pytest.skip("every tracked frame of the fixture lies inside a possession")
    with pytest.raises(VentajaError, match="outside every possession"):
        Aligner(114243, built_fixture).snapshot(min(outside))


def test_window_returns_consecutive_frames_in_order(built_fixture: Settings) -> None:
    w = Aligner(114243, built_fixture).window(SHOT_FRAME - 25, SHOT_FRAME)
    assert [s.frame_idx for s in w] == sorted(s.frame_idx for s in w)
    assert 1 <= len(w) <= 26
    assert w[-1].frame_idx == SHOT_FRAME
    assert all(len(s.offense) == 5 and len(s.defense) == 5 for s in w)


def test_teammates_of_excludes_player(built_fixture: Settings) -> None:
    s = Aligner(114243, built_fixture).snapshot_for_shot(SHOT_ID)
    mates = s.teammates_of(SHOOTER)
    assert len(mates) == 4 and all(p.player_id != SHOOTER for p in mates)
    assert all(p.team_id == 1319 for p in mates)


def test_player_missing_raises_key_error(built_fixture: Settings) -> None:
    s = Aligner(114243, built_fixture).snapshot_for_shot(SHOT_ID)
    with pytest.raises(KeyError):
        s.player(-1)


def test_snapshot_cli_marks_shooter(
    built_fixture: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(built_fixture.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(built_fixture.build_dir))
    result = CliRunner().invoke(app, ["snapshot", SHOT_ID])
    assert result.exit_code == 0, result.output
    assert f"frame {SHOT_FRAME}" in result.output
    assert sum(" OFF " in line for line in result.output.splitlines()) == 5
    assert sum(" DEF " in line for line in result.output.splitlines()) == 5
    [shooter_line] = [line for line in result.output.splitlines() if str(SHOOTER) in line]
    assert shooter_line.startswith("*")


def test_snapshot_cli_unknown_shot_errors(
    built_fixture: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(built_fixture.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(built_fixture.build_dir))
    result = CliRunner().invoke(app, ["snapshot", "shot-114243-9-99"])
    assert result.exit_code == 1
    assert "error: shot shot-114243-9-99 not found in game 114243" in result.output


def test_snapshot_cli_unparseable_shot_id_asks_for_game(
    built_fixture: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(built_fixture.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(built_fixture.build_dir))
    result = CliRunner().invoke(app, ["snapshot", "bogus"])
    assert result.exit_code == 1
    assert "--game" in result.output


def test_snapshot_outside_possession_raises_when_possession_removed(
    built_fixture: Settings,
) -> None:
    a = Aligner(114243, built_fixture)
    a._possessions = a._possessions.filter(pl.col("id") != "possession-114243-1-2")
    with pytest.raises(VentajaError, match="outside every possession"):
        a.snapshot(SHOT_FRAME)
    # possession-114243-1-2 spans frames 3642..3962; window skips its frames, no error.
    assert a.window(SHOT_FRAME - 25, SHOT_FRAME) == []


def test_snapshot_with_unknown_offense_team_raises(built_fixture: Settings) -> None:
    a = Aligner(114243, built_fixture)
    a._possessions = a._possessions.with_columns(
        off_team_id=pl.when(pl.col("id") == "possession-114243-1-2")
        .then(999)
        .otherwise(pl.col("off_team_id"))
    )
    with pytest.raises(VentajaError, match=r"frame 3895 .*off=999 def=1330"):
        a.snapshot(SHOT_FRAME)


def test_snapshot_for_shot_uses_the_shots_own_possession(built_fixture: Settings) -> None:
    # On real data some shots fall after their possession's end_frame (end-of-period
    # possessions with start_frame == end_frame); the shot must still use its own possession.
    a = Aligner(114243, built_fixture)
    a._possessions = a._possessions.with_columns(
        end_frame=pl.when(pl.col("id") == "possession-114243-1-2")
        .then(SHOT_FRAME - 1)
        .otherwise(pl.col("end_frame"))
    )
    s = a.snapshot_for_shot(SHOT_ID)
    assert s.possession_id == "possession-114243-1-2"
    assert SHOOTER in {p.player_id for p in s.offense}
    shooter = s.player(SHOOTER)
    assert math.hypot(shooter.x - (-23.53), shooter.y - (-6.66)) < 4


def test_snapshot_for_shot_missing_possession_raises(built_fixture: Settings) -> None:
    a = Aligner(114243, built_fixture)
    a._possessions = a._possessions.filter(pl.col("id") != "possession-114243-1-2")
    with pytest.raises(DataNotFoundError, match="possession-114243-1-2"):
        a.snapshot_for_shot(SHOT_ID)
