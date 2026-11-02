"""Command-line entry point for ventaja."""

from typing import Annotated

import typer

from ventaja import __version__
from ventaja.cli import curves, data, decisions, model, player, review, snapshot, validate
from ventaja.cli import reel as reel_commands

app = typer.Typer(name="ventaja", no_args_is_help=True)
app.command("sql")(snapshot.sql)
app.command("snapshot")(snapshot.snapshot)
app.command("clip")(snapshot.clip)
app.add_typer(data.app, name="data")
app.add_typer(validate.app, name="validate")
app.add_typer(model.app, name="model")
app.add_typer(decisions.app, name="decisions")
app.add_typer(curves.app, name="curves")
app.add_typer(review.app, name="review")
app.add_typer(reel_commands.app, name="reel")
app.add_typer(player.app, name="player")


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
