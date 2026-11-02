"""Court constants (feet) and the offense-oriented coordinate frame.

SkillCorner events are already offense-oriented (offensive hoop at negative x); tracking is in
camera orientation. ``orient_to_offense`` / ``orient_frame`` rotate tracking by 180 degrees when
the possession's offensive hoop is on the right (``left_hoop`` False). See ADR-0001.
"""

import math

import polars as pl

from ventaja.config import FPS

__all__ = [
    "COURT_LENGTH",
    "COURT_WIDTH",
    "FPS",
    "HALF_LENGTH",
    "CORNER_X_MAX",
    "CORNER_Y",
    "FAR_DISTANCE",
    "HOOP",
    "KEY_HALF_WIDTH",
    "KEY_X_MAX",
    "RA_RADIUS",
    "THREE_POINT_RADIUS",
    "distance_to_hoop",
    "orient_frame",
    "orient_to_offense",
]

HOOP: tuple[float, float] = (-40.7, 0.0)
COURT_LENGTH = 91.86
COURT_WIDTH = 49.21
HALF_LENGTH = 45.93
THREE_POINT_RADIUS = 22.15  # FIBA arc radius 6.75 m
# FIBA zone geometry (feet), offense frame with the baseline at x = -HALF_LENGTH (-45.93).
RA_RADIUS = 4.10  # restricted-area arc, 1.25 m from the hoop centre
KEY_HALF_WIDTH = 8.04  # key half-width, 2.45 m
KEY_X_MAX = -26.90  # free-throw line, 5.80 m from the baseline: -45.93 + 19.03
CORNER_Y = 21.65  # corner three line, 0.90 m from the sideline: 6.60 m from the centre line
CORNER_X_MAX = -36.02  # where the 22.15 ft arc meets |y| = CORNER_Y
FAR_DISTANCE = 35.0  # beyond this the shot is a heave, not a half-court shot


def orient_to_offense(x: float, y: float, left_hoop: bool) -> tuple[float, float]:
    """Express a tracking point in the offense-oriented frame."""
    return (x, y) if left_hoop else (-x, -y)


def orient_frame(df: pl.DataFrame, left_hoop: bool) -> pl.DataFrame:
    """Same as ``orient_to_offense`` for the ``x`` and ``y`` columns of a DataFrame."""
    if left_hoop:
        return df
    return df.with_columns(-pl.col("x"), -pl.col("y"))


def distance_to_hoop(x: float, y: float) -> float:
    """Distance in feet from an offense-oriented point to the offensive hoop."""
    return math.hypot(x - HOOP[0], y - HOOP[1])
