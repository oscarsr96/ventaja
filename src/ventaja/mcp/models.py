"""Output models of the ask service: frozen, ids always travel with their names."""

from ventaja.model.core import _Frozen

__all__ = [
    "Alternative",
    "ClockBand",
    "GameInfo",
    "GameSide",
    "Metrics",
    "PlayerProfile",
    "PlayerRef",
    "RankedPlayer",
    "Ranking",
    "TeamRef",
]


class TeamRef(_Frozen):
    """A team id with its name (null when unknown)."""

    team_id: int
    name: str | None


class PlayerRef(_Frozen):
    """A player id with their name and team."""

    player_id: int
    name: str | None
    team: TeamRef | None


class GameSide(TeamRef):
    """One side of a game: the team and its final score."""

    score: int | None


class GameInfo(_Frozen):
    """A game with decisions: date, both sides and how many of its shots are valued."""

    game_id: int
    date: str | None
    home: GameSide
    away: GameSide
    valued_shots: int


class ClockBand(_Frozen):
    """Readable shots and mean cost of one shot-clock band."""

    band: str
    n: int
    cost: float | None


class Metrics(_Frozen):
    """Decision metrics of a player or of the league; ``clock`` only in clock rankings."""

    n_shots: int
    n_readable: int
    mean_cost: float | None
    good_read_share: float | None
    late_held_share: float | None
    clock: ClockBand | None


class RankedPlayer(_Frozen):
    """One row of a ranking."""

    rank: int
    player: PlayerRef
    metrics: Metrics


class Ranking(_Frozen):
    """A ranking of players with the league row to compare against."""

    by: str
    clock: str | None
    min_shots: int
    players: list[RankedPlayer]
    league: Metrics


class Alternative(_Frozen):
    """Shots whose best alternative was of this type, and the mean cost of those."""

    type: str
    n: int
    cost: float | None


class PlayerProfile(_Frozen):
    """A player card in answer form, with the league for reference."""

    player: PlayerRef
    games: list[int]
    n_shots: int
    n_readable: int
    mean_shot_value: float | None
    mean_best_alt_value: float | None
    mean_cost: float | None
    good_read_share: float | None
    late_held_share: float | None
    mean_lag_held: float | None
    clock: list[ClockBand]
    ignored_alternative: str | None
    alternatives: list[Alternative]
    season: dict[str, float | int | None]
    league: Metrics
    phrase: str | None
    caution: str | None
