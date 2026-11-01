"""Opt-in checks against the full SkillCorner data (all ten games, built with tracking).

Set VENTAJA_REALDATA_DIR (raw dir, SkillCorner layout) and VENTAJA_REALDATA_BUILD_DIR (a build
dir holding events and tracking for every game) to run them.
"""

import math
import os
from pathlib import Path

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
