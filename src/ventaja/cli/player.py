"""`ventaja player` commands: build and read the player and team cards."""

from pathlib import Path
from typing import Annotated, Any

import polars as pl
import typer

from ventaja.cli._common import fmt, run_or_exit, settings_or_exit
from ventaja.data.load import load_players_cards, load_teams_cards
from ventaja.profile.card import (
    LEAGUE_ID,
    build_players,
    card_of,
    find_player,
    fold_name,
    team_card_of,
)
from ventaja.profile.render import render_card, render_team

app = typer.Typer(help="Build and read the player and team cards.", no_args_is_help=True)

RANK_KEYS = ("mean_cost", "good_read_share", "late_held_share")


@app.command("build")
def player_build(
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Output directory (default: the build's players/)."),
    ] = None,
) -> None:
    """Build players.parquet (one row per shooter plus LIGA) and teams.parquet."""
    settings = settings_or_exit()
    players_path, teams_path = run_or_exit(lambda: build_players(settings, out_dir=out))
    players = pl.read_parquet(players_path)
    league = card_of(LEAGUE_ID, players)
    typer.echo(f"{players.height - 1} jugadores -> {players_path}")
    typer.echo(f"{pl.read_parquet(teams_path).height} equipos -> {teams_path}")
    typer.echo(f"coste medio de la liga {fmt(league.mean_cost)} ({league.n_readable} legibles)")


def _candidates(matches: list[tuple[int, str, str]], query: str) -> None:
    if not matches:
        typer.echo(f"ningún jugador coincide con {query!r}", err=True)
    else:
        typer.echo(f"{len(matches)} jugadores coinciden con {query!r}:", err=True)
        for pid, name, team in matches:
            typer.echo(f"  {pid:>6}  {name:<32} {team}", err=True)
    raise typer.Exit(code=1)


def _single(matches: list[tuple[int, str, str]], query: str) -> int:
    """The one match, or the one whose full name equals the query; else list and exit 1."""
    exact = [m for m in matches if fold_name(m[1]) == fold_name(query.strip())]
    if len(matches) == 1 or len(exact) == 1:
        return (matches if len(matches) == 1 else exact)[0][0]
    _candidates(matches, query)
    raise AssertionError  # unreachable: _candidates exits


@app.command("show")
def player_show(
    query: Annotated[str, typer.Argument(help="Player id or part of the name.")],
    lang: Annotated[str, typer.Option("--lang", help="Language of the phrase: es or en.")] = "es",
) -> None:
    """Print a player's card; an ambiguous or empty search lists the candidates (exit 1)."""
    if lang not in ("es", "en"):
        typer.echo("error: --lang must be es or en", err=True)
        raise typer.Exit(code=2)
    settings = settings_or_exit()
    players = run_or_exit(lambda: load_players_cards(settings))
    pid = _single(find_player(query, players), query)
    card, league = card_of(pid, players), card_of(LEAGUE_ID, players)
    typer.echo(render_card(card, league, lang="es" if lang == "es" else "en"))


def _rank_line(i: int, r: dict[str, Any]) -> str:
    return (
        f"{i:>3} {r['name'][:26]:<26} {(r['team'] or '-')[:24]:<24} {r['n_shots']:>4} "
        f"{r['n_readable']:>5} {fmt(r['mean_cost']):>9} {fmt(r['good_read_share']):>9} "
        f"{fmt(r['late_held_share']):>9}"
    )


_RANK_HEADER = (
    f"{'#':>3} {'jugador':<26} {'equipo':<24} {'n':>4} {'legib':>5} {'coste':>9} "
    f"{'lectura':>9} {'tarde':>9}"
)


@app.command("rank")
def player_rank(
    min_shots: Annotated[
        int,
        typer.Option(
            "--min-shots",
            min=1,
            help="Minimum valued shots (n_shots); the phrase gate counts readable shots instead.",
        ),
    ] = 1,
    n: Annotated[int, typer.Option("--n", min=1, help="Rows to print.")] = 20,
    by: Annotated[str, typer.Option("--by", help=f"Sort key: {', '.join(RANK_KEYS)}.")] = (
        "mean_cost"
    ),
) -> None:
    """Rank the players (LIGA excluded) by a card metric, descending; n is always shown."""
    if by not in RANK_KEYS:
        typer.echo(f"error: --by must be one of {', '.join(RANK_KEYS)}", err=True)
        raise typer.Exit(code=2)
    settings = settings_or_exit()
    players = run_or_exit(lambda: load_players_cards(settings))
    ranked = players.filter((pl.col("player_id") != LEAGUE_ID) & (pl.col("n_shots") >= min_shots))
    if ranked.height == 0:
        typer.echo(f"ningún jugador tiene {min_shots} tiros o más")
        return
    ranked = ranked.sort(
        [by, "n_shots", "player_id"], descending=[True, True, False], nulls_last=True
    ).head(n)
    league = card_of(LEAGUE_ID, players)
    typer.echo(
        f"por {by}, mínimo {min_shots} tiros; liga: coste {fmt(league.mean_cost)}, "
        f"lectura {fmt(league.good_read_share)}, tarde {fmt(league.late_held_share)}"
    )
    typer.echo(_RANK_HEADER)
    for i, r in enumerate(ranked.iter_rows(named=True), start=1):
        typer.echo(_rank_line(i, r))


@app.command("team")
def player_team(
    query: Annotated[str, typer.Argument(help="Team id or part of the team name.")],
) -> None:
    """Print a team's card and its players ranked by shots."""
    settings = settings_or_exit()
    teams = run_or_exit(lambda: load_teams_cards(settings))
    players = run_or_exit(lambda: load_players_cards(settings))
    q = query.strip()
    hits = teams.filter(pl.col("team_id") == int(q)) if q.isdigit() else teams.head(0)
    if hits.height == 0:
        names = teams["team"].fill_null("").to_list()
        hits = teams.filter(pl.Series([fold_name(q) in fold_name(name) for name in names]))
    if hits.height != 1:
        typer.echo(f"{hits.height} equipos coinciden con {query!r}:", err=True)
        for tid, name in hits.select("team_id", "team").rows():
            typer.echo(f"  {tid:>6}  {name}", err=True)
        raise typer.Exit(code=1)
    team = team_card_of(int(hits["team_id"][0]), teams)
    typer.echo(render_team(team, card_of(LEAGUE_ID, players)))
    roster = players.filter(pl.col("team_id") == team.team_id).sort(
        ["n_shots", "player_id"], descending=[True, False]
    )
    typer.echo("\nJugadores")
    typer.echo(_RANK_HEADER)
    for i, r in enumerate(roster.iter_rows(named=True), start=1):
        typer.echo(_rank_line(i, r))
