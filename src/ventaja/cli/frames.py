"""`ventaja frames` commands."""

from pathlib import Path
from typing import Annotated

import polars as pl
import typer

from ventaja.cli._common import AllOption, GameOption
from ventaja.config import GAME_IDS, Settings
from ventaja.decision.frames import build_frames
from ventaja.errors import VentajaError

app = typer.Typer(help="Build the decision frames the whiteboard draws.", no_args_is_help=True)


@app.command("build")
def frames_build(
    game: GameOption = None,
    all_games: AllOption = False,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Output directory (default: the build's frames/)."),
    ] = None,
) -> None:
    """Write the decision frame (10 players and the ball) of every valued shot."""
    if not game and not all_games:
        typer.echo("error: choose games with --game ID (repeatable) or --all", err=True)
        raise typer.Exit(code=2)
    try:
        settings = Settings.from_env()
        for game_id in GAME_IDS if all_games else game or []:
            path = build_frames(game_id, settings, out_dir=out)
            frames = pl.read_parquet(path, columns=["shot_id"])
            typer.echo(
                f"game {game_id}: {frames['shot_id'].n_unique()} shots, {frames.height} rows"
            )
            typer.echo(f"  -> {path}")
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
