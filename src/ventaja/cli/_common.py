"""Pieces shared by the command modules."""

from collections.abc import Callable
from typing import Annotated

import typer

from ventaja.config import Settings
from ventaja.errors import DataNotFoundError, VentajaError

GameOption = Annotated[list[int] | None, typer.Option("--game", help="Game id (repeatable).")]
AllOption = Annotated[bool, typer.Option("--all", help="All ten games.")]


def game_of_shot(shot_id: str) -> int:
    """Game id embedded in a shot id of the form ``shot-{game_id}-{period}-{n}``."""
    parts = shot_id.split("-")
    if len(parts) != 4 or parts[0] != "shot" or not parts[1].isdigit():
        raise DataNotFoundError(f"cannot parse a game id from shot id {shot_id!r}; pass --game")
    return int(parts[1])


def run_or_exit[T](fn: Callable[[], T]) -> T:
    """Run ``fn``; a VentajaError becomes ``error: ...`` on stderr and exit code 1."""
    try:
        return fn()
    except VentajaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def settings_or_exit() -> Settings:
    """Settings from the environment, or exit 1 with the error."""
    return run_or_exit(Settings.from_env)


def fmt(value: float | None, spec: str = ".3f") -> str:
    """Format a number, or ``-`` when missing."""
    return "-" if value is None else format(value, spec)
