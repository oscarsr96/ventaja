"""Output models of the ask service: frozen, ids always travel with their names."""

from ventaja.model.core import _Frozen

__all__ = [
    "Alternative",
    "BestAlternative",
    "ClockBand",
    "CurveSummaryOut",
    "GameInfo",
    "GameSide",
    "Metrics",
    "OptionOut",
    "PlayerProfile",
    "PlayerRef",
    "RankedPlayer",
    "Ranking",
    "ShotExplanation",
    "ShotList",
    "ShotSummary",
    "ShotTaken",
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


class BestAlternative(_Frozen):
    """The best viable pass of a shot: who gets it, what kind of chance and its value."""

    player: PlayerRef
    type: str
    value: float


class ShotSummary(_Frozen):
    """One valued shot in a list: its cost against the best alternative and its curve verdict."""

    shot_id: str
    game_id: int
    period: int | None
    shot_clock: float | None
    shooter: PlayerRef
    shot_value: float
    best_alternative: BestAlternative | None
    cost: float
    good_read: bool | None
    verdict: str | None
    headline: str | None


class ShotList(_Frozen):
    """Shots matching a search; ``total`` counts the matches before the limit."""

    total: int
    shots: list[ShotSummary]


class OptionOut(_Frozen):
    """One option at the decision frame (the shot or a pass)."""

    player: PlayerRef
    option_type: str
    zone: str
    points: int
    proba: float
    value: float
    viability: float
    adjusted_value: float
    alternative_type: str | None
    lane_blocked: bool
    is_shot: bool
    is_best_alternative: bool


class ShotTaken(_Frozen):
    """The shot that was taken: zone, points and expected value."""

    zone: str
    points: int
    value: float


class CurveSummaryOut(_Frozen):
    """The advantage window of the possession: verdict, size and who held the ball."""

    verdict: str
    advantage_seconds: float
    release_lag_seconds: float
    advantage_holder: PlayerRef | None
    headline: str


class ShotExplanation(_Frozen):
    """Everything about one valued shot: options, best alternative, curve and the clip command."""

    shot_id: str
    game_id: int
    period: int | None
    shot_clock: float | None
    rule: str
    confidence: float
    shooter: PlayerRef
    shot: ShotTaken
    options: list[OptionOut]
    best_alternative: BestAlternative | None
    cost: float
    good_read: bool | None
    curve: CurveSummaryOut | None
    clip_command: str
