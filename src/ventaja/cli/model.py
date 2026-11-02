"""`ventaja model` commands."""

from pathlib import Path
from typing import Annotated, Any

import polars as pl
import typer

from ventaja.cli._common import AllOption, GameOption, run_or_exit
from ventaja.config import GAME_IDS, Settings
from ventaja.decision.align import Aligner
from ventaja.errors import VentajaError
from ventaja.value import model as model_module
from ventaja.value.features import shot_rows
from ventaja.value.priors import Priors

app = typer.Typer(help="Train and inspect the value model.", no_args_is_help=True)


DEFAULT_FIGURE_PATH = Path("docs/figures/calibration.png")


def _print_metrics(metrics: dict[str, float | None]) -> None:
    for name, value in metrics.items():
        typer.echo(f"{name:>32} {'null' if value is None else f'{value:.4f}'}")


def _print_zone_table(rows: list[dict[str, Any]]) -> None:
    """Per-zone LOGO comparison: mean prediction, observed and league rates."""
    if not rows:
        typer.echo("zone table: not stored in this model (retrain to add it)")
        return
    typer.echo(f"{'zone':16} {'n':>5} {'mean_pred':>9} {'observed':>9} {'league':>7}")
    for r in rows:
        typer.echo(
            f"{r['zone']:16} {r['n']:>5} {r['mean_pred']:>9.3f} "
            f"{r['observed_rate']:>9.3f} {r['league_rate']:>7.3f}"
        )


@app.command("train")
def model_train(
    game: GameOption = None,
    all_games: AllOption = False,
    out: Annotated[Path | None, typer.Option("--out", help="Model JSON path.")] = None,
    figure: Annotated[
        Path, typer.Option("--figure", help="Calibration figure path.")
    ] = DEFAULT_FIGURE_PATH,
) -> None:
    """Train with leave-one-game-out validation and save the model and calibration figure."""
    try:
        settings = Settings.from_env()
        priors = Priors.from_settings(settings)
        ids = GAME_IDS if all_games or not game else game
        frames = [shot_rows(Aligner(g, settings), priors) for g in ids]
        df = pl.concat([f for f in frames if not f.is_empty()], how="diagonal_relaxed")
        fitted, preds = model_module.train_logo(df)
        fitted.zone_table = model_module.zone_table(preds, priors).to_dicts()
        path = out or model_module.DEFAULT_MODEL_PATH
        fitted.save(path)
        model_module.plot_calibration(
            model_module.calibration_table(preds),
            figure,
            n_shots=preds.height,
            logloss=fitted.metrics["logloss"],
        )
    except (VentajaError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"games {fitted.trained_on}")
    _print_metrics(fitted.metrics)
    _print_zone_table(fitted.zone_table)
    typer.echo(f"model -> {path}")
    typer.echo(f"figure -> {figure}")


@app.command("report")
def model_report(
    path: Annotated[Path | None, typer.Option("--model", help="Model JSON path.")] = None,
) -> None:
    """Print the metrics and standardized coefficients of a saved model."""
    loaded = run_or_exit(
        lambda: model_module.ValueModel.load(path or model_module.DEFAULT_MODEL_PATH)
    )
    typer.echo(f"trained on {loaded.trained_on} ({loaded.n_rows} shots) at {loaded.trained_at}")
    _print_metrics(loaded.metrics)
    with pl.Config(tbl_rows=50):
        typer.echo(repr(loaded.feature_table()))
    _print_zone_table(loaded.zone_table)
