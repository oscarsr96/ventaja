"""Tests for the per-player, per-team and league aggregates of the decisions."""

import polars as pl
import pytest
from helpers import make_decisions, make_summaries

from ventaja.config import Settings
from ventaja.data.load import load_curve_summaries, load_decisions
from ventaja.profile.aggregate import league_row, player_table, team_table

GAME_ID = 114243


def _row(table: pl.DataFrame, player_id: int) -> dict[str, object]:
    return table.filter(pl.col("player_id") == player_id).row(0, named=True)


def _two_players() -> tuple[pl.DataFrame, pl.DataFrame]:
    decisions = make_decisions(
        [
            {
                "shot_id": "a1",
                "cost": 0.5,
                "shot_clock": 20.0,
                "best_alt_type": "rim_cut",
                "good_read": False,
            },
            {
                "shot_id": "a2",
                "cost": 0.3,
                "shot_clock": 10.0,
                "best_alt_type": "rim_cut",
                "good_read": False,
            },
            {
                "shot_id": "a3",
                "cost": 0.0,
                "shot_clock": 3.0,
                "best_alt_type": "post",
                "good_read": True,
            },
            {"shot_id": "b1", "shooter_id": 20, "cost": 0.1, "shot_clock": 12.0, "good_read": True},
            {"shot_id": "x1", "rule": "excluded", "cost": 9.0},
        ]
    )
    summaries = make_summaries(
        [
            {
                "shot_id": "a1",
                "verdict": "late",
                "held_to_decision": True,
                "release_lag_seconds": 0.8,
            },
            {"shot_id": "a2", "verdict": "during"},
            {"shot_id": "b1"},
        ]
    )
    return decisions, summaries


def test_player_table_counts_and_means() -> None:
    table = player_table(*_two_players())
    assert table["player_id"].to_list() == [10, 20]  # n_shots desc
    a = _row(table, 10)
    assert a["n_shots"] == 3 and a["n_readable"] == 3
    assert a["good_read_share"] == pytest.approx(1 / 3)
    assert a["mean_cost"] == pytest.approx((0.5 + 0.3 + 0.0) / 3)
    assert a["total_cost"] == pytest.approx(0.8)
    assert a["cost_24-14"] == pytest.approx(0.5) and a["n_24-14"] == 1
    assert a["cost_14-6"] == pytest.approx(0.3)
    assert a["cost_6-0"] == pytest.approx(0.0)
    assert a["n_alt_rim_cut"] == 2 and a["cost_alt_rim_cut"] == pytest.approx(0.4)
    assert a["n_alt_post"] == 0 and a["cost_alt_post"] is None  # post cost 0.0 is not > tolerance
    assert a["ignored_alt"] == "rim_cut"
    assert a["n_with_summary"] == 2 and a["n_late_held"] == 1
    assert a["late_held_share"] == pytest.approx(0.5) and a["mean_lag_held"] == pytest.approx(0.8)
    assert a["n_during"] == 1 and a["during_share"] == pytest.approx(0.5)
    b = _row(table, 20)
    assert b["cost_24-14"] is None and b["n_24-14"] == 0  # empty bucket is null, not 0
    assert b["n_14-6"] == 1
    assert b["late_held_share"] == 0.0 and b["mean_lag_held"] is None


def test_null_good_read_and_clock_excluded_but_counted() -> None:
    decisions = make_decisions(
        [
            {
                "shot_id": "n1",
                "good_read": None,
                "cost": 0.0,
                "shot_clock": None,
                "best_alt_type": None,
            },
            {"shot_id": "n2", "good_read": True, "cost": 0.2, "shot_clock": 10.0},
        ]
    )
    row = _row(player_table(decisions, make_summaries([])), 10)
    assert row["n_shots"] == 2 and row["n_readable"] == 1
    assert row["good_read_share"] == 1.0
    assert row["mean_cost"] == pytest.approx(0.2)  # the unreadable 0 does not dilute it
    assert row["total_cost"] == pytest.approx(0.2)
    assert row["n_clock_known"] == 1
    assert row["n_14-6"] == 1 and row["n_24-14"] == 0
    assert row["n_with_summary"] == 0 and row["late_held_share"] is None


def test_single_shot_player_has_no_division_by_zero() -> None:
    decisions = make_decisions(
        [
            {
                "shot_id": "s",
                "good_read": None,
                "cost": 0.0,
                "shot_clock": None,
                "best_alt_type": None,
            }
        ]
    )
    row = _row(player_table(decisions, make_summaries([])), 10)
    assert row["n_shots"] == 1 and row["n_readable"] == 0
    for key in (
        "good_read_share",
        "mean_cost",
        "mean_shot_value",
        "mean_best_alt_value",
        "cost_24-14",
        "cost_14-6",
        "cost_6-0",
        "late_held_share",
        "during_share",
        "mean_lag_held",
        "ignored_alt",
    ):
        assert row[key] is None, key


def test_ignored_alt_tie_follows_alt_types_order() -> None:
    decisions = make_decisions(
        [
            {"shot_id": "p", "best_alt_type": "post", "cost": 0.5},
            {"shot_id": "e", "best_alt_type": "extra_pass", "cost": 0.5},
        ]
    )
    assert _row(player_table(decisions, make_summaries([])), 10)["ignored_alt"] == "extra_pass"


def test_team_table_uses_meta_team() -> None:
    decisions = make_decisions(
        [
            {"shot_id": "g1", "game_id": 1, "cost": 0.4},
            {"shot_id": "g2", "game_id": 2, "cost": 0.2},
            {"shot_id": "g3", "game_id": 2, "shooter_id": 30, "cost": 0.6},
        ]
    )
    meta = pl.DataFrame(
        {
            "game_id": [1, 2, 2],
            "team_id": [100, 200, 200],
            "player_id": [10, 10, 30],
            "first_name": ["A", "A", "C"],
            "last_name": ["A", "A", "C"],
            "jersey": [1, 1, 3],
        }
    )
    table = team_table(decisions, make_summaries([]), meta)
    assert table["team_id"].to_list() == [100, 200]
    assert table["n_shots"].to_list() == [1, 2]
    assert table["n_players"].to_list() == [1, 2]
    assert table["mean_cost"].to_list() == pytest.approx([0.4, 0.4])


def test_league_row_matches_decisions_mean(fixture_curves_built: Settings) -> None:
    decisions = load_decisions(GAME_ID, fixture_curves_built)
    summaries = load_curve_summaries(GAME_ID, fixture_curves_built)
    row = league_row(decisions, summaries)
    valid = decisions.filter((pl.col("rule") != "excluded") & pl.col("good_read").is_not_null())
    assert row["mean_cost"] == pytest.approx(valid["cost"].mean())
    assert row["n_shots"] == decisions.filter(pl.col("rule") != "excluded").height
    assert "player_id" not in row


def test_bucket_means_ignore_unreadable_rows() -> None:
    decisions = make_decisions(
        [
            {"shot_id": "r", "good_read": False, "cost": 0.4, "shot_clock": 3.0},
            {
                "shot_id": "u",
                "good_read": None,
                "cost": 0.0,
                "shot_clock": 4.0,
                "best_alt_type": None,
            },
        ]
    )
    row = _row(player_table(decisions, make_summaries([])), 10)
    assert row["n_6-0"] == 1 and row["cost_6-0"] == pytest.approx(0.4)
    assert row["n_clock_known"] == 2


def test_league_row_on_empty_frame_keeps_all_keys() -> None:
    row = league_row(make_decisions([]), make_summaries([]))
    assert row["n_shots"] == 0 and row["mean_cost"] is None and row["n_6-0"] == 0
    assert "ignored_alt" in row
