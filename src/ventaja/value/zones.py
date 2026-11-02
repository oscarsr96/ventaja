"""Court zones of the offense-oriented frame (offensive hoop at negative x)."""

from typing import Literal, get_args

from ventaja.geometry.court import (
    CORNER_X_MAX,
    CORNER_Y,
    FAR_DISTANCE,
    KEY_HALF_WIDTH,
    KEY_X_MAX,
    RA_RADIUS,
    THREE_POINT_RADIUS,
    distance_to_hoop,
)

__all__ = ["ZONES", "Zone", "is_three", "points", "region_to_zone", "zone_of"]

Zone = Literal[
    "restricted_area",
    "paint_non_ra",
    "mid_range",
    "corner_3",
    "above_break_3",
    "backcourt",
    "far",
]
ZONES: tuple[Zone, ...] = get_args(Zone)

_REGION_ZONES: dict[str, Zone] = {
    "ra": "restricted_area",
    "key": "paint_non_ra",
    "backcourt": "backcourt",
    "far": "far",
}


def is_three(x: float, y: float) -> bool:
    """Whether a shot from this offensive-half point is worth three points."""
    if x > 0:
        return False
    corner = abs(y) >= CORNER_Y and x <= CORNER_X_MAX
    return corner or distance_to_hoop(x, y) >= THREE_POINT_RADIUS


def zone_of(x: float, y: float) -> Zone:
    """Zone of an offense-oriented point."""
    if x > 0:
        return "backcourt"
    distance = distance_to_hoop(x, y)
    if distance > FAR_DISTANCE:
        return "far"
    if is_three(x, y):
        return "corner_3" if x <= CORNER_X_MAX else "above_break_3"
    if distance <= RA_RADIUS:
        return "restricted_area"
    if abs(y) <= KEY_HALF_WIDTH and x <= KEY_X_MAX:
        return "paint_non_ra"
    return "mid_range"


def region_to_zone(region: str | None) -> Zone | None:
    """Map a SkillCorner event ``region`` to a zone (``None`` when unknown)."""
    if region is None:
        return None
    if region in _REGION_ZONES:
        return _REGION_ZONES[region]
    if region.endswith("two"):
        return "mid_range"
    if region.endswith("corner three"):
        return "corner_3"
    if region.endswith("wing three") or region == "middle three":
        return "above_break_3"
    return None


def points(zone: Zone) -> int:
    """Points of a made shot from the zone (``backcourt`` and ``far`` are beyond the arc)."""
    return 3 if zone in ("corner_3", "above_break_3", "backcourt", "far") else 2
