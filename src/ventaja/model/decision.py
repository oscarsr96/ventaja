"""The frame at which a shot decision is judged."""

from typing import Literal

from ventaja.model.core import _Frozen

Rule = Literal["gather", "last_dribble", "touch_start", "excluded"]


class DecisionFrame(_Frozen):
    """Decision frame of one shot; ``frame_idx`` is None when ``rule`` is ``excluded``."""

    shot_id: str
    frame_idx: int | None
    rule: Rule
    reason: str | None
