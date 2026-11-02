"""`ventaja curves` commands."""

from pathlib import Path
from typing import Annotated, Any

import polars as pl
import typer

from ventaja.cli._common import AllOption, GameOption, fmt, game_of_shot
from ventaja.config import GAME_IDS, Settings
from ventaja.data.load import (
    load_curve_summaries,
    load_curves,
    load_decision_options,
    load_decisions,
)
from ventaja.decision.cost import decision_from_tables
from ventaja.decision.curve import build_curves
from ventaja.errors import DataNotFoundError, VentajaError
from ventaja.value import model as model_module
from ventaja.value.priors import Priors
from ventaja.viz import clip as clip_module
from ventaja.viz import kit as kit_module

app = typer.Typer(help="Build and inspect possession advantage curves.", no_args_is_help=True)


VERDICTS = ("late", "during", "none", "no_window")


def _curve_summary(valued: int, summaries: pl.DataFrame) -> str:
    counts = dict(summaries.group_by("verdict").len().iter_rows())
    verdicts = ", ".join(f"{v} {counts.get(v, 0)}" for v in VERDICTS)
    windows = summaries.filter(pl.col("window_start").is_not_null())["advantage_seconds"]
    median = f"{float(windows.median()):.1f} s" if windows.len() else "n/a"  # type: ignore[arg-type]
    return (
        f"{valued} shots, {summaries.height} curves; {verdicts}; "
        f"median advantage {median} (over {windows.len()} windows)"
    )


@app.command("build")
def curves_build(
    game: GameOption = None,
    all_games: AllOption = False,
    model_path: Annotated[
        Path | None, typer.Option("--model", help="Model JSON path (default: versioned model).")
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Output directory (default: the build's curves/)."),
    ] = None,
) -> None:
    """Sample the handler's best option along each valued shot's chance and summarize it."""
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
        priors = Priors.from_settings(settings)
        for game_id in GAME_IDS if all_games else game or []:
            valued = load_decisions(game_id, settings).filter(pl.col("rule") != "excluded")
            curve_path, summary_path = build_curves(
                game_id, settings, model=loaded, priors=priors, out_dir=out
            )
            summary = _curve_summary(valued.height, pl.read_parquet(summary_path))
            typer.echo(f"game {game_id}: {summary}")
            typer.echo(f"  -> {curve_path}")
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _best(row: dict[str, Any]) -> str:
    if row["best_option_type"] == "shot":
        return f"{row['best_player_id']} shot"
    return f"{row['best_player_id']} pass/{row['best_alt_type']}"


@app.command("show")
def curves_show(
    shot_id: Annotated[str, typer.Argument(help="Shot id, e.g. shot-114243-1-0.")],
) -> None:
    """Print a shot's curve summary and its curve, one row per sampled frame."""
    try:
        settings = Settings.from_env()
        game_id = game_of_shot(shot_id)
        hit = load_curve_summaries(game_id, settings).filter(pl.col("shot_id") == shot_id)
        if hit.height == 0:
            raise DataNotFoundError(
                f"shot {shot_id} not found in the curve summaries of {game_id} "
                "(excluded shots have no curve)"
            )
        s = hit.row(0, named=True)
        curve = load_curves(game_id, settings).filter(pl.col("shot_id") == shot_id)
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"{shot_id}  {s['headline_es']}")
    typer.echo(
        f"verdict {s['verdict']}  rows {s['n_rows']}  span {s['span_start']}-{s['span_end']}  "
        f"shot value {fmt(s['shot_value'])}  skipped off court {s['skipped_off_court']}"
    )
    typer.echo(
        f"window {s['window_start'] or '-'}-{s['window_end'] or '-'}  "
        f"handler {s['window_handler_id'] or '-'}  best pass {fmt(s['window_peak_value'])}  "
        f"advantage {s['advantage_seconds']:.1f} s  lag {fmt(s['release_lag_seconds'], '.1f')} s"
    )
    typer.echo(
        f"peak {fmt(s['peak_value'])} at {s['peak_frame'] or '-'}  "
        f"value at decision {fmt(s['value_at_decision'])}"
    )
    typer.echo(
        f"{'t_to_release':>12} {'handler':>8} {'shot_clock':>10} {'handler_shot_value':>18} "
        f"{'best_value':>10} {'best_pass_value':>15}  best"
    )
    for r in curve.sort("frame_idx").iter_rows(named=True):
        typer.echo(
            f"{r['t_to_release']:>12.1f} {r['handler_id']:>8} {fmt(r['shot_clock'], '.2f'):>10} "
            f"{r['handler_shot_value']:>18.3f} {r['best_value']:>10.3f} "
            f"{fmt(r['best_pass_value']):>15}  {_best(r)}"
        )


@app.command("plot")
def curves_plot(
    shot_id: Annotated[str, typer.Argument(help="Shot id, e.g. shot-114243-1-0.")],
    out: Annotated[Path, typer.Option("--out", help="Output image file (e.g. curve.png).")],
) -> None:
    """Save a shot's advantage curve as an image, titled with its headline."""
    try:
        settings = Settings.from_env()
        game_id = game_of_shot(shot_id)
        decision = decision_from_tables(
            shot_id, load_decisions(game_id, settings), load_decision_options(game_id, settings)
        )
        curve, summary = clip_module.curve_of_shot(
            shot_id, load_curves(game_id, settings), load_curve_summaries(game_id, settings)
        )
        name = kit_module.player_name(
            kit_module.players_table(settings), game_id, summary.window_handler_id
        )
        path = clip_module.curve_figure(
            curve,
            summary,
            decision.decision_frame,
            out,
            shooter_id=decision.shooter_id,
            handler_name=name,
        )
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"curve -> {path}")
