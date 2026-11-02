"""Pure aggregation of decisions and curve summaries per player, team and league.

Shares and means are ``None`` when their denominator is empty; nothing is filled with 0.
Every cost mean (``mean_cost`` and the shot-clock bucket means) and the value means run over the
readable decisions only (``good_read`` not null); an unreadable decision has cost 0 by
construction. ``n_{bucket}`` counts the readable decisions of the bucket. Lost moments
(``n_late_held``, ``late_held_share``, ``mean_lag_held``) skip decisions with a known shot clock
under ``LATE_MIN_CLOCK``, as the reel does; ``n_with_summary`` counts every curve. The
face-validity check ``cost_falls_with_clock`` keeps its own all-valid-rows convention.
"""

from typing import Any

import polars as pl

from ventaja.value.params import (
    ADVANTAGE_TOLERANCE,
    ALT_TYPES,
    CLOCK_BUCKETS,
    LATE_MIN_CLOCK,
    MIN_RANK_CONFIDENCE,
)

__all__ = ["clock_bucket_expr", "league_row", "player_table", "team_table"]

_SUMMARY_COLUMNS = ["shot_id", "verdict", "release_lag_seconds", "held_to_decision"]


def clock_bucket_expr(index: int) -> pl.Expr:
    """Membership of ``shot_clock`` in ``CLOCK_BUCKETS[index]``.

    The first bucket has no upper bound (a clock slightly above 24 still opens the possession);
    the last one includes its lower bound 0.0.
    """
    _, lo, hi = CLOCK_BUCKETS[index]
    clock = pl.col("shot_clock")
    if index == 0:
        return clock > lo
    return (clock >= lo if index == len(CLOCK_BUCKETS) - 1 else clock > lo) & (clock <= hi)


def _joined(decisions: pl.DataFrame, summaries: pl.DataFrame) -> pl.DataFrame:
    """Non-excluded decisions with their summary columns (null when the shot has none)."""
    summ = summaries.select(_SUMMARY_COLUMNS).unique(subset="shot_id", keep="first")
    return (
        decisions.filter(pl.col("rule") != "excluded")
        .join(summ, on="shot_id", how="left")
        .with_columns(has_summary=pl.col("verdict").is_not_null())
    )


def _metrics(joined: pl.DataFrame, by: list[str]) -> pl.DataFrame:
    readable = pl.col("good_read").is_not_null()
    # A lost moment counts only with a known clock of at least LATE_MIN_CLOCK (or an unknown
    # one), the reel's floor: below it the shot clock, not the shooter, closed the window.
    clock_ok = pl.col("shot_clock").is_null() | (pl.col("shot_clock") >= LATE_MIN_CLOCK)
    late_held = (pl.col("verdict") == "late") & pl.col("held_to_decision") & clock_ok
    aggs: list[pl.Expr] = [
        pl.len().alias("n_shots"),
        readable.sum().alias("n_readable"),
        pl.col("good_read").sum().alias("_n_good"),
        pl.col("shot_value").filter(readable).mean().alias("mean_shot_value"),
        pl.col("best_alt_value").filter(readable).mean().alias("mean_best_alt_value"),
        pl.col("cost").filter(readable).mean().alias("mean_cost"),
        pl.col("cost").sum().alias("total_cost"),
        pl.col("shot_clock").is_not_null().sum().alias("n_clock_known"),
    ]
    for i, (label, _, _) in enumerate(CLOCK_BUCKETS):
        member = clock_bucket_expr(i)
        aggs.append(pl.col("cost").filter(member & readable).mean().alias(f"cost_{label}"))
        aggs.append((member & readable).sum().alias(f"n_{label}"))
    for alt in ALT_TYPES:
        member = (pl.col("cost") > ADVANTAGE_TOLERANCE) & (pl.col("best_alt_type") == alt)
        aggs.append(member.sum().alias(f"n_alt_{alt}"))
        aggs.append(pl.col("cost").filter(member).mean().alias(f"cost_alt_{alt}"))
    aggs += [
        pl.col("has_summary").sum().alias("n_with_summary"),
        late_held.sum().alias("n_late_held"),
        pl.col("release_lag_seconds").filter(late_held).mean().alias("mean_lag_held"),
        (pl.col("verdict") == "during").sum().alias("n_during"),
        pl.col("confidence").mean().alias("mean_confidence"),
        (pl.col("confidence") < MIN_RANK_CONFIDENCE).sum().alias("n_low_confidence"),
    ]
    n_alt = [f"n_alt_{a}" for a in ALT_TYPES]
    out = joined.group_by(by).agg(aggs)
    out = out.with_columns(
        good_read_share=pl.when(pl.col("n_readable") > 0)
        .then(pl.col("_n_good") / pl.col("n_readable"))
        .otherwise(None),
        late_held_share=pl.when(pl.col("n_with_summary") > 0)
        .then(pl.col("n_late_held") / pl.col("n_with_summary"))
        .otherwise(None),
        during_share=pl.when(pl.col("n_with_summary") > 0)
        .then(pl.col("n_during") / pl.col("n_with_summary"))
        .otherwise(None),
        ignored_alt=pl.when(pl.max_horizontal(n_alt) > 0)
        .then(
            pl.concat_list(n_alt)
            .list.arg_max()
            .replace_strict(dict(enumerate(ALT_TYPES)), return_dtype=pl.String)
        )
        .otherwise(None),
    )
    counts = [c for c in out.columns if c.startswith("n_")]
    return out.with_columns(pl.col(counts).cast(pl.Int64)).drop("_n_good")


def _order(table: pl.DataFrame, first: list[str]) -> pl.DataFrame:
    return table.select(first + [c for c in table.columns if c not in first])


def player_table(decisions: pl.DataFrame, summaries: pl.DataFrame) -> pl.DataFrame:
    """One row per shooter: counts, cost means, ignored alternatives and late-read shares."""
    table = _metrics(_joined(decisions, summaries), ["shooter_id"])
    table = table.rename({"shooter_id": "player_id"})
    table = table.sort(["n_shots", "player_id"], descending=[True, False])
    return _order(table, ["player_id"])


def team_table(
    decisions: pl.DataFrame, summaries: pl.DataFrame, players_meta: pl.DataFrame
) -> pl.DataFrame:
    """The same metrics per team, the team being the shooter's in that game (``meta/players``).

    Decisions whose shooter has no row in ``players_meta`` for that game belong to no team and
    are silently dropped.
    """
    teams = players_meta.select("game_id", "team_id", pl.col("player_id").alias("shooter_id"))
    teams = teams.unique(subset=["game_id", "shooter_id"], keep="first")
    joined = _joined(decisions, summaries).join(teams, on=["game_id", "shooter_id"], how="left")
    joined = joined.filter(pl.col("team_id").is_not_null())
    table = _metrics(joined, ["team_id"])
    players = joined.group_by("team_id").agg(
        pl.col("shooter_id").n_unique().cast(pl.Int64).alias("n_players")
    )
    table = table.join(players, on="team_id", how="left").sort("team_id")
    return _order(table, ["team_id"])


def league_row(decisions: pl.DataFrame, summaries: pl.DataFrame) -> dict[str, Any]:
    """The same metrics over every non-excluded decision, as a plain dict.

    On an empty frame every key is still present: counts are 0, the rest ``None``.
    """
    joined = _joined(decisions, summaries).with_columns(_all=pl.lit(0))
    table = _metrics(joined, ["_all"]).drop("_all")
    if table.height == 0:
        return {c: 0 if c.startswith("n_") else None for c in table.columns}
    row: dict[str, Any] = table.row(0, named=True)
    return row
