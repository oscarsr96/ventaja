import pytest

from ventaja.config import Settings
from ventaja.data.load import load_events
from ventaja.value.zones import is_three, points, region_to_zone, zone_of

GAME_ID = 114243


def test_zone_of_known_points() -> None:
    assert zone_of(-40.7, 0.0) == "restricted_area"
    assert zone_of(-30.0, 0.0) == "paint_non_ra"
    assert zone_of(-25.0, 10.0) == "mid_range"
    assert zone_of(-42.0, 23.0) == "corner_3"
    assert zone_of(-18.0, 0.0) == "above_break_3"
    assert zone_of(5.0, 0.0) == "backcourt"
    assert zone_of(-5.0, 0.0) == "far"


def test_is_three_corner_and_arc() -> None:
    assert is_three(-42.0, 22.0)
    assert not is_three(-30.0, 15.0)  # inside the arc and past the corner segment
    assert not is_three(-25.0, 10.0)


@pytest.mark.parametrize(
    ("region", "zone"),
    [
        ("ra", "restricted_area"),
        ("key", "paint_non_ra"),
        ("left corner two", "mid_range"),
        ("middle two", "mid_range"),
        ("right wing two", "mid_range"),
        ("left corner three", "corner_3"),
        ("right corner three", "corner_3"),
        ("left wing three", "above_break_3"),
        ("middle three", "above_break_3"),
        ("backcourt", "backcourt"),
        ("far", "far"),
        (None, None),
    ],
)
def test_region_to_zone(region: str | None, zone: str | None) -> None:
    assert region_to_zone(region) == zone


def test_points() -> None:
    assert points("corner_3") == 3
    assert points("above_break_3") == 3
    assert points("mid_range") == 2
    assert points("restricted_area") == 2


def test_zone_agrees_with_event_region(built_fixture: Settings) -> None:
    shots = load_events(GAME_ID, "shots", built_fixture).drop_nulls(["loc_x", "loc_y", "region"])
    rows = shots.select("loc_x", "loc_y", "region").iter_rows()
    agree = sum(zone_of(x, y) == region_to_zone(r) for x, y, r in rows)
    assert agree / shots.height >= 0.95
