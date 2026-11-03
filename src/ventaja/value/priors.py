"""Season priors per player and zone, shrunk toward the league rate."""

from pathlib import Path
from typing import Literal, Self

import polars as pl
import polars.selectors as cs

from ventaja.config import Settings
from ventaja.data.build import write_parquet_atomic
from ventaja.data.load import load_aggregates
from ventaja.errors import DataNotFoundError
from ventaja.value.params import K_SHRINK
from ventaja.value.zones import Zone

__all__ = ["DEFAULT_PRIORS_PATH", "ContestLevel", "Priors"]

# Next to the model; resolved from the package location (the repo root in an editable install).
DEFAULT_PRIORS_PATH = Path(__file__).parents[3] / "models" / "priors.parquet"

ContestLevel = Literal["open", "light", "average", "plus", "blocked"]


class Priors:
    """Shrunk shooting rates: ``(mades + K * league) / (attempts + K)``."""

    def __init__(self, players: pl.DataFrame) -> None:
        """``players``: one row per ``player_id`` with summed ``attempts``/``mades`` columns."""
        self._rows = {row["player_id"]: row for row in players.iter_rows(named=True)}
        self._players = players

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Sum the shots aggregate per player, skipping the ``total`` rows (null team)."""
        shots = load_aggregates("shots", settings).filter(pl.col("team_id").is_not_null())
        numeric = shots.select("player_id", cs.numeric().exclude("player_id", "team_id"))
        return cls(numeric.group_by("player_id").sum())

    def save(self, path: Path) -> None:
        """Write the per-player summed table the priors are built from, atomically."""
        path.parent.mkdir(parents=True, exist_ok=True)
        write_parquet_atomic(self._players, path)

    @classmethod
    def load(cls, path: Path) -> Self:
        """Read priors written by ``save``."""
        if not path.exists():
            raise DataNotFoundError(f"no priors at {path}; run `ventaja model train`")
        return cls(pl.read_parquet(path))

    @classmethod
    def default(cls) -> Self:
        """The priors saved at ``DEFAULT_PRIORS_PATH`` (packaged next to the model)."""
        return cls.load(DEFAULT_PRIORS_PATH)

    def _total(self, column: str) -> float:
        return float(self._players.select(pl.col(column).cast(pl.Float64).sum()).item())

    def _league(self, attempts_col: str, mades_col: str) -> float:
        attempts = self._total(attempts_col)
        if attempts == 0:
            attempts, mades = self._total("attempts"), self._total("mades")
            return mades / attempts if attempts else 0.0
        return self._total(mades_col) / attempts

    def _shrunk(self, player_id: int, key: str, league: float) -> float:
        row = self._rows.get(player_id)
        if row is None:
            return league
        mades, attempts = float(row[f"{key}_mades"]), float(row[f"{key}_attempts"])
        if attempts == 0:
            return league
        return (mades + K_SHRINK * league) / (attempts + K_SHRINK)

    def league_rate(self, zone: Zone) -> float:
        """League FG rate in a zone (overall rate if the zone has no attempts)."""
        return self._league(f"zone_{zone}_attempts", f"zone_{zone}_mades")

    def player_rate(self, player_id: int, zone: Zone) -> float:
        """Shrunk FG rate of a player in a zone; unknown player gives the league rate."""
        return self._shrunk(player_id, f"zone_{zone}", self.league_rate(zone))

    def league_contest_rate(self, level: ContestLevel) -> float:
        """League FG rate at a contest level (overall rate if there are no attempts)."""
        return self._league(f"cl_{level}_attempts", f"cl_{level}_mades")

    def player_contest_rate(self, player_id: int, level: ContestLevel) -> float:
        """Shrunk FG rate of a player at a contest level."""
        return self._shrunk(player_id, f"cl_{level}", self.league_contest_rate(level))
