from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from ventaja.cli import app
from ventaja.config import Settings
from ventaja.data import load as load_module
from ventaja.data.duck import connect
from ventaja.data.load import load_decision_options, load_decisions
from ventaja.decision import cost as cost_module
from ventaja.decision.align import Aligner
from ventaja.decision.cost import build_decisions, classify_alternative, decide, viability
from ventaja.errors import DataNotFoundError, VentajaError
from ventaja.value.features import OPTION_FEATURES
from ventaja.value.model import ValueModel
from ventaja.value.priors import Priors

SHOT_ID = "shot-114243-1-0"
TIP_ID = "shot-114243-4-138"
NO_TOUCH_ID = "shot-114243-1-8"  # excluded, but its release frame has tracking


def test_viability_rules() -> None:
    assert viability(10, False, 12.0) == 1.0
    assert viability(10, True, 12.0) == 0.4
    assert viability(45, False, 12.0) == pytest.approx(0.5)
    assert viability(10, False, 1.5) == 0.0
    assert viability(10, False, None) == 1.0
    assert viability(70, False, 12.0) == 0.0
    assert viability(45, True, 12.0) == pytest.approx(0.2)


@pytest.mark.parametrize(
    ("zone", "moving", "def_dist", "expected"),
    [
        ("restricted_area", 5.0, 2.0, "rim_cut"),
        ("paint_non_ra", 4.0, 2.0, "rim_cut"),
        ("corner_3", 0.0, 7.0, "open_corner"),
        ("corner_3", 0.0, 3.0, "other"),
        ("paint_non_ra", 1.0, 2.0, "post"),
        ("above_break_3", 0.0, 6.0, "extra_pass"),
        ("mid_range", -2.0, 8.0, "extra_pass"),
        ("mid_range", 0.0, 3.0, "other"),
        ("restricted_area", 1.0, 9.0, "other"),
    ],
)
def test_classify_alternative_cases(
    zone: str, moving: float, def_dist: float, expected: str
) -> None:
    row = {"zone": zone, "moving_to_hoop": moving, "nearest_def_dist": def_dist}
    assert classify_alternative(row) == expected


def test_decide_on_fixture_shot(
    built_fixture: Settings, fixture_priors: Priors, trained_fixture_model: ValueModel
) -> None:
    d = decide(Aligner(114243, built_fixture), SHOT_ID, fixture_priors, trained_fixture_model)
    assert d is not None and len(d.options) == 5 and d.cost >= 0
    assert d.good_read == (d.best_alt_value is None or d.best_alt_value <= d.shot_value)
    assert (d.decision_frame, d.release_frame, d.rule) == (3885, 3895, "gather")
    assert d.shooter_id == 35028 and d.game_id == 114243
    assert 0.0 <= d.confidence <= 1.0
    shot, *passes = d.options
    assert shot.option_type == "shot" and shot.player_id == 35028
    assert shot.viability == 1.0 and shot.alternative_type is None
    assert shot.value == pytest.approx(shot.proba * shot.points)
    assert d.shot_value == pytest.approx(shot.value)
    adjusted = [o.adjusted_value for o in passes]
    assert adjusted == sorted(adjusted, reverse=True)
    best = passes[0]
    assert (d.best_alt_player_id, d.best_alt_type) == (best.player_id, best.alternative_type)
    assert d.best_alt_value == pytest.approx(best.adjusted_value)
    assert d.cost == pytest.approx(max(0.0, best.adjusted_value - shot.value))
    for o in passes:
        assert o.option_type == "pass" and o.alternative_type is not None
        assert o.adjusted_value == pytest.approx(o.value * o.viability)
    assert set(shot.features) <= set(OPTION_FEATURES)


class _FixedModel:
    """Stub model: the shot row scores with 0.2, every pass row with 0.9."""

    def predict_proba(self, df: pl.DataFrame) -> pl.Series:
        return pl.Series(
            "proba", [0.2 if t == "shot" else 0.9 for t in df["option_type"]], dtype=pl.Float64
        )


def test_decide_cost_arithmetic(built_fixture: Settings, fixture_priors: Priors) -> None:
    model: ValueModel = _FixedModel()  # type: ignore[assignment]
    d = decide(Aligner(114243, built_fixture), SHOT_ID, fixture_priors, model)
    assert d is not None
    shot, best = d.options[0], d.options[1]
    assert d.shot_value == pytest.approx(0.2 * shot.points)
    assert best.adjusted_value == pytest.approx(0.9 * best.points * best.viability)
    assert d.cost == pytest.approx(max(0.0, best.adjusted_value - d.shot_value))
    assert d.good_read is (best.adjusted_value <= d.shot_value)


def test_decide_without_viable_pass_names_no_alternative(
    built_fixture: Settings, fixture_priors: Priors, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = Aligner(114243, built_fixture)
    real = a.snapshot_for_shot(SHOT_ID, decision=True)
    late = real.model_copy(update={"shot_clock": 1.5})  # under SHOT_CLOCK_MIN_PASS
    monkeypatch.setattr(a, "snapshot_for_shot", lambda *_a, **_k: late)
    model: ValueModel = _FixedModel()  # type: ignore[assignment]
    d = decide(a, SHOT_ID, fixture_priors, model)
    assert d is not None
    assert all(o.viability == 0.0 for o in d.options[1:])
    assert d.best_alt_player_id is None and d.best_alt_type is None
    assert d.best_alt_value is None and d.cost == 0.0 and d.good_read is None
    assert len(d.options) == 5


def test_decision_summary_counts_good_read_over_non_null() -> None:
    from ventaja.cli import _decision_summary

    df = pl.DataFrame(
        {
            "rule": ["gather", "gather", "gather", "excluded"],
            "reason": [None, None, None, "tip"],
            "cost": [0.0, 0.2, 0.0, None],
            "good_read": [True, False, None, None],
        }
    )
    summary = _decision_summary(df)
    assert "good_read 50.0%" in summary and "no viable pass 1" in summary


def test_decide_excluded_returns_none(
    built_fixture: Settings,
    fixture_priors: Priors,
    trained_fixture_model: ValueModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = Aligner(114243, built_fixture)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("snapshot read for an excluded shot")

    monkeypatch.setattr(a, "snapshot_for_shot", boom)
    monkeypatch.setattr(a, "snapshot", boom)
    assert decide(a, TIP_ID, fixture_priors, trained_fixture_model) is None
    assert decide(a, NO_TOUCH_ID, fixture_priors, trained_fixture_model) is None


def test_build_decisions_has_one_row_per_shot(
    built_fixture: Settings, trained_fixture_model: ValueModel
) -> None:
    path = build_decisions(114243, built_fixture, model=trained_fixture_model)
    assert path == built_fixture.decisions_parquet(114243)
    df = pl.read_parquet(path)
    assert df.height == 159
    excluded = df.filter(pl.col("rule") == "excluded")
    assert excluded["reason"].is_not_null().all()
    assert excluded.height == 159 - 17
    assert excluded["cost"].is_null().all() and excluded["decision_frame"].is_null().all()
    assert excluded["release_frame"].is_not_null().all()
    assert excluded["shooter_id"].is_not_null().all()
    valid = df.filter(pl.col("rule") != "excluded")
    assert valid["reason"].is_null().all() and valid["cost"].is_not_null().all()
    assert "options" not in df.columns
    assert df.filter(pl.col("shot_id") == SHOT_ID)["release_frame"].item() == 3895
    counts = dict(excluded.group_by("reason").len().iter_rows())
    assert counts == {"no_tracking": 124, "no_touch": 14, "no_type": 3, "tip": 1}


def test_build_decisions_writes_options(
    built_fixture: Settings, trained_fixture_model: ValueModel
) -> None:
    build_decisions(114243, built_fixture, model=trained_fixture_model)
    path = built_fixture.decisions_options_parquet(114243)
    assert path == built_fixture.build_dir / "decisions" / "114243.options.parquet"
    opts = pl.read_parquet(path)
    assert opts.height == 17 * 5
    assert opts.group_by("shot_id").len()["len"].to_list() == [5] * 17
    for col in ("shot_id", "game_id", "player_id", "adjusted_value", *OPTION_FEATURES):
        assert col in opts.columns
    assert opts.schema["shot_clock"] == pl.Float64
    assert opts.filter(pl.col("option_type") == "shot")["viability"].to_list() == [1.0] * 17


def test_build_decisions_records_shooter_off_court(
    built_fixture: Settings,
    trained_fixture_model: ValueModel,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real = cost_module.option_rows

    def flaky(snapshot, shooter_id, priors, **kwargs):  # type: ignore[no-untyped-def]
        if snapshot.frame_idx == 3885:
            raise VentajaError("shooter is not on court")
        return real(snapshot, shooter_id, priors, **kwargs)

    monkeypatch.setattr(cost_module, "option_rows", flaky)
    settings = Settings(data_dir=built_fixture.data_dir, build_dir=tmp_path / "b")
    for sub in ("events", "tracking", "meta", "aggregates"):
        (settings.build_dir / sub).parent.mkdir(parents=True, exist_ok=True)
        (settings.build_dir / sub).symlink_to(built_fixture.build_dir / sub)
    df = pl.read_parquet(build_decisions(114243, settings, model=trained_fixture_model))
    row = df.filter(pl.col("shot_id") == SHOT_ID).row(0, named=True)
    assert (row["rule"], row["reason"]) == ("excluded", "shooter_off_court")
    assert df.filter(pl.col("rule") != "excluded").height == 16


def test_load_decisions_fallback_to_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path, build_dir=tmp_path / "build")
    artifacts = tmp_path / "artifacts"
    monkeypatch.setattr(load_module, "ARTIFACTS_DIR", artifacts)
    with pytest.raises(DataNotFoundError, match="ventaja decisions build"):
        load_decisions(1, settings)
    with pytest.raises(DataNotFoundError, match="ventaja decisions build"):
        load_decision_options(1, settings)
    (artifacts / "decisions").mkdir(parents=True)
    pl.DataFrame({"shot_id": ["packaged"]}).write_parquet(artifacts / "decisions" / "1.parquet")
    pl.DataFrame({"shot_id": ["opt"]}).write_parquet(artifacts / "decisions" / "1.options.parquet")
    assert load_decisions(1, settings)["shot_id"].to_list() == ["packaged"]
    assert load_decision_options(1, settings)["shot_id"].to_list() == ["opt"]
    settings.decisions_parquet(1).parent.mkdir(parents=True)
    pl.DataFrame({"shot_id": ["built"]}).write_parquet(settings.decisions_parquet(1))
    assert load_decisions(1, settings)["shot_id"].to_list() == ["built"]


def test_built_decisions_never_mix_with_packaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path, build_dir=tmp_path / "build")
    artifacts = tmp_path / "artifacts" / "decisions"
    artifacts.mkdir(parents=True)
    monkeypatch.setattr(load_module, "ARTIFACTS_DIR", artifacts.parent)
    for g in (1, 2):
        pl.DataFrame({"shot_id": [f"packaged-{g}"]}).write_parquet(artifacts / f"{g}.parquet")
        pl.DataFrame({"shot_id": [f"opt-{g}"]}).write_parquet(artifacts / f"{g}.options.parquet")
    assert load_module.decisions_dir(settings) == artifacts
    assert load_decisions(2, settings)["shot_id"].to_list() == ["packaged-2"]
    # Building one game switches every reader to the build dir, with no per-file fallback.
    built = settings.build_dir / "decisions"
    built.mkdir(parents=True)
    pl.DataFrame({"shot_id": ["built-1"]}).write_parquet(built / "1.parquet")
    pl.DataFrame({"shot_id": ["opt-1"]}).write_parquet(built / "1.options.parquet")
    assert load_module.decisions_dir(settings) == built
    assert load_decisions(1, settings)["shot_id"].to_list() == ["built-1"]
    with pytest.raises(DataNotFoundError, match="ventaja decisions build --game 2"):
        load_decisions(2, settings)
    with pytest.raises(DataNotFoundError, match="ventaja decisions build --game 2"):
        load_decision_options(2, settings)
    decisions, options = load_module.decision_files(settings)
    assert decisions == [built / "1.parquet"] and options == [built / "1.options.parquet"]
    assert connect(settings).sql("select shot_id from decisions").fetchall() == [("built-1",)]


def test_options_file_alone_does_not_select_build_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path, build_dir=tmp_path / "build")
    monkeypatch.setattr(load_module, "ARTIFACTS_DIR", tmp_path / "artifacts")
    built = settings.build_dir / "decisions"
    built.mkdir(parents=True)
    pl.DataFrame({"shot_id": ["o"]}).write_parquet(built / "1.options.parquet")
    assert load_module.decisions_dir(settings) == tmp_path / "artifacts" / "decisions"


def test_build_decisions_out_dir(
    built_fixture: Settings,
    trained_fixture_model: ValueModel,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    out = tmp_path / "packaged"
    path = build_decisions(114243, built_fixture, model=trained_fixture_model, out_dir=out)
    assert path == out / "114243.parquet" and (out / "114243.options.parquet").exists()
    _env(monkeypatch, built_fixture)
    model_path = tmp_path / "m.json"
    trained_fixture_model.save(model_path)
    cli_out = tmp_path / "cli"
    result = CliRunner().invoke(
        app,
        ["decisions", "build", "--game", "114243", "--model", str(model_path)]
        + ["--out", str(cli_out)],
    )
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in cli_out.iterdir()) == ["114243.options.parquet", "114243.parquet"]


def test_duck_decision_views_and_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = tmp_path / "artifacts" / "decisions"
    artifacts.mkdir(parents=True)
    monkeypatch.setattr(load_module, "ARTIFACTS_DIR", artifacts.parent)
    pl.DataFrame({"shot_id": ["a", "b"]}).write_parquet(artifacts / "1.parquet")
    pl.DataFrame({"shot_id": ["a"] * 5}).write_parquet(artifacts / "1.options.parquet")
    settings = Settings(data_dir=tmp_path, build_dir=tmp_path / "build")
    con = connect(settings)
    assert con.sql("select count(*) from decisions").fetchall()[0][0] == 2
    assert con.sql("select count(*) from decision_options").fetchall()[0][0] == 5
    built = settings.decisions_parquet(2)
    built.parent.mkdir(parents=True)
    pl.DataFrame({"shot_id": ["c"]}).write_parquet(built)
    pl.DataFrame({"shot_id": ["c"] * 5}).write_parquet(settings.decisions_options_parquet(2))
    con = connect(settings)
    assert con.sql("select count(*) from decisions").fetchall()[0][0] == 1
    assert con.sql("select count(*) from decision_options").fetchall()[0][0] == 5


def _env(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(settings.build_dir))


def test_cli_decisions_build_and_show(
    built_fixture: Settings,
    trained_fixture_model: ValueModel,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _env(monkeypatch, built_fixture)
    model_path = tmp_path / "m.json"
    trained_fixture_model.save(model_path)
    runner = CliRunner()
    built = runner.invoke(
        app, ["decisions", "build", "--game", "114243", "--model", str(model_path)]
    )
    assert built.exit_code == 0, built.output
    assert "valid 17" in built.output and "no_tracking 124" in built.output
    assert "good_read" in built.output
    shown = runner.invoke(app, ["decisions", "show", SHOT_ID])
    assert shown.exit_code == 0, shown.output
    assert "frame 3885" in shown.output and "gather" in shown.output
    lines = shown.output.splitlines()
    assert sum(line.startswith("*") for line in lines) == 1
    assert sum(line.startswith(">") for line in lines) == 1
    excluded = runner.invoke(app, ["decisions", "show", TIP_ID])
    assert excluded.exit_code == 1 and "tip" in excluded.output


def test_cli_decisions_build_requires_selection() -> None:
    result = CliRunner().invoke(app, ["decisions", "build"])
    assert result.exit_code == 2
