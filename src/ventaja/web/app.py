"""FastAPI app of ventaja: whiteboard, ask tools, advantage curves, reel, featured shots, about."""

import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

import polars as pl
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError

from ventaja import __version__
from ventaja.board.engine import Board, court_payload
from ventaja.config import FPS, Settings
from ventaja.data.load import ARTIFACTS_DIR, frame_files, load_curves
from ventaja.errors import DataNotFoundError, VentajaError
from ventaja.mcp.server import TOOL_NAMES, call_tool, create_server, render_glossary, tool_schemas
from ventaja.mcp.service import AskService
from ventaja.profile.card import LEAGUE_ID
from ventaja.value.model import ValueModel
from ventaja.value.params import BOARD_MAX_MOVES
from ventaja.value.priors import Priors

STATIC_DIR = Path(__file__).parent / "static"
REPO_ROOT = ARTIFACTS_DIR.parent
_DECISION_DOC = re.compile(r"^\d{4}-[a-z0-9-]+\.md$")
_SHOT_GAME = re.compile(r"^shot-(\d+)-")
_REEL_CLIP = re.compile(r"^\d+-(?:worst|best|late)-(?P<shot>.+)\.gif$")
_MAX_FEATURED = 50
_SUMMARY_KEYS = (
    "verdict",
    "advantage_seconds",
    "release_lag_seconds",
    "window_handler_id",
    "held_to_decision",
    "headline_en",
    "shot_value",
    "window_peak_value",
)
_NO_FRAMES = "no decision frames found; run `ventaja frames build --all` first"


class _NoCacheStatic(StaticFiles):
    """Static files that browsers must revalidate (ETag) on every load: no stale ES modules."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


class Move(BaseModel):
    """One player dragged to a position (court feet, offense orientation)."""

    model_config = ConfigDict(extra="forbid")

    player_id: int
    x: FiniteFloat
    y: FiniteFloat


class EvaluateRequest(BaseModel):
    """Moves applied in order on top of the shot's decision frame."""

    model_config = ConfigDict(extra="forbid")

    moves: Annotated[list[Move], Field(max_length=BOARD_MAX_MOVES)]


def _json_rows(frame: pl.DataFrame) -> list[dict[str, Any]]:
    """Rows as plain dicts; NaN floats become None so the response is valid JSON."""
    return [
        {k: None if isinstance(v, float) and math.isnan(v) else v for k, v in row.items()}
        for row in frame.to_dicts()
    ]


def create_app(
    settings: Settings,
    *,
    model: ValueModel | None = None,
    priors: Priors | None = None,
    games: Sequence[int] | None = None,
) -> FastAPI:
    """Build the service and the board eagerly and the app around them.

    ``games`` restricts the board's shot list, default shot and Games view. Missing artifacts raise a ``VentajaError``.
    """
    if not frame_files(settings):
        raise VentajaError(_NO_FRAMES)
    try:
        service = AskService(settings, model=model, priors=priors)
        board = service.board
    except DataNotFoundError as exc:
        raise VentajaError(str(exc)) from exc
    schemas = tool_schemas(create_server(settings, service=service))  # asyncio.run: sync code only
    allowed = None if games is None else set(games)

    app = FastAPI(title="ventaja")

    @app.exception_handler(RequestValidationError)
    def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        # The default handler echoes the offending input, and a NaN cannot be serialised.
        detail = [{k: v for k, v in e.items() if k in ("type", "loc", "msg")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": detail})

    app.mount("/static", _NoCacheStatic(directory=STATIC_DIR), name="static")
    reel_root = REPO_ROOT / "docs" / "reel"
    if reel_root.is_dir():
        app.mount("/reel", StaticFiles(directory=reel_root), name="reel")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/api/court")
    def court() -> dict[str, Any]:
        return court_payload()

    @app.get("/api/shots")
    def shots(game: int | None = None) -> list[dict[str, Any]]:
        frame = board.shots(game)
        if allowed is not None:
            frame = frame.filter(pl.col("game_id").is_in(sorted(allowed)))
        return _json_rows(frame.sort("cost", descending=True, nulls_last=True))

    @app.get("/api/shot/{shot_id}")
    def shot(shot_id: str) -> dict[str, Any]:
        return _evaluate(board, shot_id, [])

    @app.post("/api/shot/{shot_id}/evaluate")
    def evaluate(shot_id: str, request: EvaluateRequest) -> dict[str, Any]:
        return _evaluate(board, shot_id, request.moves)

    @app.get("/api/ask/schema")
    def ask_schema() -> list[dict[str, Any]]:
        return schemas

    @app.get("/api/ask/glossary")
    def ask_glossary() -> PlainTextResponse:
        return PlainTextResponse(render_glossary(), media_type="text/markdown")

    @app.post("/api/ask/{tool}", response_model=None)
    def ask(tool: str, body: Annotated[Any, Body()] = None) -> Any:
        if tool not in TOOL_NAMES:
            return _error(404, f"unknown tool {tool!r}; tools: {', '.join(TOOL_NAMES)}")
        if body is not None and not isinstance(body, dict):
            return _error(400, "arguments must be a JSON object")
        try:
            result = call_tool(service, tool, body or {})
        except DataNotFoundError as exc:
            return _error(404, str(exc))
        except ValidationError as exc:
            detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            return _error(400, detail)
        except (VentajaError, ValueError) as exc:
            return _error(400, str(exc))
        return [r.model_dump() for r in result] if isinstance(result, list) else result.model_dump()

    @app.get("/api/curve/{shot_id}", response_model=None)
    def curve(shot_id: str) -> Any:
        rows = _curve_rows(settings, shot_id)
        if rows is None or rows.is_empty():
            return _error(404, f"no advantage curve for {shot_id!r}")
        return _curve_payload(service, shot_id, rows)

    @app.get("/api/reel")
    def reel() -> dict[str, Any]:
        return _reel_clips(REPO_ROOT / "docs" / "reel")

    @app.get("/api/featured", response_model=None)
    def featured(n: int = 10) -> Any:
        if not 1 <= n <= _MAX_FEATURED:
            return _error(400, f"n must be between 1 and {_MAX_FEATURED}")
        return service.featured(n).model_dump()

    @app.get("/api/about")
    def about() -> dict[str, Any]:
        carded = service.players.filter(pl.col("player_id") != LEAGUE_ID)
        first = service.players.row(0, named=True) if service.players.height else {}
        return {
            "version": __version__,
            "games": service.games.height,
            "valued_shots": int(service.decisions.filter(pl.col("rule") != "excluded").height),
            "players": carded.height,
            "model_trained_at": first.get("model_trained_at"),
            "built_at": first.get("built_at"),
            "games_filter": None if allowed is None else sorted(allowed),
        }

    @app.get("/docs/decisions/{name}", response_model=None)
    def decision_doc(name: str) -> Any:
        directory = (REPO_ROOT / "docs" / "decisions").resolve()
        path = (directory / name).resolve()
        if not _DECISION_DOC.match(name) or path.parent != directory or not path.is_file():
            return _error(404, f"no decision record {name!r}")
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")

    return app


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


def _clean(value: Any) -> Any:
    return None if isinstance(value, float) and math.isnan(value) else value


def _curve_rows(settings: Settings, shot_id: str) -> pl.DataFrame | None:
    match = _SHOT_GAME.match(shot_id)
    if match is None:
        return None
    try:
        curves = load_curves(int(match.group(1)), settings)
    except DataNotFoundError:
        return None
    return curves.filter(pl.col("shot_id") == shot_id).sort("frame_idx")


def _curve_payload(service: AskService, shot_id: str, rows: pl.DataFrame) -> dict[str, Any]:
    decision = service.decisions.filter(pl.col("shot_id") == shot_id)
    summary_rows = service.summaries.filter(pl.col("shot_id") == shot_id)
    summary = summary_rows.row(0, named=True) if summary_rows.height else None
    release = decision["release_frame"][0] if decision.height else None
    decision_t = (decision["decision_frame"][0] - release) / FPS if release is not None else None
    window = None
    if (
        summary
        and release is not None
        and None not in (summary["window_start"], summary["window_end"])
    ):
        window = [(summary[k] - release) / FPS for k in ("window_start", "window_end")]
    handler_ids = sorted({int(h) for h in rows["handler_id"] if h is not None})
    jerseys = service.people.jerseys
    return {
        "shot_id": shot_id,
        "rows": [
            {
                "t": _clean(r["t_to_release"]),
                "frame": r["frame_idx"],
                "handler_id": r["handler_id"],
                "handler_shot_value": _clean(r["handler_shot_value"]),
                "best_pass_value": _clean(r["best_pass_value"]),
                "best_value": _clean(r["best_value"]),
                "n_viable": r["n_viable"],
            }
            for r in rows.iter_rows(named=True)
        ],
        "summary": None if summary is None else {k: _clean(summary[k]) for k in _SUMMARY_KEYS},
        "decision_t": decision_t,
        "release_t": 0.0,
        "window": window,
        "handlers": {str(h): jerseys.get(h) or str(h)[-2:] for h in handler_ids},
    }


def _reel_clips(root: Path) -> dict[str, Any]:
    """Clips of the lexicographically last reel directory that holds GIFs."""
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), reverse=True) if root.is_dir() else []
    for directory in dirs:
        gifs = sorted(directory.glob("*.gif"))
        if not gifs:
            continue
        clips: dict[str, str] = {}
        for gif in gifs:
            match = _REEL_CLIP.match(gif.name)
            if match:
                clips.setdefault(match.group("shot"), f"/reel/{directory.name}/{gif.name}")
        return {"dir": directory.name, "clips": clips}
    return {"dir": None, "clips": {}}


def _evaluate(board: Board, shot_id: str, moves: Sequence[Move]) -> dict[str, Any]:
    try:
        state = board.load(shot_id)
    except DataNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    for move in moves:
        try:
            state = board.move(state, move.player_id, move.x, move.y)
        except KeyError as exc:
            raise HTTPException(
                status_code=422, detail=f"player {move.player_id} is not on court in {shot_id}"
            ) from exc
    return board.payload(state, board.evaluate(state))
