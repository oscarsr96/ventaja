"""Player and team cards (layer 3); built and flattened by ``profile.card``."""

from ventaja.model.core import _Frozen

__all__ = ["Block", "PlayerCard", "TeamCard"]

Block = tuple[int, float | None]  # (n, mean cost)


class _Card(_Frozen):
    """Decision metrics shared by player and team cards (``profile.aggregate`` semantics)."""

    games: list[int]
    n_shots: int
    n_readable: int
    n_low_confidence: int
    n_clock_known: int
    n_with_summary: int
    n_during: int
    n_late_held: int
    good_read_share: float | None
    mean_shot_value: float | None
    mean_best_alt_value: float | None
    mean_cost: float | None
    total_cost: float | None
    mean_confidence: float | None
    ignored_alt: str | None
    late_held_share: float | None
    mean_lag_held: float | None
    during_share: float | None
    clock: dict[str, Block]  # bucket label -> (readable n, mean cost)
    alternatives: dict[str, Block]  # alternative type -> (n with cost, mean cost)
    built_at: str
    model_trained_at: str


class PlayerCard(_Card):
    """One shooter's card; ``player_id = 0`` is the league row (no team, no phrase)."""

    player_id: int
    name: str
    team_id: int | None
    team: str | None
    season: dict[str, float | int | None]
    tracked_zone: dict[str, float | int | None]
    zone_shift: dict[str, float | None]
    phrase_es: str | None
    phrase_en: str | None


class TeamCard(_Card):
    """One team's card: the metrics of its shooters' decisions (no season, no phrase)."""

    team_id: int
    team: str | None
    n_players: int
    players: list[int]
