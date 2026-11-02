"""Tests for the possession clip (court + advantage curve) and the curve figure."""

import warnings
from pathlib import Path

import polars as pl
import pytest
from PIL import Image
from typer.testing import CliRunner

from ventaja.cli import app
from ventaja.config import Settings
from ventaja.data.load import (
    load_curve_summaries,
    load_curves,
    load_decision_options,
    load_decisions,
)
from ventaja.decision.align import Aligner
from ventaja.decision.cost import decide, decision_from_tables
from ventaja.errors import DataNotFoundError, VentajaError
from ventaja.value.model import ValueModel
from ventaja.value.priors import Priors
from ventaja.viz.clip import curve_figure, curve_of_shot, render_clip

GAME_ID = 114243
SHOT_ID = "shot-114243-1-0"
EXCLUDED_SHOT_ID = "shot-114243-1-2"  # excluded in the fixture: no shot type


def _env(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(settings.build_dir))


def test_decision_from_tables_roundtrip(
    fixture_curves_built: Settings,
    fixture_priors: Priors,
    trained_fixture_model: ValueModel,
) -> None:
    s = fixture_curves_built
    live = decide(Aligner(GAME_ID, s), SHOT_ID, fixture_priors, trained_fixture_model)
    assert live is not None
    rebuilt = decision_from_tables(
        SHOT_ID, load_decisions(GAME_ID, s), load_decision_options(GAME_ID, s)
    )
    assert rebuilt.shot_value == pytest.approx(live.shot_value, abs=1e-9)
    assert rebuilt.cost == pytest.approx(live.cost, abs=1e-9)
    assert rebuilt.good_read == live.good_read
    assert rebuilt.best_alt_player_id == live.best_alt_player_id
    assert [o.player_id for o in rebuilt.options] == [o.player_id for o in live.options]
    for got, want in zip(rebuilt.options, live.options, strict=True):
        assert got.adjusted_value == pytest.approx(want.adjusted_value, abs=1e-9)
        assert got.features == pytest.approx(want.features, abs=1e-9)


def test_decision_from_tables_errors(fixture_curves_built: Settings) -> None:
    s = fixture_curves_built
    decisions, options = load_decisions(GAME_ID, s), load_decision_options(GAME_ID, s)
    with pytest.raises(VentajaError, match="no_type"):
        decision_from_tables(EXCLUDED_SHOT_ID, decisions, options)
    with pytest.raises(DataNotFoundError):
        decision_from_tables("shot-114243-9-999", decisions, options)


def test_render_clip_writes_gif(fixture_curves_built: Settings, tmp_path: Path) -> None:
    s = fixture_curves_built
    d = decision_from_tables(SHOT_ID, load_decisions(GAME_ID, s), load_decision_options(GAME_ID, s))
    curve, summary = curve_of_shot(
        SHOT_ID, load_curves(GAME_ID, s), load_curve_summaries(GAME_ID, s)
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = render_clip(
            Aligner(GAME_ID, s),
            d,
            curve,
            summary,
            tmp_path / "clip.gif",
            before_s=1.0,
            after_s=0.2,
            fps=6,
        )
    assert out.exists() and out.stat().st_size > 10_000
    with Image.open(out) as gif:
        assert getattr(gif, "n_frames", 1) >= 2


def test_curve_figure_writes_png(fixture_curves_built: Settings, tmp_path: Path) -> None:
    s = fixture_curves_built
    curve, summary = curve_of_shot(
        SHOT_ID, load_curves(GAME_ID, s), load_curve_summaries(GAME_ID, s)
    )
    d = load_decisions(GAME_ID, s).filter(pl.col("shot_id") == SHOT_ID).row(0, named=True)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = curve_figure(curve, summary, d["decision_frame"], tmp_path / "curve.png")
    assert out.exists() and out.stat().st_size > 5_000


def test_clip_cli_errors_on_excluded_shot(
    fixture_curves_built: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _env(fixture_curves_built, monkeypatch)
    result = CliRunner().invoke(app, ["clip", EXCLUDED_SHOT_ID, "--out", str(tmp_path / "x.gif")])
    assert result.exit_code == 1
    assert "excluded" in result.output and "no_type" in result.output
    assert not (tmp_path / "x.gif").exists()


def test_clip_cli_writes_gif(
    fixture_curves_built: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _env(fixture_curves_built, monkeypatch)
    out = tmp_path / "c.gif"
    result = CliRunner().invoke(
        app,
        ["clip", SHOT_ID, "--out", str(out), "--fps", "5", "--before", "0.4", "--after", "0.1"],
    )
    assert result.exit_code == 0, result.output
    assert out.exists() and str(out) in result.output


def test_curves_plot_cli(
    fixture_curves_built: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _env(fixture_curves_built, monkeypatch)
    out = tmp_path / "curve.png"
    result = CliRunner().invoke(app, ["curves", "plot", SHOT_ID, "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists() and out.stat().st_size > 5_000
