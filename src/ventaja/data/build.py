"""Build layer: convert raw SkillCorner files into tidy parquet tables."""

import gzip
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import polars as pl

from ventaja.config import Settings
from ventaja.data.load import (
    apply_aliases,
    load_aliases,
    load_game,
    load_matches,
    pull_hint,
    read_raw_json,
    require_raw,
)
from ventaja.errors import CorruptFileError

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

TRACKING_SCHEMA = pl.Schema(
    {
        "game_id": pl.Int64(),
        "frame_idx": pl.Int64(),
        "wall_clock": pl.Int64(),
        "game_clock": pl.Float64(),
        "game_clock_stopped": pl.Boolean(),
        "period": pl.Int64(),
        "shot_clock": pl.Float64(),
        "side": pl.Enum(["home", "away", "ball"]),
        "player_id": pl.Int64(),
        "jersey": pl.String(),
        "x": pl.Float64(),
        "y": pl.Float64(),
        "z": pl.Float64(),
        "speed": pl.Float64(),
        "is_detected": pl.Boolean(),
        "pred_error": pl.Float64(),
    }
)
TRACKING_BATCH_FRAMES = 50_000

AGGREGATE_TABLES: tuple[str, ...] = ("shots", "drives", "picks")
AGGREGATES_DIR = "aggregates"
AGGREGATES_SEASON = "20252026"

GAMES_SCHEMA = pl.Schema(
    {
        "game_id": pl.Int64(),
        "date": pl.Datetime("us", "UTC"),
        "season": pl.String(),
        "home_team_id": pl.Int64(),
        "home_team_name": pl.String(),
        "away_team_id": pl.Int64(),
        "away_team_name": pl.String(),
    }
)
PLAYERS_SCHEMA = pl.Schema(
    {
        "game_id": pl.Int64(),
        "team_id": pl.Int64(),
        "player_id": pl.Int64(),
        "first_name": pl.String(),
        "last_name": pl.String(),
        "jersey": pl.String(),
    }
)
MATCHES_SCHEMA = pl.Schema(
    {
        "game_id": pl.Int64(),
        "date_time": pl.Datetime("us", "UTC"),
        "home_team_id": pl.Int64(),
        "away_team_id": pl.Int64(),
        "home_score": pl.Int64(),
        "away_score": pl.Int64(),
    }
)

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def dynamic_events_relpath(game_id: int) -> str:
    """Relative path of a game's dynamic_events.json inside data_dir."""
    return f"matches/{game_id}/{game_id}_dynamic_events.json"


def tracking_relpath(game_id: int) -> str:
    """Relative path of a game's 25 fps tracking JSONL (gzipped) inside data_dir."""
    return f"matches/{game_id}/{game_id}_tracking_data.jsonl.gz"


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
    raw = read_raw_json(settings.raw_path(dynamic_events_relpath(game_id)), game_id)
    aliases = load_aliases(settings)
    out: dict[str, Path] = {}
    for table in EVENT_TABLES:
        df = apply_aliases(_events_frame(raw.get(table, []), game_id), aliases)
        path = settings.events_parquet(game_id, table)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
        out[table] = path
    return out


class _TrackingColumns:
    """Column-wise accumulator of long-format tracking rows (one row per player/ball)."""

    def __init__(self) -> None:
        self.columns: dict[str, list[Any]] = {name: [] for name in TRACKING_SCHEMA.names()}

    def add_frame(self, game_id: int, frame: dict[str, Any]) -> None:
        """Append one row per home player, away player and ball; empty frames add nothing."""
        entities: list[tuple[str, dict[str, Any]]] = [
            *(("home", p) for p in frame["homePlayers"]),
            *(("away", p) for p in frame["awayPlayers"]),
        ]
        if frame["ball"]:
            entities.append(("ball", frame["ball"]))
        cols = self.columns
        for side, entity in entities:
            x, y, z = entity["xyz"]
            cols["game_id"].append(game_id)
            cols["frame_idx"].append(frame["frameIdx"])
            cols["wall_clock"].append(frame["wallClock"])
            cols["game_clock"].append(frame["gameClock"])
            cols["game_clock_stopped"].append(frame["gameClockStopped"])
            cols["period"].append(frame["period"])
            cols["shot_clock"].append(frame["shotClock"])
            cols["side"].append(side)
            cols["player_id"].append(entity.get("playerId"))
            cols["jersey"].append(entity.get("jersey"))
            cols["x"].append(x)
            cols["y"].append(y)
            cols["z"].append(z)
            cols["speed"].append(entity["speed"])
            cols["is_detected"].append(bool(entity["isDetected"]))
            cols["pred_error"].append(entity["predError"])

    def to_frame(self) -> pl.DataFrame:
        return pl.DataFrame(self.columns, schema=TRACKING_SCHEMA)


def _tracking_frames(path: Path) -> Iterator[dict[str, Any]]:
    """Stream the JSON objects of a gzipped JSONL file, one per line."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def _tracking_batches(path: Path, game_id: int) -> Iterator[pl.DataFrame]:
    """Long-format DataFrames, one per batch of ``TRACKING_BATCH_FRAMES`` raw frames."""
    acc = _TrackingColumns()
    for n, frame in enumerate(_tracking_frames(path), start=1):
        acc.add_frame(game_id, frame)
        if n % TRACKING_BATCH_FRAMES == 0:
            yield acc.to_frame()
            acc = _TrackingColumns()
    yield acc.to_frame()


def build_tracking(game_id: int, settings: Settings) -> Path:
    """Write the long-format tracking parquet of a game: one row per player or ball per frame.

    Empty frames (dead time, broadcast cuts) produce no rows. Player ids are canonical.
    Overwrites an existing file; a truncated or corrupt gzip raises CorruptFileError and
    leaves no parquet behind.
    """
    raw = require_raw(settings.raw_path(tracking_relpath(game_id)), game_id)
    aliases = load_aliases(settings)
    out = settings.tracking_parquet(game_id)
    out.unlink(missing_ok=True)
    try:
        batches = [apply_aliases(b, aliases) for b in _tracking_batches(raw, game_id)]
    except (EOFError, OSError, json.JSONDecodeError) as exc:
        raise CorruptFileError(
            f"{raw} is truncated or corrupt ({exc}); run {pull_hint(game_id)} to download it again"
        ) from exc
    out.parent.mkdir(parents=True, exist_ok=True)
    pl.concat(batches).write_parquet(out)
    return out


def _write_parquet_atomic(df: pl.DataFrame, path: Path) -> None:
    """Write ``df`` to a ``.tmp`` sibling and rename it, so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.write_parquet(tmp)
    tmp.replace(path)


def _accumulate(new: pl.DataFrame, path: Path, game_id: int) -> pl.DataFrame:
    """``new`` appended to the rows already at ``path`` for other games (idempotent per game)."""
    if not path.exists():
        return new
    kept = pl.read_parquet(path).filter(pl.col("game_id") != game_id)
    return pl.concat([kept, new]).sort("game_id")


def build_meta(game_id: int, settings: Settings) -> dict[str, Path]:
    """Write the ``games``, ``players`` and ``matches`` metadata tables.

    ``games`` and ``players`` accumulate one game at a time: rows of ``game_id`` are replaced,
    those of other games kept. ``matches`` is rebuilt whole from matches.json. Player ids are
    canonical. Returns the path written for each table.
    """
    game = load_game(game_id, settings)
    games = pl.DataFrame(
        [
            {
                "game_id": game.game_id,
                "date": game.date,
                "season": game.season,
                "home_team_id": game.home.team_id,
                "home_team_name": game.home.name,
                "away_team_id": game.away.team_id,
                "away_team_name": game.away.name,
            }
        ],
        schema=GAMES_SCHEMA,
    )
    players = pl.DataFrame(
        [
            {"game_id": game.game_id, "team_id": team.team_id, **p.model_dump()}
            for team in (game.home, game.away)
            for p in team.players
        ],
        schema=PLAYERS_SCHEMA,
    )
    matches = pl.DataFrame([m.model_dump() for m in load_matches(settings)], schema=MATCHES_SCHEMA)
    out: dict[str, Path] = {}
    for table, df in (("games", games), ("players", players), ("matches", matches)):
        path = settings.meta_parquet(table)
        if table != "matches":
            df = _accumulate(df, path, game_id)
        _write_parquet_atomic(df, path)
        out[table] = path
    return out


def aggregates_csv_relpath(name: str) -> str:
    """Relative path of a season-aggregate CSV inside data_dir."""
    return f"{AGGREGATES_DIR}/acb_{name}aggregates_{AGGREGATES_SEASON}.csv"


def build_aggregates(settings: Settings) -> dict[str, Path]:
    """Convert the season-aggregate CSVs present in data_dir to parquet, ids canonical.

    A missing CSV is skipped (it is simply absent from the result). A null ``team_id``
    (season-total rows of players with several teams) is preserved.
    """
    aliases = load_aliases(settings)
    out: dict[str, Path] = {}
    for name in AGGREGATE_TABLES:
        csv = settings.raw_path(aggregates_csv_relpath(name))
        if not csv.exists():
            continue
        df = apply_aliases(pl.read_csv(csv, infer_schema_length=None), aliases)
        path = settings.aggregates_parquet(name)
        _write_parquet_atomic(df, path)
        out[name] = path
    return out
