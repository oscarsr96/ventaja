from typing import Any

import polars as pl
import pytest

from ventaja.config import Settings
from ventaja.decision.align import Aligner
from ventaja.decision.curve import headline, possession_curve, summarize_curve
from ventaja.model.decision import CurveSummary
from ventaja.value.model import ValueModel
from ventaja.value.priors import Priors

SHOT_ID = "shot-114243-1-0"  # release 3895, decision 3885, handler 35028; tracking 3820-3895
FLIGHT_SHOT_ID = "shot-114243-1-1"  # release 4157; ball in flight at sampled frames 4107, 4112
TIP_ID = "shot-114243-4-138"
NO_TOUCH_ID = "shot-114243-1-8"
NO_TYPE_ID = "shot-114243-1-2"


def _curve(a: Aligner, shot_id: str, priors: Priors, model: ValueModel) -> pl.DataFrame:
    c = possession_curve(a, shot_id, priors, model)
    assert c is not None
    return c


def test_curve_rows_and_release_present(
    built_fixture: Settings, fixture_priors: Priors, trained_fixture_model: ValueModel
) -> None:
    a = Aligner(114243, built_fixture)
    c = _curve(a, SHOT_ID, fixture_priors, trained_fixture_model)
    assert c["frame_idx"].to_list() == list(range(3820, 3896, 5))  # every tracked step frame
    assert (c["frame_idx"] % 5 == 3895 % 5).all()
    assert c.filter(pl.col("frame_idx") == 3895)["handler_id"][0] == 35028
    assert c.filter(pl.col("frame_idx") == 3840)["handler_id"][0] == 28247
    assert c["best_value"].is_between(0.0, 3.0).all()
    assert (c["best_value"] >= c["handler_shot_value"]).all()
    assert c["t_to_release"].max() == 0.0
    assert c.filter(pl.col("frame_idx") == 3820)["t_to_release"][0] == pytest.approx(-3.0)
    assert set(c["shot_id"]) == {SHOT_ID} and set(c["game_id"]) == {114243}
    assert c["n_viable"].is_between(0, 4).all()
    shots = c.filter(pl.col("best_option_type") == "shot")
    passes = c.filter(pl.col("best_option_type") == "pass")
    assert shots["best_alt_type"].null_count() == shots.height
    assert passes["best_alt_type"].null_count() == 0
    assert (shots["best_player_id"] == shots["handler_id"]).all()
    assert (shots["best_value"] == shots["handler_shot_value"]).all()


def test_curve_skips_ball_in_flight(
    built_fixture: Settings, fixture_priors: Priors, trained_fixture_model: ValueModel
) -> None:
    a = Aligner(114243, built_fixture)
    frames = _curve(a, FLIGHT_SHOT_ID, fixture_priors, trained_fixture_model)["frame_idx"]
    assert 4157 in frames.to_list() and 4102 in frames.to_list() and 4117 in frames.to_list()
    assert 4107 not in frames.to_list() and 4112 not in frames.to_list()


@pytest.mark.parametrize("shot_id", [TIP_ID, NO_TOUCH_ID, NO_TYPE_ID])
def test_curve_none_for_excluded_shot(
    built_fixture: Settings,
    fixture_priors: Priors,
    trained_fixture_model: ValueModel,
    shot_id: str,
) -> None:
    a = Aligner(114243, built_fixture)
    assert possession_curve(a, shot_id, fixture_priors, trained_fixture_model) is None


@pytest.mark.parametrize(
    ("frontcourt_frame", "start_frame", "first_frame"),
    [
        (None, 3858, 3860),  # no frontcourt frame: the span starts at the chance start
        (3871, 3642, 3875),  # frontcourt frame known: it wins over the chance start
    ],
)
def test_curve_span_start(
    built_fixture: Settings,
    fixture_priors: Priors,
    trained_fixture_model: ValueModel,
    monkeypatch: pytest.MonkeyPatch,
    frontcourt_frame: int | None,
    start_frame: int,
    first_frame: int,
) -> None:
    a = Aligner(114243, built_fixture)
    real = a.chance_of_shot(SHOT_ID)
    patched: dict[str, Any] = {
        **real,
        "frontcourt_frame": frontcourt_frame,
        "start_frame": start_frame,
    }
    monkeypatch.setattr(a, "chance_of_shot", lambda shot_id: patched)
    c = _curve(a, SHOT_ID, fixture_priors, trained_fixture_model)
    assert c["frame_idx"].min() == first_frame and c["frame_idx"].max() == 3895


def test_curve_real_null_frontcourt_frame(
    built_fixture: Settings, fixture_priors: Priors, trained_fixture_model: ValueModel
) -> None:
    a = Aligner(114243, built_fixture)
    assert a.chance_of_shot("shot-114243-1-14")["frontcourt_frame"] is None
    c = _curve(a, "shot-114243-1-14", fixture_priors, trained_fixture_model)
    assert c["frame_idx"].max() == 12670 and c.height > 0


def test_curve_skips_frames_with_handler_off_court(
    built_fixture: Settings,
    fixture_priors: Priors,
    trained_fixture_model: ValueModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = Aligner(114243, built_fixture)
    touches = a.touches_of("possession-114243-1-2").with_columns(
        player_id=pl.when(pl.col("player_id") == 28247)
        .then(pl.lit(999))
        .otherwise(pl.col("player_id"))
    )
    monkeypatch.setattr(a, "touches_of", lambda possession_id: touches)
    frames = _curve(a, SHOT_ID, fixture_priors, trained_fixture_model)["frame_idx"].to_list()
    assert frames == [3820, 3825, 3830, *range(3855, 3896, 5)]  # 3835-3850 skipped


def _summary_curve(values: list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {"frame_idx": [100 + 5 * i for i in range(len(values))], "best_value": values}
    )


def _summarize(values: list[float], decision_frame: int) -> CurveSummary:
    return summarize_curve(
        _summary_curve(values),
        shot_id="shot-1-1-0",
        game_id=1,
        decision_frame=decision_frame,
        shot_value=0.85,
    )


def test_summary_late() -> None:
    s = _summarize([0.8, 1.2, 1.25, 1.2, 0.9, 0.85], 125)
    assert (s.shot_id, s.game_id, s.n_rows, s.span_start, s.span_end) == (
        "shot-1-1-0",
        1,
        6,
        100,
        125,
    )
    assert (s.peak_frame, s.peak_value) == (110, 1.25)
    assert (s.window_start, s.window_end) == (105, 115)
    assert s.advantage_seconds == pytest.approx(0.6)
    assert s.verdict == "late" and s.release_lag_seconds == pytest.approx(0.4)
    assert s.value_at_decision == 0.85 and s.shot_value == 0.85


def test_summary_on_time() -> None:
    s = _summarize([0.8, 1.2, 1.25, 1.2, 0.9, 0.85], 112)
    assert s.verdict == "on_time" and s.release_lag_seconds == 0.0
    assert s.value_at_decision == 1.25  # 112 is closest to 110


def test_summary_early() -> None:
    s = _summarize([0.8, 1.2, 1.25, 1.2, 0.9, 0.85], 101)
    assert s.verdict == "early" and s.release_lag_seconds == pytest.approx(-0.16)
    assert s.value_at_decision == 0.8


def test_summary_peak_tie_takes_earlier_and_single_row_window() -> None:
    s = _summarize([1.0, 0.5, 1.0, 0.5], 107)
    assert s.peak_frame == 100 and (s.window_start, s.window_end) == (100, 100)
    assert s.advantage_seconds == pytest.approx(0.2)  # a single-row window lasts one step
    assert s.verdict == "late" and s.release_lag_seconds == pytest.approx(0.28)
    assert s.value_at_decision == 0.5  # 107 is closest to 105


def test_summary_value_at_decision_tie_takes_earlier() -> None:
    curve = pl.DataFrame({"frame_idx": [100, 110, 115], "best_value": [0.3, 1.0, 0.9]})
    s = summarize_curve(curve, shot_id="s", game_id=1, decision_frame=105, shot_value=0.5)
    assert s.value_at_decision == 0.3  # 105 is 5 from both 100 and 110
    assert s.verdict == "early"


def test_summary_window_stops_at_first_drop() -> None:
    s = _summarize([1.0, 1.0, 0.5, 1.0, 1.0], 120)  # two plateaus, peak on the first
    assert (s.window_start, s.window_end) == (100, 105)


def test_summary_no_window() -> None:
    s = _summarize([1.0, 1.2], 105)
    assert s.verdict == "no_window" and s.n_rows == 2 and s.advantage_seconds == 0.0
    assert (s.span_start, s.span_end) == (100, 105)
    assert s.peak_frame is None and s.peak_value is None
    assert s.window_start is None and s.window_end is None
    assert s.release_lag_seconds is None and s.value_at_decision is None


def test_summary_empty_curve() -> None:
    empty = pl.DataFrame(schema={"frame_idx": pl.Int64, "best_value": pl.Float64})
    s = summarize_curve(empty, shot_id="s", game_id=1, decision_frame=10, shot_value=0.5)
    assert s.verdict == "no_window" and s.n_rows == 0
    assert s.span_start is None and s.span_end is None


def test_summary_of_fixture_curve(
    built_fixture: Settings, fixture_priors: Priors, trained_fixture_model: ValueModel
) -> None:
    a = Aligner(114243, built_fixture)
    c = _curve(a, SHOT_ID, fixture_priors, trained_fixture_model)
    s = summarize_curve(c, shot_id=SHOT_ID, game_id=114243, decision_frame=3885, shot_value=0.9)
    assert s.n_rows == 16 and (s.span_start, s.span_end) == (3820, 3895)
    assert s.verdict in ("on_time", "late", "early")
    start, peak, end = s.window_start, s.peak_frame, s.window_end
    assert start is not None and peak is not None and end is not None
    assert start <= peak <= end


def _make(verdict: str, advantage: float, lag: float | None, n_rows: int = 6) -> CurveSummary:
    return CurveSummary.model_validate(
        {
            "shot_id": "s",
            "game_id": 1,
            "n_rows": n_rows,
            "span_start": 100,
            "span_end": 125,
            "peak_frame": None,
            "peak_value": None,
            "window_start": None,
            "window_end": None,
            "advantage_seconds": advantage,
            "release_lag_seconds": lag,
            "value_at_decision": None,
            "shot_value": 0.9,
            "verdict": verdict,
        }
    )


def test_headline_es_en() -> None:
    on_time, late = _make("on_time", 0.6, 0.0), _make("late", 0.6, 0.4)
    early, none = _make("early", 0.6, -0.36), _make("no_window", 0.0, None, n_rows=2)
    assert headline(on_time) == "La ventaja duró 0.6 s y el tiro llegó a tiempo"
    assert headline(late) == "La ventaja duró 0.6 s; el tiro llegó 0.4 s tarde"
    assert headline(early) == "El tiro salió 0.4 s antes del pico de ventaja"
    assert headline(none) == "Sin curva suficiente (2 frames)"
    assert headline(on_time, "en") == "The advantage lasted 0.6 s and the shot came on time"
    assert headline(late, "en") == "The advantage lasted 0.6 s; the shot came 0.4 s late"
    assert headline(early, "en") == "The shot went up 0.4 s before the peak of advantage"
    assert headline(none, "en") == "Not enough curve (2 frames)"
