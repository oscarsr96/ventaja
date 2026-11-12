"""`ventaja frames` commands."""

from pathlib import Path
from typing import Annotated

import polars as pl
import typer

from ventaja.cli._common import AllOption, GameOption
from ventaja.config import GAME_IDS, Settings
from ventaja.decision.frames import build_frames, build_plays
from ventaja.errors import VentajaError

app = typer.Typer(help="Build the decision frames the whiteboard draws.", no_args_is_help=True)


def _plays_dir(out: Path) -> Path:
    return out.parent / "plays" if out.name == "frames" else out / "plays"


@app.command("build")
def frames_build(
    game: GameOption = None,
    all_games: AllOption = False,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            help="Frames directory (default: the build's frames/); plays go to its sibling "
            "plays/ when it is named 'frames', else to DIR/plays.",
        ),
    ] = None,
    no_plays: Annotated[
        bool, typer.Option("--no-plays", help="Do not write the full-possession plays.")
    ] = False,
) -> None:
    """Write the decision frame (10 players and the ball) of every valued shot.

    Also writes the full possession of each shot at 25 fps (plays). With --out DIR, frames go
    to DIR and plays to DIR/../plays when DIR is named "frames", else to DIR/plays.
    """
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
            if no_plays:
                continue
            plays_out = None if out is None else _plays_dir(out)
            plays_path = build_plays(game_id, settings, out_dir=plays_out)
            plays = pl.read_parquet(plays_path, columns=["shot_id"])
            typer.echo(
                f"  plays: {plays['shot_id'].n_unique()} shots, {plays.height} rows -> {plays_path}"
            )
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
