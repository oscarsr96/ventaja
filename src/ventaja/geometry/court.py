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
    "HOOP",
    "THREE_POINT_RADIUS",
    "distance_to_hoop",
    "orient_frame",
    "orient_to_offense",
]

HOOP: tuple[float, float] = (-40.7, 0.0)
COURT_LENGTH = 91.86
COURT_WIDTH = 49.21
HALF_LENGTH = 45.93
THREE_POINT_RADIUS = 22.15


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
