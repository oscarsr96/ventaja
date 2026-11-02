import math

import polars as pl
import pytest

from ventaja.config import Settings
from ventaja.data.load import load_tracking
from ventaja.decision.align import Aligner, _velocities

GAME = 114243


def test_velocity_matches_tracking_speed(built_fixture: Settings) -> None:
    s = Aligner(GAME, built_fixture).snapshot_for_shot("shot-114243-1-0")
    for p in s.offense + s.defense:
        assert p.vx is not None and p.vy is not None
        assert abs(math.hypot(p.vx, p.vy) - p.speed) < 1.0  # ft/s
        assert p.speed_vec == pytest.approx(math.hypot(p.vx, p.vy))


def test_velocity_is_oriented_like_positions(built_fixture: Settings) -> None:
    a = Aligner(GAME, built_fixture)
    frames = {s.frame_idx: s for s in a.window(3880, 3910) if s.possession_id == _poss(a, 3895)}
    centre = 3895
    assert centre in frames and centre - 2 in frames and centre + 2 in frames
    s = frames[centre]
    p = max(s.offense + s.defense, key=lambda q: abs(q.vx or 0.0))
    dx = frames[centre + 2].player(p.player_id).x - frames[centre - 2].player(p.player_id).x
    assert p.vx is not None
    assert p.vx * dx > 0
    assert p.vx == pytest.approx(dx * 25 / 4)


def _poss(a: Aligner, frame: int) -> str:
    row = a.possession_at(frame)
    assert row is not None
    return str(row["id"])


def test_window_velocities_match_snapshot(built_fixture: Settings) -> None:
    a = Aligner(GAME, built_fixture)
    w = {s.frame_idx: s for s in a.window(3893, 3897)}
    assert set(w) <= set(range(3893, 3898))
    for f, s in w.items():
        assert a.snapshot(f).ball.vx == s.ball.vx


def test_velocity_none_when_no_neighbours(built_fixture: Settings) -> None:
    a = Aligner(GAME, built_fixture)
    frames = set(
        load_tracking(GAME, built_fixture).select("frame_idx").unique().collect()["frame_idx"]
    )
    lone = next(
        (
            f
            for f in sorted(frames)
            if not frames & {f - 2, f - 1, f + 1, f + 2} and a.possession_at(f) is not None
        ),
        None,
    )
    if lone is None:
        pytest.skip("fixture tracking windows are contiguous: no isolated tracked frame")
    s = a.snapshot(lone)
    assert all(p.vx is None for p in s.offense + s.defense)
    assert s.ball.vx is None


def _rows(frame: int, x: float, with_p2: bool = True) -> list[dict[str, object]]:
    out: list[dict[str, object]] = [
        {"frame_idx": frame, "side": "home", "player_id": 1, "x": x, "y": 0.0},
        {"frame_idx": frame, "side": "ball", "player_id": 0, "x": x, "y": 1.0},
    ]
    if with_p2:
        out.append({"frame_idx": frame, "side": "away", "player_id": 2, "x": 5.0, "y": 0.0})
    return out


def _ctx(spec: dict[int, tuple[float, bool]]) -> pl.DataFrame:
    rows = [r for f, (x, p2) in spec.items() for r in _rows(f, x, p2)]
    return pl.DataFrame(rows)


def test_velocities_central_difference() -> None:
    v = _velocities(_ctx({8: (0.0, True), 10: (1.0, True), 12: (4.0, True)}), 10, True)
    assert v[1] == pytest.approx((4.0 * 25 / 4, 0.0))
    assert v["ball"] == pytest.approx((4.0 * 25 / 4, 0.0))


def test_velocities_one_sided_and_rotation() -> None:
    ctx = _ctx({10: (1.0, True), 11: (2.0, True)})
    assert _velocities(ctx, 10, True)[1] == pytest.approx((25.0, 0.0))
    # left_hoop False rotates 180 degrees: velocity flips sign
    assert _velocities(ctx, 10, False)[1] == pytest.approx((-25.0, 0.0))
    back = _ctx({8: (0.0, True), 10: (1.0, True)})
    assert _velocities(back, 10, True)[1] == pytest.approx((12.5, 0.0))


def test_velocities_none_without_neighbours_or_missing_player() -> None:
    assert _velocities(_ctx({10: (1.0, True)}), 10, True) == {
        1: (None, None),
        2: (None, None),
        "ball": (None, None),
    }
    v = _velocities(_ctx({10: (1.0, True), 12: (3.0, False)}), 10, True)
    assert v[1] == pytest.approx((25.0, 0.0))
    assert v[2] == (None, None)


def test_velocities_nearest_neighbour_prefers_distance_one_forward() -> None:
    # f-2 and f+1 exist: the distance-1 forward neighbour wins over the distance-2 backward one
    v = _velocities(_ctx({8: (0.0, True), 10: (1.0, True), 11: (3.0, True)}), 10, True)
    assert v[1] == pytest.approx((2.0 * 25, 0.0))
    # tie at equal distance: backward preferred
    v = _velocities(_ctx({9: (0.0, True), 10: (1.0, True), 11: (5.0, True)}), 10, True)
    assert v[1] == pytest.approx((1.0 * 25, 0.0))
