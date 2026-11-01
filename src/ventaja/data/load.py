"""Loaders for raw metadata and built parquet tables, plus player-id canonicalisation."""

import json
from pathlib import Path
from typing import Any

import polars as pl

from ventaja.config import Settings
from ventaja.errors import DataNotFoundError
from ventaja.model.core import Game, Match, Player, Team

ALIASES_FILE = "player_id_aliases.csv"
MATCHES_FILE = "matches.json"

# Columns ending in ``_id`` that are not player ids: the game id and event-id references.
# Team ids (``team_id`` and every ``*_team_id``) are excluded by suffix.
_NON_PLAYER_ID_COLUMNS = frozenset(
    {
        "game_id",
        "id",
        "chance_id",
        "possession_id",
        "touch_id",
        "foul_id",
        "shot_id",
        "last_chance_id",
    }
)
_PLAYER_ID_LIST_COLUMNS = frozenset({"off_player_ids", "def_player_ids"})


def game_data_relpath(game_id: int) -> str:
    """Relative path of a game's game_data.json inside data_dir."""
    return f"matches/{game_id}/{game_id}_game_data.json"


def require_raw(path: Path) -> Path:
    """Return ``path`` if it exists, else raise DataNotFoundError with a pull hint."""
    if not path.exists():
        raise DataNotFoundError(f"{path} not found; run `ventaja data pull` first")
    return path


def read_raw_json(path: Path) -> Any:
    """Parse a raw JSON file, raising DataNotFoundError with a hint if it is missing."""
    return json.loads(require_raw(path).read_text())


def load_aliases(settings: Settings) -> dict[int, int]:
    """Map player_id -> canonical_player_id, only for rows where they differ."""
    df = pl.read_csv(
        require_raw(settings.raw_path(ALIASES_FILE)),
        columns=["player_id", "canonical_player_id"],
        schema_overrides={"player_id": pl.Int64, "canonical_player_id": pl.Int64},
    ).filter(pl.col("player_id") != pl.col("canonical_player_id"))
    return dict(zip(df["player_id"].to_list(), df["canonical_player_id"].to_list(), strict=True))


def canonical(player_id: int, aliases: dict[int, int]) -> int:
    """Canonical id of a player."""
    return aliases.get(player_id, player_id)


def _is_player_id_column(name: str, dtype: pl.DataType) -> bool:
    is_team_id = name == "team_id" or name.endswith("_team_id")
    return (
        name.endswith("_id")
        and not is_team_id
        and name not in _NON_PLAYER_ID_COLUMNS
        and dtype.is_integer()
    )


def apply_aliases(df: pl.DataFrame, aliases: dict[int, int]) -> pl.DataFrame:
    """Replace player ids by their canonical ids.

    Applies to every integer column whose name ends in ``_id`` (except ``game_id``, team ids
    such as ``team_id`` / ``*_team_id``, and event-id columns) and to
    the list columns ``off_player_ids`` / ``def_player_ids``.
    """
    if not aliases:
        return df
    exprs: list[pl.Expr] = []
    for name, dtype in df.schema.items():
        if _is_player_id_column(name, dtype):
            exprs.append(pl.col(name).replace(aliases))
        elif name in _PLAYER_ID_LIST_COLUMNS and isinstance(dtype, pl.List):
            exprs.append(pl.col(name).list.eval(pl.element().replace(aliases)))
    return df.with_columns(exprs) if exprs else df


def load_matches(settings: Settings) -> list[Match]:
    """All entries of matches.json."""
    raw = read_raw_json(settings.raw_path(MATCHES_FILE))
    return [
        Match(
            game_id=m["id"],
            date_time=m["date_time"],
            home_team_id=m["home_team"]["id"],
            away_team_id=m["away_team"]["id"],
            home_score=m["home_score"],
            away_score=m["away_score"],
        )
        for m in raw
    ]


def _team(raw: dict[str, Any], aliases: dict[int, int]) -> Team:
    return Team(
        team_id=raw["teamId"],
        name=raw["teamName"],
        players=[
            Player(
                player_id=canonical(p["playerId"], aliases),
                first_name=p["firstName"],
                last_name=p["lastName"],
                jersey=p["jersey"],
            )
            for p in raw["players"]
        ],
    )


def load_game(game_id: int, settings: Settings) -> Game:
    """Metadata and rosters of one game, with canonical player ids."""
    raw = read_raw_json(settings.raw_path(game_data_relpath(game_id)))
    aliases = load_aliases(settings)
    return Game(
        game_id=raw["gameId"],
        date=raw["date"],
        season=raw["seasonName"],
        home=_team(raw["homeTeam"], aliases),
        away=_team(raw["awayTeam"], aliases),
    )


def load_events(game_id: int, table: str, settings: Settings) -> pl.DataFrame:
    """One built dynamic-events table of a game."""
    path = settings.events_parquet(game_id, table)
    if not path.exists():
        raise DataNotFoundError(
            f"{path} not found; run `ventaja data build --game {game_id}` first"
        )
    return pl.read_parquet(path)


def load_tracking(game_id: int, settings: Settings) -> pl.LazyFrame:
    """The built long-format tracking table of a game, scanned lazily."""
    path = settings.tracking_parquet(game_id)
    if not path.exists():
        raise DataNotFoundError(
            f"{path} not found; run `ventaja data build --game {game_id}` first"
        )
    return pl.scan_parquet(path)


def frame_range(game_id: int, settings: Settings) -> tuple[int, int]:
    """First and last ``frame_idx`` with tracking data in a game."""
    row = (
        load_tracking(game_id, settings)
        .select(lo=pl.col("frame_idx").min(), hi=pl.col("frame_idx").max())
        .collect()
        .row(0)
    )
    return int(row[0]), int(row[1])
