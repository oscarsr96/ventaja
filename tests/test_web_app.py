import shutil
import socket
import threading
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient
from helpers import decisions_for_all_frames_for_one
from typer.testing import CliRunner

from ventaja.board.engine import Board, court_payload
from ventaja.cli import app as cli_app
from ventaja.config import Settings
from ventaja.data.load import ARTIFACTS_DIR, load_decisions
from ventaja.errors import VentajaError
from ventaja.mcp.server import TOOL_NAMES
from ventaja.mcp.service import AskService
from ventaja.value.model import ValueModel
from ventaja.value.params import BOARD_MAX_MOVES
from ventaja.value.priors import Priors
from ventaja.web.app import create_app

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


def test_index_has_view_structure(client: TestClient) -> None:
    text = client.get("/").text
    for marker in ('id="viewSel"', "id: 'ground'", "id: 'figures'"):
        assert marker in text


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


@pytest.mark.parametrize("command", ["board", "app"])
def test_cli_board_no_frames_exits_1(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ventaja.data.load.ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(tmp_path / "build"))
    result = CliRunner().invoke(cli_app, [command, "--no-open"])
    assert result.exit_code == 1
    assert "ventaja frames build" in result.output


@pytest.mark.parametrize("command", ["board", "app"])
def test_cli_board_serves_without_opening(
    command: str, fixture_frames_built: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    served: dict[str, Any] = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: served.update(kw))
    monkeypatch.setattr("webbrowser.open", lambda url: pytest.fail("opened"))
    monkeypatch.setattr("ventaja.web.app.create_app", lambda settings, **kw: object())
    result = CliRunner().invoke(cli_app, [command, "--no-open", "--port", "8799", "--game", "1"])
    assert result.exit_code == 0
    assert served == {"host": "127.0.0.1", "port": 8799, "log_level": "warning"}


@pytest.mark.parametrize("command", ["board", "app"])
def test_cli_board_opens_browser_once_listening(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setattr("webbrowser.open", fake_open)
    monkeypatch.setattr("ventaja.web.app.create_app", lambda settings, **kw: object())
    result = CliRunner().invoke(cli_app, [command, "--port", "8798"])
    assert result.exit_code == 0
    assert opened == ["http://127.0.0.1:8798/"]


def test_index_page_static_contract(client: TestClient) -> None:
    html = client.get("/").text
    for needle in ('id="court"', "fetch('/api/shots')", "pointerdown", "/evaluate"):
        assert needle in html
    assert "<script src=" not in html
    assert "<link " not in html
    index = Path(__file__).parent.parent / "src" / "ventaja" / "web" / "static" / "index.html"
    assert len(index.read_text(encoding="utf-8").splitlines()) <= 600


def test_shots_endpoint_with_more_decisions_than_frames(tmp_path: Path) -> None:
    settings = decisions_for_all_frames_for_one(tmp_path)
    rows = TestClient(create_app(settings)).get("/api/shots").json()
    assert rows and {r["game_id"] for r in rows} == {GAME_ID}


# --- the unified app over the packaged artifacts ---------------------------------------------


@pytest.fixture(scope="module")
def clean_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    tmp = tmp_path_factory.mktemp("web")
    return Settings(data_dir=tmp / "raw", build_dir=tmp / "build")


@pytest.fixture(scope="module")
def service(clean_settings: Settings) -> AskService:
    return AskService(clean_settings)


@pytest.fixture(scope="module")
def pkg_client(clean_settings: Settings) -> TestClient:
    return TestClient(create_app(clean_settings))


def test_ask_schema_lists_six_tools(pkg_client: TestClient) -> None:
    schemas = pkg_client.get("/api/ask/schema").json()
    assert [s["name"] for s in schemas] == list(TOOL_NAMES)


def test_ask_matches_the_service(pkg_client: TestClient, service: AskService) -> None:
    body = {"team": "Breogan", "clock": "6-0"}
    posted = pkg_client.post("/api/ask/rank_players", json=body).json()
    assert posted == service.rank_players(**body).model_dump()
    games = pkg_client.post("/api/ask/list_games", json={}).json()
    assert isinstance(games, list) and len(games) == 10


@pytest.mark.parametrize(
    ("tool", "body", "status", "needle"),
    [
        ("nope", {}, 404, "unknown tool"),
        ("rank_players", {"limit": 0}, 400, "limit"),
        ("player_profile", {"player": "a"}, 400, "players match"),
        ("explain_shot", {"shot_id": "shot-114243-9-9"}, 404, "not found"),
        (
            "what_if",
            {"shot_id": "shot-114243-1-0", "moves": [{"player": "1", "x": "nan", "y": 0}]},
            400,
            "x",
        ),
    ],
)
def test_ask_errors_are_json(
    pkg_client: TestClient, tool: str, body: dict[str, Any], status: int, needle: str
) -> None:
    r = pkg_client.post(f"/api/ask/{tool}", json=body)
    assert r.status_code == status and needle in r.json()["error"] and "Traceback" not in r.text


def test_glossary_is_markdown(pkg_client: TestClient) -> None:
    r = pkg_client.get("/api/ask/glossary")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "# Ventaja glossary" in r.text


def test_curve_payload(pkg_client: TestClient) -> None:
    c = pkg_client.get("/api/curve/shot-191313-1-31").json()
    assert c["rows"] and c["rows"][0]["t"] < 0 and c["summary"]["verdict"] == "during"
    assert c["decision_t"] < 0 and c["window"] is not None and c["window"][0] <= c["window"][1]
    assert all(str(r["handler_id"]) in c["handlers"] for r in c["rows"])
    found = pkg_client.post("/api/ask/find_shots", json={"verdict": "none", "limit": 1}).json()
    none_shot = found["shots"][0]
    assert pkg_client.get(f"/api/curve/{none_shot['shot_id']}").json()["window"] is None
    assert pkg_client.get("/api/curve/shot-114243-9-9").status_code == 404


def test_curve_without_summary_row(tmp_path: Path) -> None:
    build = tmp_path / "build"
    shutil.copytree(ARTIFACTS_DIR / "decisions", build / "decisions")
    (build / "curves").mkdir()
    shutil.copy(ARTIFACTS_DIR / "curves" / "114243.parquet", build / "curves")  # no summary file
    partial = TestClient(create_app(Settings(data_dir=tmp_path / "raw", build_dir=build)))
    curve = partial.get("/api/curve/shot-114243-1-0")
    assert curve.status_code == 200 and curve.json()["summary"] is None
    assert curve.json()["window"] is None


def test_reel_lists_clips_or_nothing(
    pkg_client: TestClient,
    clean_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = pkg_client.get("/api/reel").json()
    assert set(r) == {"dir", "clips"}
    if r["dir"]:
        assert all(
            v.startswith(f"/reel/{r['dir']}/") and v.endswith(".gif") for v in r["clips"].values()
        )
    monkeypatch.setattr("ventaja.web.app.REPO_ROOT", tmp_path)  # no docs/reel here
    app2 = TestClient(create_app(clean_settings))
    assert app2.get("/api/reel").json() == {"dir": None, "clips": {}}


def test_reel_maps_names_and_first_wins(
    clean_settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reel = tmp_path / "docs" / "reel"
    for month, names in (
        ("2026-10", ["01-worst-shot-1-1-1.gif"]),
        (
            "2026-11",
            ["01-worst-shot-2-1-1.gif", "02-late-shot-2-1-1.gif", "03-best-shot-3-1-1.gif"],
        ),
        ("2026-12", []),  # newest directory has no gifs: it is skipped
    ):
        (reel / month).mkdir(parents=True)
        for n in names:
            (reel / month / n).write_bytes(b"GIF89a")
    monkeypatch.setattr("ventaja.web.app.REPO_ROOT", tmp_path)
    got = TestClient(create_app(clean_settings)).get("/api/reel").json()
    assert got == {
        "dir": "2026-11",
        "clips": {
            "shot-2-1-1": "/reel/2026-11/01-worst-shot-2-1-1.gif",
            "shot-3-1-1": "/reel/2026-11/03-best-shot-3-1-1.gif",
        },
    }


def test_featured_and_about(pkg_client: TestClient) -> None:
    f = pkg_client.get("/api/featured", params={"n": 3}).json()
    assert f["default_shot"] == "shot-191313-1-31" and len(f["worst"]) == 3
    assert pkg_client.get("/api/featured", params={"n": 0}).status_code == 400
    assert pkg_client.get("/api/featured", params={"n": 51}).status_code == 400
    a = pkg_client.get("/api/about").json()
    assert a["games"] == 10 and a["valued_shots"] == 1351 and a["model_trained_at"] and a["version"]


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("0009-pizarra.md", 200),
        ("0099-nope.md", 404),
        ("../README.md", 404),
        ("0009-pizarra.txt", 404),
    ],
)
def test_docs_route_is_confined(pkg_client: TestClient, name: str, status: int) -> None:
    assert pkg_client.get(f"/docs/decisions/{name}").status_code == status


def test_cli_app_and_board_alias() -> None:
    out = CliRunner().invoke(cli_app, ["board", "--help"]).stdout
    assert "ventaja app" in out
    assert "app" in CliRunner().invoke(cli_app, ["app", "--help"]).stdout
