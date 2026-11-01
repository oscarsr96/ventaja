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
            data_dir=Path(data_dir) if data_dir else _CACHE_ROOT / "raw",
            build_dir=Path(build_dir) if build_dir else _CACHE_ROOT / "build",
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
