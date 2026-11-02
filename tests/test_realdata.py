"""Opt-in checks against the full SkillCorner data (all ten games, built with tracking).

Set VENTAJA_REALDATA_DIR (raw dir, SkillCorner layout) and VENTAJA_REALDATA_BUILD_DIR (a build
dir holding events and tracking for every game) to run them.
"""

import math
import os
from pathlib import Path

import polars as pl
import pytest

from ventaja.config import GAME_IDS, Settings
from ventaja.decision.align import Aligner
from ventaja.errors import NoTrackingError

RAW_ENV = "VENTAJA_REALDATA_DIR"
BUILD_ENV = "VENTAJA_REALDATA_BUILD_DIR"
MAX_SHOOTER_DIST_FT = 4.0

pytestmark = [
    pytest.mark.realdata,
    pytest.mark.skipif(
        not (os.environ.get(RAW_ENV) and os.environ.get(BUILD_ENV)),
        reason=f"set {RAW_ENV} and {BUILD_ENV} to run the real-data checks",
    ),
]


@pytest.fixture(scope="module")
def real_settings() -> Settings:
    return Settings(data_dir=Path(os.environ[RAW_ENV]), build_dir=Path(os.environ[BUILD_ENV]))


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_every_shot_snapshot_puts_shooter_on_offense_at_shot_location(
    game_id: int, real_settings: Settings
) -> None:
    """Every shot snapshot succeeds with the shooter on offense near (loc_x, loc_y).

    The only tolerated failure is NoTrackingError on a shot without ``loc_x`` (a tracking gap).
    """
    a = Aligner(game_id, real_settings)
    failures: list[str] = []
    for shot in a._shots.iter_rows(named=True):
        shot_id = shot["id"]
        try:
            s = a.snapshot_for_shot(shot_id)
        except NoTrackingError as exc:
            # A few shots fall in a tracking gap; SkillCorner also leaves them unlocated.
            if shot["loc_x"] is not None:
                failures.append(f"{shot_id}: NoTrackingError: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - collect every failing shot
            failures.append(f"{shot_id}: {type(exc).__name__}: {exc}")
            continue
        shooter = next((p for p in s.offense if p.player_id == shot["shooter_id"]), None)
        if shooter is None:
            failures.append(f"{shot_id}: shooter {shot['shooter_id']} not in offense")
            continue
        if shot["loc_x"] is not None:
            dist = math.hypot(shooter.x - shot["loc_x"], shooter.y - shot["loc_y"])
            if dist > MAX_SHOOTER_DIST_FT:
                failures.append(f"{shot_id}: shooter {dist:.2f} ft from (loc_x, loc_y)")
    assert not failures, f"{len(failures)} of {a._shots.height} shots fail:\n" + "\n".join(failures)


def test_shot_option_points_match_the_event(real_settings: Settings) -> None:
    """The taken shot is valued with the event's points: 3 if ``three`` else 2 (ADR-0004)."""
    from ventaja.data.load import load_decision_options, load_events

    for game_id in GAME_IDS:
        shots = load_events(game_id, "shots", real_settings).select(
            pl.col("id").alias("shot_id"), "three"
        )
        rows = (
            load_decision_options(game_id, real_settings)
            .filter(pl.col("option_type") == "shot")
            .join(shots, on="shot_id", how="left")
        )
        assert rows.height > 0 and rows["three"].null_count() == 0
        expected = pl.when(pl.col("three")).then(3).otherwise(2)
        bad = rows.filter(
            (pl.col("points") != expected)
            | (pl.col("is_three") != pl.col("three").cast(pl.Float64))
        )
        assert bad.height == 0, f"game {game_id}: {bad.select('shot_id', 'points', 'three')}"


def test_decision_face_validity_checks(real_settings: Settings) -> None:
    """The four automatic sanity checks (spec 5.5) over the decisions of the ten games."""
    from ventaja.data.load import load_decision_options, load_decisions
    from ventaja.validate.decisions import checks
    from ventaja.value.model import ValueModel

    result = {
        name: (ok, detail)
        for name, ok, detail in checks(
            pl.concat([load_decisions(g, real_settings) for g in GAME_IDS], how="diagonal"),
            pl.concat([load_decision_options(g, real_settings) for g in GAME_IDS], how="diagonal"),
            ValueModel.default(),
        )
    }
    assert len(result) == 4
    for name in (
        "rim_open_beats_contested_three",
        "prior_moves_value",
        "excluded_share_below_15pct",
    ):
        assert result[name][0], f"{name}: {result[name][1]}"
    ok, detail = result["cost_falls_with_clock"]
    if not ok:
        pytest.xfail(
            "known: mean cost by clock is 0.148 (24-14), 0.184 (14-6), 0.122 (6-0), "
            f"not monotone (see ADR-0004); measured now: {detail}"
        )
    pytest.fail(f"cost_falls_with_clock now passes ({detail}); drop the xfail", pytrace=False)


# player_id of the receivers judged in the live session of 2026-11-02 (ADR-0005), from
# meta/players.parquet: jersey 47 / 37 / 7 of game 191313 and jersey 10 (Spagnolo) of 114086.
SESSION_RECEIVERS = {
    "shot-191313-2-46": (59105, False),  # Kurucs: mid-lane defender, open receiver, set passer
    "shot-191313-4-127": (58771, False),  # Andric
    "shot-191313-4-137": (59206, False),  # Gonzalez
    "shot-114086-4-102": (59135, True),  # Spagnolo: receiver is covered
}


def test_lane_rule_after_the_live_session(real_settings: Settings) -> None:
    """ADR-0005: fewer pass options are blocked, and the coach's four shots flip as he judged."""
    from ventaja.data.load import load_decision_options

    options = pl.concat([load_decision_options(g, real_settings) for g in GAME_IDS], how="diagonal")
    passes = options.filter(pl.col("option_type") == "pass")
    share = passes["lane_blocked"].mean()
    assert share is not None and share < 0.45, f"lane_blocked share {share:.3f}"
    for shot_id, (player_id, expected) in SESSION_RECEIVERS.items():
        row = passes.filter(
            (pl.col("shot_id") == shot_id) & (pl.col("option_player_id") == player_id)
        )
        assert row.height == 1, shot_id
        assert row["lane_blocked"][0] is expected, shot_id
