"""Command-line entry point for ventaja."""

import sys
from collections.abc import Callable
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
from ventaja.decision.align import Aligner
from ventaja.errors import DataNotFoundError, VentajaError
from ventaja.validate import score as score_module

app = typer.Typer(name="ventaja", no_args_is_help=True)
data = typer.Typer(help="Download, inspect and build SkillCorner data.", no_args_is_help=True)
app.add_typer(data, name="data")
validate = typer.Typer(help="Check the event model against official data.", no_args_is_help=True)
app.add_typer(validate, name="validate")


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
