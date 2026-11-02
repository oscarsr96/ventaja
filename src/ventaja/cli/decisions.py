"""`ventaja decisions` commands."""

from pathlib import Path
from typing import Annotated

import polars as pl
import typer

from ventaja.cli._common import AllOption, GameOption, fmt, game_of_shot
from ventaja.config import GAME_IDS, Settings
from ventaja.data.load import (
    load_decision_options,
    load_decisions,
)
from ventaja.decision.cost import build_decisions
from ventaja.errors import DataNotFoundError, VentajaError
from ventaja.value import model as model_module
from ventaja.viz.text import format_option_table

app = typer.Typer(help="Build and inspect shot decision costs.", no_args_is_help=True)


def _decision_summary(df: pl.DataFrame) -> str:
    valid = df.filter(pl.col("rule") != "excluded")
    excluded = df.filter(pl.col("rule") == "excluded").group_by("reason").len().sort("reason")
    reasons = ", ".join(f"{r} {n}" for r, n in excluded.iter_rows()) or "none"
    reads = valid["good_read"].drop_nulls() if valid.height else pl.Series([], dtype=pl.Boolean)
    mean_cost = f"{float(valid['cost'].mean()):.3f}" if valid.height else "n/a"  # type: ignore[arg-type]
    good = f"{float(reads.mean()):.1%}" if reads.len() else "n/a"  # type: ignore[arg-type]
    no_pass = valid.height - reads.len()
    return (
        f"{df.height} shots: valid {valid.height}; excluded {reasons}; "
        f"mean cost {mean_cost}; good_read {good} (no viable pass {no_pass})"
    )


@app.command("build")
def decisions_build(
    game: GameOption = None,
    all_games: AllOption = False,
    model_path: Annotated[
        Path | None, typer.Option("--model", help="Model JSON path (default: versioned model).")
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Output directory (default: the build's decisions/)."),
    ] = None,
) -> None:
    """Value every shot against its pass options and write the decisions tables."""
    if not game and not all_games:
        typer.echo("error: choose games with --game ID (repeatable) or --all", err=True)
        raise typer.Exit(code=2)
    try:
        settings = Settings.from_env()
        loaded = (
            model_module.ValueModel.load(model_path)
            if model_path
            else model_module.ValueModel.default()
        )
        for game_id in GAME_IDS if all_games else game or []:
            path = build_decisions(game_id, settings, model=loaded, out_dir=out)
            typer.echo(f"game {game_id}: {_decision_summary(pl.read_parquet(path))}")
            typer.echo(f"  -> {path}")
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _read(good_read: bool | None) -> str:
    return "- (no viable pass)" if good_read is None else str(good_read)


@app.command("show")
def decisions_show(
    shot_id: Annotated[str, typer.Argument(help="Shot id, e.g. shot-114243-1-0.")],
) -> None:
    """Print a shot's decision and its five options (* shooter, > best alternative)."""
    try:
        settings = Settings.from_env()
        game_id = game_of_shot(shot_id)
        hit = load_decisions(game_id, settings).filter(pl.col("shot_id") == shot_id)
        if hit.height == 0:
            raise DataNotFoundError(f"shot {shot_id} not found in the decisions of {game_id}")
        d = hit.row(0, named=True)
        if d["rule"] == "excluded":
            raise VentajaError(f"shot {shot_id} is excluded: {d['reason']}")
        opts = load_decision_options(game_id, settings).filter(pl.col("shot_id") == shot_id)
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"{shot_id}  frame {d['decision_frame']} ({d['rule']})  release {d['release_frame']}  "
        f"shot_clock {fmt(d['shot_clock'], '.2f')}"
    )
    typer.echo(
        f"shot value {fmt(d['shot_value'])}  best alt {fmt(d['best_alt_value'])}  "
        f"cost {fmt(d['cost'])}  good_read {_read(d['good_read'])}  "
        f"confidence {fmt(d['confidence'], '.1f')}"
    )
    typer.echo(
        format_option_table(
            opts, shooter_id=d["shooter_id"], best_alt_player_id=d["best_alt_player_id"]
        )
    )
