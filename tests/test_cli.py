from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from ventaja import __version__
from ventaja.cli import app
from ventaja.config import Settings


def test_version_flag_prints_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_data_build_requires_selection() -> None:
    result = CliRunner().invoke(app, ["data", "build"])
    assert result.exit_code != 0
    assert "--game" in result.output and "--all" in result.output


def test_data_build_writes_event_tables(
    fixture_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(fixture_settings.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(fixture_settings.build_dir))
    result = CliRunner().invoke(app, ["data", "build", "--game", "114243", "--events-only"])
    assert result.exit_code == 0, result.output
    assert result.output.count("wrote ") == 20
    assert fixture_settings.events_parquet(114243, "shots").exists()


def test_data_build_missing_raw_reports_hint(
    fixture_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(fixture_settings.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(fixture_settings.build_dir))
    result = CliRunner().invoke(app, ["data", "build", "--game", "114086"])
    assert result.exit_code == 1
    assert "ventaja data pull --game 114086" in result.output


def test_data_build_writes_tracking_unless_events_only(
    fixture_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(fixture_settings.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(fixture_settings.build_dir))
    tracking = fixture_settings.tracking_parquet(114243)

    result = CliRunner().invoke(app, ["data", "build", "--game", "114243", "--events-only"])
    assert result.exit_code == 0, result.output
    assert not tracking.exists()
    assert "tracking" not in result.output

    result = CliRunner().invoke(app, ["data", "build", "--game", "114243"])
    assert result.exit_code == 0, result.output
    assert result.output.count("wrote ") == 21
    assert f"wrote 114243 tracking -> {tracking}" in result.output
    assert tracking.exists()


def test_data_pull_network_error_prints_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    real_client = httpx.Client

    def offline_client(**kwargs: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(refuse), **kwargs)

    monkeypatch.setattr(httpx, "Client", offline_client)
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(tmp_path / "build"))
    result = CliRunner().invoke(app, ["data", "pull"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "error: cannot download https://" in result.output
    assert "matches.json" in result.output
    assert "check your connection" in result.output


def test_data_pull_unknown_game_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(tmp_path / "raw"))
    result = CliRunner().invoke(app, ["data", "pull", "--game", "999"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "error:" in result.output and "999" in result.output
