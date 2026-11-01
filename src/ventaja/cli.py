"""Command-line entry point for ventaja."""

from typing import Annotated

import typer

from ventaja import __version__

app = typer.Typer(name="ventaja", no_args_is_help=True)


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
