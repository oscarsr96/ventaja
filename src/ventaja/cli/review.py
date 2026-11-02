"""`ventaja review` commands."""

from pathlib import Path
from typing import Annotated

import typer

from ventaja.cli._common import AllOption, GameOption, run_or_exit, settings_or_exit
from ventaja.config import GAME_IDS
from ventaja.viz import kit as kit_module

app = typer.Typer(help="Prepare the live review of decisions.", no_args_is_help=True)


@app.command("sample")
def review_sample(
    out: Annotated[Path, typer.Option("--out", help="Output directory of the kit.")],
    game: GameOption = None,
    all_games: AllOption = False,
    n: Annotated[int, typer.Option("--n", help="Number of shots to sample.")] = 20,
    seed: Annotated[int, typer.Option("--seed", help="Random seed of the sample.")] = 7,
) -> None:
    """Sample shots stratified by decision rule, render one GIF each and write review.md."""
    ids = GAME_IDS if all_games or not game else game
    path = run_or_exit(lambda: kit_module.review_kit(settings_or_exit(), list(ids), n, seed, out))
    count = sum(line.startswith("## ") for line in path.read_text().splitlines())
    typer.echo(f"review -> {path}")
    typer.echo(f"{count} {'GIF' if count == 1 else 'GIFs'} in {path.parent}")
