"""`ventaja board`: serve the whiteboard locally."""

import webbrowser
from typing import Annotated

import typer
import uvicorn

from ventaja.board.app import create_app
from ventaja.cli._common import GameOption, run_or_exit, settings_or_exit
from ventaja.value.params import BOARD_PORT


def board(
    host: Annotated[str, typer.Option("--host", help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port to serve on.")] = BOARD_PORT,
    game: GameOption = None,
    no_open: Annotated[bool, typer.Option("--no-open", help="Do not open the browser.")] = False,
) -> None:
    """Serve the whiteboard: drag players and see what the decision would cost."""
    settings = settings_or_exit()
    app = run_or_exit(lambda: create_app(settings, games=game or None))
    url = f"http://{host}:{port}/"
    typer.echo(f"ventaja board at {url} (Ctrl+C to stop)")
    if not no_open:
        webbrowser.open(url)
    uvicorn.run(app, host=host, port=port, log_level="warning")
