"""Tests for the player and team cards: artifacts, round trip, lookup, loaders and CLI."""

from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from ventaja.cli import app
from ventaja.config import Settings
from ventaja.data import load as load_module
from ventaja.data.load import (
    load_decisions,
    load_meta,
    load_players_cards,
    load_teams_cards,
)
from ventaja.errors import DataNotFoundError
from ventaja.profile.aggregate import league_row
from ventaja.profile.card import (
    LEAGUE_ID,
    LEAGUE_NAME,
    PLAYERS_SCHEMA,
    TEAMS_SCHEMA,
    build_players,
    card_of,
    find_player,
    flatten_card,
    league_season_shares,
)
from ventaja.value.model import ValueModel
from ventaja.value.params import CLOCK_BUCKETS

GAME_ID = 114243
FIXTURE_VALUED_SHOTS = 17
FIXTURE_SHOOTERS = 10  # distinct shooters among the 17 valued shots (measured)

runner = CliRunner()


def _players(settings: Settings) -> pl.DataFrame:
    return pl.read_parquet(settings.players_parquet())


def test_build_players_fixture(fixture_players_built: Settings) -> None:
    players = _players(fixture_players_built)
    assert dict(players.schema) == PLAYERS_SCHEMA
    league = players.filter(pl.col("player_id") == LEAGUE_ID)
    shooters = players.filter(pl.col("player_id") != LEAGUE_ID)
    assert league.height == 1 and league["name"][0] == LEAGUE_NAME
    assert league["team_id"][0] is None
    assert shooters.height == FIXTURE_SHOOTERS
    assert shooters["n_shots"].sum() == FIXTURE_VALUED_SHOTS
    assert league["n_shots"][0] == FIXTURE_VALUED_SHOTS
    assert (shooters["n_shots"] >= 1).all()
    assert shooters["games"].to_list() == [[GAME_ID]] * FIXTURE_SHOOTERS
    assert shooters["name"].null_count() == 0 and shooters["team"].null_count() == 0
    assert shooters["phrase_es"].null_count() == 0 and shooters["phrase_en"].null_count() == 0
    assert players["built_at"].str.ends_with("+00:00").all()

    teams = pl.read_parquet(fixture_players_built.teams_parquet())
    assert dict(teams.schema) == TEAMS_SCHEMA
    assert teams["n_shots"].sum() == FIXTURE_VALUED_SHOTS
    assert teams["n_players"].sum() == FIXTURE_SHOOTERS
    assert sorted(pid for ps in teams["players"].to_list() for pid in ps) == sorted(
        shooters["player_id"].to_list()
    )


def test_league_row_has_season_keys(fixture_players_built: Settings) -> None:
    league = card_of(LEAGUE_ID, _players(fixture_players_built))
    shares = league_season_shares(
        pl.read_parquet(fixture_players_built.aggregates_parquet("shots"))
    )
    assert set(shares) == {"season_cns_share", "season_contested_share"}
    for key, value in shares.items():
        assert value is not None and 0.0 <= value <= 1.0
        assert league.season[key] == pytest.approx(value)
    assert league.season["season_attempts"] is None
    assert league.phrase_es is None
    decisions = load_decisions(GAME_ID, fixture_players_built)
    readable = decisions.filter(pl.col("good_read").is_not_null())
    assert league.mean_cost == pytest.approx(float(readable["cost"].mean()))  # type: ignore[arg-type]


def test_card_of_roundtrip(fixture_players_built: Settings) -> None:
    players = _players(fixture_players_built)
    pid = int(players.filter(pl.col("player_id") != LEAGUE_ID)["player_id"][0])
    card = card_of(pid, players)
    assert set(card.clock) == {label for label, _, _ in CLOCK_BUCKETS}
    row = players.filter(pl.col("player_id") == pid).row(0, named=True)
    for label in card.clock:
        assert card.clock[label] == (row[f"clock_{label}_n"], row[f"clock_{label}_cost"])
    assert card.alternatives["extra_pass"] == (row["alt_extra_pass_n"], row["alt_extra_pass_cost"])
    assert card.season["season_attempts"] == row["season_attempts"]
    assert card.tracked_zone["tracked_attempts"] == row["tracked_attempts"]
    assert set(card.zone_shift) == {c for c in players.columns if c.startswith("shift_")}
    flat = flatten_card(card)
    assert flat == row
    again = card_of(pid, pl.DataFrame([flat], schema=PLAYERS_SCHEMA))
    assert again == card


def test_card_of_unknown_player_raises(fixture_players_built: Settings) -> None:
    with pytest.raises(DataNotFoundError, match="player 1 not found"):
        card_of(1, _players(fixture_players_built))


def test_find_player_by_name_and_ambiguity(fixture_players_built: Settings) -> None:
    meta = load_meta("players", fixture_players_built)
    several = find_player("a", meta)
    assert len(several) > 1
    assert [r[1] for r in several] == sorted(r[1] for r in several)
    assert find_player("zzz", meta) == []
    games = load_meta("games", fixture_players_built)
    [(pid, name, team)] = find_player("GOLDEN", meta, games)
    assert (name, team) == ("Grant Golden", "BAXI Manresa")
    assert find_player(str(pid), meta, games) == [(pid, name, team)]
    assert find_player("GOLDEN", meta) == [(pid, name, "1330")]  # no games table: the team id
    # the cards table works too, and never returns the LIGA row
    cards = _players(fixture_players_built)
    assert find_player("liga", cards) == []
    assert find_player("0", cards) == []
    assert find_player("golden", cards) == [(pid, name, team)]


def test_find_player_ignores_accents() -> None:
    meta = pl.DataFrame(
        {
            "game_id": [1, 1],
            "team_id": [7, 7],
            "player_id": [10, 11],
            "first_name": ["Darío", "Dario"],
            "last_name": ["Brizuela", "Brizzi"],
            "jersey": ["8", "9"],
        }
    )
    assert [r[0] for r in find_player("DARIO BRI", meta)] == [10, 11]
    assert [r[0] for r in find_player("darío brizu", meta)] == [10]
    assert find_player("brizuela", meta)[0][2] == "7"  # no games table: the team id


@pytest.fixture
def cli_env(fixture_players_built: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(fixture_players_built.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(fixture_players_built.build_dir))
    return fixture_players_built


def test_player_show_cli(cli_env: Settings) -> None:
    card = card_of(int(find_player("golden", _players(cli_env))[0][0]), _players(cli_env))
    result = runner.invoke(app, ["player", "show", "golden"])
    assert result.exit_code == 0, result.output
    assert "Grant Golden" in result.output
    assert card.phrase_es is not None and card.phrase_es in result.output
    assert "Por reloj" in result.output and "24-14" in result.output and "6-0" in result.output
    assert "Por alternativa" in result.output and "Temporada" in result.output
    no_pass = card.n_shots - card.n_readable
    assert "descontado por la viabilidad del pase" in result.output
    assert f"sin pase viable: {no_pass}" in result.output
    en = runner.invoke(app, ["player", "show", str(card.player_id), "--lang", "en"])
    assert en.exit_code == 0 and card.phrase_en is not None and card.phrase_en in en.output
    assert "discounted by pass viability" in en.output
    assert f"no viable pass: {no_pass}" in en.output
    missing = runner.invoke(app, ["player", "show", "zzz"])
    assert missing.exit_code == 1
    ambiguous = runner.invoke(app, ["player", "show", "a"])
    assert ambiguous.exit_code == 1
    assert "Grant Golden" in ambiguous.output  # candidates listed (stderr is mixed in)


def test_player_rank_cli_min_shots(cli_env: Settings) -> None:
    result = runner.invoke(app, ["player", "rank", "--min-shots", "1", "--n", "50"])
    assert result.exit_code == 0, result.output
    rows = [line for line in result.output.splitlines() if line[:3].strip().isdigit()]
    assert len(rows) == FIXTURE_SHOOTERS
    assert LEAGUE_NAME not in result.output
    by_read = runner.invoke(app, ["player", "rank", "--by", "good_read_share"])
    assert by_read.exit_code == 0, by_read.output
    none = runner.invoke(app, ["player", "rank", "--min-shots", "100"])
    assert none.exit_code == 0
    assert "ningún jugador" in none.output
    bad = runner.invoke(app, ["player", "rank", "--by", "nope"])
    assert bad.exit_code == 2


def test_player_team_cli(cli_env: Settings) -> None:
    teams = load_teams_cards(cli_env)
    team = teams.sort("n_shots", descending=True).row(0, named=True)
    result = runner.invoke(app, ["player", "team", str(team["team_id"])])
    assert result.exit_code == 0, result.output
    assert team["team"] in result.output
    by_name = runner.invoke(app, ["player", "team", team["team"].lower()[:5]])
    assert by_name.exit_code == 0, by_name.output
    assert runner.invoke(app, ["player", "team", "zzz"]).exit_code == 1


def test_player_build_cli(cli_env: Settings, tmp_path: Path) -> None:
    result = runner.invoke(app, ["player", "build", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "players.parquet").exists() and (tmp_path / "teams.parquet").exists()
    assert f"{FIXTURE_SHOOTERS} jugadores" in result.output


def test_artifact_files_players(fixture_players_built: Settings) -> None:
    root = fixture_players_built.build_dir / "players"
    assert load_module._artifact_files("players", fixture_players_built) == (
        [root / "players.parquet"],
        [root / "teams.parquet"],
    )


def test_build_players_stamps_the_given_model(
    fixture_curves_built: Settings, trained_fixture_model: ValueModel, tmp_path: Path
) -> None:
    players_path, teams_path = build_players(
        fixture_curves_built, out_dir=tmp_path, model=trained_fixture_model
    )
    for path in (players_path, teams_path):
        stamps = set(pl.read_parquet(path)["model_trained_at"])
        assert stamps == {trained_fixture_model.trained_at}


def test_load_players_falls_back_to_artifacts(
    fixture_players_built: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packaged = tmp_path / "artifacts"
    packaged.mkdir()
    for name in ("players.parquet", "teams.parquet"):
        (packaged / name).write_bytes(
            (fixture_players_built.build_dir / "players" / name).read_bytes()
        )
    monkeypatch.setattr(load_module, "ARTIFACTS_DIR", packaged)
    empty = Settings(data_dir=fixture_players_built.data_dir, build_dir=tmp_path / "build")
    assert load_module.artifact_dir("players", empty) == packaged
    assert load_players_cards(empty).height == FIXTURE_SHOOTERS + 1
    assert load_teams_cards(empty).height == pl.read_parquet(packaged / "teams.parquet").height
    assert load_module.artifact_dir("players", fixture_players_built) == (
        fixture_players_built.build_dir / "players"
    )
    monkeypatch.setattr(load_module, "ARTIFACTS_DIR", tmp_path / "nothing")
    with pytest.raises(DataNotFoundError, match="ventaja player build"):
        load_players_cards(empty)


def test_duck_has_card_views(fixture_players_built: Settings) -> None:
    from ventaja.data.duck import connect

    con = connect(fixture_players_built)
    n = con.execute("select count(*) from player_cards where player_id <> 0").fetchone()
    assert n == (FIXTURE_SHOOTERS,)
    t = con.execute("select sum(n_shots) from team_cards").fetchone()
    assert t == (FIXTURE_VALUED_SHOTS,)


def test_league_row_mean_cost_matches_cards(fixture_players_built: Settings) -> None:
    decisions = load_decisions(GAME_ID, fixture_players_built)
    summaries = pl.read_parquet(fixture_players_built.curve_summaries_parquet(GAME_ID))
    league = league_row(decisions, summaries)
    card = card_of(LEAGUE_ID, _players(fixture_players_built))
    assert card.mean_cost == pytest.approx(league["mean_cost"])
    assert card.clock["6-0"] == (league["n_6-0"], league["cost_6-0"])
