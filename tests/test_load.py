from datetime import UTC, datetime

import polars as pl
import pytest

from ventaja.config import Settings
from ventaja.data.load import canonical, load_aliases, load_events, load_game, load_matches
from ventaja.errors import DataNotFoundError


def test_load_game_reads_rosters(fixture_settings: Settings) -> None:
    g = load_game(114243, fixture_settings)
    assert g.game_id == 114243
    assert g.home.name == "BAXI Manresa" and g.away.name == "Coviran Granada"
    assert len(g.home.players) == 12 and len(g.away.players) == 12
    assert g.date == datetime(2025, 10, 11, 19, 0, tzinfo=UTC)
    assert g.date.tzinfo is not None
    assert g.season == "2025-2026"
    first = g.home.players[0]
    assert (first.player_id, first.first_name, first.jersey) == (15630, "Kaodirichi", "0")


def test_load_game_missing_raises_with_hint(fixture_settings: Settings) -> None:
    with pytest.raises(DataNotFoundError, match="ventaja data pull"):
        load_game(114086, fixture_settings)


def test_load_matches_reads_scores(fixture_settings: Settings) -> None:
    [m] = load_matches(fixture_settings)
    assert (m.home_score, m.away_score) == (83, 68)
    assert (m.game_id, m.home_team_id, m.away_team_id) == (114243, 1330, 1319)
    assert m.date_time.tzinfo is not None


def test_load_aliases_only_differing_rows(fixture_settings: Settings) -> None:
    aliases = load_aliases(fixture_settings)
    assert aliases[59237] == 59129
    assert 59129 not in aliases
    assert all(k != v for k, v in aliases.items())


def test_canonical() -> None:
    assert canonical(59237, {59237: 59129}) == 59129
    assert canonical(1, {59237: 59129}) == 1


def test_load_events_before_build_raises_with_hint(fixture_settings: Settings) -> None:
    with pytest.raises(DataNotFoundError, match="ventaja data build"):
        load_events(114243, "shots", fixture_settings)


def test_load_events_reads_built_table(built_fixture: Settings) -> None:
    shots = load_events(114243, "shots", built_fixture)
    assert isinstance(shots, pl.DataFrame)
    assert shots.height == 159
