from pathlib import Path
from typing import Any, get_args

import polars as pl
import pytest
from typer.testing import CliRunner

from ventaja.cli import app
from ventaja.config import Settings
from ventaja.data import load as load_module
from ventaja.data.duck import connect
from ventaja.data.load import load_curve_summaries, load_curves, load_decisions
from ventaja.decision import curve as curve_module
from ventaja.decision.align import Aligner
from ventaja.decision.curve import (
    CURVE_SCHEMA,
    SUMMARY_SCHEMA,
    build_curves,
    headline,
    possession_curve,
    summarize_curve,
)
from ventaja.errors import DataNotFoundError
from ventaja.model.decision import CurveSummary, Verdict
from ventaja.value.model import ValueModel
from ventaja.value.priors import Priors

SHOT_ID = "shot-114243-1-0"  # release 3895, decision 3885, handler 35028; tracking 3820-3895
FLIGHT_SHOT_ID = "shot-114243-1-1"  # release 4157; ball in flight at sampled frames 4107, 4112
TIP_ID = "shot-114243-4-138"
NO_TOUCH_ID = "shot-114243-1-8"
NO_TYPE_ID = "shot-114243-1-2"


def _curve(a: Aligner, shot_id: str, priors: Priors, model: ValueModel) -> pl.DataFrame:
    result = possession_curve(a, shot_id, priors, model)
    assert result is not None
    return result.curve


def test_curve_rows_and_release_present(
    built_fixture: Settings, fixture_priors: Priors, trained_fixture_model: ValueModel
) -> None:
    a = Aligner(114243, built_fixture)
    result = possession_curve(a, SHOT_ID, fixture_priors, trained_fixture_model)
    assert result is not None and result.skipped_off_court == 0
    c = result.curve
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
    assert (passes["best_pass_value"] == passes["best_value"]).all()
    assert (c["best_pass_value"] <= c["best_value"]).all()
    assert c.filter(pl.col("n_viable") == 0)["best_pass_value"].null_count() == (
        c.filter(pl.col("n_viable") == 0).height
    )


def test_curve_best_pass_value_null_without_viable_pass(
    built_fixture: Settings,
    fixture_priors: Priors,
    trained_fixture_model: ValueModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(curve_module, "viability", lambda *args: 0.0)
    a = Aligner(114243, built_fixture)
    c = _curve(a, SHOT_ID, fixture_priors, trained_fixture_model)
    assert c.height == 16 and (c["n_viable"] == 0).all()
    assert c["best_pass_value"].null_count() == c.height
    assert (c["best_option_type"] == "shot").all()
    s = summarize_curve(
        c, shot_id=SHOT_ID, game_id=114243, decision_frame=3885, shot_value=0.0, shooter_id=35028
    )
    assert s.verdict == "none"  # the handler's own shot never counts as advantage


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
    result = possession_curve(a, SHOT_ID, fixture_priors, trained_fixture_model)
    assert result is not None and result.skipped_off_court == 4  # 3835-3850
    frames = result.curve["frame_idx"].to_list()
    assert frames == [3820, 3825, 3830, *range(3855, 3896, 5)]


def _summary_curve(
    passes: list[float | None],
    handlers: list[int] | None = None,
    best: list[float] | None = None,
) -> pl.DataFrame:
    n = len(passes)
    return pl.DataFrame(
        {
            "frame_idx": [100 + 5 * i for i in range(n)],
            "handler_id": handlers or [8] * n,
            "best_value": best or [p if p is not None else 0.5 for p in passes],
            "best_pass_value": passes,
        },
        schema_overrides={"best_pass_value": pl.Float64},
    )


def _summarize(
    passes: list[float | None],
    decision_frame: int,
    *,
    handlers: list[int] | None = None,
    best: list[float] | None = None,
    shooter_id: int = 8,
) -> CurveSummary:
    return summarize_curve(
        _summary_curve(passes, handlers, best),
        shot_id="shot-1-1-0",
        game_id=1,
        decision_frame=decision_frame,
        shot_value=0.8,
        shooter_id=shooter_id,
    )


# frames:    100  105  110  115  120  125   (advantage: best_pass_value >= 0.8 + 0.10)
LATE: list[float | None] = [0.5, 1.2, 1.3, 1.0, 0.6, 0.7]


def test_summary_late() -> None:
    s = _summarize(LATE, 125)
    assert (s.shot_id, s.game_id, s.n_rows, s.span_start, s.span_end) == (
        "shot-1-1-0",
        1,
        6,
        100,
        125,
    )
    assert (s.window_start, s.window_end) == (105, 115)  # 120 drops out of the run
    assert (s.window_handler_id, s.window_peak_value) == (8, 1.3)
    assert s.advantage_seconds == pytest.approx(0.6)
    assert s.verdict == "late" and s.release_lag_seconds == pytest.approx(0.4)
    assert (s.peak_frame, s.peak_value) == (110, 1.3)
    assert s.value_at_decision == 0.7 and s.shot_value == 0.8


def test_summary_during() -> None:
    s = _summarize(LATE, 112)
    assert s.verdict == "during" and s.release_lag_seconds == 0.0
    assert (s.window_start, s.window_end) == (105, 115)
    assert s.value_at_decision == 1.3  # 112 is closest to 110


def test_summary_during_at_run_start() -> None:
    s = _summarize(LATE, 105)
    assert s.verdict == "during" and (s.window_start, s.window_end) == (105, 115)


def test_summary_none_when_advantage_only_after_decision() -> None:
    s = _summarize(LATE, 101)
    assert s.verdict == "none" and s.release_lag_seconds is None
    assert s.advantage_seconds == 0.0
    assert s.window_start is None and s.window_end is None
    assert s.window_handler_id is None and s.window_peak_value is None
    assert (s.peak_frame, s.peak_value) == (110, 1.3)  # global descriptors stay
    assert s.value_at_decision == 0.5


def test_summary_none_when_nothing_beats_the_shot() -> None:
    s = _summarize([0.85, 0.89, 0.7, 0.6], 115)  # 0.89 < 0.8 + 0.10
    assert s.verdict == "none" and s.advantage_seconds == 0.0


def test_summary_own_shot_is_not_advantage() -> None:
    # the handler's own hypothetical shot (best_value 1.5) beats the threshold; no pass does
    s = _summarize([0.6, 0.7, None, 0.6], 115, best=[1.5, 1.5, 1.5, 1.5])
    assert s.verdict == "none" and s.window_start is None
    assert (s.peak_frame, s.peak_value) == (100, 1.5)  # the peak still reads best_value


def test_summary_last_run_before_decision_counts() -> None:
    # runs 100-105 and 115-120; a third run at 130 starts after the decision frame
    s = _summarize([1.5, 1.0, 0.5, 1.1, 0.95, 0.5, 2.0], 127)
    assert (s.window_start, s.window_end) == (115, 120)
    assert (s.window_handler_id, s.window_peak_value) == (8, 1.1)
    assert s.advantage_seconds == pytest.approx(0.4)
    assert s.verdict == "late" and s.release_lag_seconds == pytest.approx(0.28)
    assert (s.peak_frame, s.peak_value) == (130, 2.0)


def test_summary_runs_split_on_handler_change() -> None:
    s = _summarize([1.0, 1.4, 1.1, 1.2, 0.5], 112, handlers=[5, 5, 6, 6, 6])
    assert (s.window_start, s.window_end) == (110, 115)  # handler 6's run, not 100-115
    assert (s.window_handler_id, s.window_peak_value) == (6, 1.2)
    assert s.verdict == "during" and s.advantage_seconds == pytest.approx(0.4)
    t = _summarize([1.0, 1.4, 1.1, 1.2, 0.5], 107, handlers=[5, 5, 6, 6, 6])
    assert (t.window_start, t.window_end, t.window_handler_id) == (100, 105, 5)
    assert t.verdict == "late" and t.release_lag_seconds == pytest.approx(0.08)
    assert t.window_peak_value == 1.4


def test_summary_null_pass_value_breaks_run() -> None:
    s = _summarize([1.0, None, 1.2, 0.5], 120)
    assert (s.window_start, s.window_end) == (110, 110)


def test_summary_single_row_run_and_peak_tie() -> None:
    s = _summarize([1.0, 0.5, 1.0, 0.5], 107)
    assert (s.window_start, s.window_end) == (100, 100)
    assert s.advantage_seconds == pytest.approx(0.2)  # a single-row run lasts one step
    assert s.verdict == "late" and s.release_lag_seconds == pytest.approx(0.28)
    assert s.peak_frame == 100  # global peak tie takes the earliest row
    assert s.value_at_decision == 0.5  # 107 is closest to 105


def test_summary_value_at_decision_tie_takes_earlier() -> None:
    curve = pl.DataFrame(
        {
            "frame_idx": [100, 110, 115],
            "handler_id": [1, 1, 1],
            "best_value": [0.3, 1.0, 0.9],
            "best_pass_value": [0.3, 1.0, 0.9],
        }
    )
    s = summarize_curve(
        curve, shot_id="s", game_id=1, decision_frame=105, shot_value=0.5, shooter_id=1
    )
    assert s.value_at_decision == 0.3  # 105 is 5 from both 100 and 110
    assert s.verdict == "none"  # the only run starts at 110, after the decision


def test_held_to_decision() -> None:
    # late, and the shooter (8) holds the ball from the window's end (115) to the decision
    held = _summarize(LATE, 125)
    assert held.verdict == "late" and held.held_to_decision is True
    # late, but another handler has the ball between the window and the decision frame
    passed = _summarize(LATE, 125, handlers=[8, 8, 8, 8, 6, 8])
    assert passed.verdict == "late" and passed.held_to_decision is False
    # late, the window was a teammate's (5) and the shooter (8) holds it afterwards
    earlier = _summarize(LATE, 125, handlers=[5, 5, 5, 5, 8, 8])
    assert earlier.verdict == "late" and earlier.held_to_decision is False
    # during, none and no_window are never held
    assert _summarize(LATE, 112).held_to_decision is False
    assert _summarize(LATE, 101).held_to_decision is False
    assert _summarize([1.0, 1.2], 105).held_to_decision is False


def test_summary_no_window() -> None:
    s = _summarize([1.0, 1.2], 105)
    assert s.verdict == "no_window" and s.n_rows == 2 and s.advantage_seconds == 0.0
    assert (s.span_start, s.span_end) == (100, 105)
    assert s.peak_frame is None and s.peak_value is None
    assert s.window_start is None and s.window_end is None
    assert s.window_handler_id is None and s.window_peak_value is None
    assert s.release_lag_seconds is None and s.value_at_decision is None


def test_summary_empty_curve() -> None:
    empty = pl.DataFrame(schema={c: CURVE_SCHEMA[c] for c in CURVE_SCHEMA})
    s = summarize_curve(
        empty, shot_id="s", game_id=1, decision_frame=10, shot_value=0.5, shooter_id=1
    )
    assert s.verdict == "no_window" and s.n_rows == 0
    assert s.span_start is None and s.span_end is None


def test_summary_of_fixture_curve(
    built_fixture: Settings, fixture_priors: Priors, trained_fixture_model: ValueModel
) -> None:
    a = Aligner(114243, built_fixture)
    c = _curve(a, SHOT_ID, fixture_priors, trained_fixture_model)
    s = summarize_curve(
        c, shot_id=SHOT_ID, game_id=114243, decision_frame=3885, shot_value=0.0, shooter_id=35028
    )
    assert s.n_rows == 16 and (s.span_start, s.span_end) == (3820, 3895)
    # every viable pass beats a zero-value shot; runs split at 35028 -> 28247 -> 35028
    assert s.verdict == "during" and s.window_handler_id == 35028
    assert (s.window_start, s.window_end) == (3855, 3895)
    run = c.filter(pl.col("frame_idx") >= 3855)
    assert s.window_peak_value == run["best_pass_value"].max()


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
            "window_handler_id": None,
            "window_peak_value": None if verdict != "during" else 1.234,
            "advantage_seconds": advantage,
            "release_lag_seconds": lag,
            "value_at_decision": None,
            "shot_value": 0.9,
            "verdict": verdict,
            "held_to_decision": False,
        }
    )


def test_headline_es_en() -> None:
    late, during = _make("late", 0.6, 0.36), _make("during", 0.8, 0.0)
    none, short = _make("none", 0.0, None), _make("no_window", 0.0, None, n_rows=2)
    assert headline(late) == "La ventaja duró 0.6 s y se esfumó 0.4 s antes del tiro"
    assert headline(during) == (
        "Había una opción mejor en el instante del tiro (+0.33 pts, abierta 0.8 s)"
    )
    assert headline(none) == "No hubo mejor opción que el tiro en la posesión"
    assert headline(short) == "Sin curva suficiente (2 frames)"
    assert headline(late, "en") == "The advantage lasted 0.6 s and vanished 0.4 s before the shot"
    assert headline(during, "en") == (
        "A better option was open at the shot (+0.33 pts, open for 0.8 s)"
    )
    assert headline(none, "en") == "Nothing beat the shot during the possession"
    assert headline(short, "en") == "Not enough curve (2 frames)"


# --- artifacts, loaders, SQL views and CLI -------------------------------------------------


def test_build_curves_fixture(fixture_curves_built: Settings) -> None:
    settings = fixture_curves_built
    curves = pl.read_parquet(settings.curves_parquet(114243))
    summaries = pl.read_parquet(settings.curve_summaries_parquet(114243))
    assert settings.curves_parquet(114243) == settings.build_dir / "curves" / "114243.parquet"
    assert settings.curve_summaries_parquet(114243) == (
        settings.build_dir / "curves" / "114243.summary.parquet"
    )
    assert dict(curves.schema) == CURVE_SCHEMA
    assert dict(summaries.schema) == SUMMARY_SCHEMA
    valued = load_decisions(114243, settings).filter(pl.col("rule") != "excluded")
    assert valued.height == 17 and summaries.height == 17
    assert sorted(summaries["shot_id"]) == sorted(valued["shot_id"])
    per_shot = curves.group_by("shot_id").len()
    assert per_shot.height == 17 and per_shot["len"].min() >= 1  # type: ignore[operator]
    assert set(summaries["verdict"]) <= set(get_args(Verdict))
    assert summaries["headline_es"].null_count() == 0
    assert summaries["headline_en"].null_count() == 0
    assert (summaries["skipped_off_court"] >= 0).all()
    assert (summaries["advantage_seconds"] >= 0).all()
    # the summary's shot_value is the real shot's, from the decisions table
    joined = summaries.join(valued, on="shot_id", suffix="_d")
    assert (joined["shot_value"] - joined["shot_value_d"]).abs().max() == 0.0  # type: ignore[operator]
    row = summaries.filter(pl.col("shot_id") == SHOT_ID).row(0, named=True)
    summary = CurveSummary.model_validate({k: row[k] for k in CurveSummary.model_fields})
    assert row["headline_es"] == headline(summary, "es")
    assert row["headline_en"] == headline(summary, "en")


def test_build_curves_out_dir_and_loaders(
    fixture_curves_built: Settings,
    trained_fixture_model: ValueModel,
    fixture_priors: Priors,
    tmp_path: Path,
) -> None:
    out = tmp_path / "packaged"
    paths = build_curves(
        114243,
        fixture_curves_built,
        model=trained_fixture_model,
        priors=fixture_priors,
        out_dir=out,
    )
    assert paths == (out / "114243.parquet", out / "114243.summary.parquet")
    assert sorted(p.name for p in out.iterdir()) == ["114243.parquet", "114243.summary.parquet"]
    assert load_module.artifact_dir("curves", fixture_curves_built) == (
        fixture_curves_built.build_dir / "curves"
    )
    assert load_curves(114243, fixture_curves_built).equals(pl.read_parquet(paths[0]))
    assert load_curve_summaries(114243, fixture_curves_built).equals(pl.read_parquet(paths[1]))
    con = connect(fixture_curves_built)
    assert con.sql("select count(distinct shot_id) from curves").fetchall()[0][0] == 17
    assert con.sql("select count(*) from curve_summaries").fetchall()[0][0] == 17


def test_load_curves_falls_back_to_artifacts(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, build_dir=tmp_path / "build")
    assert load_module.artifact_dir("curves", settings) == load_module.ARTIFACTS_DIR / "curves"
    assert load_module.artifact_dir("decisions", settings) == (
        load_module.ARTIFACTS_DIR / "decisions"
    )
    summaries = load_curve_summaries(191313, settings)
    curves = load_curves(191313, settings)
    assert summaries.height > 0 and set(summaries["game_id"]) == {191313}
    assert set(curves["shot_id"]) <= set(summaries["shot_id"])
    curve_paths, summary_paths = load_module.curve_files(settings)
    assert len(curve_paths) == 10 and len(summary_paths) == 10
    assert not any(p.name.endswith(".summary.parquet") for p in curve_paths)


def test_no_mixing_curves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = tmp_path / "artifacts"
    (artifacts / "curves").mkdir(parents=True)
    monkeypatch.setattr(load_module, "ARTIFACTS_DIR", artifacts)
    pl.DataFrame({"shot_id": ["p2"]}).write_parquet(artifacts / "curves" / "2.parquet")
    pl.DataFrame({"shot_id": ["p2"]}).write_parquet(artifacts / "curves" / "2.summary.parquet")
    settings = Settings(data_dir=tmp_path, build_dir=tmp_path / "build")
    built = settings.build_dir / "curves"
    built.mkdir(parents=True)
    # a summary file alone does not select the build dir
    pl.DataFrame({"shot_id": ["s1"]}).write_parquet(built / "1.summary.parquet")
    assert load_module.artifact_dir("curves", settings) == artifacts / "curves"
    assert load_curves(2, settings)["shot_id"].to_list() == ["p2"]
    pl.DataFrame({"shot_id": ["b1"]}).write_parquet(built / "1.parquet")
    assert load_module.artifact_dir("curves", settings) == built
    assert load_curves(1, settings)["shot_id"].to_list() == ["b1"]
    with pytest.raises(DataNotFoundError, match="ventaja curves build --game 2"):
        load_curves(2, settings)
    with pytest.raises(DataNotFoundError, match="ventaja curves build --game 2"):
        load_curve_summaries(2, settings)
    assert load_module.curve_files(settings) == (
        [built / "1.parquet"],
        [built / "1.summary.parquet"],
    )
    con = connect(settings)
    assert con.sql("select shot_id from curves").fetchall() == [("b1",)]
    assert con.sql("select shot_id from curve_summaries").fetchall() == [("s1",)]


def _env(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(settings.build_dir))


def test_curves_cli_show(fixture_curves_built: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, fixture_curves_built)
    row = (
        load_curve_summaries(114243, fixture_curves_built)
        .filter(pl.col("shot_id") == SHOT_ID)
        .row(0, named=True)
    )
    result = CliRunner().invoke(app, ["curves", "show", SHOT_ID])
    assert result.exit_code == 0, result.output
    assert row["headline_es"] in result.output
    assert f"verdict {row['verdict']}" in result.output
    assert "t_to_release" in result.output and "best_pass_value" in result.output
    n_rows = load_curves(114243, fixture_curves_built).filter(pl.col("shot_id") == SHOT_ID).height
    assert sum(line.lstrip().startswith("-") for line in result.output.splitlines()) >= n_rows - 1
    missing = CliRunner().invoke(app, ["curves", "show", TIP_ID])
    assert missing.exit_code == 1 and "not found" in missing.output
    bad = CliRunner().invoke(app, ["curves", "show", "nope"])
    assert bad.exit_code == 1


def test_curves_cli_build(
    fixture_curves_built: Settings,
    trained_fixture_model: ValueModel,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _env(monkeypatch, fixture_curves_built)
    model_path = tmp_path / "m.json"
    trained_fixture_model.save(model_path)
    out = tmp_path / "cli"
    result = CliRunner().invoke(
        app,
        ["curves", "build", "--game", "114243", "--model", str(model_path), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert "game 114243: 17 shots, 17 curves" in result.output
    assert "late" in result.output and "no_window" in result.output
    assert "median advantage" in result.output
    assert sorted(p.name for p in out.iterdir()) == ["114243.parquet", "114243.summary.parquet"]
    assert CliRunner().invoke(app, ["curves", "build"]).exit_code == 2
