"""FastAPI app of the whiteboard: court, shots, and shot evaluation with moved players."""

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

import polars as pl
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from ventaja.board.engine import Board, court_payload
from ventaja.config import Settings
from ventaja.data.load import frame_files
from ventaja.errors import DataNotFoundError, VentajaError
from ventaja.value.model import ValueModel
from ventaja.value.params import BOARD_MAX_MOVES
from ventaja.value.priors import Priors

STATIC_DIR = Path(__file__).parent / "static"
_NO_FRAMES = "no decision frames found; run `ventaja frames build --all` first"


class Move(BaseModel):
    """One player dragged to a position (court metres, offense orientation)."""

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
    """Build the board eagerly and the app around it.

    ``games`` restricts the shot list. Missing artifacts raise a ``VentajaError``.
    """
    if not frame_files(settings):
        raise VentajaError(_NO_FRAMES)
    try:
        board = Board(settings, model=model, priors=priors)
    except DataNotFoundError as exc:
        raise VentajaError(f"{exc}; run `ventaja frames build --all` first") from exc
    allowed = None if games is None else set(games)

    app = FastAPI(title="ventaja board")

    @app.exception_handler(RequestValidationError)
    def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        # The default handler echoes the offending input, and a NaN cannot be serialised.
        detail = [{k: v for k, v in e.items() if k in ("type", "loc", "msg")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/api/court")
    def court() -> dict[str, Any]:
        return court_payload()

    @app.get("/api/shots")
    def shots(game: int | None = None) -> list[dict[str, Any]]:
        if game is not None:
            frame = board.shots(game) if allowed is None or game in allowed else board.shots(-1)
        elif allowed is None:
            frame = board.shots()
        else:
            frame = board.shots().filter(pl.col("game_id").is_in(sorted(allowed)))
        return _json_rows(frame.sort("cost", descending=True, nulls_last=True))

    @app.get("/api/shot/{shot_id}")
    def shot(shot_id: str) -> dict[str, Any]:
        return _evaluate(board, shot_id, [])

    @app.post("/api/shot/{shot_id}/evaluate")
    def evaluate(shot_id: str, request: EvaluateRequest) -> dict[str, Any]:
        return _evaluate(board, shot_id, request.moves)

    return app


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
