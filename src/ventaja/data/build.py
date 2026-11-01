"""Build layer: convert raw SkillCorner files into tidy parquet tables."""

import re
from pathlib import Path
from typing import Any

import polars as pl

from ventaja.config import Settings
from ventaja.data.load import apply_aliases, load_aliases, read_raw_json

EVENT_TABLES: tuple[str, ...] = (
    "chance_players",
    "chances",
    "closeouts",
    "dribbles",
    "drives",
    "fouls",
    "free_throws",
    "handoffs",
    "isolations",
    "matchups",
    "off_ball_screens",
    "passes",
    "picks",
    "possessions",
    "posts",
    "rebounds",
    "shots",
    "timeouts",
    "touches",
    "turnovers",
)

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def dynamic_events_relpath(game_id: int) -> str:
    """Relative path of a game's dynamic_events.json inside data_dir."""
    return f"matches/{game_id}/{game_id}_dynamic_events.json"


def to_snake(name: str) -> str:
    """Convert a camelCase key to snake_case (``offPlayerIds`` -> ``off_player_ids``)."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def _loc_prefix(key: str) -> str | None:
    """Column prefix for an ``[x, y]`` location key, or None if ``key`` is not one."""
    if key == "location":
        return "loc"
    if key.endswith("Loc"):
        return to_snake(key)
    return None


def _flatten(record: dict[str, Any]) -> dict[str, Any]:
    """Snake-case the keys of one event and split ``[x, y]`` locations into ``_x``/``_y``."""
    row: dict[str, Any] = {}
    for key, value in record.items():
        prefix = _loc_prefix(key)
        if prefix is None:
            row[to_snake(key)] = value
        else:
            x, y = (None, None) if value is None else value
            row[f"{prefix}_x"] = x
            row[f"{prefix}_y"] = y
    return row


def _events_frame(records: list[dict[str, Any]], game_id: int) -> pl.DataFrame:
    if not records:
        return pl.DataFrame(schema={"id": pl.String, "game_id": pl.Int64})
    df = pl.from_dicts([_flatten(r) for r in records], infer_schema_length=None)
    coords = [c for c in df.columns if c.endswith(("_x", "_y")) and c[:-2].endswith("loc")]
    df = df.with_columns(pl.col(coords).cast(pl.Float64))
    if "game_id" not in df.columns:
        df = df.with_columns(pl.lit(game_id, dtype=pl.Int64).alias("game_id"))
    return df


def build_events(game_id: int, settings: Settings) -> dict[str, Path]:
    """Write one parquet per dynamic-events table of a game, with canonical player ids.

    Overwrites existing files. Returns the path written for each table.
    """
    raw = read_raw_json(settings.raw_path(dynamic_events_relpath(game_id)))
    aliases = load_aliases(settings)
    out: dict[str, Path] = {}
    for table in EVENT_TABLES:
        df = apply_aliases(_events_frame(raw.get(table, []), game_id), aliases)
        path = settings.events_parquet(game_id, table)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
        out[table] = path
    return out
