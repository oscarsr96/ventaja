import socket
import threading
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from ventaja.board.app import create_app
from ventaja.board.engine import Board, court_payload
from ventaja.cli import app as cli_app
from ventaja.config import Settings
from ventaja.data.load import load_decisions
from ventaja.errors import VentajaError
from ventaja.value.model import ValueModel
from ventaja.value.params import BOARD_MAX_MOVES
from ventaja.value.priors import Priors

GAME_ID = 114243
SHOT_ID = "shot-114243-1-0"


@pytest.fixture(scope="module")
def engine(
    fixture_frames_built: Settings, trained_fixture_model: ValueModel, fixture_priors: Priors
) -> Board:
    return Board(fixture_frames_built, model=trained_fixture_model, priors=fixture_priors)


@pytest.fixture(scope="module")
def client(
    fixture_frames_built: Settings, trained_fixture_model: ValueModel, fixture_priors: Priors
) -> TestClient:
    app = create_app(fixture_frames_built, model=trained_fixture_model, priors=fixture_priors)
    return TestClient(app)


def test_index_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in response.text.lower()


def test_court(client: TestClient) -> None:
    response = client.get("/api/court")
    assert response.status_code == 200
    assert response.json() == court_payload()


def test_shots_list_only_valued(client: TestClient, fixture_frames_built: Settings) -> None:
    rows = client.get("/api/shots").json()
    decisions = load_decisions(GAME_ID, fixture_frames_built)
    valued = set(decisions.filter(pl.col("rule") != "excluded")["shot_id"])
    excluded = set(decisions.filter(pl.col("rule") == "excluded")["shot_id"])
    ids = {r["shot_id"] for r in rows}
    assert excluded and ids and ids <= valued and not ids & excluded
    assert all(client.get(f"/api/shot/{i}").status_code == 200 for i in ids)
    costs = [r["cost"] for r in rows if r["cost"] is not None]
    assert costs == sorted(costs, reverse=True)
    nulls = [r["cost"] is None for r in rows]
    assert nulls == sorted(nulls)  # null costs last
    assert len(client.get("/api/shots", params={"game": GAME_ID}).json()) == len(rows)
    assert client.get("/api/shots", params={"game": 1}).json() == []


def test_shot_payload_matches_engine(client: TestClient, engine: Board) -> None:
    state = engine.load(SHOT_ID)
    expected = engine.payload(state, engine.evaluate(state))
    response = client.get(f"/api/shot/{SHOT_ID}")
    assert response.status_code == 200
    assert response.json() == expected


def test_evaluate_moves_and_clamps(client: TestClient) -> None:
    base = client.get(f"/api/shot/{SHOT_ID}").json()
    shooter = next(p for p in base["players"] if p["is_shooter"])
    body = {"moves": [{"player_id": shooter["player_id"], "x": 1e6, "y": -1e6}]}
    response = client.post(f"/api/shot/{SHOT_ID}/evaluate", json=body)
    assert response.status_code == 200
    moved = next(p for p in response.json()["players"] if p["player_id"] == shooter["player_id"])
    court = court_payload()
    assert moved["x"] == 0.0
    assert moved["y"] == -court["width"] / 2
    assert client.post(f"/api/shot/{SHOT_ID}/evaluate", json={"moves": []}).status_code == 200


def test_evaluate_unknown_player_422(client: TestClient) -> None:
    body = {"moves": [{"player_id": -7, "x": 1.0, "y": 1.0}]}
    response = client.post(f"/api/shot/{SHOT_ID}/evaluate", json=body)
    assert response.status_code == 422
    assert "-7" in str(response.json()["detail"])


def test_evaluate_rejects_non_finite(client: TestClient) -> None:
    response = client.post(
        f"/api/shot/{SHOT_ID}/evaluate",
        content='{"moves": [{"player_id": 1, "x": NaN, "y": 1.0}]}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422


def test_unknown_shot_404(client: TestClient) -> None:
    response = client.get("/api/shot/shot-114243-9-9")
    assert response.status_code == 404
    assert "shot-114243-9-9" in response.json()["detail"]
    posted = client.post("/api/shot/shot-114243-9-9/evaluate", json={"moves": []})
    assert posted.status_code == 404


def test_too_many_moves_422(client: TestClient) -> None:
    moves = [{"player_id": 1, "x": 0.0, "y": 0.0}] * (BOARD_MAX_MOVES + 1)
    response = client.post(f"/api/shot/{SHOT_ID}/evaluate", json={"moves": moves})
    assert response.status_code == 422


def test_games_option_restricts_shots(
    fixture_frames_built: Settings, trained_fixture_model: ValueModel, fixture_priors: Priors
) -> None:
    other = create_app(
        fixture_frames_built, model=trained_fixture_model, priors=fixture_priors, games=[1]
    )
    assert TestClient(other).get("/api/shots").json() == []


def test_create_app_without_frames_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ventaja.data.load.ARTIFACTS_DIR", tmp_path / "artifacts")
    empty = Settings(data_dir=tmp_path / "raw", build_dir=tmp_path / "build")
    with pytest.raises(VentajaError, match="ventaja frames build"):
        create_app(empty)


def test_cli_board_no_frames_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ventaja.data.load.ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(tmp_path / "build"))
    result = CliRunner().invoke(cli_app, ["board", "--no-open"])
    assert result.exit_code == 1
    assert "ventaja frames build" in result.output


def test_cli_board_serves_without_opening(
    fixture_frames_built: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    served: dict[str, Any] = {}
    monkeypatch.setattr("ventaja.cli.board.uvicorn.run", lambda app, **kw: served.update(kw))
    monkeypatch.setattr("ventaja.cli.board.webbrowser.open", lambda url: pytest.fail("opened"))
    monkeypatch.setattr("ventaja.cli.board.create_app", lambda settings, **kw: object())
    result = CliRunner().invoke(cli_app, ["board", "--no-open", "--port", "8799", "--game", "1"])
    assert result.exit_code == 0
    assert served == {"host": "127.0.0.1", "port": 8799, "log_level": "warning"}


def test_cli_board_opens_browser_once_listening(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    done = threading.Event()

    def fake_open(url: str) -> None:
        opened.append(url)
        done.set()

    def fake_run(app: object, **kw: Any) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", kw["port"]))
        listener.listen()
        assert done.wait(5) and not opened[1:]
        listener.close()

    monkeypatch.setattr("ventaja.cli.board.uvicorn.run", fake_run)
    monkeypatch.setattr("ventaja.cli.board.webbrowser.open", fake_open)
    monkeypatch.setattr("ventaja.cli.board.create_app", lambda settings, **kw: object())
    result = CliRunner().invoke(cli_app, ["board", "--port", "8798"])
    assert result.exit_code == 0
    assert opened == ["http://127.0.0.1:8798/"]
