"""`ventaja data` commands."""

from collections.abc import Callable
from typing import Annotated

import httpx
import typer

from ventaja.cli._common import AllOption, GameOption, run_or_exit, settings_or_exit
from ventaja.config import GAME_IDS, Settings
from ventaja.data import build as build_module
from ventaja.data import pull as pull_module
from ventaja.data.catalog import files_for
from ventaja.errors import VentajaError

app = typer.Typer(help="Download, inspect and build SkillCorner data.", no_args_is_help=True)


def _selection(game: list[int] | None, all_games: bool) -> list[int] | None:
    """Game ids to act on: None means all, empty means only the common files."""
    return None if all_games else list(game or [])


def _recorder(sizes: list[int]) -> Callable[[str, int, int], None]:
    def record(_relpath: str, done: int, _total: int) -> None:
        sizes.append(done)

    return record


@app.command("pull")
def data_pull(
    game: GameOption = None,
    all_games: AllOption = False,
    no_tracking: Annotated[
        bool, typer.Option("--no-tracking", help="Skip the large tracking files.")
    ] = False,
) -> None:
    """Download raw files (only the common ones without --game/--all)."""
    settings = settings_or_exit()
    files = run_or_exit(lambda: files_for(_selection(game, all_games), tracking=not no_tracking))
    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        for f in files:
            sizes: list[int] = []
            try:
                pull_module.pull([f], settings, client=client, progress=_recorder(sizes))
            except httpx.HTTPError as exc:
                typer.echo(
                    f"error: cannot download {f.url}: {exc}; check your connection", err=True
                )
                raise typer.Exit(code=1) from exc
            if sizes:
                typer.echo(f"pull {f.relpath} ({sizes[0]} bytes)")
            else:
                typer.echo(f"skip {f.relpath}")


@app.command("status")
def data_status(game: GameOption = None, all_games: AllOption = False) -> None:
    """Show which raw files are present locally."""
    rows = run_or_exit(lambda: pull_module.status(settings_or_exit(), _selection(game, all_games)))
    for f, present in rows:
        typer.echo(f"{'present' if present else 'missing'} {f.relpath}")
    typer.echo(f"{sum(p for _, p in rows)}/{len(rows)} present")


@app.command("build")
def data_build(
    game: GameOption = None,
    all_games: AllOption = False,
    events_only: Annotated[
        bool, typer.Option("--events-only", help="Skip the slow tracking build.")
    ] = False,
) -> None:
    """Build parquet tables from raw files for the selected games."""
    if not game and not all_games:
        typer.echo("error: choose games with --game ID (repeatable) or --all", err=True)
        raise typer.Exit(code=2)
    settings = Settings.from_env()
    for game_id in GAME_IDS if all_games else game or []:
        try:
            written = build_module.build_events(game_id, settings)
            for table, path in written.items():
                typer.echo(f"wrote {game_id} {table} -> {path}")
            if not events_only:
                path = build_module.build_tracking(game_id, settings)
                typer.echo(f"wrote {game_id} tracking -> {path}")
            for table, path in build_module.build_meta(game_id, settings).items():
                typer.echo(f"meta {game_id} {table} -> {path}")
        except VentajaError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    aggregates = build_module.build_aggregates(settings)
    for name in build_module.AGGREGATE_TABLES:
        if name in aggregates:
            typer.echo(f"aggregate {name} -> {aggregates[name]}")
        else:
            typer.echo(f"skip aggregate {name} (no CSV in {settings.raw_path('aggregates')})")
