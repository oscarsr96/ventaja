"""Command-line entry point for ventaja."""

from collections.abc import Callable
from typing import Annotated

import httpx
import typer

from ventaja import __version__
from ventaja.config import GAME_IDS, Settings
from ventaja.data import build as build_module
from ventaja.data import pull as pull_module
from ventaja.data.catalog import files_for
from ventaja.errors import VentajaError

app = typer.Typer(name="ventaja", no_args_is_help=True)
data = typer.Typer(help="Download, inspect and build SkillCorner data.", no_args_is_help=True)
app.add_typer(data, name="data")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ventaja {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Basketball tracking analytics."""


GameOption = Annotated[list[int] | None, typer.Option("--game", help="Game id (repeatable).")]
AllOption = Annotated[bool, typer.Option("--all", help="All ten games.")]


def _selection(game: list[int] | None, all_games: bool) -> list[int] | None:
    """Game ids to act on: None means all, empty means only the common files."""
    return None if all_games else list(game or [])


def _recorder(sizes: list[int]) -> Callable[[str, int, int], None]:
    def record(_relpath: str, done: int, _total: int) -> None:
        sizes.append(done)

    return record


@data.command("pull")
def data_pull(
    game: GameOption = None,
    all_games: AllOption = False,
    no_tracking: Annotated[
        bool, typer.Option("--no-tracking", help="Skip the large tracking files.")
    ] = False,
) -> None:
    """Download raw files (only the common ones without --game/--all)."""
    settings = Settings.from_env()
    files = files_for(_selection(game, all_games), tracking=not no_tracking)
    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        for f in files:
            sizes: list[int] = []
            pull_module.pull([f], settings, client=client, progress=_recorder(sizes))
            if sizes:
                typer.echo(f"pull {f.relpath} ({sizes[0]} bytes)")
            else:
                typer.echo(f"skip {f.relpath}")


@data.command("status")
def data_status(game: GameOption = None, all_games: AllOption = False) -> None:
    """Show which raw files are present locally."""
    rows = pull_module.status(Settings.from_env(), _selection(game, all_games))
    for f, present in rows:
        typer.echo(f"{'present' if present else 'missing'} {f.relpath}")
    typer.echo(f"{sum(p for _, p in rows)}/{len(rows)} present")


@data.command("build")
def data_build(game: GameOption = None, all_games: AllOption = False) -> None:
    """Build parquet tables from raw files for the selected games."""
    if not game and not all_games:
        typer.echo("error: choose games with --game ID (repeatable) or --all", err=True)
        raise typer.Exit(code=2)
    settings = Settings.from_env()
    for game_id in GAME_IDS if all_games else game or []:
        try:
            written = build_module.build_events(game_id, settings)
        except VentajaError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        for table, path in written.items():
            typer.echo(f"wrote {game_id} {table} -> {path}")
        # Task 6: build tracking here (skipped with --events-only).
