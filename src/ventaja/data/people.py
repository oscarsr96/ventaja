"""People directory: player and team names, jerseys and player teams from the packaged data."""

from typing import NamedTuple

from ventaja.config import Settings
from ventaja.data.load import (
    load_players_cards,
    load_roster,
    load_teams_cards,
    meta_people,
)
from ventaja.errors import DataNotFoundError

__all__ = ["People", "load_people"]

_LEAGUE_ID = 0  # the LIGA row of the player cards


class People(NamedTuple):
    """Names, jerseys, team names and the team of each player, keyed by id."""

    names: dict[int, str]
    jerseys: dict[int, str]
    teams: dict[int, str]
    player_team: dict[int, int]


def load_people(settings: Settings) -> People:
    """Names, jerseys and team names: packaged roster, then ``meta/``, then player cards.

    Each source only fills the ids still missing. The roster is exactly the players of the
    frames and travels with them; ``meta/`` covers frames that predate the roster; the cards
    cover the carded players (no jerseys), so a clean clone still names the shooters.
    ``player_team`` maps a player to their team id (roster first, then cards).
    """
    names: dict[int, str] = {}
    jerseys: dict[int, str] = {}
    teams: dict[int, str] = {}
    player_team: dict[int, int] = {}
    try:
        for r in load_roster(settings).iter_rows(named=True):
            names.setdefault(r["player_id"], r["name"])
            if r["jersey"] is not None:
                jerseys.setdefault(r["player_id"], r["jersey"])
            if r["team"] is not None:
                teams.setdefault(r["team_id"], r["team"])
            if r["team_id"] is not None:
                player_team.setdefault(r["player_id"], r["team_id"])
    except DataNotFoundError:
        pass
    try:
        meta_names, meta_jerseys, meta_teams = meta_people(settings)
        for k, v in meta_names.items():
            names.setdefault(k, v)
        for k, v in meta_jerseys.items():
            jerseys.setdefault(k, v)
        for k, v in meta_teams.items():
            teams.setdefault(k, v)
    except DataNotFoundError:
        pass
    try:
        for c in load_players_cards(settings).iter_rows(named=True):
            if c["player_id"] != _LEAGUE_ID:
                names.setdefault(c["player_id"], c["name"])
                teams.setdefault(c["team_id"], c["team"])
                if c["team_id"] is not None:
                    player_team.setdefault(c["player_id"], c["team_id"])
        for t in load_teams_cards(settings).iter_rows(named=True):
            teams.setdefault(t["team_id"], t["team"])
    except DataNotFoundError:
        pass
    return People(names, jerseys, teams, player_team)
