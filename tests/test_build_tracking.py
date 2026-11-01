import gzip
import json
import shutil
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ventaja.config import Settings
from ventaja.data.build import TRACKING_SCHEMA, build_tracking, tracking_relpath
from ventaja.data.load import frame_range, load_tracking
from ventaja.errors import CorruptFileError, DataNotFoundError

EXPECTED_COLUMNS = [
    "game_id",
    "frame_idx",
    "wall_clock",
    "game_clock",
    "game_clock_stopped",
    "period",
    "shot_clock",
    "side",
    "player_id",
    "jersey",
    "x",
    "y",
    "z",
    "speed",
    "is_detected",
    "pred_error",
]
FIRST_SHOT_FRAME = 3895


def test_tracking_relpath() -> None:
    assert tracking_relpath(114243) == "matches/114243/114243_tracking_data.jsonl.gz"


def test_build_tracking_long_format_schema(built_fixture: Settings) -> None:
    df = pl.read_parquet(built_fixture.tracking_parquet(114243))
    assert df.columns == EXPECTED_COLUMNS
    assert dict(df.schema) == dict(TRACKING_SCHEMA)
    assert df.schema["side"] == pl.Enum(["home", "away", "ball"])
    assert df["game_id"].unique().to_list() == [114243]


def test_build_tracking_one_row_per_player_and_ball(built_fixture: Settings) -> None:
    df = pl.read_parquet(built_fixture.tracking_parquet(114243))
    per_frame = df.group_by("frame_idx").len()
    assert per_frame.height == 1944
    assert per_frame["len"].max() == 11
    assert per_frame["len"].min() >= 1
    assert (per_frame["len"] == 11).mean() >= 0.95
    sides = df.group_by("side").len().sort("side")
    assert dict(zip(sides["side"], sides["len"], strict=True)) == {
        "home": 5 * 1944,
        "away": 5 * 1944,
        "ball": 1944,
    }
    ball = df.filter(pl.col("side") == "ball")
    assert ball["player_id"].is_null().all()
    assert ball["jersey"].is_null().all()
    players = df.filter(pl.col("side") != "ball")
    assert players["player_id"].is_not_null().all()
    assert players["jersey"].is_not_null().all()
    assert df["shot_clock"].is_null().sum() == 65 * 11


def test_build_tracking_values_match_raw_first_frame(built_fixture: Settings) -> None:
    df = pl.read_parquet(built_fixture.tracking_parquet(114243))
    first = df.filter(pl.col("frame_idx") == 3820)
    assert first.height == 11
    row = first.filter(pl.col("jersey") == "33").row(0, named=True)
    assert row["side"] == "home"
    assert row["player_id"] == 18503
    assert row["wall_clock"] == 152800
    assert row["game_clock"] == pytest.approx(559.536)
    assert row["game_clock_stopped"] is False
    assert row["period"] == 1
    assert row["x"] == pytest.approx(27.835875984251967)
    assert row["y"] == pytest.approx(-2.361307619750656)
    assert row["z"] == 0.0
    assert row["speed"] == pytest.approx(3.7614316765091864)
    assert row["is_detected"] is True
    assert row["pred_error"] == pytest.approx(1.390512221128609)
    undetected = first.filter(pl.col("jersey") == "8").row(0, named=True)
    assert undetected["is_detected"] is False


def test_build_tracking_applies_player_aliases(built_fixture: Settings) -> None:
    # The fixture aliases file maps 92815 -> 59180; 59180 is already canonical.
    ids = pl.read_parquet(built_fixture.tracking_parquet(114243))["player_id"].unique()
    assert 59180 in ids.to_list()


def _tmp_data_dir(tmp_path: Path, fixture_settings: Settings) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(fixture_settings.data_dir, data_dir)
    return data_dir


def _frame(frame_idx: int, **overrides: Any) -> dict[str, Any]:
    player = {
        "xyz": [1.0, 2.0, 0.0],
        "speed": 3,
        "predError": -0.5,
        "jersey": "8",
        "isDetected": 1,
        "playerId": 35028,
    }
    frame: dict[str, Any] = {
        "frameIdx": frame_idx,
        "wallClock": frame_idx * 40,
        "gameClock": 600.0,
        "gameClockStopped": False,
        "period": 1,
        "homePlayers": [player],
        "awayPlayers": [],
        "ball": {"xyz": [4.0, 5.0, 2.5], "speed": 9.0, "isDetected": 0.0, "predError": 1.2},
        "shotClock": 24.0,
    }
    frame.update(overrides)
    return frame


def _write_tracking(data_dir: Path, frames: list[dict[str, Any]]) -> None:
    path = data_dir / tracking_relpath(114243)
    with gzip.open(path, "wt") as fh:
        for frame in frames:
            fh.write(json.dumps(frame) + "\n")


def test_build_tracking_skips_empty_frames_and_aliases(
    fixture_settings: Settings, tmp_path: Path
) -> None:
    data_dir = _tmp_data_dir(tmp_path, fixture_settings)
    with (data_dir / "player_id_aliases.csv").open("a") as fh:
        fh.write("35028,Some Player,999999,Some Player,1\n")
    empty = {"homePlayers": [], "awayPlayers": [], "ball": {}, "shotClock": None}
    _write_tracking(data_dir, [_frame(10, **empty), _frame(11), _frame(12, **empty)])
    settings = Settings(data_dir=data_dir, build_dir=tmp_path / "build")

    df = pl.read_parquet(build_tracking(114243, settings))
    assert df["frame_idx"].unique().to_list() == [11]
    assert df.height == 2
    player = df.filter(pl.col("side") == "home").row(0, named=True)
    assert player["player_id"] == 999999
    assert player["speed"] == 3.0
    assert player["pred_error"] == -0.5
    ball = df.filter(pl.col("side") == "ball").row(0, named=True)
    assert (ball["x"], ball["y"], ball["z"]) == (4.0, 5.0, 2.5)
    assert ball["is_detected"] is False
    assert ball["player_id"] is None


def test_build_tracking_all_empty_frames_keeps_schema(
    fixture_settings: Settings, tmp_path: Path
) -> None:
    data_dir = _tmp_data_dir(tmp_path, fixture_settings)
    empty = {"homePlayers": [], "awayPlayers": [], "ball": {}, "shotClock": None}
    _write_tracking(data_dir, [_frame(10, **empty)])
    settings = Settings(data_dir=data_dir, build_dir=tmp_path / "build")

    df = pl.read_parquet(build_tracking(114243, settings))
    assert df.height == 0
    assert dict(df.schema) == dict(TRACKING_SCHEMA)


def test_build_tracking_truncated_gzip_raises_corrupt(
    fixture_settings: Settings, tmp_path: Path
) -> None:
    data_dir = _tmp_data_dir(tmp_path, fixture_settings)
    gz = data_dir / tracking_relpath(114243)
    raw = gz.read_bytes()
    gz.write_bytes(raw[: len(raw) // 2])
    settings = Settings(data_dir=data_dir, build_dir=tmp_path / "build")

    with pytest.raises(CorruptFileError, match="ventaja data pull") as exc:
        build_tracking(114243, settings)
    assert str(gz) in str(exc.value)
    assert not settings.tracking_parquet(114243).exists()


def test_build_tracking_missing_raw_raises_with_hint(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", build_dir=tmp_path / "build")
    with pytest.raises(DataNotFoundError, match="ventaja data pull"):
        build_tracking(114243, settings)


def test_load_tracking_is_lazy_and_frame_range_matches_excerpt(built_fixture: Settings) -> None:
    lf = load_tracking(114243, built_fixture)
    assert isinstance(lf, pl.LazyFrame)
    assert lf.collect_schema().names() == EXPECTED_COLUMNS
    lo, hi = frame_range(114243, built_fixture)
    assert lo >= FIRST_SHOT_FRAME - 75
    assert (lo, hi) == (3820, 17275)


def test_load_tracking_missing_raises_with_build_hint(fixture_settings: Settings) -> None:
    with pytest.raises(DataNotFoundError, match="ventaja data build --game 114243"):
        load_tracking(114243, fixture_settings)
    with pytest.raises(DataNotFoundError, match="ventaja data build --game 114243"):
        frame_range(114243, fixture_settings)
