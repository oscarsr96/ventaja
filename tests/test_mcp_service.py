"""The ask service over the packaged artifacts: games, resolvers, rankings and profiles."""

from pathlib import Path
from typing import Any

import pytest

from ventaja.config import Settings
from ventaja.data.load import decision_files
from ventaja.data.people import load_people
from ventaja.errors import AmbiguousQueryError
from ventaja.mcp.service import AskService
from ventaja.value.params import MCP_DEFAULT_LIMIT, MCP_MAX_LIMIT, PROFILE_MIN_SHOTS


@pytest.fixture(scope="module")
def service(tmp_path_factory: pytest.TempPathFactory) -> AskService:
    tmp = tmp_path_factory.mktemp("mcp")
    return AskService(Settings(data_dir=tmp / "raw", build_dir=tmp / "build"))


def test_list_games_covers_the_packaged_decisions(service: AskService) -> None:
    games = service.list_games()
    assert [g.game_id for g in games] == sorted(
        int(p.stem) for p in decision_files(service.settings)[0]
    )
    assert all(g.home.name and g.away.name and g.valued_shots > 0 for g in games)
    assert sum(g.valued_shots for g in games) == 1351  # the packaged valued shots (ADR-0009)


def test_resolve_player_by_id_name_and_accent(service: AskService) -> None:
    assert service.resolve_player("58474") == 58474
    assert service.resolve_player("russell") == 58474
    assert service.resolve_player("RUSSELL") == 58474


def test_resolve_player_ambiguous_lists_candidates(service: AskService) -> None:
    with pytest.raises(AmbiguousQueryError, match=r"\d+ players match 'a':") as exc:
        service.resolve_player("a")
    message = str(exc.value)
    assert message.count(" — ") >= 4  # at least two candidate lines
    assert len(message.splitlines()) <= 22  # header, 20 candidates, "… and N more"


def test_resolve_team_lists_every_team_on_no_match(service: AskService) -> None:
    with pytest.raises(AmbiguousQueryError) as exc:
        service.resolve_team("Barça")
    assert "BC Barcelona" in str(exc.value) and str(exc.value).count("\n") >= 16


def test_resolve_team_by_substring(service: AskService) -> None:
    team_id = service.resolve_team("Breogan")
    assert service.people.teams[team_id] == "Leche Rio Breogan"


def test_rank_players_default_and_team(service: AskService) -> None:
    ranking = service.rank_players()
    assert ranking.by == "mean_cost" and len(ranking.players) == MCP_DEFAULT_LIMIT
    costs = [p.metrics.mean_cost for p in ranking.players]
    assert costs == sorted(costs, reverse=True) and ranking.league.mean_cost is not None
    breogan = service.rank_players(team="Breogan", limit=50)
    assert {p.player.team.name for p in breogan.players if p.player.team} == {"Leche Rio Breogan"}
    assert [p.rank for p in breogan.players] == list(range(1, len(breogan.players) + 1))


def test_rank_players_clock_band(service: AskService) -> None:
    ranking = service.rank_players(team="Breogan", clock="6-0", min_shots=5)
    assert ranking.players[0].player.player_id == 58474
    band = ranking.players[0].metrics.clock
    assert band is not None and band.band == "6-0" and band.n == 7 and band.cost is not None
    assert ranking.league.clock is not None and ranking.league.clock.band == "6-0"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"by": "cost"}, "by must be one of"),
        ({"clock": "6-0", "by": "good_read_share"}, "clock rankings only support"),
        ({"clock": "last-6"}, "clock must be one of"),
        ({"limit": 0}, "limit"),
        ({"limit": MCP_MAX_LIMIT + 1}, "limit"),
        ({"min_shots": 0}, "min_shots"),
    ],
)
def test_rank_players_rejects_bad_arguments(
    service: AskService, kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        service.rank_players(**kwargs)


def test_player_profile_russell(service: AskService) -> None:
    profile = service.player_profile("Russell")
    assert profile.player.name == "DeWayne Russell" and profile.n_shots == 30
    assert [b.band for b in profile.clock] == ["24-14", "14-6", "6-0"]
    assert profile.phrase and profile.caution is None
    assert profile.league.n_shots > profile.n_shots
    assert profile.mean_cost == round(profile.mean_cost, 3)
    assert "attempts" in profile.season or "games" in profile.season


def test_player_profile_caution_below_threshold(service: AskService) -> None:
    small = next(
        p for p in service.players.iter_rows(named=True) if 0 < p["n_readable"] < PROFILE_MIN_SHOTS
    )
    assert service.player_profile(str(small["player_id"])).caution


def test_board_uses_people_directory(tmp_path: Path) -> None:
    clean = Settings(data_dir=tmp_path / "raw", build_dir=tmp_path / "build")
    people = load_people(clean)
    assert people.names[58474] == "DeWayne Russell" and people.player_team[58474] in people.teams
