import json
import shutil
from pathlib import Path

import polars as pl
import pytest

from ventaja.config import Settings
from ventaja.data.build import EVENT_TABLES, build_events, to_snake
from ventaja.data.load import apply_aliases


@pytest.mark.parametrize(
    ("camel", "snake"),
    [
        ("offPlayerIds", "off_player_ids"),
        ("closestDefLoc", "closest_def_loc"),
        ("endLoc", "end_loc"),
        ("gameId", "game_id"),
        ("isDetected", "is_detected"),
        ("xyz", "xyz"),
        ("startFrame", "start_frame"),
        ("leftHoop", "left_hoop"),
    ],
)
def test_to_snake(camel: str, snake: str) -> None:
    assert to_snake(camel) == snake


def test_build_events_writes_twenty_parquets_in_snake_case(fixture_settings: Settings) -> None:
    out = build_events(114243, fixture_settings)
    assert set(out) == set(EVENT_TABLES)
    assert len(EVENT_TABLES) == 20
    for table, path in out.items():
        assert path == fixture_settings.events_parquet(114243, table)
        assert path.exists()
    shots = pl.read_parquet(out["shots"])
    assert {"start_frame", "shooter_id", "off_team_id", "loc_x", "loc_y", "shot_clock"} <= set(
        shots.columns
    )
    assert "location" not in shots.columns
    assert shots.height == 159
    assert shots.filter(pl.col("loc_x").is_null()).height == 3
    assert shots.filter(pl.col("loc_y").is_null()).height == 3


def test_build_events_columns_are_snake_case_with_game_id(built_fixture: Settings) -> None:
    for table in EVENT_TABLES:
        df = pl.read_parquet(built_fixture.events_parquet(114243, table))
        assert "game_id" in df.columns, table
        assert df["game_id"].unique().to_list() == [114243], table
        assert all(c == c.lower() for c in df.columns), (table, df.columns)


def test_build_events_splits_loc_pairs_and_keeps_lists(built_fixture: Settings) -> None:
    possessions = pl.read_parquet(built_fixture.events_parquet(114243, "possessions"))
    assert {"end_loc_x", "end_loc_y"} <= set(possessions.columns)
    assert possessions.schema["off_player_ids"] == pl.List(pl.Int64)
    assert possessions.schema["def_player_ids"] == pl.List(pl.Int64)

    touches = pl.read_parquet(built_fixture.events_parquet(114243, "touches"))
    for prefix in ("loc", "end_loc", "closest_def_loc", "end_closest_def_loc"):
        assert {f"{prefix}_x", f"{prefix}_y"} <= set(touches.columns)
        assert touches.schema[f"{prefix}_x"] == pl.Float64
    assert isinstance(touches.schema["outcomes"], pl.List)
    assert isinstance(touches.schema["regions_in"], pl.List)

    passes = pl.read_parquet(built_fixture.events_parquet(114243, "passes"))
    assert {"passer_loc_x", "passer_loc_y", "receiver_loc_x", "receiver_loc_y"} <= set(
        passes.columns
    )


def test_build_events_shot_location_matches_raw(built_fixture: Settings) -> None:
    shots = pl.read_parquet(built_fixture.events_parquet(114243, "shots"))
    first = shots.filter(pl.col("id") == "shot-114243-1-0").row(0, named=True)
    assert first["loc_x"] == pytest.approx(-23.529773622047244)
    assert first["loc_y"] == pytest.approx(-6.657798146325459)


def test_build_events_is_idempotent(fixture_settings: Settings) -> None:
    first = pl.read_parquet(build_events(114243, fixture_settings)["shots"])
    second = pl.read_parquet(build_events(114243, fixture_settings)["shots"])
    assert first.equals(second)


def _copy_fixture(tmp_path: Path, fixture_settings: Settings) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(fixture_settings.data_dir, data_dir)
    return data_dir


def test_build_events_applies_player_aliases(fixture_settings: Settings, tmp_path: Path) -> None:
    data_dir = _copy_fixture(tmp_path, fixture_settings)
    with (data_dir / "player_id_aliases.csv").open("a") as fh:
        fh.write("35028,Some Shooter,999999,Some Shooter,1\n")
    settings = Settings(data_dir=data_dir, build_dir=tmp_path / "build")
    out = build_events(114243, settings)

    shooters = pl.read_parquet(out["shots"])["shooter_id"].to_list()
    assert 35028 not in shooters
    assert 999999 in shooters

    possessions = pl.read_parquet(out["possessions"])
    off = possessions.filter(pl.col("id") == "possession-114243-1-2")["off_player_ids"].item()
    assert 999999 in off.to_list()
    assert 35028 not in possessions["off_player_ids"].explode().to_list()


def test_build_events_handles_empty_table(fixture_settings: Settings, tmp_path: Path) -> None:
    data_dir = _copy_fixture(tmp_path, fixture_settings)
    events_path = data_dir / "matches/114243/114243_dynamic_events.json"
    events = json.loads(events_path.read_text())
    events["timeouts"] = []
    events_path.write_text(json.dumps(events))
    settings = Settings(data_dir=data_dir, build_dir=tmp_path / "build")

    out = build_events(114243, settings)
    timeouts = pl.read_parquet(out["timeouts"])
    assert timeouts.height == 0
    assert {"id", "game_id"} <= set(timeouts.columns)


def test_apply_aliases_skips_team_and_event_ids() -> None:
    df = pl.DataFrame(
        {
            "id": ["a"],
            "game_id": [7],
            "team_id": [7],
            "off_team_id": [7],
            "def_team_id": [7],
            "shooter_id": [7],
            "off_player_ids": [[7, 8]],
            "def_player_ids": [[9, 7]],
            "period": [7],
        }
    )
    out = apply_aliases(df, {7: 70})
    row = out.row(0, named=True)
    assert row["shooter_id"] == 70
    assert row["off_player_ids"] == [70, 8]
    assert row["def_player_ids"] == [9, 70]
    for col in ("game_id", "team_id", "off_team_id", "def_team_id", "period"):
        assert row[col] == 7, col


def test_apply_aliases_keeps_nulls_and_unmapped() -> None:
    df = pl.DataFrame({"passer_id": [1, None, 3]}, schema={"passer_id": pl.Int64})
    out = apply_aliases(df, {3: 30})
    assert out["passer_id"].to_list() == [1, None, 30]
    assert out.schema["passer_id"] == pl.Int64
