"""`ventaja validate` commands."""

from pathlib import Path
from typing import Annotated

import polars as pl
import typer

from ventaja.cli._common import AllOption, GameOption, run_or_exit, settings_or_exit
from ventaja.config import GAME_IDS, Settings
from ventaja.data.load import (
    load_decision_options,
    load_decisions,
)
from ventaja.errors import VentajaError
from ventaja.validate import decisions as decisions_checks
from ventaja.validate import score as score_module
from ventaja.value import model as model_module

app = typer.Typer(help="Check the event model against official data.", no_args_is_help=True)


@app.command("score")
def validate_score(game: GameOption = None, all_games: AllOption = False) -> None:
    """Rebuild final scores from shots and free throws and compare with matches.json."""
    if not game and not all_games:
        typer.echo("error: choose games with --game ID (repeatable) or --all", err=True)
        raise typer.Exit(code=2)
    rows = run_or_exit(
        lambda: score_module.check_scores(GAME_IDS if all_games else game or [], settings_or_exit())
    )
    for game_id, got, official, ok in rows:
        typer.echo(
            f"game {game_id}: {got.home}-{got.away} "
            f"(official {official.home}-{official.away}) {'ok' if ok else 'MISMATCH'}"
        )
    if not all(ok for *_, ok in rows):
        raise typer.Exit(code=1)


@app.command("decisions")
def validate_decisions(
    game: GameOption = None,
    all_games: AllOption = False,
    model_path: Annotated[
        Path | None, typer.Option("--model", help="Model JSON path (default: versioned model).")
    ] = None,
    allow_fail: Annotated[
        list[str] | None,
        typer.Option(
            "--allow-fail",
            help="Check name whose failure is reported but does not fail (repeatable).",
        ),
    ] = None,
) -> None:
    """Run the face-validity checks over the decisions tables (default: all games)."""
    ids = game if game and not all_games else GAME_IDS
    try:
        settings = Settings.from_env()
        loaded = (
            model_module.ValueModel.load(model_path)
            if model_path
            else model_module.ValueModel.default()
        )
        results = decisions_checks.checks(
            pl.concat([load_decisions(g, settings) for g in ids], how="diagonal"),
            pl.concat([load_decision_options(g, settings) for g in ids], how="diagonal"),
            loaded,
        )
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    allowed = set(allow_fail or [])
    unknown = allowed - {name for name, _, _ in results}
    if unknown:
        typer.echo(f"error: unknown check for --allow-fail: {', '.join(sorted(unknown))}", err=True)
        raise typer.Exit(code=2)
    for name, ok, detail in results:
        status = "ok  " if ok else "FAIL (allowed)" if name in allowed else "FAIL"
        typer.echo(f"{status} {name} — {detail}")
    if not all(ok or name in allowed for name, ok, _ in results):
        raise typer.Exit(code=1)
