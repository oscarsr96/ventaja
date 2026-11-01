"""Core domain models: players, teams, games and match results."""

from pydantic import AwareDatetime, BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Player(_Frozen):
    """A rostered player of one game, identified by canonical id."""

    player_id: int
    first_name: str
    last_name: str
    jersey: str


class Team(_Frozen):
    """A team and its roster for one game."""

    team_id: int
    name: str
    players: list[Player]


class Game(_Frozen):
    """Metadata of one game: date, season and both rosters."""

    game_id: int
    date: AwareDatetime
    season: str
    home: Team
    away: Team


class Score(_Frozen):
    """A home/away score."""

    home: int
    away: int


class Match(_Frozen):
    """One entry of matches.json: teams and final score of a game."""

    game_id: int
    date_time: AwareDatetime
    home_team_id: int
    away_team_id: int
    home_score: int
    away_score: int
