"""Shot-clock bucket membership shared by the face-validity checks and the player cards."""

import polars as pl

from ventaja.value.params import CLOCK_BUCKETS

__all__ = ["clock_bucket_expr"]


def clock_bucket_expr(index: int) -> pl.Expr:
    """Membership of ``shot_clock`` in ``CLOCK_BUCKETS[index]``.

    The first bucket has no upper bound (a clock slightly above 24 still opens the possession);
    the last one includes its lower bound 0.0. A null clock belongs to no bucket.
    """
    _, lo, hi = CLOCK_BUCKETS[index]
    clock = pl.col("shot_clock")
    if index == 0:
        return clock > lo
    return (clock >= lo if index == len(CLOCK_BUCKETS) - 1 else clock > lo) & (clock <= hi)
