import pytest
from typer.testing import CliRunner

from ventaja.cli import app
from ventaja.config import Settings
from ventaja.errors import DataNotFoundError, VentajaError
from ventaja.model.core import Score
from ventaja.validate import score
from ventaja.validate.score import check_scores, reconstruct_score


def _zero(_game_id: int, _settings: Settings) -> Score:
    return Score(home=0, away=0)


def test_reconstruct_score_matches_official(built_fixture: Settings) -> None:
    assert reconstruct_score(114243, built_fixture) == Score(home=83, away=68)


def test_check_scores_ok(built_fixture: Settings) -> None:
    [(gid, got, official, ok)] = check_scores([114243], built_fixture)
    assert (gid, ok) == (114243, True)
    assert got == official == Score(home=83, away=68)


def test_check_scores_flags_mismatch(
    built_fixture: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(score, "reconstruct_score", _zero)
    [(_gid, _got, official, ok)] = check_scores([114243], built_fixture)
    assert not ok
    assert official == Score(home=83, away=68)


def test_check_scores_unknown_game_raises(built_fixture: Settings) -> None:
    with pytest.raises(DataNotFoundError, match="999"):
        check_scores([999], built_fixture)


def test_reconstruct_score_unknown_team_raises(
    built_fixture: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import polars as pl

    from ventaja.data import load

    real = load.load_events

    def fake(game_id: int, table: str, settings: Settings) -> pl.DataFrame:
        df = real(game_id, table, settings)
        return (
            df.with_columns(off_team_id=pl.lit(42, dtype=df.schema["off_team_id"]))
            if table == "shots"
            else df
        )

    monkeypatch.setattr(score, "load_events", fake)
    with pytest.raises(VentajaError, match="42"):
        reconstruct_score(114243, built_fixture)


def _env(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(settings.build_dir))


def test_cli_validate_score_exit_code(
    built_fixture: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(built_fixture, monkeypatch)
    result = CliRunner().invoke(app, ["validate", "score", "--game", "114243"])
    assert result.exit_code == 0, result.output
    assert "game 114243: 83-68 (official 83-68) ok" in result.output
    monkeypatch.setattr(score, "reconstruct_score", _zero)
    result = CliRunner().invoke(app, ["validate", "score", "--game", "114243"])
    assert result.exit_code == 1
    assert "game 114243: 0-0 (official 83-68) MISMATCH" in result.output


def test_cli_validate_score_requires_selection() -> None:
    result = CliRunner().invoke(app, ["validate", "score"])
    assert result.exit_code != 0
    assert "--game" in result.output and "--all" in result.output
