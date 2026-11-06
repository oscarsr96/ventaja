"""`ventaja app` (alias `board`): serve the ventaja app locally."""

import socket
import threading
import time
import webbrowser
from typing import Annotated

import typer

from ventaja.cli._common import GameOption, run_or_exit, settings_or_exit
from ventaja.value.params import BOARD_PORT

OPEN_WAIT_SECONDS = 10.0  # how long to wait for the server before giving up opening the browser


def _open_when_listening(host: str, port: int, url: str) -> None:
    """Open the browser once the server accepts connections (it starts after this call)."""
    deadline = time.monotonic() + OPEN_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        return
    webbrowser.open(url)


def app(
    host: Annotated[str, typer.Option("--host", help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port to serve on.")] = BOARD_PORT,
    game: GameOption = None,
    no_open: Annotated[bool, typer.Option("--no-open", help="Do not open the browser.")] = False,
) -> None:
    """Serve the ventaja app: shot, whiteboard, curve, players, games and the MCP tools in one page."""  # noqa: E501
    import uvicorn

    from ventaja.web.app import create_app

    settings = settings_or_exit()
    app = run_or_exit(lambda: create_app(settings, games=game or None))
    url = f"http://{host}:{port}/"
    typer.echo(f"ventaja app at {url} (Ctrl+C to stop)")
    if not no_open:
        threading.Thread(target=_open_when_listening, args=(host, port, url), daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


def board(
    host: Annotated[str, typer.Option("--host", help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port to serve on.")] = BOARD_PORT,
    game: GameOption = None,
    no_open: Annotated[bool, typer.Option("--no-open", help="Do not open the browser.")] = False,
) -> None:
    """Alias of `ventaja app` (kept for the whiteboard users)."""
    app(host=host, port=port, game=game, no_open=no_open)
