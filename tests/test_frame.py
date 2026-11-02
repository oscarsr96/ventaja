import pytest
from typer.testing import CliRunner

from ventaja.cli import app
from ventaja.config import Settings
from ventaja.decision.align import Aligner
from ventaja.decision.frame import decision_frame
from ventaja.errors import VentajaError

# Concrete frames below were computed from the built fixture of game 114243 with Polars:
# shots.start_frame, touches.start_frame of shots.touch_id, and sorted dribbles.frame of
# that touch, filtered to frames <= start_frame.


def _shot(kind: str | None, start: int = 110, touch_id: str | None = "t") -> dict[str, object]:
    return {"id": "s", "complex_shot_type": kind, "touch_id": touch_id, "start_frame": start}


def test_gather_rule_for_pull_up(built_fixture: Settings) -> None:
    # shot-114243-1-0: dribblePullUp, release 3895, touch starts 3852
    d = Aligner(114243, built_fixture).decision_frame("shot-114243-1-0")
    assert d.rule == "gather" and d.frame_idx == 3895 - 10


def test_last_dribble_rule_for_layup(built_fixture: Settings) -> None:
    # shot-114243-1-7: layup, release 10030, dribbles 9990, 10000, 10002
    d = Aligner(114243, built_fixture).decision_frame("shot-114243-1-7")
    assert d.rule == "last_dribble" and d.frame_idx == 10002


def test_touch_start_rule_for_finish_without_dribble(built_fixture: Settings) -> None:
    # shot-114243-1-1: floater, release 4157, touch starts 4115, no dribbles
    d = Aligner(114243, built_fixture).decision_frame("shot-114243-1-1")
    assert d.rule == "touch_start" and d.frame_idx == 4115


def test_excluded_without_touch_and_without_tracking(built_fixture: Settings) -> None:
    aligner = Aligner(114243, built_fixture)
    # shot-114243-1-9: layup with null touch_id
    assert aligner.decision_frame("shot-114243-1-9").reason == "no_touch"
    # shot-114243-1-2: null type with a touch
    assert aligner.decision_frame("shot-114243-1-2").reason == "no_type"
    # shot-114243-1-20: floater outside the fixture's tracking sample
    d = aligner.decision_frame("shot-114243-1-20")
    assert d.rule == "excluded" and d.frame_idx is None and d.reason == "no_tracking"


def test_finish_lag_cap_on_fixture(built_fixture: Settings) -> None:
    # shot-114243-1-16: layup, release 16144, touch starts 16045 (99 frames before) with no
    # tracking until later; the cap moves the frame to 16144 - 60 = 16084
    d = Aligner(114243, built_fixture).decision_frame("shot-114243-1-16")
    assert d.rule == "touch_start" and d.frame_idx == 16084


def test_excluded_rules() -> None:
    touch = {"start_frame": 90}
    assert decision_frame(_shot("tip"), touch, [], lambda f: True).reason == "tip"
    assert decision_frame(_shot("layup", touch_id=None), None, [], lambda f: True).reason == (
        "no_touch"
    )
    assert decision_frame(_shot(None), touch, [], lambda f: True).reason == "no_type"
    d = decision_frame(_shot("bogus"), touch, [], lambda f: True)
    assert d.rule == "excluded" and d.reason == "unknown_type:bogus"


def test_gather_is_clamped_to_touch_start() -> None:
    d = decision_frame(_shot("catchAndShoot", 110), {"start_frame": 105}, [], lambda f: True)
    assert d.rule == "gather" and d.frame_idx == 105


def test_dribbles_after_release_are_ignored() -> None:
    d = decision_frame(_shot("layup"), {"start_frame": 80}, [90, 100, 120], lambda f: True)
    assert d.rule == "last_dribble" and d.frame_idx == 100
    d = decision_frame(_shot("layup"), {"start_frame": 80}, [120], lambda f: True)
    assert d.rule == "touch_start" and d.frame_idx == 80


def test_finish_lag_is_capped() -> None:
    # last dribble 100 frames before release -> capped at release - 60, rule unchanged
    d = decision_frame(_shot("layup", 200), {"start_frame": 50}, [100], lambda f: True)
    assert d.rule == "last_dribble" and d.frame_idx == 200 - 60
    # touch start 150 frames before release, no dribbles -> capped as well
    d = decision_frame(_shot("dunk", 200), {"start_frame": 50}, [], lambda f: True)
    assert d.rule == "touch_start" and d.frame_idx == 140
    # within the cap the candidate is kept
    d = decision_frame(_shot("layup", 200), {"start_frame": 50}, [150], lambda f: True)
    assert d.frame_idx == 150
    # the cap applies before the no-tracking lookahead
    d = decision_frame(_shot("floater", 200), {"start_frame": 50}, [], lambda f: f >= 145)
    assert d.rule == "touch_start" and d.frame_idx == 145
    # jump shots are not capped by this rule
    d = decision_frame(_shot("catchAndShoot", 200), {"start_frame": 50}, [], lambda f: True)
    assert d.rule == "gather" and d.frame_idx == 190


def test_no_tracking_lookahead() -> None:
    touch = {"start_frame": 90}
    d = decision_frame(_shot("catchAndShoot"), touch, [], lambda f: f >= 105)
    assert d.frame_idx == 105 and d.rule == "gather"
    assert decision_frame(_shot("catchAndShoot"), touch, [], lambda f: f >= 111).reason == (
        "no_tracking"
    )
    assert decision_frame(_shot("catchAndShoot"), touch, [], lambda f: False).reason == (
        "no_tracking"
    )


def test_snapshot_for_shot_decision_uses_decision_frame(built_fixture: Settings) -> None:
    aligner = Aligner(114243, built_fixture)
    assert aligner.snapshot_for_shot("shot-114243-1-0", decision=True).frame_idx == 3885
    assert aligner.snapshot_for_shot("shot-114243-1-0").frame_idx == 3895


def test_snapshot_for_shot_decision_excluded_raises(built_fixture: Settings) -> None:
    with pytest.raises(VentajaError, match="no_touch"):
        Aligner(114243, built_fixture).snapshot_for_shot("shot-114243-1-9", decision=True)


def test_decision_snapshot_cli(built_fixture: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(built_fixture.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(built_fixture.build_dir))
    result = CliRunner().invoke(app, ["snapshot", "shot-114243-1-0", "--decision"])
    assert result.exit_code == 0, result.output
    assert "decision frame 3885 (gather)" in result.output
    assert "frame 3885  period" in result.output


def test_decision_snapshot_cli_excluded(
    built_fixture: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(built_fixture.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(built_fixture.build_dir))
    result = CliRunner().invoke(app, ["snapshot", "shot-114243-1-9", "--decision"])
    assert result.exit_code == 1
    assert "no_touch" in result.output
