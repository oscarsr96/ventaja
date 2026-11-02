import polars as pl
import pytest

from ventaja.config import Settings
from ventaja.data.build import build_aggregates, build_meta
from ventaja.data.duck import connect
from ventaja.data.load import load_aggregates, load_meta
from ventaja.errors import DataNotFoundError

PLAYER_ROWS = 24
NULL_TEAM_ROWS = 5  # season-total rows (empty team_id) in the CSV


def test_build_meta_games_players_matches(fixture_settings: Settings) -> None:
    out = build_meta(114243, fixture_settings)
    games = pl.read_parquet(out["games"])
    players = pl.read_parquet(out["players"])
    assert games.height == 1 and games["home_team_id"][0] == 1330
    assert players.height == PLAYER_ROWS and players["team_id"].n_unique() == 2
    matches = pl.read_parquet(out["matches"])
    assert matches.select("home_score", "away_score").row(0) == (83, 68)


def test_build_meta_is_idempotent(fixture_settings: Settings) -> None:
    build_meta(114243, fixture_settings)
    out = build_meta(114243, fixture_settings)
    assert pl.read_parquet(out["players"]).height == PLAYER_ROWS
    assert pl.read_parquet(out["games"]).height == 1


def test_build_aggregates_shots_only_in_fixture(fixture_settings: Settings) -> None:
    out = build_aggregates(fixture_settings)
    assert set(out) == {"shots"}
    agg = pl.read_parquet(out["shots"])
    assert agg.height == 326
    assert agg.filter(pl.col("team_id").is_null()).height == NULL_TEAM_ROWS


def test_load_meta_and_aggregates_need_build(fixture_settings: Settings) -> None:
    with pytest.raises(DataNotFoundError, match="ventaja data build"):
        load_meta("games", fixture_settings)
    with pytest.raises(DataNotFoundError, match="ventaja data build"):
        load_aggregates("shots", fixture_settings)
    build_meta(114243, fixture_settings)
    build_aggregates(fixture_settings)
    assert load_meta("games", fixture_settings).height == 1
    assert load_aggregates("shots", fixture_settings).height == 326


def test_duck_has_meta_and_aggregate_views(built_fixture: Settings) -> None:
    con = connect(built_fixture)
    assert con.sql("select count(*) from players").fetchall()[0][0] == PLAYER_ROWS
    assert con.sql("select count(*) from agg_shots").fetchall()[0][0] == 326
    assert con.sql("select count(*) from games").fetchall()[0][0] == 1
    assert con.sql("select count(*) from matches").fetchall()[0][0] == 1
