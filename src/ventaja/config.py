"""Runtime settings and project-wide constants."""

import os
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict

FPS: int = 25
SEASON = "2025-2026"
GAME_IDS: tuple[int, ...] = (
    114086,
    114099,
    114169,
    114234,
    114243,
    178442,
    179612,
    184439,
    188630,
    191313,
)

_CACHE_ROOT = Path.home() / ".cache" / "ventaja"


class Settings(BaseModel):
    """Where raw SkillCorner files and built parquet files live."""

    model_config = ConfigDict(frozen=True)

    data_dir: Path
    build_dir: Path

    @classmethod
    def from_env(cls) -> Self:
        """Build settings from VENTAJA_DATA_DIR / VENTAJA_BUILD_DIR, with cache defaults."""
        data_dir = os.environ.get("VENTAJA_DATA_DIR")
        build_dir = os.environ.get("VENTAJA_BUILD_DIR")
        return cls(
            data_dir=Path(data_dir).expanduser() if data_dir else _CACHE_ROOT / "raw",
            build_dir=Path(build_dir).expanduser() if build_dir else _CACHE_ROOT / "build",
        )

    def raw_path(self, relpath: str) -> Path:
        """Path of a raw file, relative to the SkillCorner repo's data/ directory."""
        return self.data_dir / relpath

    def events_parquet(self, game_id: int, table: str) -> Path:
        """Path of the built parquet for one dynamic-events table of a game."""
        return self.build_dir / "events" / str(game_id) / f"{table}.parquet"

    def tracking_parquet(self, game_id: int) -> Path:
        """Path of the built long-format tracking parquet of a game."""
        return self.build_dir / "tracking" / f"{game_id}.parquet"

    def meta_parquet(self, table: str) -> Path:
        """Path of a built metadata table (``games``, ``players`` or ``matches``)."""
        return self.build_dir / "meta" / f"{table}.parquet"

    def aggregates_parquet(self, name: str) -> Path:
        """Path of a built season-aggregate table (``shots``, ``drives`` or ``picks``)."""
        return self.build_dir / "aggregates" / f"{name}.parquet"

    def decisions_parquet(self, game_id: int) -> Path:
        """Path of the built decisions parquet of a game."""
        return self.build_dir / "decisions" / f"{game_id}.parquet"

    def decisions_options_parquet(self, game_id: int) -> Path:
        """Path of the built per-option parquet of a game's decisions."""
        return self.build_dir / "decisions" / f"{game_id}.options.parquet"

    def curves_parquet(self, game_id: int) -> Path:
        """Path of the built per-frame advantage curves of a game's shots."""
        return self.build_dir / "curves" / f"{game_id}.parquet"

    def curve_summaries_parquet(self, game_id: int) -> Path:
        """Path of the built one-row-per-shot curve summaries of a game."""
        return self.build_dir / "curves" / f"{game_id}.summary.parquet"

    def players_parquet(self) -> Path:
        """Path of the built player cards (one row per shooter plus the ``LIGA`` row)."""
        return self.build_dir / "players" / "players.parquet"

    def teams_parquet(self) -> Path:
        """Path of the built team cards."""
        return self.build_dir / "players" / "teams.parquet"
