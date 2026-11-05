"""The ask service over the packaged artifacts: games, resolvers, rankings and profiles."""

import shutil
from pathlib import Path
from typing import Any, get_args

import polars as pl
import pydantic
import pytest

from ventaja.config import Settings
from ventaja.data.load import ARTIFACTS_DIR, decision_files
from ventaja.data.people import load_people
from ventaja.errors import AmbiguousQueryError, DataNotFoundError, VentajaError
from ventaja.geometry.court import HALF_LENGTH
from ventaja.mcp.models import Move
from ventaja.mcp.service import (
    CLOCK_BANDS,
    RANK_KEYS,
    VERDICTS,
    AskService,
    ClockBandName,
    RankKey,
    VerdictName,
)
from ventaja.value.params import (
    BOARD_MAX_MOVES,
    MCP_DEFAULT_LIMIT,
    MCP_MAX_LIMIT,
    PROFILE_MIN_SHOTS,
)


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


def test_find_shots_default_is_costliest_first(service: AskService) -> None:
    found = service.find_shots()
    assert len(found.shots) == MCP_DEFAULT_LIMIT and found.total == 1351
    costs = [s.cost for s in found.shots]
    assert costs == sorted(costs, reverse=True) and found.shots[0].shooter.name


def test_find_shots_filters_compose(service: AskService) -> None:
    mine = service.find_shots(player="Spissu", game=191313, limit=50)
    assert mine.total >= 1
    assert all(s.shooter.name == "Marco Spissu" and s.game_id == 191313 for s in mine.shots)
    late = service.find_shots(
        team="Zaragoza", verdict="late", good_read=False, min_cost=0.3, limit=50
    )
    assert all(s.verdict == "late" and s.good_read is False and s.cost >= 0.3 for s in late.shots)
    versus = service.find_shots(opponent="Zaragoza", game=191313, limit=50)
    assert versus.total > 0
    assert not {s.shooter.team.name for s in versus.shots if s.shooter.team} & {
        "Casademont Zaragoza"
    }


def test_find_shots_clock_band_skips_unknown_clock(service: AskService) -> None:
    band = service.find_shots(clock="6-0", limit=50)
    assert band.total > 0
    assert all(s.shot_clock is not None and 0.0 <= s.shot_clock <= 6.0 for s in band.shots)
    with pytest.raises(ValueError, match="verdict must be one of"):
        service.find_shots(verdict="early")
    with pytest.raises(ValueError, match="clock must be one of"):
        service.find_shots(clock="30-24")
    with pytest.raises(ValueError, match="limit must be between"):
        service.find_shots(limit=0)


def test_find_shots_without_summary_keeps_the_shot(tmp_path: Path) -> None:
    build = tmp_path / "build"
    shutil.copytree(ARTIFACTS_DIR / "decisions", build / "decisions")  # no curves/ in the build
    (build / "curves").mkdir()
    shutil.copy(ARTIFACTS_DIR / "curves" / "114243.parquet", build / "curves")  # no summary file
    partial = AskService(Settings(data_dir=tmp_path / "raw", build_dir=build))
    found = partial.find_shots(game=114243, limit=50)
    assert found.total > 0 and all(s.verdict is None and s.headline is None for s in found.shots)


def test_explain_shot(service: AskService) -> None:
    shot = service.explain_shot("shot-114243-1-0")
    assert shot.shooter.name and len(shot.options) == 5
    assert sum(o.is_shot for o in shot.options) == 1
    assert sum(o.is_best_alternative for o in shot.options) <= 1
    assert shot.clip_command == "ventaja clip shot-114243-1-0 --out shot-114243-1-0.gif"
    assert shot.curve is None or shot.curve.verdict in VERDICTS


def test_explain_shot_errors_name_the_shot(service: AskService) -> None:
    with pytest.raises(DataNotFoundError, match="shot-114243-9-9"):
        service.explain_shot("shot-114243-9-9")
    excluded = service.decisions.filter(pl.col("rule") == "excluded")["shot_id"][0]
    with pytest.raises(VentajaError, match=f"{excluded} is excluded"):
        service.explain_shot(excluded)


def test_what_if_without_moves_reproduces_the_decision(service: AskService) -> None:
    result = service.what_if("shot-114243-1-0", [])
    assert result.after.cost == pytest.approx(result.before.cost, abs=1e-3)
    assert result.delta_cost == 0.0 and not any(p.moved for p in result.players)
    row = service.decisions.filter(pl.col("shot_id") == "shot-114243-1-0").row(0, named=True)
    assert result.after.cost == pytest.approx(row["cost"], abs=1e-3)
    assert result.after.shot_value == pytest.approx(row["shot_value"], abs=1e-3)
    assert result.after.best_alternative is not None
    assert result.after.best_alternative.value == pytest.approx(row["best_alt_value"], abs=1e-3)


def _excluded_id(service: AskService) -> str:
    return str(service.decisions.filter(pl.col("rule") == "excluded")["shot_id"][0])


def test_what_if_says_why_an_unknown_or_excluded_shot_is_refused(service: AskService) -> None:
    with pytest.raises(DataNotFoundError, match="shot shot-1-9-9 not found in the decisions"):
        service.what_if("shot-1-9-9", [])
    excluded = _excluded_id(service)
    with pytest.raises(VentajaError, match=f"shot {excluded} is excluded: "):
        service.what_if(excluded, [])
    with pytest.raises(VentajaError, match="is excluded: "):
        service.explain_shot(excluded)


def test_what_if_checks_the_move_count_before_the_shot(service: AskService) -> None:
    moves = [Move(player="1", x=0.0, y=0.0)] * (BOARD_MAX_MOVES + 1)
    with pytest.raises(ValueError, match=f"at most {BOARD_MAX_MOVES} moves"):
        service.what_if("shot-1-9-9", moves)


@pytest.mark.parametrize("verdict", VERDICTS)
def test_explain_shot_handles_every_verdict(service: AskService, verdict: str) -> None:
    shot_id = service.summaries.filter(pl.col("verdict") == verdict)["shot_id"][0]
    curve = service.explain_shot(shot_id).curve
    assert curve is not None and curve.verdict == verdict


def test_explain_shot_covers_every_valued_shot(service: AskService) -> None:
    valued = service.decisions.filter(pl.col("rule") != "excluded")["shot_id"].to_list()
    assert len(valued) == 1351
    for shot_id in valued:
        assert service.explain_shot(shot_id).shot_id == shot_id


def test_schema_literals_match_the_tuples() -> None:
    assert get_args(ClockBandName) == CLOCK_BANDS
    assert get_args(RankKey) == RANK_KEYS
    assert get_args(VerdictName) == VERDICTS


def test_what_if_moves_the_shooter_and_clamps(service: AskService) -> None:
    shot = service.explain_shot("shot-114243-1-0")
    result = service.what_if(
        "shot-114243-1-0", [Move(player=str(shot.shooter.player_id), x=-99.0, y=0.0)]
    )
    assert result.moves[0].x == -HALF_LENGTH
    assert result.moves[0].player.player_id == shot.shooter.player_id
    assert next(p for p in result.players if p.is_shooter).moved
    assert result.after.cost != result.before.cost


def test_what_if_resolves_player_by_name_and_rejects_strangers(service: AskService) -> None:
    name = service.explain_shot("shot-114243-1-0").options[1].player.name
    assert name is not None
    result = service.what_if("shot-114243-1-0", [Move(player=name, x=-20.0, y=20.0)])
    assert len(result.moves) == 1
    with pytest.raises(AmbiguousQueryError, match="offense|defense"):
        # Russell (Breogán) is not in Granada-Manresa
        service.what_if("shot-114243-1-0", [Move(player="58474", x=-20.0, y=0.0)])
    with pytest.raises(ValueError, match=f"at most {BOARD_MAX_MOVES}"):
        service.what_if("shot-114243-1-0", [Move(player="1", x=0.0, y=0.0)] * (BOARD_MAX_MOVES + 1))
    with pytest.raises(pydantic.ValidationError):
        Move(player="1", x=float("nan"), y=0.0)
