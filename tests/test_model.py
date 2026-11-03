import json
import warnings
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ventaja.config import Settings
from ventaja.decision.align import Aligner
from ventaja.errors import DataNotFoundError
from ventaja.value import model as model_module
from ventaja.value.features import OPTION_FEATURES, shot_rows
from ventaja.value.model import (
    ValueModel,
    calibration_table,
    fit,
    plot_calibration,
    train_logo,
    zone_table,
)
from ventaja.value.priors import Priors


def _synthetic(n: int = 400, games: int = 1, seed: int = 0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    data: dict[str, object] = {f: rng.normal(size=n) for f in OPTION_FEATURES}
    logit = -0.1 * np.asarray(data["dist_hoop"]) * 10 + 2 * np.asarray(data["prior_zone"])
    outcome = rng.random(n) < 1 / (1 + np.exp(-logit))
    df = pl.DataFrame(data).with_columns(
        pl.lit("shot").alias("option_type"),
        pl.Series("outcome", outcome),
        pl.Series("points", rng.choice([2, 3], size=n)),
        pl.Series("game_id", np.arange(n) % games),
        pl.Series("shot_id", [f"s{i}" for i in range(n)]),
        pl.Series("shot_quality", rng.uniform(0, 100, size=n)),
        pl.Series("zone", rng.choice(["restricted_area", "mid_range", "corner_3"], size=n)),
    )
    return df


def test_fit_and_roundtrip(tmp_path: Path) -> None:
    df = _synthetic()
    m = fit(df)
    m.save(tmp_path / "m.json")
    m2 = ValueModel.load(tmp_path / "m.json")
    assert (m.predict_proba(df) - m2.predict_proba(df)).abs().max() < 1e-9  # type: ignore[operator]
    assert m.feature_table().filter(pl.col("feature") == "dist_hoop")["coef"][0] < 0
    table = m.feature_table()
    assert table.columns == ["feature", "coef", "odds_ratio"]
    assert table["coef"].abs().to_list() == sorted(table["coef"].abs().to_list(), reverse=True)


def test_null_shot_clock_uses_training_mean() -> None:
    df = _synthetic().with_columns(
        pl.when(pl.int_range(pl.len()) % 50 == 0)
        .then(None)
        .otherwise(pl.col("shot_clock"))
        .alias("shot_clock")
    )
    m = fit(df)
    mean_clock = float(df["shot_clock"].drop_nulls().mean())  # type: ignore[arg-type]
    nulled = df.head(5).with_columns(pl.lit(None, dtype=pl.Float64).alias("shot_clock"))
    filled = df.head(5).with_columns(pl.lit(mean_clock).alias("shot_clock"))
    assert (m.predict_proba(nulled) - m.predict_proba(filled)).abs().max() < 1e-9  # type: ignore[operator]
    assert m.fill["shot_clock"] == pytest.approx(mean_clock)


def test_null_without_training_nulls_uses_training_mean() -> None:
    df = _synthetic()
    m = fit(df)
    assert "nearest_def_dist" not in m.fill
    mean = m.mean[m.features.index("nearest_def_dist")]
    nulled = df.head(5).with_columns(pl.lit(None, dtype=pl.Float64).alias("nearest_def_dist"))
    filled = df.head(5).with_columns(pl.lit(mean).alias("nearest_def_dist"))
    assert (m.predict_proba(nulled) - m.predict_proba(filled)).abs().max() < 1e-9  # type: ignore[operator]


def test_value_is_proba_times_points() -> None:
    df = _synthetic(100)
    m = fit(df)
    expected = m.predict_proba(df) * df["points"]
    assert (m.value(df) - expected).abs().max() < 1e-12  # type: ignore[operator]


def test_train_logo_on_fixture_runs(built_fixture: Settings) -> None:
    df = shot_rows(Aligner(114243, built_fixture), Priors.from_settings(built_fixture))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        m, preds = train_logo(df)
    assert {"logloss", "brier", "auc", "n_shots"} <= set(m.metrics)
    assert preds.height == df.filter(pl.col("option_type") == "shot").height
    assert preds.columns == [
        "shot_id", "game_id", "zone", "proba", "outcome", "points", "shot_quality",
    ]  # fmt: skip
    assert m.trained_on == [114243]
    json.dumps(m.metrics)


def test_train_logo_holds_out_each_game() -> None:
    df = _synthetic(600, games=3)
    m, preds = train_logo(df)
    assert preds.height == 600 and sorted(m.trained_on) == [0, 1, 2]
    assert m.metrics["corr_with_skillcorner_dropped"] == 0
    assert 0.0 < m.metrics["logloss"] < 1.0


def test_single_class_gives_null_auc() -> None:
    preds = pl.DataFrame(
        {
            "proba": [0.2, 0.4, 0.6],
            "outcome": [False, False, False],
            "shot_quality": [None, 30.0, 50.0],
        }
    )
    metrics = model_module._metrics(preds)
    assert metrics["auc"] is None and metrics["corr_with_skillcorner_dropped"] == 1
    json.dumps(metrics)


def test_calibration_table_bins(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    proba = rng.uniform(size=200)
    preds = pl.DataFrame({"proba": proba, "outcome": rng.random(200) < proba})
    table = calibration_table(preds)
    assert table.columns == ["bin", "n", "mean_pred", "mean_outcome"]
    assert table.height == 10 and table["n"].sum() == 200
    out = tmp_path / "c.png"
    plot_calibration(table, out, n_shots=200, logloss=0.6)
    assert out.stat().st_size > 0


class _LeaguePriors:
    def league_rate(self, zone: str) -> float:
        return {"restricted_area": 0.6, "mid_range": 0.4, "corner_3": 0.38}[zone]


def test_zone_table_compares_predictions_with_rates(tmp_path: Path) -> None:
    preds = pl.DataFrame(
        {
            "zone": ["corner_3", "restricted_area", "restricted_area", "mid_range"],
            "proba": [0.3, 0.5, 0.7, 0.4],
            "outcome": [False, True, False, True],
        }
    )
    table = zone_table(preds, _LeaguePriors())  # type: ignore[arg-type]
    assert table.columns == ["zone", "n", "mean_pred", "observed_rate", "league_rate"]
    assert table["zone"].to_list() == ["restricted_area", "mid_range", "corner_3"]  # ZONES order
    ra = table.row(0, named=True)
    assert ra["n"] == 2 and ra["mean_pred"] == pytest.approx(0.6)
    assert ra["observed_rate"] == pytest.approx(0.5) and ra["league_rate"] == 0.6
    m = fit(_synthetic())
    m.zone_table = table.to_dicts()
    m.save(tmp_path / "m.json")
    assert ValueModel.load(tmp_path / "m.json").zone_table == table.to_dicts()


def test_load_model_without_zone_table(tmp_path: Path) -> None:
    m = fit(_synthetic())
    m.save(tmp_path / "m.json")
    raw = json.loads((tmp_path / "m.json").read_text())
    del raw["zone_table"]
    (tmp_path / "old.json").write_text(json.dumps(raw))
    assert ValueModel.load(tmp_path / "old.json").zone_table == []


def test_cli_model_train_and_report_print_zone_table(
    built_fixture: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from ventaja.cli import app

    monkeypatch.setenv("VENTAJA_DATA_DIR", str(built_fixture.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(built_fixture.build_dir))
    out, fig = tmp_path / "m.json", tmp_path / "c.png"
    runner = CliRunner()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        trained = runner.invoke(
            app,
            ["model", "train", "--game", "114243", "--out", str(out), "--figure", str(fig)],
        )
    assert trained.exit_code == 0, trained.output
    assert (tmp_path / "priors.parquet").exists() and "priors ->" in trained.output
    assert "mean_pred" in trained.output and "league" in trained.output
    stored = json.loads(out.read_text())["zone_table"]
    assert stored and {"zone", "n", "mean_pred", "observed_rate", "league_rate"} == set(stored[0])
    assert sum(r["n"] for r in stored) == json.loads(out.read_text())["n_rows"]
    report = runner.invoke(app, ["model", "report", "--model", str(out)])
    assert report.exit_code == 0, report.output
    assert "observed" in report.output and stored[0]["zone"] in report.output


def test_default_missing_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(model_module, "DEFAULT_MODEL_PATH", tmp_path / "nope.json")
    with pytest.raises(DataNotFoundError, match="ventaja model train"):
        ValueModel.default()
