"""Top-level commands: sql, snapshot and clip."""

import sys
from pathlib import Path
from typing import Annotated

import duckdb
import polars as pl
import typer

from ventaja.cli._common import (
    game_of_shot,
)
from ventaja.config import Settings
from ventaja.data.duck import connect
from ventaja.data.load import (
    load_curve_summaries,
    load_curves,
    load_decision_options,
    load_decisions,
)
from ventaja.decision.align import Aligner
from ventaja.decision.cost import decision_from_tables
from ventaja.errors import VentajaError
from ventaja.value.params import CLIP_AFTER_S, CLIP_BEFORE_S
from ventaja.viz import clip as clip_module
from ventaja.viz import kit as kit_module


def _unique(names: list[str]) -> list[str]:
    """Suffix repeated column names with _1, _2, ... so Polars accepts them."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for name in names:
        n = seen.get(name, 0)
        seen[name] = n + 1
        out.append(name if n == 0 else f"{name}_{n}")
    return out


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
        game_id = game if game is not None else game_of_shot(shot_id)
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
        game_id = game_of_shot(shot_id)
        decision = decision_from_tables(
            shot_id, load_decisions(game_id, settings), load_decision_options(game_id, settings)
        )
        curve, summary = clip_module.curve_of_shot(
            shot_id, load_curves(game_id, settings), load_curve_summaries(game_id, settings)
        )
        players = kit_module.players_table(settings)
        labels = kit_module.jersey_labels(players, game_id)
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
            handler_name=kit_module.player_name(players, game_id, summary.window_handler_id),
        )
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"clip -> {path}")
