"""Decision-frame rules (ADR-0003): where in time a shot is judged."""

from collections.abc import Callable
from typing import Any

from ventaja.model.decision import DecisionFrame, Rule
from ventaja.value.params import (
    EXCLUDED_TYPES,
    FINISH_TYPES,
    GATHER_FRAMES,
    JUMP_SHOT_TYPES,
    NO_TRACKING_LOOKAHEAD,
)


def _excluded(shot_id: str, reason: str) -> DecisionFrame:
    return DecisionFrame(shot_id=shot_id, frame_idx=None, rule="excluded", reason=reason)


def decision_frame(
    shot: dict[str, Any],
    touch: dict[str, Any] | None,
    dribble_frames: list[int],
    has_tracking: Callable[[int], bool],
) -> DecisionFrame:
    """Decision frame of a shot.

    Jump shots are judged at the start of the gather (``GATHER_FRAMES`` before release, not
    before the touch start); finishes at the last dribble at or before release, else at the
    touch start. If the chosen frame has no tracking, the next ``NO_TRACKING_LOOKAHEAD``
    frames are tried; otherwise the shot is excluded.
    """
    shot_id = str(shot["id"])
    kind = shot.get("complex_shot_type")
    if shot.get("touch_id") is None or touch is None:
        return _excluded(shot_id, "no_touch")
    if kind is None:
        return _excluded(shot_id, "no_type")
    if kind in EXCLUDED_TYPES:
        return _excluded(shot_id, str(kind))
    release = int(shot["start_frame"])
    touch_start = int(touch["start_frame"])
    rule: Rule
    if kind in JUMP_SHOT_TYPES:
        frame = max(release - GATHER_FRAMES, touch_start)
        rule = "gather"
    elif kind in FINISH_TYPES:
        before = [f for f in dribble_frames if f <= release]
        frame, rule = (max(before), "last_dribble") if before else (touch_start, "touch_start")
    else:
        return _excluded(shot_id, f"unknown_type:{kind}")
    for candidate in range(frame, frame + NO_TRACKING_LOOKAHEAD + 1):
        if has_tracking(candidate):
            return DecisionFrame(shot_id=shot_id, frame_idx=candidate, rule=rule, reason=None)
    return _excluded(shot_id, "no_tracking")
