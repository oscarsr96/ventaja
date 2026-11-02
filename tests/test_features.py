import math

import polars as pl
import pytest
from helpers import PlayerSpec, make_snapshot

from ventaja.config import Settings
from ventaja.decision.align import Aligner
from ventaja.errors import VentajaError
from ventaja.geometry.court import distance_to_hoop
from ventaja.value.features import OPTION_FEATURES, option_rows, shot_kwargs, shot_rows
from ventaja.value.params import PROJECTION_CAP
from ventaja.value.priors import Priors

SHOT_ID = "shot-114243-1-0"
FAR_DEF = [(100 + i, 0.0, 20.0 + i) for i in range(5)]


def _priors(settings: Settings) -> Priors:
    return Priors.from_settings(settings)


def _row(rows: pl.DataFrame, pid: int) -> dict[str, object]:
    return rows.filter(pl.col("option_player_id") == pid).row(0, named=True)


def _team(*mates: PlayerSpec) -> list[PlayerSpec]:
    return [(1, -10.0, 0.0), *mates]


def test_option_rows_shape_and_shooter_row(built_fixture: Settings) -> None:
    a = Aligner(114243, built_fixture)
    s = a.snapshot_for_shot(SHOT_ID, decision=True)
    rows = option_rows(s, 35028, _priors(built_fixture))
    assert rows.height == 5 and rows.filter(pl.col("option_type") == "shot").height == 1
    shooter = _row(rows, 35028)
    assert shooter["pass_distance"] == 0 and shooter["lane_blocked"] is False
    assert shooter["projected_dx"] == 0 and shooter["projected_dy"] == 0
    p = s.player(35028)
    assert abs(float(shooter["dist_hoop"]) - distance_to_hoop(p.x, p.y)) < 1e-6  # type: ignore[arg-type]
    assert set(OPTION_FEATURES) <= set(rows.columns)


def test_projection_moves_cutter_toward_hoop() -> None:
    s = make_snapshot(
        offense=_team(
            (2, -30.0, 0.0, -10.0, 0.0),
            (3, 0.0, 15.0),
            (4, 0.0, -15.0),
            (5, 0.0, 10.0),
        ),
        defense=FAR_DEF,
    )
    rows = option_rows(s, 1, _priors_stub())
    r = _row(rows, 2)
    # pass distance 20 ft -> t = 0.5 s -> 5 ft displacement
    assert r["pass_distance"] == pytest.approx(20.0)
    assert r["x"] == pytest.approx(-35.0) and r["projected_dx"] == pytest.approx(-5.0)
    assert r["moving_to_hoop"] == pytest.approx(10.0)


def test_projection_is_capped() -> None:
    s = make_snapshot(
        offense=_team((2, -30.0, 0.0, -30.0, 40.0), (3, 0, 15), (4, 0, -15), (5, 0, 10)),
        defense=FAR_DEF,
    )
    r = _row(option_rows(s, 1, _priors_stub()), 2)
    norm = math.hypot(float(r["projected_dx"]), float(r["projected_dy"]))  # type: ignore[arg-type]
    assert norm == pytest.approx(PROJECTION_CAP)
    assert float(r["projected_dx"]) / float(r["projected_dy"]) == pytest.approx(-30 / 40)  # type: ignore[arg-type]


def test_projection_without_velocity_is_identity() -> None:
    s = make_snapshot(
        offense=_team((2, -30.0, 3.0), (3, 0, 15), (4, 0, -15), (5, 0, 10)),
        defense=FAR_DEF,
    )
    r = _row(option_rows(s, 1, _priors_stub()), 2)
    assert (r["x"], r["y"]) == (-30.0, 3.0)
    assert r["projected_dx"] == 0 and r["projected_dy"] == 0 and r["moving_to_hoop"] == 0


def _lane(defender_y: float) -> bool:
    """Passer (-10, 0) -> receiver (-30, 0); a second defender keeps the receiver covered."""
    s = make_snapshot(
        offense=[(1, -10.0, 0.0), (2, -30.0, 0.0), (3, 0, 15), (4, 0, -15), (5, 0, 10)],
        defense=[(100, -20.0, defender_y), (101, -30.0, 5.0), *FAR_DEF[2:]],
    )
    return bool(_row(option_rows(s, 1, _priors_stub()), 2)["lane_blocked"])


def test_lane_blocked_detects_defender_on_segment() -> None:
    # The receiver has a defender at 5 ft (not open), so a mid-lane defender blocks (ADR-0005).
    assert _lane(1.0) is True
    assert _lane(5.0) is False


def _lane_case(
    defender: tuple[float, float],
    *,
    receiver_def: tuple[float, float] | None = None,
    passer_vx: float | None = None,
) -> bool:
    """Passer (-10, 0) -> receiver (-30, 0), 20 ft; ``defender`` is the one in the lane."""
    passer: PlayerSpec = (1, -10.0, 0.0) if passer_vx is None else (1, -10.0, 0.0, passer_vx, 0.0)
    defense: list[PlayerSpec] = [(100, *defender)]
    defense += [(101, *receiver_def)] if receiver_def else []
    defense += FAR_DEF[len(defense) :]
    s = make_snapshot(
        offense=[passer, (2, -30.0, 0.0), (3, 0, 15), (4, 0, -15), (5, 0, 10)], defense=defense
    )
    return bool(_row(option_rows(s, 1, _priors_stub()), 2)["lane_blocked"])


def test_lane_mid_lane_defender_open_receiver_set_passer_not_blocked() -> None:
    """Kurucs / Andric / Gonzalez: a set passer lobs over a defender in the middle."""
    assert _lane_case((-20.0, 1.0)) is False


def test_lane_mid_lane_defender_receiver_not_open_blocked() -> None:
    """Mid-lane defender and a covered receiver (defender at 4 ft)."""
    assert _lane_case((-20.0, 1.0), receiver_def=(-30.0, 4.0)) is True


def test_lane_mid_lane_defender_passer_driving_spagnolo_omoruyi_blocked() -> None:
    """Spagnolo / Omoruyi: open receiver, passer driving to the hoop (at x=-40.7) at 10 ft/s."""
    assert _lane_case((-20.0, 1.0), passer_vx=-10.0) is True
    assert _lane_case((-20.0, 1.0), passer_vx=10.0) is False


def test_lane_defender_near_passer_end_blocked_regardless() -> None:
    assert _lane_case((-13.0, 0.5)) is True
    assert _lane_case((-27.0, 0.5)) is True


def test_lane_ignores_defender_guarding_endpoints() -> None:
    s = make_snapshot(
        offense=[(1, -10.0, 0.0), (2, -30.0, 0.0), (3, 0, 15), (4, 0, -15), (5, 0, 10)],
        defense=[(100, -11.0, 0.5), (101, -29.0, 0.5), *FAR_DEF[2:]],
    )
    assert _row(option_rows(s, 1, _priors_stub()), 2)["lane_blocked"] is False


def test_defender_features() -> None:
    s = make_snapshot(
        offense=[(1, -20.0, 0.0), (2, 0, 15), (3, 0, -15), (4, 0, 10), (5, 0, 12)],
        defense=[(100, -28.0, 0.0, 4.0, 0.0), *FAR_DEF[1:]],
        shot_clock=3.0,
    )
    r = _row(option_rows(s, 1, _priors_stub()), 1)
    assert r["nearest_def_dist"] == pytest.approx(8.0)
    assert r["closing_speed"] == pytest.approx(4.0)  # defender (-28,0) moves +x toward player
    assert r["def_between"] == 1
    assert r["angle_abs"] == pytest.approx(0.0)
    assert r["shot_clock_low"] == 1 and r["shot_clock"] == 3.0


def test_null_shot_clock() -> None:
    s = make_snapshot(
        offense=[(1, -20.0, 0.0), (2, 0, 15), (3, 0, -15), (4, 0, 10), (5, 0, 12)],
        defense=FAR_DEF,
        shot_clock=None,
    )
    r = _row(option_rows(s, 1, _priors_stub()), 1)
    assert r["shot_clock"] is None and r["shot_clock_low"] == 0


def test_shooter_not_on_court_raises() -> None:
    s = make_snapshot(offense=[(1, -20.0, 0.0), (2, 0, 15)], defense=FAR_DEF)
    with pytest.raises(VentajaError):
        option_rows(s, 999, _priors_stub())


def test_shot_rows_covers_non_excluded_shots(built_fixture: Settings) -> None:
    a = Aligner(114243, built_fixture)
    df = shot_rows(a, _priors(built_fixture))
    ids = a._shots["id"].to_list()
    n_valid = sum(a.decision_frame(i).rule != "excluded" for i in ids)
    assert n_valid > 0
    assert df.filter(pl.col("option_type") == "shot").height == n_valid
    assert df.height == 5 * n_valid
    assert df.group_by("shot_id").len()["len"].to_list() == [5] * n_valid
    assert df["prior_zone"].is_between(0.0, 1.0).all()
    shooters = df.filter(pl.col("option_type") == "shot")
    assert shooters["outcome"].null_count() == 0
    assert df.filter(pl.col("option_type") == "pass")["shot_quality"].null_count() == 4 * n_valid
    for col in ("decision_frame", "rule", "game_id", "three", "shot_clock"):
        assert col in df.columns


def test_shot_row_uses_the_attempted_shot_zone_and_points() -> None:
    # The shooter stands beyond the arc at the decision frame (a finish's last dribble)...
    s = make_snapshot(
        offense=[(1, -10.0, 0.0), (2, -30.0, 0.0), (3, 0, 15), (4, 0, -15), (5, 0, 10)],
        defense=FAR_DEF,
    )
    default = _row(option_rows(s, 1, _zone_priors()), 1)
    assert default["zone"] == "above_break_3" and default["points"] == 3
    assert default["is_three"] is True and default["prior_zone"] == 0.3
    # ...but the event says the shot was a two at the rim.
    rows = option_rows(s, 1, _zone_priors(), shot_zone="restricted_area", shot_three=False)
    shot = _row(rows, 1)
    assert shot["zone"] == "restricted_area" and shot["points"] == 2
    assert shot["is_three"] is False and shot["prior_zone"] == 0.6
    # Geometry stays the decision-frame state; pass rows are unchanged.
    assert shot["dist_hoop"] == default["dist_hoop"]
    assert shot["nearest_def_dist"] == default["nearest_def_dist"]
    assert rows.filter(pl.col("option_type") == "pass").equals(
        option_rows(s, 1, _zone_priors()).filter(pl.col("option_type") == "pass")
    )


def test_shot_row_three_flag_without_zone_falls_back_to_position() -> None:
    s = make_snapshot(
        offense=[(1, -10.0, 0.0), (2, -30.0, 0.0), (3, 0, 15), (4, 0, -15), (5, 0, 10)],
        defense=FAR_DEF,
    )
    shot = _row(option_rows(s, 1, _zone_priors(), shot_zone=None, shot_three=False), 1)
    assert shot["zone"] == "above_break_3" and shot["points"] == 2 and shot["is_three"] is False


def test_shot_kwargs_from_event() -> None:
    assert shot_kwargs({"region": "ra", "three": False}) == {
        "shot_zone": "restricted_area",
        "shot_three": False,
    }
    assert shot_kwargs({"region": None, "three": True}) == {"shot_zone": None, "shot_three": True}
    assert shot_kwargs({"region": "backcourt", "three": True})["shot_zone"] == "backcourt"


def test_no_defenders_raises_ventaja_error() -> None:
    s = make_snapshot(offense=_team((2, 0, 15), (3, 0, -15), (4, 0, 10), (5, 0, 12)), defense=[])
    with pytest.raises(VentajaError, match="no defenders in frame"):
        option_rows(s, 1, _priors_stub())


def test_shot_rows_shot_row_matches_event_points(built_fixture: Settings) -> None:
    a = Aligner(114243, built_fixture)
    shots = shot_rows(a, _priors(built_fixture)).filter(pl.col("option_type") == "shot")
    assert shots.height > 0
    expected = shots["three"].map_elements(lambda t: 3 if t else 2, return_dtype=pl.Int64)
    assert shots["points"].to_list() == expected.to_list()
    assert shots["is_three"].to_list() == shots["three"].to_list()


class _Stub:
    def player_rate(self, player_id: int, zone: str) -> float:
        return 0.4


class _ZonePriors:
    def player_rate(self, player_id: int, zone: str) -> float:
        return 0.6 if zone == "restricted_area" else 0.3


def _priors_stub() -> Priors:
    return _Stub()  # type: ignore[return-value]


def _zone_priors() -> Priors:
    return _ZonePriors()  # type: ignore[return-value]
