"""Interpretable value model: ``P(score | option features) x points``.

A logistic regression on the shot options, fitted with standardized features. Only the
coefficients are stored (JSON), never the sklearn object.
"""

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import matplotlib
import numpy as np
import numpy.typing as npt
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from ventaja import __version__
from ventaja.errors import DataNotFoundError
from ventaja.value.features import OPTION_FEATURES

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

__all__ = [
    "DEFAULT_MODEL_PATH",
    "ValueModel",
    "calibration_table",
    "fit",
    "plot_calibration",
    "train_logo",
]

# Resolved from the package location: the repo root in an editable install only.
DEFAULT_MODEL_PATH = Path(__file__).parents[3] / "models" / "value_model.json"

Array = npt.NDArray[np.float64]
_PRED_COLUMNS = ["shot_id", "game_id", "proba", "outcome", "points", "shot_quality"]


@dataclass
class ValueModel:
    """Standardized logistic model; ``fill`` imputes null features before standardizing."""

    features: tuple[str, ...]
    coef: list[float]
    intercept: float
    mean: list[float]
    scale: list[float]
    fill: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, float | None] = field(default_factory=dict)
    trained_on: list[int] = field(default_factory=list)
    n_rows: int = 0
    trained_at: str = ""
    ventaja_version: str = __version__

    def _matrix(self, df: pl.DataFrame) -> Array:
        # A null becomes the training mean (z = 0) unless ``fill`` stores a value. During
        # ``fit`` the mean is not known yet, but then every null is already in ``fill``.
        cols = [
            pl.col(f)
            .cast(pl.Float64)
            .fill_null(self.fill.get(f, self.mean[i] if self.mean else 0.0))
            .alias(f)
            for i, f in enumerate(self.features)
        ]
        return df.select(cols).to_numpy().astype(np.float64)

    def predict_proba(self, df: pl.DataFrame) -> pl.Series:
        """Probability that each row scores."""
        z = (self._matrix(df) - np.array(self.mean)) / np.array(self.scale)
        logit = z @ np.array(self.coef) + self.intercept
        return pl.Series("proba", 1.0 / (1.0 + np.exp(-logit)))

    def value(self, df: pl.DataFrame) -> pl.Series:
        """Expected points: ``proba x points``."""
        return (self.predict_proba(df) * df["points"]).alias("value")

    def save(self, path: Path) -> None:
        """Write the model as JSON."""
        payload: dict[str, Any] = {
            "features": list(self.features),
            "coef": self.coef,
            "intercept": self.intercept,
            "mean": self.mean,
            "scale": self.scale,
            "fill": self.fill,
            "metrics": self.metrics,
            "trained_on": self.trained_on,
            "n_rows": self.n_rows,
            "trained_at": self.trained_at,
            "ventaja_version": self.ventaja_version,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> Self:
        """Read a model written by ``save``."""
        if not path.exists():
            raise DataNotFoundError(f"no model at {path}; run `ventaja model train`")
        raw = json.loads(path.read_text())
        raw["features"] = tuple(raw["features"])
        return cls(**raw)

    @classmethod
    def default(cls) -> Self:
        """The model saved at ``DEFAULT_MODEL_PATH``."""
        return cls.load(DEFAULT_MODEL_PATH)

    def feature_table(self) -> pl.DataFrame:
        """Standardized coefficients and odds ratios, largest effect first."""
        return (
            pl.DataFrame({"feature": list(self.features), "coef": self.coef})
            .with_columns(pl.col("coef").exp().alias("odds_ratio"))
            .sort(pl.col("coef").abs(), descending=True)
        )


def _shots(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(pl.col("option_type") == "shot")


def fit(df: pl.DataFrame) -> ValueModel:
    """Fit on the ``shot`` rows of ``df`` (label ``outcome``) over ``OPTION_FEATURES``."""
    shots = _shots(df)
    fill = {
        f: float(shots[f].drop_nulls().cast(pl.Float64).mean() or 0.0)  # type: ignore[arg-type]
        for f in OPTION_FEATURES
        if shots[f].null_count() > 0
    }
    model = ValueModel(OPTION_FEATURES, [], 0.0, [], [], fill=fill)
    x = model._matrix(shots)
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale == 0] = 1.0
    y = shots["outcome"].cast(pl.Int64).to_numpy()
    clf = LogisticRegression(C=1.0, max_iter=1000).fit((x - mean) / scale, y)
    model.coef = [float(c) for c in clf.coef_[0]]
    model.intercept = float(clf.intercept_[0])
    model.mean = [float(m) for m in mean]
    model.scale = [float(s) for s in scale]
    model.n_rows = shots.height
    model.trained_at = datetime.now(UTC).isoformat(timespec="seconds")
    if "game_id" in shots.columns:
        model.trained_on = sorted(int(g) for g in shots["game_id"].unique())
    return model


def _metrics(preds: pl.DataFrame) -> dict[str, float | None]:
    y = preds["outcome"].cast(pl.Int64).to_numpy()
    p = np.clip(preds["proba"].to_numpy(), 1e-12, 1 - 1e-12)
    both = len(set(y.tolist())) == 2
    scored = preds.drop_nulls("shot_quality")
    corr = scored.select(pl.corr("proba", pl.col("shot_quality") / 100.0)).item()
    return {
        "logloss": float(log_loss(y, p, labels=[0, 1])),
        "brier": float(brier_score_loss(y, p)),
        "auc": float(roc_auc_score(y, p)) if both else None,
        "n_shots": float(preds.height),
        "corr_with_skillcorner": None if corr is None or math.isnan(corr) else float(corr),
        "corr_with_skillcorner_dropped": float(preds.height - scored.height),
    }


def train_logo(df: pl.DataFrame) -> tuple[ValueModel, pl.DataFrame]:
    """Leave-one-game-out validation; returns the all-games model and out-of-sample predictions.

    With a single game there is nothing to hold out, so the fold trains and predicts on that
    same game (in-sample metrics).
    """
    shots = _shots(df)
    games = sorted(shots["game_id"].unique().to_list())
    folds: list[pl.DataFrame] = []
    for game in games:
        test = shots.filter(pl.col("game_id") == game)
        train = shots.filter(pl.col("game_id") != game) if len(games) > 1 else test
        proba = fit(train).predict_proba(test)
        folds.append(test.with_columns(proba.alias("proba")).select(_PRED_COLUMNS))
    preds = pl.concat(folds)
    model = fit(shots)
    model.metrics = _metrics(preds)
    return model, preds


def calibration_table(preds: pl.DataFrame, bins: int = 10) -> pl.DataFrame:
    """Equal-width probability bins: ``bin, n, mean_pred, mean_outcome`` (empty bins dropped)."""
    idx = (pl.col("proba") * bins).floor().clip(0, bins - 1).cast(pl.Int64)
    return (
        preds.with_columns(idx.alias("bin"))
        .group_by("bin")
        .agg(
            pl.len().alias("n"),
            pl.col("proba").mean().alias("mean_pred"),
            pl.col("outcome").cast(pl.Float64).mean().alias("mean_outcome"),
        )
        .sort("bin")
    )


def plot_calibration(
    table: pl.DataFrame, path: Path, *, n_shots: int, logloss: float | None
) -> None:
    """Save the reliability diagram (point size proportional to bin count)."""
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color="grey", label="perfect calibration")
    counts = table["n"].to_numpy().astype(np.float64)
    sizes = counts / counts.max() * 300
    ax.scatter(table["mean_pred"], table["mean_outcome"], s=sizes, alpha=0.7)
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Observed make rate")
    ll = "n/a" if logloss is None else f"{logloss:.3f}"
    ax.set_title(f"Calibration (leave-one-game-out), n_shots={n_shots}, logloss={ll}")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(loc="upper left")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
