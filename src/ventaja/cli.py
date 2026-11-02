"""Command-line entry point for ventaja."""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import duckdb
import httpx
import polars as pl
import typer

from ventaja import __version__
from ventaja.config import GAME_IDS, Settings
from ventaja.data import build as build_module
from ventaja.data import pull as pull_module
from ventaja.data.catalog import files_for
from ventaja.data.duck import connect
from ventaja.data.load import load_decision_options, load_decisions
from ventaja.decision.align import Aligner
from ventaja.decision.cost import build_decisions
from ventaja.errors import DataNotFoundError, VentajaError
from ventaja.validate import score as score_module
from ventaja.value import model as model_module
from ventaja.value.features import shot_rows
from ventaja.value.priors import Priors

app = typer.Typer(name="ventaja", no_args_is_help=True)
data = typer.Typer(help="Download, inspect and build SkillCorner data.", no_args_is_help=True)
app.add_typer(data, name="data")
validate = typer.Typer(help="Check the event model against official data.", no_args_is_help=True)
app.add_typer(validate, name="validate")
model = typer.Typer(help="Train and inspect the value model.", no_args_is_help=True)
app.add_typer(model, name="model")
decisions = typer.Typer(help="Build and inspect shot decision costs.", no_args_is_help=True)
app.add_typer(decisions, name="decisions")


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
    try:
        files = files_for(_selection(game, all_games), tracking=not no_tracking)
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
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


@data.command("status")
def data_status(game: GameOption = None, all_games: AllOption = False) -> None:
    """Show which raw files are present locally."""
    try:
        rows = pull_module.status(Settings.from_env(), _selection(game, all_games))
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for f, present in rows:
        typer.echo(f"{'present' if present else 'missing'} {f.relpath}")
    typer.echo(f"{sum(p for _, p in rows)}/{len(rows)} present")


@data.command("build")
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


def _unique(names: list[str]) -> list[str]:
    """Suffix repeated column names with _1, _2, ... so Polars accepts them."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for name in names:
        n = seen.get(name, 0)
        seen[name] = n + 1
        out.append(name if n == 0 else f"{name}_{n}")
    return out


@app.command("sql")
def sql(
    query: Annotated[str, typer.Argument(help="SQL over the built tables and tracking.")],
    csv: Annotated[bool, typer.Option("--csv", help="Write CSV to stdout.")] = False,
) -> None:
    """Run SQL against the built parquet files through DuckDB."""
    try:
        con = connect(Settings.from_env())
        rel = con.sql(query)
        if rel is None:
            typer.echo("ok (no rows)")
            return
        df = pl.DataFrame(
            rel.fetchall(),
            schema=_unique(rel.columns),
            orient="row",
            infer_schema_length=None,
        )
    except duckdb.Error as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if csv:
        df.write_csv(sys.stdout)
    else:
        with pl.Config(tbl_rows=50, tbl_cols=20):
            typer.echo(repr(df))


def _game_of_shot(shot_id: str) -> int:
    """Game id embedded in a shot id of the form ``shot-{game_id}-{period}-{n}``."""
    parts = shot_id.split("-")
    if len(parts) != 4 or parts[0] != "shot" or not parts[1].isdigit():
        raise DataNotFoundError(f"cannot parse a game id from shot id {shot_id!r}; pass --game")
    return int(parts[1])


@app.command("snapshot")
def snapshot(
    shot_id: Annotated[str, typer.Argument(help="Shot id, e.g. shot-114243-1-0.")],
    game: Annotated[
        int | None, typer.Option("--game", help="Game id (parsed from the shot id if omitted).")
    ] = None,
    decision: Annotated[
        bool, typer.Option("--decision", help="Use the decision frame instead of the release.")
    ] = False,
) -> None:
    """Print the offense-oriented snapshot at a shot's frame; the shooter is marked *."""
    try:
        settings = Settings.from_env()
        game_id = game if game is not None else _game_of_shot(shot_id)
        aligner = Aligner(game_id, settings)
        shooter = aligner.shot(shot_id)["shooter_id"]
        chosen = aligner.decision_frame(shot_id) if decision else None
        snap = aligner.snapshot_for_shot(shot_id, decision=decision)
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if chosen is not None:
        typer.echo(f"decision frame {chosen.frame_idx} ({chosen.rule})")
    shot_clock = "-" if snap.shot_clock is None else f"{snap.shot_clock:.2f}"
    typer.echo(
        f"frame {snap.frame_idx}  period {snap.period}  "
        f"game_clock {snap.game_clock:.2f}  shot_clock {shot_clock}"
    )
    typer.echo(f"  {'player_id':>9} {'team_id':>7} {'side':4} {'x':>7} {'y':>7} {'speed':>6}")
    for side, players in (("OFF", snap.offense), ("DEF", snap.defense)):
        for p in players:
            mark = "*" if p.player_id == shooter else " "
            typer.echo(
                f"{mark} {p.player_id:>9} {p.team_id:>7} {side:4} "
                f"{p.x:>7.2f} {p.y:>7.2f} {p.speed:>6.2f}"
            )


@validate.command("score")
def validate_score(game: GameOption = None, all_games: AllOption = False) -> None:
    """Rebuild final scores from shots and free throws and compare with matches.json."""
    if not game and not all_games:
        typer.echo("error: choose games with --game ID (repeatable) or --all", err=True)
        raise typer.Exit(code=2)
    try:
        rows = score_module.check_scores(GAME_IDS if all_games else game or [], Settings.from_env())
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for game_id, got, official, ok in rows:
        typer.echo(
            f"game {game_id}: {got.home}-{got.away} "
            f"(official {official.home}-{official.away}) {'ok' if ok else 'MISMATCH'}"
        )
    if not all(ok for *_, ok in rows):
        raise typer.Exit(code=1)


DEFAULT_FIGURE_PATH = Path("docs/figures/calibration.png")


def _print_metrics(metrics: dict[str, float | None]) -> None:
    for name, value in metrics.items():
        typer.echo(f"{name:>32} {'null' if value is None else f'{value:.4f}'}")


@model.command("train")
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
    typer.echo(f"model -> {path}")
    typer.echo(f"figure -> {figure}")


@model.command("report")
def model_report(
    path: Annotated[Path | None, typer.Option("--model", help="Model JSON path.")] = None,
) -> None:
    """Print the metrics and standardized coefficients of a saved model."""
    try:
        loaded = model_module.ValueModel.load(path or model_module.DEFAULT_MODEL_PATH)
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"trained on {loaded.trained_on} ({loaded.n_rows} shots) at {loaded.trained_at}")
    _print_metrics(loaded.metrics)
    with pl.Config(tbl_rows=50):
        typer.echo(repr(loaded.feature_table()))


def _decision_summary(df: pl.DataFrame) -> str:
    valid = df.filter(pl.col("rule") != "excluded")
    excluded = df.filter(pl.col("rule") == "excluded").group_by("reason").len().sort("reason")
    reasons = ", ".join(f"{r} {n}" for r, n in excluded.iter_rows()) or "none"
    if valid.height:
        mean_cost = f"{float(valid['cost'].mean()):.3f}"  # type: ignore[arg-type]
        good = f"{float(valid['good_read'].mean()):.1%}"  # type: ignore[arg-type]
    else:
        mean_cost = good = "n/a"
    return (
        f"{df.height} shots: valid {valid.height}; excluded {reasons}; "
        f"mean cost {mean_cost}; good_read {good}"
    )


@decisions.command("build")
def decisions_build(
    game: GameOption = None,
    all_games: AllOption = False,
    model_path: Annotated[
        Path | None, typer.Option("--model", help="Model JSON path (default: versioned model).")
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
            path = build_decisions(game_id, settings, model=loaded)
            typer.echo(f"game {game_id}: {_decision_summary(pl.read_parquet(path))}")
            typer.echo(f"  -> {path}")
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _fmt(value: float | None, spec: str = ".3f") -> str:
    return "-" if value is None else format(value, spec)


@decisions.command("show")
def decisions_show(
    shot_id: Annotated[str, typer.Argument(help="Shot id, e.g. shot-114243-1-0.")],
) -> None:
    """Print a shot's decision and its five options (* shooter, > best alternative)."""
    try:
        settings = Settings.from_env()
        game_id = _game_of_shot(shot_id)
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
        f"shot_clock {_fmt(d['shot_clock'], '.2f')}"
    )
    typer.echo(
        f"shot value {_fmt(d['shot_value'])}  best alt {_fmt(d['best_alt_value'])}  "
        f"cost {_fmt(d['cost'])}  good_read {d['good_read']}  "
        f"confidence {_fmt(d['confidence'], '.1f')}"
    )
    typer.echo(
        f"  {'player_id':>9} {'type':5} {'zone':16} {'P':>5} {'value':>6} "
        f"{'viab':>5} {'adj':>6} alternative"
    )
    for o in opts.iter_rows(named=True):
        if o["option_type"] == "shot":
            mark = "*"
        elif o["player_id"] == d["best_alt_player_id"]:
            mark = ">"
        else:
            mark = " "
        typer.echo(
            f"{mark} {o['player_id']:>9} {o['option_type']:5} {o['zone']:16} "
            f"{o['proba']:>5.2f} {o['value']:>6.3f} {o['viability']:>5.2f} "
            f"{o['adjusted_value']:>6.3f} {o['alternative_type'] or '-'}"
        )
