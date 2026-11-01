import polars as pl

from ventaja.config import Settings
from ventaja.data.load import load_events, load_tracking
from ventaja.geometry.court import (
    FPS,
    HOOP,
    distance_to_hoop,
    orient_frame,
    orient_to_offense,
)

GAME_ID = 114243


def test_orient_identity_when_left_hoop() -> None:
    assert orient_to_offense(10.0, -3.0, True) == (10.0, -3.0)


def test_orient_rotates_180_when_right_hoop() -> None:
    assert orient_to_offense(10.0, -3.0, False) == (-10.0, 3.0)


def test_distance_to_hoop_at_rim_is_zero() -> None:
    assert distance_to_hoop(*HOOP) == 0.0


def test_fps_reexported() -> None:
    assert FPS == 25


def test_orient_frame_negates_only_when_right_hoop() -> None:
    df = pl.DataFrame({"x": [1.0, -2.0], "y": [3.0, 4.0], "k": [1, 2]})
    assert orient_frame(df, True).equals(df)
    out = orient_frame(df, False)
    assert out["x"].to_list() == [-1.0, 2.0]
    assert out["y"].to_list() == [-3.0, -4.0]
    assert out["k"].to_list() == [1, 2]


def test_shot_distance_field_matches_hoop_constant(built_fixture: Settings) -> None:
    shots = load_events(GAME_ID, "shots", built_fixture).drop_nulls("loc_x")
    computed = shots.select(
        ((pl.col("loc_x") - HOOP[0]) ** 2 + (pl.col("loc_y") - HOOP[1]) ** 2).sqrt().alias("d")
    )
    diff = (computed["d"] - shots["distance"]).abs().max()
    assert diff is not None
    assert float(diff) < 0.5  # type: ignore[arg-type]


def test_oriented_shooter_position_matches_event_location(built_fixture: Settings) -> None:
    shots = (
        load_events(GAME_ID, "shots", built_fixture)
        .drop_nulls("loc_x")
        .select("start_frame", "shooter_id", "possession_id", "loc_x", "loc_y")
    )
    poss = load_events(GAME_ID, "possessions", built_fixture).select(
        pl.col("id").alias("possession_id"), "left_hoop"
    )
    tracking = (
        load_tracking(GAME_ID, built_fixture).select("frame_idx", "player_id", "x", "y").collect()
    )
    joined = shots.join(poss, on="possession_id").join(
        tracking,
        left_on=["start_frame", "shooter_id"],
        right_on=["frame_idx", "player_id"],
    )
    assert joined.height >= 15
    assert set(joined["left_hoop"].to_list()) == {True, False}
    oriented = pl.concat(
        [orient_frame(joined.filter(pl.col("left_hoop") == flag), flag) for flag in (True, False)]
    )
    assert oriented.height == joined.height
    dist = oriented.select(
        ((pl.col("x") - pl.col("loc_x")) ** 2 + (pl.col("y") - pl.col("loc_y")) ** 2).sqrt()
    ).to_series()
    max_dist = dist.max()
    assert isinstance(max_dist, float)
    assert max_dist < 4.0
