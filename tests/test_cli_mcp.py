import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ventaja.cli import app as cli_app
from ventaja.config import Settings
from ventaja.mcp.server import TOOL_NAMES
from ventaja.mcp.service import AskService


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    """CLI runner whose build dir is empty, so the service reads the packaged artifacts."""
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(tmp_path / "build"))
    return CliRunner()


def test_mcp_call_list_games_prints_json(runner: CliRunner) -> None:
    result = runner.invoke(cli_app, ["mcp", "call", "list_games"])
    assert result.exit_code == 0, result.output
    games = json.loads(result.stdout)
    assert isinstance(games, list) and len(games) == 10 and games[0]["home"]["name"]


def test_mcp_call_matches_the_service(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(cli_app, ["mcp", "call", "player_profile", '{"player": "Russell"}'])
    assert result.exit_code == 0, result.output
    service = AskService(Settings(data_dir=tmp_path / "raw", build_dir=tmp_path / "build"))
    assert json.loads(result.stdout) == service.player_profile("Russell").model_dump()


def test_mcp_call_rejects_bad_input(runner: CliRunner) -> None:
    assert runner.invoke(cli_app, ["mcp", "call", "nope"]).exit_code == 2
    assert runner.invoke(cli_app, ["mcp", "call", "list_games", "{not json"]).exit_code == 2
    failed = runner.invoke(cli_app, ["mcp", "call", "player_profile", '{"player": "a"}'])
    assert failed.exit_code == 1 and "players match" in failed.output


def test_mcp_call_invalid_arguments_exit_one(runner: CliRunner) -> None:
    result = runner.invoke(cli_app, ["mcp", "call", "player_profile", "{}"])
    assert result.exit_code == 1 and result.output.startswith("error:")


def test_mcp_tools_lists_six(runner: CliRunner) -> None:
    result = runner.invoke(cli_app, ["mcp", "tools"])
    assert result.exit_code == 0, result.output
    assert all(name in result.stdout for name in TOOL_NAMES)
    assert '"type": "object"' in result.stdout
