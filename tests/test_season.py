"""Tests for the season profile crossed with the tracked games."""

import polars as pl
import pytest

from ventaja.config import Settings
from ventaja.data.load import load_decision_options
from ventaja.profile.season import MAIN_ZONES, season_profile, tracked_zone_mix, zone_shift

GAME_ID = 114243
ZONE_COLS = [f"zone_{z}_attempts" for z in MAIN_ZONES]


def _shots_row(player_id: int, team_id: int | None, **over: float) -> dict[str, float | int | None]:
    base: dict[str, float | int | None] = {
        "player_id": player_id,
        "team_id": team_id,
        "games_played": 10,
        "attempts": 100,
        "mades": 40,
        "three_attempts": 50,
        "cns_attempts": 20,
        "contested_attempts": 30,
        "cl_open_attempts": 25,
        "cl_open_mades": 10,
        "zone_restricted_area_attempts": 20,
        "zone_paint_non_ra_attempts": 10,
        "zone_mid_range_attempts": 20,
        "zone_corner_3_attempts": 10,
        "zone_above_break_3_attempts": 40,
        "avg_attempts_distance": 20.0,
    }
    return base | over


def _shots(rows: list[dict[str, float | int | None]]) -> pl.DataFrame:
    return pl.DataFrame(rows, infer_schema_length=None)


def test_season_profile_sums_team_rows_not_total() -> None:
    agg = _shots(
        [
            _shots_row(7, 1, attempts=100, mades=40, games_played=6, avg_attempts_distance=10.0),
            _shots_row(7, 2, attempts=300, mades=120, games_played=4, avg_attempts_distance=20.0),
            _shots_row(7, None, attempts=400, mades=160, games_played=10),
            _shots_row(8, 1),
        ]
    )
    prof = season_profile(7, agg, None)
    assert prof["season_attempts"] == 400
    assert prof["season_games"] == 10
    assert prof["season_fg"] == pytest.approx(0.4)
    assert prof["season_avg_distance"] == pytest.approx(17.5)


def test_missing_player_gives_nulls() -> None:
    prof = season_profile(999, _shots([_shots_row(7, 1)]), None)
    assert len(prof) == 17
    assert all(v is None for v in prof.values())


def test_zero_denominators_give_none() -> None:
    zeros = dict.fromkeys(ZONE_COLS, 0)
    agg = _shots(
        [
            _shots_row(
                7,
                1,
                attempts=0,
                mades=0,
                three_attempts=0,
                cns_attempts=0,
                contested_attempts=0,
                cl_open_attempts=0,
                cl_open_mades=0,
                **zeros,
            )
        ]
    )
    drives = pl.DataFrame(
        {
            "player_id": [7],
            "team_id": [1],
            "games_played": [3],
            "total_drives": [0],
            "end_type_kickout_count": [0],
            "end_type_pullup_count": [0],
            "end_type_shot_near_basket_count": [0],
        }
    )
    prof = season_profile(7, agg, drives)
    assert prof["season_games"] == 10
    assert prof["season_attempts"] == 0
    assert prof["season_drives"] == 0
    for key, value in prof.items():
        if key not in ("season_games", "season_attempts", "season_drives"):
            assert value is None, key


def test_drives_block() -> None:
    agg = _shots([_shots_row(7, 1)])
    drives = pl.DataFrame(
        {
            "player_id": [7, 7],
            "team_id": [1, 2],
            "games_played": [3, 2],
            "total_drives": [30, 10],
            "end_type_kickout_count": [4, 4],
            "end_type_pullup_count": [8, 0],
            "end_type_shot_near_basket_count": [10, 10],
        }
    )
    prof = season_profile(7, agg, drives)
    assert prof["season_drives"] == 40
    assert prof["season_drive_kickout_share"] == pytest.approx(0.2)
    assert prof["season_drive_pullup_share"] == pytest.approx(0.2)
    assert prof["season_drive_rim_share"] == pytest.approx(0.5)


def test_drives_none_path() -> None:
    prof = season_profile(7, _shots([_shots_row(7, 1)]), None)
    assert prof["season_attempts"] == 100
    for key in (
        "season_drives",
        "season_drive_kickout_share",
        "season_drive_pullup_share",
        "season_drive_rim_share",
    ):
        assert prof[key] is None
    absent = pl.DataFrame(
        {
            "player_id": [8],
            "team_id": [1],
            "games_played": [3],
            "total_drives": [5],
            "end_type_kickout_count": [1],
            "end_type_pullup_count": [1],
            "end_type_shot_near_basket_count": [1],
        }
    )
    assert season_profile(7, _shots([_shots_row(7, 1)]), absent)["season_drives"] is None


def test_tracked_zone_mix_on_fixture(fixture_curves_built: Settings) -> None:
    options = load_decision_options(GAME_ID, fixture_curves_built)
    shots = options.filter(pl.col("option_type") == "shot")
    counts = shots.group_by("player_id").len().filter(pl.col("len") >= 2)
    assert counts.height > 0
    pid, n = counts.row(0)
    mix = tracked_zone_mix(pid, options)
    assert mix["tracked_attempts"] == n
    total = sum(v for k, v in mix.items() if k.startswith("tracked_zone_share_") and v is not None)
    assert total == pytest.approx(1.0, abs=1e-9)
    assert "tracked_zone_share_other" in mix


def test_tracked_zone_mix_groups_other_and_absent() -> None:
    options = pl.DataFrame(
        {
            "player_id": [1, 1, 1, 1, 2],
            "option_type": ["shot", "shot", "shot", "pass", "pass"],
            "zone": ["mid_range", "far", "backcourt", "mid_range", "mid_range"],
        }
    )
    mix = tracked_zone_mix(1, options)
    assert mix["tracked_attempts"] == 3
    assert mix["tracked_zone_share_mid_range"] == pytest.approx(1 / 3)
    assert mix["tracked_zone_share_other"] == pytest.approx(2 / 3)
    none = tracked_zone_mix(2, options)
    assert none["tracked_attempts"] == 0
    assert none["tracked_zone_share_mid_range"] is None


def test_zone_shift() -> None:
    season: dict[str, float | int | None] = {f"season_zone_share_{z}": 0.2 for z in MAIN_ZONES}
    season["season_zone_share_corner_3"] = None
    tracked: dict[str, float | None] = {f"tracked_zone_share_{z}": 0.5 for z in MAIN_ZONES}
    tracked["tracked_zone_share_mid_range"] = None
    shift = zone_shift(season, tracked)
    assert shift["shift_restricted_area"] == pytest.approx(0.3)
    assert shift["shift_corner_3"] is None
    assert shift["shift_mid_range"] is None
    assert len(shift) == 5
