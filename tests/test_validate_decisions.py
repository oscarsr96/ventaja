"""Automatic face-validity checks of the decisions tables (spec 5.5)."""

from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from ventaja.cli import app
from ventaja.config import Settings
from ventaja.data.load import load_decision_options, load_decisions
from ventaja.decision.cost import build_decisions
from ventaja.validate.decisions import checks
from ventaja.value.features import OPTION_FEATURES
from ventaja.value.model import ValueModel

runner = CliRunner()


class _StubModel:
    """Minimal stand-in: probability grows with ``prior_zone`` (or shrinks if ``sign`` < 0)."""

    def __init__(self, sign: float = 1.0) -> None:
        self.sign = sign

    def predict_proba(self, df: pl.DataFrame) -> pl.Series:
        return (0.5 + self.sign * df["prior_zone"]).alias("proba")


def _decisions(rows: list[tuple[str, float | None, float | None, str | None]]) -> pl.DataFrame:
    """Rows of (rule, shot_clock, cost, reason)."""
    return pl.DataFrame(
        {
            "rule": [r[0] for r in rows],
            "shot_clock": [r[1] for r in rows],
            "cost": [r[2] for r in rows],
            "reason": [r[3] for r in rows],
        },
        schema={
            "rule": pl.String,
            "shot_clock": pl.Float64,
            "cost": pl.Float64,
            "reason": pl.String,
        },
    )


def _options(rows: list[tuple[str, float, float]]) -> pl.DataFrame:
    """Rows of (zone, nearest_def_dist, value) plus a shot row carrying every feature."""
    n = len(rows)
    data: dict[str, list[object]] = {
        "option_type": ["shot"] * n,
        "zone": [r[0] for r in rows],
        "nearest_def_dist": [r[1] for r in rows],
        "value": [r[2] for r in rows],
    }
    for f in OPTION_FEATURES:
        data.setdefault(f, [0.35] * n)
    return pl.DataFrame(data)


def _by_name(result: list[tuple[str, bool, str]], name: str) -> tuple[bool, str]:
    for n, ok, detail in result:
        if n == name:
            return ok, detail
    raise AssertionError(name)


GOOD_OPTS = _options([("restricted_area", 8.0, 1.3), ("above_break_3", 1.5, 0.7)])
NO_DEC = _decisions([("early", 20.0, 0.1, None)])


def test_cost_falls_with_clock_pass_and_fail() -> None:
    good = _decisions([("a", 20.0, 0.30, None), ("a", 10.0, 0.20, None), ("a", 3.0, 0.10, None)])
    ok, detail = _by_name(checks(good, GOOD_OPTS, _StubModel()), "cost_falls_with_clock")
    assert ok
    assert "0.300" in detail and "0.100" in detail
    bad = _decisions([("a", 20.0, 0.10, None), ("a", 10.0, 0.20, None), ("a", 3.0, 0.30, None)])
    assert not _by_name(checks(bad, GOOD_OPTS, _StubModel()), "cost_falls_with_clock")[0]


def test_cost_check_ignores_excluded_and_null_clock_and_flags_empty_bucket() -> None:
    dec = _decisions(
        [("a", 20.0, 0.3, None), ("a", 10.0, 0.2, None), ("excluded", 3.0, None, "tip")]
    )
    ok, detail = _by_name(checks(dec, GOOD_OPTS, _StubModel()), "cost_falls_with_clock")
    assert not ok
    assert "6-0" in detail and "empty" in detail
    with_null = _decisions([("a", None, 0.3, None)])
    assert not _by_name(checks(with_null, GOOD_OPTS, _StubModel()), "cost_falls_with_clock")[0]


def test_rim_open_beats_contested_three_pass_and_fail() -> None:
    ok, detail = _by_name(checks(NO_DEC, GOOD_OPTS, _StubModel()), "rim_open_beats_contested_three")
    assert ok and "1.300" in detail and "0.700" in detail
    bad = _options([("restricted_area", 8.0, 0.5), ("above_break_3", 1.5, 0.9)])
    assert not _by_name(checks(NO_DEC, bad, _StubModel()), "rim_open_beats_contested_three")[0]


def test_rim_check_fails_on_empty_group() -> None:
    only_rim = _options([("restricted_area", 8.0, 1.3), ("restricted_area", 2.0, 1.0)])
    ok, detail = _by_name(checks(NO_DEC, only_rim, _StubModel()), "rim_open_beats_contested_three")
    assert not ok and "empty" in detail


def test_prior_moves_value_pass_and_fail() -> None:
    ok, detail = _by_name(checks(NO_DEC, GOOD_OPTS, _StubModel(1.0)), "prior_moves_value")
    assert ok and "0.30" in detail and "0.45" in detail
    assert not _by_name(checks(NO_DEC, GOOD_OPTS, _StubModel(-1.0)), "prior_moves_value")[0]


def test_excluded_share_ignores_no_tracking() -> None:
    rows = [("a", 5.0, 0.1, None)] * 17 + [("excluded", None, None, "tip")] * 3
    rows += [("excluded", None, None, "no_tracking")] * 50
    ok, detail = _by_name(
        checks(_decisions(rows), GOOD_OPTS, _StubModel()), "excluded_share_below_15pct"
    )
    assert ok and "3/20" in detail
    rows = [("a", 5.0, 0.1, None)] * 16 + [("excluded", None, None, "tip")] * 4
    ok, detail = _by_name(
        checks(_decisions(rows), GOOD_OPTS, _StubModel()), "excluded_share_below_15pct"
    )
    assert not ok and "4/20" in detail


def _fixture_tables(
    built_fixture: Settings, trained_fixture_model: ValueModel
) -> tuple[pl.DataFrame, pl.DataFrame]:
    build_decisions(114243, built_fixture, model=trained_fixture_model)
    return load_decisions(114243, built_fixture), load_decision_options(114243, built_fixture)


def test_checks_on_fixture_game(built_fixture: Settings, trained_fixture_model: ValueModel) -> None:
    dec, opts = _fixture_tables(built_fixture, trained_fixture_model)
    result = checks(dec, opts, trained_fixture_model)
    assert len(result) == 4
    assert all(isinstance(ok, bool) and detail for _, ok, detail in result)
    assert _by_name(result, "prior_moves_value")[0]
    assert "18/35" in _by_name(result, "excluded_share_below_15pct")[1]


def test_validate_decisions_cli_prints_four_lines(
    built_fixture: Settings,
    trained_fixture_model: ValueModel,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_tables(built_fixture, trained_fixture_model)
    model_path = tmp_path / "model.json"
    trained_fixture_model.save(model_path)
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(built_fixture.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(built_fixture.build_dir))
    result = runner.invoke(
        app, ["validate", "decisions", "--game", "114243", "--model", str(model_path)]
    )
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert len(lines) == 4, result.output
    assert all(ln.startswith(("ok  ", "FAIL ")) for ln in lines)
    assert result.exit_code == (1 if any(ln.startswith("FAIL") for ln in lines) else 0)


def test_validate_decisions_allow_fail(
    built_fixture: Settings,
    trained_fixture_model: ValueModel,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_tables(built_fixture, trained_fixture_model)
    model_path = tmp_path / "model.json"
    trained_fixture_model.save(model_path)
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(built_fixture.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(built_fixture.build_dir))
    base = ["validate", "decisions", "--game", "114243", "--model", str(model_path)]
    plain = runner.invoke(app, base)
    failing = [ln.split()[1] for ln in plain.output.splitlines() if ln.startswith("FAIL")]
    assert failing, plain.output  # the one-game fixture fails excluded_share_below_15pct
    assert plain.exit_code == 1
    allowed = runner.invoke(app, base + [a for name in failing for a in ("--allow-fail", name)])
    assert allowed.exit_code == 0, allowed.output
    for name in failing:
        assert f"FAIL (allowed) {name}" in allowed.output
    partial = runner.invoke(app, [*base, "--allow-fail", "prior_moves_value"])
    assert partial.exit_code == 1
    bogus = runner.invoke(app, [*base, "--allow-fail", "nope"])
    assert bogus.exit_code == 2 and "unknown check" in bogus.output
