"""`ventaja reel` commands."""

from pathlib import Path
from typing import Annotated

import typer

from ventaja import reel as reel_module
from ventaja.cli._common import AllOption, GameOption, fmt, run_or_exit, settings_or_exit
from ventaja.config import GAME_IDS

app = typer.Typer(help="Rank decisions and build the reel of clips.", no_args_is_help=True)


def _reel_games(game: list[int] | None, all_games: bool) -> list[int]:
    if not game and not all_games:
        typer.echo("error: choose games with --game ID (repeatable) or --all", err=True)
        raise typer.Exit(code=2)
    return list(GAME_IDS) if all_games else list(game or [])


_METRIC = {"worst": "cost", "best": "margin", "late": "lost_value"}


@app.command("rankings")
def reel_rankings(
    game: GameOption = None,
    all_games: AllOption = False,
    n: Annotated[int, typer.Option("--n", min=1, help="Shots per ranking.")] = 10,
) -> None:
    """Print the worst decisions, the best reads and the lost moments (late, held)."""
    ids = _reel_games(game, all_games)
    tables = run_or_exit(lambda: reel_module.rankings(settings_or_exit(), ids, n=n))
    *ranked, low = tables
    typer.echo(f"{low} decisions left out by confidence")
    for (kind, heading, _), table in zip(reel_module.SECTIONS, ranked, strict=True):
        typer.echo(f"\n{heading} ({kind}, by {_METRIC[kind]})")
        for r in table.iter_rows(named=True):
            typer.echo(
                f"{r['rank']:>3} {r['shot_id']:<20} {r['shooter'][:24]:<24} "
                f"{fmt(r[_METRIC[kind]], '.2f'):>6}  {r['headline_es']}"
            )


@app.command("build")
def reel_build(
    out: Annotated[Path, typer.Option("--out", help="Output directory of the reel.")],
    game: GameOption = None,
    all_games: AllOption = False,
    n: Annotated[int, typer.Option("--n", min=1, help="Shots per ranking.")] = 10,
    fps: Annotated[int, typer.Option("--fps", help="Frames per second of the GIFs.")] = 12,
) -> None:
    """Render one clip per ranked shot (three rankings) and write index.md."""
    ids = _reel_games(game, all_games)
    path = run_or_exit(
        lambda: reel_module.build_reel(settings_or_exit(), ids, n=n, out_dir=out, fps=fps)
    )
    count = len(list(path.parent.glob("*.gif")))
    typer.echo(f"reel -> {path}")
    typer.echo(f"{count} {'GIF' if count == 1 else 'GIFs'} in {path.parent}")
    skipped = reel_module.skipped_clips(path)
    typer.echo(f"{skipped} {'clip' if skipped == 1 else 'clips'} not available (see index.md)")
