"""Command-line entry point for ventaja."""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import duckdb
import httpx
import polars as pl
import typer

from ventaja import __version__
from ventaja import reel as reel_module
from ventaja.config import GAME_IDS, Settings
from ventaja.data import build as build_module
from ventaja.data import pull as pull_module
from ventaja.data.catalog import files_for
from ventaja.data.duck import connect
from ventaja.data.load import (
    load_curve_summaries,
    load_curves,
    load_decision_options,
    load_decisions,
)
from ventaja.decision.align import Aligner
from ventaja.decision.cost import build_decisions, decision_from_tables
from ventaja.decision.curve import build_curves
from ventaja.errors import DataNotFoundError, VentajaError
from ventaja.validate import decisions as decisions_checks
from ventaja.validate import score as score_module
from ventaja.value import model as model_module
from ventaja.value.features import shot_rows
from ventaja.value.params import CLIP_AFTER_S, CLIP_BEFORE_S
from ventaja.value.priors import Priors
from ventaja.viz import clip as clip_module
from ventaja.viz import kit as kit_module
from ventaja.viz.text import format_option_table

app = typer.Typer(name="ventaja", no_args_is_help=True)
data = typer.Typer(help="Download, inspect and build SkillCorner data.", no_args_is_help=True)
app.add_typer(data, name="data")
validate = typer.Typer(help="Check the event model against official data.", no_args_is_help=True)
app.add_typer(validate, name="validate")
model = typer.Typer(help="Train and inspect the value model.", no_args_is_help=True)
app.add_typer(model, name="model")
decisions = typer.Typer(help="Build and inspect shot decision costs.", no_args_is_help=True)
app.add_typer(decisions, name="decisions")
curves = typer.Typer(help="Build and inspect possession advantage curves.", no_args_is_help=True)
app.add_typer(curves, name="curves")
review = typer.Typer(help="Prepare the live review of decisions.", no_args_is_help=True)
app.add_typer(review, name="review")
reel = typer.Typer(help="Rank decisions and build the reel of clips.", no_args_is_help=True)
app.add_typer(reel, name="reel")


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


@validate.command("decisions")
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
    _print_zone_table(loaded.zone_table)


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


@decisions.command("build")
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


def _fmt(value: float | None, spec: str = ".3f") -> str:
    return "-" if value is None else format(value, spec)


def _read(good_read: bool | None) -> str:
    return "- (no viable pass)" if good_read is None else str(good_read)


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
        f"cost {_fmt(d['cost'])}  good_read {_read(d['good_read'])}  "
        f"confidence {_fmt(d['confidence'], '.1f')}"
    )
    typer.echo(
        format_option_table(
            opts, shooter_id=d["shooter_id"], best_alt_player_id=d["best_alt_player_id"]
        )
    )


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


@curves.command("build")
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


@curves.command("show")
def curves_show(
    shot_id: Annotated[str, typer.Argument(help="Shot id, e.g. shot-114243-1-0.")],
) -> None:
    """Print a shot's curve summary and its curve, one row per sampled frame."""
    try:
        settings = Settings.from_env()
        game_id = _game_of_shot(shot_id)
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
        f"shot value {_fmt(s['shot_value'])}  skipped off court {s['skipped_off_court']}"
    )
    typer.echo(
        f"window {s['window_start'] or '-'}-{s['window_end'] or '-'}  "
        f"handler {s['window_handler_id'] or '-'}  best pass {_fmt(s['window_peak_value'])}  "
        f"advantage {s['advantage_seconds']:.1f} s  lag {_fmt(s['release_lag_seconds'], '.1f')} s"
    )
    typer.echo(
        f"peak {_fmt(s['peak_value'])} at {s['peak_frame'] or '-'}  "
        f"value at decision {_fmt(s['value_at_decision'])}"
    )
    typer.echo(
        f"{'t_to_release':>12} {'handler':>8} {'shot_clock':>10} {'handler_shot_value':>18} "
        f"{'best_value':>10} {'best_pass_value':>15}  best"
    )
    for r in curve.sort("frame_idx").iter_rows(named=True):
        typer.echo(
            f"{r['t_to_release']:>12.1f} {r['handler_id']:>8} {_fmt(r['shot_clock'], '.2f'):>10} "
            f"{r['handler_shot_value']:>18.3f} {r['best_value']:>10.3f} "
            f"{_fmt(r['best_pass_value']):>15}  {_best(r)}"
        )


@curves.command("plot")
def curves_plot(
    shot_id: Annotated[str, typer.Argument(help="Shot id, e.g. shot-114243-1-0.")],
    out: Annotated[Path, typer.Option("--out", help="Output image file (e.g. curve.png).")],
) -> None:
    """Save a shot's advantage curve as an image, titled with its headline."""
    try:
        settings = Settings.from_env()
        game_id = _game_of_shot(shot_id)
        decision = decision_from_tables(
            shot_id, load_decisions(game_id, settings), load_decision_options(game_id, settings)
        )
        curve, summary = clip_module.curve_of_shot(
            shot_id, load_curves(game_id, settings), load_curve_summaries(game_id, settings)
        )
        path = clip_module.curve_figure(curve, summary, decision.decision_frame, out)
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"curve -> {path}")


@app.command("clip")
def clip(
    shot_id: Annotated[str, typer.Argument(help="Shot id, e.g. shot-114243-1-0.")],
    out: Annotated[Path, typer.Option("--out", help="Output GIF file.")],
    fps: Annotated[int, typer.Option("--fps", help="Frames per second of the GIF.")] = 12,
    before: Annotated[
        float, typer.Option("--before", help="Seconds shown before the decision frame.")
    ] = CLIP_BEFORE_S,
    after: Annotated[
        float, typer.Option("--after", help="Seconds shown after the release.")
    ] = CLIP_AFTER_S,
) -> None:
    """Animate a shot's possession (court) with its advantage curve underneath, as a GIF.

    Decisions and curves come from the build or the packaged artifacts; the court needs the
    game's built events and tracking (`ventaja data build --game N`).
    """
    try:
        settings = Settings.from_env()
        game_id = _game_of_shot(shot_id)
        decision = decision_from_tables(
            shot_id, load_decisions(game_id, settings), load_decision_options(game_id, settings)
        )
        curve, summary = clip_module.curve_of_shot(
            shot_id, load_curves(game_id, settings), load_curve_summaries(game_id, settings)
        )
        labels = kit_module.jersey_labels(kit_module.players_table(settings), game_id)
        path = clip_module.render_clip(
            Aligner(game_id, settings),
            decision,
            curve,
            summary,
            out,
            before_s=before,
            after_s=after,
            fps=fps,
            labels=labels,
        )
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"clip -> {path}")


@review.command("sample")
def review_sample(
    out: Annotated[Path, typer.Option("--out", help="Output directory of the kit.")],
    game: GameOption = None,
    all_games: AllOption = False,
    n: Annotated[int, typer.Option("--n", help="Number of shots to sample.")] = 20,
    seed: Annotated[int, typer.Option("--seed", help="Random seed of the sample.")] = 7,
) -> None:
    """Sample shots stratified by decision rule, render one GIF each and write review.md."""
    ids = GAME_IDS if all_games or not game else game
    try:
        path = kit_module.review_kit(Settings.from_env(), list(ids), n, seed, out)
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    count = sum(line.startswith("## ") for line in path.read_text().splitlines())
    typer.echo(f"review -> {path}")
    typer.echo(f"{count} {'GIF' if count == 1 else 'GIFs'} in {path.parent}")


def _reel_games(game: list[int] | None, all_games: bool) -> list[int]:
    if not game and not all_games:
        typer.echo("error: choose games with --game ID (repeatable) or --all", err=True)
        raise typer.Exit(code=2)
    return list(GAME_IDS) if all_games else list(game or [])


_METRIC = {"worst": "cost", "best": "margin", "late": "release_lag_seconds"}


@reel.command("rankings")
def reel_rankings(
    game: GameOption = None,
    all_games: AllOption = False,
    n: Annotated[int, typer.Option("--n", min=1, help="Shots per ranking.")] = 10,
) -> None:
    """Print the worst decisions, the best reads and the lost moments (late, held)."""
    ids = _reel_games(game, all_games)
    try:
        tables = reel_module.rankings(Settings.from_env(), ids, n=n)
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    *ranked, low = tables
    typer.echo(f"{low} decisions left out by confidence")
    for (kind, heading, _), table in zip(reel_module.SECTIONS, ranked, strict=True):
        typer.echo(f"\n{heading} ({kind}, by {_METRIC[kind]})")
        for r in table.iter_rows(named=True):
            typer.echo(
                f"{r['rank']:>3} {r['shot_id']:<20} {r['shooter'][:24]:<24} "
                f"{_fmt(r[_METRIC[kind]], '.2f'):>6}  {r['headline_es']}"
            )


@reel.command("build")
def reel_build(
    out: Annotated[Path, typer.Option("--out", help="Output directory of the reel.")],
    game: GameOption = None,
    all_games: AllOption = False,
    n: Annotated[int, typer.Option("--n", min=1, help="Shots per ranking.")] = 10,
    fps: Annotated[int, typer.Option("--fps", help="Frames per second of the GIFs.")] = 12,
) -> None:
    """Render one clip per ranked shot (three rankings) and write index.md."""
    ids = _reel_games(game, all_games)
    try:
        path = reel_module.build_reel(Settings.from_env(), ids, n=n, out_dir=out, fps=fps)
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    count = len(list(path.parent.glob("*.gif")))
    typer.echo(f"reel -> {path}")
    typer.echo(f"{count} {'GIF' if count == 1 else 'GIFs'} in {path.parent}")
    skipped = reel_module.skipped_clips(path)
    typer.echo(f"{skipped} {'clip' if skipped == 1 else 'clips'} not available (see index.md)")
