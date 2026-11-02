import polars as pl
import pytest

from ventaja.config import Settings
from ventaja.decision.align import Aligner
from ventaja.decision.handler import BallHandler
from ventaja.errors import DataNotFoundError

POSSESSION = "possession-114243-1-2"


def test_handler_follows_touches(built_fixture: Settings) -> None:
    a = Aligner(114243, built_fixture)
    h = BallHandler(a.touches_of(POSSESSION))
    assert h.handler_at(3860) == 35028  # inside touch-114243-1-16 (3852-3895)
    assert h.handler_at(3840) == 28247  # touch-114243-1-15 (3835-3850)
    assert h.handler_at(3851) is None  # ball in flight between two touches
    assert h.handler_at(1) is None
    assert h.spans()[-1] == (3852, 3895, 35028)
    assert h.spans() == sorted(h.spans())


def test_handler_overlap_takes_later_start() -> None:
    df = pl.DataFrame({"start_frame": [10, 15], "end_frame": [20, 25], "player_id": [1, 2]})
    h = BallHandler(df)
    assert h.handler_at(12) == 1
    assert h.handler_at(17) == 2
    assert h.handler_at(22) == 2


def test_touches_of_sorted(built_fixture: Settings) -> None:
    t = Aligner(114243, built_fixture).touches_of(POSSESSION)
    assert t["start_frame"].to_list() == sorted(t["start_frame"].to_list())
    assert set(t["possession_id"]) == {POSSESSION}


def test_chance_of_shot(built_fixture: Settings) -> None:
    c = Aligner(114243, built_fixture).chance_of_shot("shot-114243-1-0")
    assert c["id"] == "chance-114243-1-3" and c["possession_id"] == POSSESSION


def test_chance_of_unknown_shot_raises(built_fixture: Settings) -> None:
    with pytest.raises(DataNotFoundError, match="nope"):
        Aligner(114243, built_fixture).chance_of_shot("nope")
