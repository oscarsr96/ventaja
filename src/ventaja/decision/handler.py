"""Who holds the ball at each frame of a possession, from its ``touches``."""

import polars as pl


class BallHandler:
    """Answers "which player holds the ball at this frame" for one possession.

    Spans are built once from the touches DataFrame, so ``handler_at`` does no Polars work.
    Touches do not overlap in the data; if two did, the one that starts later wins.
    """

    def __init__(self, touches: pl.DataFrame) -> None:
        self._spans: list[tuple[int, int, int]] = sorted(
            (int(s), int(e), int(p))
            for s, e, p in zip(
                touches["start_frame"], touches["end_frame"], touches["player_id"], strict=True
            )
        )

    def spans(self) -> list[tuple[int, int, int]]:
        """``(start_frame, end_frame, player_id)`` of every touch, sorted by start."""
        return list(self._spans)

    def handler_at(self, frame_idx: int) -> int | None:
        """Player id whose touch has ``start_frame <= frame_idx <= end_frame``, else None.

        None means the ball is in flight between touches (or outside the possession). On
        overlapping touches the one that starts later is returned.
        """
        for start, end, player_id in reversed(self._spans):
            if start <= frame_idx <= end:
                return player_id
        return None
