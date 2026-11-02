"""Face-validity checks of the decisions tables (spec 5.5)."""

from typing import Protocol

import polars as pl

from ventaja.value.clock import clock_bucket_expr
from ventaja.value.params import CLOCK_BUCKETS

__all__ = ["checks"]

Check = tuple[str, bool, str]

# (label, filter) of the shot-clock buckets, from the start of the possession to its end.
_CLOCK_BUCKETS: tuple[tuple[str, pl.Expr], ...] = tuple(
    (label, clock_bucket_expr(i)) for i, (label, _, _) in enumerate(CLOCK_BUCKETS)
)
MAX_EXCLUDED_SHARE = 0.15
LOW_PRIOR, HIGH_PRIOR = 0.30, 0.45


class _Model(Protocol):
    def predict_proba(self, df: pl.DataFrame) -> pl.Series: ...


def _mean_count(df: pl.DataFrame, column: str) -> tuple[float, int]:
    return (float(df[column].mean()), df.height) if df.height else (float("nan"), 0)  # type: ignore[arg-type]


def cost_falls_with_clock(decisions: pl.DataFrame) -> Check:
    """Mean cost falls from the 24-14 bucket to 14-6 to 6-0."""
    name = "cost_falls_with_clock"
    valid = decisions.filter((pl.col("rule") != "excluded") & pl.col("shot_clock").is_not_null())
    stats = [(label, *_mean_count(valid.filter(f), "cost")) for label, f in _CLOCK_BUCKETS]
    empty = [label for label, _, n in stats if n == 0]
    detail = ", ".join(f"{label} {mean:.3f} (n={n})" for label, mean, n in stats)
    if empty:
        return name, False, f"empty bucket {', '.join(empty)}: {detail}"
    return name, stats[0][1] > stats[1][1] > stats[2][1], detail


def rim_open_beats_contested_three(options: pl.DataFrame) -> Check:
    """An open restricted-area option is worth more than a contested above-the-break three."""
    name = "rim_open_beats_contested_three"
    rim = options.filter((pl.col("zone") == "restricted_area") & (pl.col("nearest_def_dist") >= 6))
    three = options.filter((pl.col("zone") == "above_break_3") & (pl.col("nearest_def_dist") < 3))
    (m_rim, n_rim), (m_three, n_three) = _mean_count(rim, "value"), _mean_count(three, "value")
    detail = f"open rim {m_rim:.3f} (n={n_rim}) vs contested 3 {m_three:.3f} (n={n_three})"
    if not n_rim or not n_three:
        return name, False, f"empty group: {detail}"
    return name, m_rim > m_three, detail


def prior_moves_value(options: pl.DataFrame, model: _Model) -> Check:
    """Raising ``prior_zone`` from 0.30 to 0.45 raises the model's probability."""
    name = "prior_moves_value"
    shots = options.filter(pl.col("option_type") == "shot")
    if shots.height == 0:
        return name, False, "no shot option rows"
    row = shots.head(1)
    low = float(model.predict_proba(row.with_columns(prior_zone=pl.lit(LOW_PRIOR)))[0])
    high = float(model.predict_proba(row.with_columns(prior_zone=pl.lit(HIGH_PRIOR)))[0])
    return (
        name,
        high > low,
        f"P(prior {LOW_PRIOR:.2f}) {low:.3f}, P(prior {HIGH_PRIOR:.2f}) {high:.3f}",
    )


def excluded_share_below_15pct(decisions: pl.DataFrame) -> Check:
    """At most 15% of the shots with tracking are excluded."""
    name = "excluded_share_below_15pct"
    tracked = decisions.filter(pl.col("reason").is_null() | (pl.col("reason") != "no_tracking"))
    excluded = tracked.filter(pl.col("rule") == "excluded").height
    total = tracked.height
    share = excluded / total if total else 1.0
    return name, total > 0 and share <= MAX_EXCLUDED_SHARE, f"{excluded}/{total} = {share:.1%}"


def checks(decisions: pl.DataFrame, options: pl.DataFrame, model: _Model) -> list[Check]:
    """Run the four checks over the decisions and option tables of the selected games."""
    return [
        cost_falls_with_clock(decisions),
        rim_open_beats_contested_three(options),
        prior_moves_value(options, model),
        excluded_share_below_15pct(decisions),
    ]
