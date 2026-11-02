"""Half court in offense orientation (offensive hoop at negative x), drawn with matplotlib."""

import math
from typing import TYPE_CHECKING, Any

from matplotlib import patches

if TYPE_CHECKING:
    from matplotlib.axes import Axes

from ventaja.geometry.court import (
    CORNER_X_MAX,
    CORNER_Y,
    COURT_WIDTH,
    HALF_LENGTH,
    HOOP,
    KEY_HALF_WIDTH,
    KEY_X_MAX,
    RA_RADIUS,
    THREE_POINT_RADIUS,
)

__all__ = ["draw_half_court"]

HOOP_RADIUS = 0.75
FREE_THROW_RADIUS = 6.0
_LINE: dict[str, Any] = {"color": "black", "linewidth": 1.0, "fill": False}


def draw_half_court(ax: "Axes") -> None:
    """Draw the offensive half court on ``ax``: x in [-47, 0], y in [-25, 25], aspect 1:1."""
    baseline = -HALF_LENGTH
    side = COURT_WIDTH / 2
    lines: dict[str, Any] = {"color": "black", "linewidth": 1.0}
    ax.plot([baseline, baseline], [-side, side], **lines)
    ax.plot([baseline, 0.0], [side, side], **lines)
    ax.plot([baseline, 0.0], [-side, -side], **lines)
    ax.plot([0.0, 0.0], [-side, side], **lines)
    ax.add_patch(patches.Circle(HOOP, HOOP_RADIUS, **_LINE))
    ax.add_patch(
        patches.Arc(HOOP, 2 * RA_RADIUS, 2 * RA_RADIUS, theta1=-90.0, theta2=90.0, **lines)
    )
    ax.add_patch(
        patches.Rectangle(
            (baseline, -KEY_HALF_WIDTH), KEY_X_MAX - baseline, 2 * KEY_HALF_WIDTH, **_LINE
        )
    )
    ax.add_patch(patches.Circle((KEY_X_MAX, 0.0), FREE_THROW_RADIUS, **_LINE))
    for y in (-CORNER_Y, CORNER_Y):
        ax.plot([baseline, CORNER_X_MAX], [y, y], **lines)
    theta = math.degrees(math.atan2(CORNER_Y, CORNER_X_MAX - HOOP[0]))
    diameter = 2 * THREE_POINT_RADIUS
    ax.add_patch(patches.Arc(HOOP, diameter, diameter, theta1=-theta, theta2=theta, **lines))
    ax.set_xlim(-47.0, 0.0)
    ax.set_ylim(-25.0, 25.0)
    ax.set_aspect("equal")
    ax.set_axis_off()
