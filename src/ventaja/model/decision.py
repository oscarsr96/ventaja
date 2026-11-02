"""The frame at which a shot decision is judged, and the valued decision itself."""

from typing import Literal

from ventaja.model.core import _Frozen

Rule = Literal["gather", "last_dribble", "touch_start", "excluded"]
AlternativeType = Literal["rim_cut", "open_corner", "extra_pass", "post", "other"]


class DecisionFrame(_Frozen):
    """Decision frame of one shot; ``frame_idx`` is None when ``rule`` is ``excluded``."""

    shot_id: str
    frame_idx: int | None
    rule: Rule
    reason: str | None


class Option(_Frozen):
    """One option at the decision frame: the shot taken or a pass to a teammate.

    ``value = proba x points`` (expected points), ``adjusted_value = value x viability``.
    ``features`` holds the non-null ``OPTION_FEATURES`` of the option.
    """

    player_id: int
    option_type: Literal["shot", "pass"]
    zone: str
    points: int
    x: float
    y: float
    pass_distance: float
    lane_blocked: bool
    proba: float
    value: float
    viability: float
    adjusted_value: float
    alternative_type: AlternativeType | None
    features: dict[str, float]


class Decision(_Frozen):
    """A valued shot decision: the shot against the best viable pass (ADR-0004).

    ``best_alt_value`` is the viability-adjusted value of the best pass;
    ``cost = max(0, best_alt_value - shot_value)``. ``options`` lists the shot first, then the
    passes by ``adjusted_value`` descending. ``confidence`` is the share of the ten players
    detected (not predicted) in the decision frame.
    """

    shot_id: str
    game_id: int
    shooter_id: int
    decision_frame: int
    release_frame: int
    rule: Rule
    shot_clock: float | None
    shot_value: float
    best_alt_player_id: int | None
    best_alt_type: AlternativeType | None
    best_alt_value: float | None
    cost: float
    good_read: bool
    confidence: float
    options: list[Option]
