"""Loaders for raw metadata and built parquet tables, plus player-id canonicalisation."""

import json
from pathlib import Path
from typing import Any, Literal

import polars as pl

from ventaja.config import Settings
from ventaja.errors import DataNotFoundError
from ventaja.model.core import Game, Match, Player, Team

# Versioned outputs shipped with the repo (an editable install), like ``DEFAULT_MODEL_PATH``.
ARTIFACTS_DIR = Path(__file__).parents[3] / "artifacts"
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


def pull_hint(game_id: int | None = None) -> str:
    """The ``ventaja data pull`` command that downloads a game's files (or the common ones)."""
    return "`ventaja data pull`" if game_id is None else f"`ventaja data pull --game {game_id}`"


def require_raw(path: Path, game_id: int | None = None) -> Path:
    """Return ``path`` if it exists, else raise DataNotFoundError with a pull hint.

    Pass ``game_id`` for per-game files so the hint downloads that game, not only the
    common files.
    """
    if not path.exists():
        raise DataNotFoundError(f"{path} not found; run {pull_hint(game_id)} first")
    return path


def read_raw_json(path: Path, game_id: int | None = None) -> Any:
    """Parse a raw JSON file, raising DataNotFoundError with a hint if it is missing."""
    return json.loads(require_raw(path, game_id).read_text())


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
    raw = read_raw_json(settings.raw_path(game_data_relpath(game_id)), game_id)
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


def load_meta(table: str, settings: Settings) -> pl.DataFrame:
    """One built metadata table (``games``, ``players`` or ``matches``)."""
    path = settings.meta_parquet(table)
    if not path.exists():
        raise DataNotFoundError(f"{path} not found; run `ventaja data build --game ID` first")
    return pl.read_parquet(path)


def load_aggregates(name: str, settings: Settings) -> pl.DataFrame:
    """One built season-aggregate table (``shots``, ``drives`` or ``picks``)."""
    path = settings.aggregates_parquet(name)
    if not path.exists():
        raise DataNotFoundError(f"{path} not found; run `ventaja data build --game ID` first")
    return pl.read_parquet(path)


ArtifactKind = Literal["decisions", "curves", "players"]

# The per-game kinds keep ``{game_id}.parquet`` main tables with a secondary file next to each.
# ``players`` is not per game: its main table is ``players.parquet``, with ``teams.parquet`` next
# to it, and its packaged copy sits directly in ``artifacts/`` (not in ``artifacts/players/``).
_SECONDARY_SUFFIX: dict[str, str] = {
    "decisions": ".options.parquet",
    "curves": ".summary.parquet",
}
_BUILD_HINT: dict[ArtifactKind, str] = {
    "decisions": "decisions build",
    "curves": "curves build",
    "players": "player build",
}
PLAYERS_FILE = "players.parquet"
TEAMS_FILE = "teams.parquet"


def _main_tables(root: Path, kind: ArtifactKind) -> list[Path]:
    """Main tables of a directory: ``{game_id}.parquet`` (secondary files excluded), or
    ``players.parquet`` for ``players``."""
    if kind == "players":
        path = root / PLAYERS_FILE
        return [path] if path.exists() else []
    suffix = _SECONDARY_SUFFIX[kind]
    return [p for p in sorted(root.glob("[0-9]*.parquet")) if not p.name.endswith(suffix)]


def artifact_dir(kind: ArtifactKind, settings: Settings) -> Path:
    """The one directory every reader of ``kind`` uses, chosen once and never mixed.

    The build's ``{kind}/`` if it holds any main table, else the packaged ``artifacts/{kind}/``
    (``artifacts/`` itself for ``players``).
    """
    built = settings.build_dir / kind
    if _main_tables(built, kind):
        return built
    return ARTIFACTS_DIR if kind == "players" else ARTIFACTS_DIR / kind


def _artifact_files(kind: ArtifactKind, settings: Settings) -> tuple[list[Path], list[Path]]:
    root = artifact_dir(kind, settings)
    if kind == "players":
        return _main_tables(root, kind), sorted(root.glob(TEAMS_FILE))
    return _main_tables(root, kind), sorted(root.glob(f"*{_SECONDARY_SUFFIX[kind]}"))


def _artifact_table(
    game_id: int | None, kind: ArtifactKind, name: str, settings: Settings
) -> pl.DataFrame:
    path = artifact_dir(kind, settings) / name
    if not path.exists():
        games = "--all" if game_id is None else f"--game {game_id}"
        hint = _BUILD_HINT[kind] if kind == "players" else f"{_BUILD_HINT[kind]} {games}"
        raise DataNotFoundError(f"{path} not found; run `ventaja {hint}` first")
    return pl.read_parquet(path)


def decisions_dir(settings: Settings) -> Path:
    """``artifact_dir("decisions", settings)``: the build's decisions, else the packaged ones."""
    return artifact_dir("decisions", settings)


def decision_files(settings: Settings) -> tuple[list[Path], list[Path]]:
    """(decision, option) parquet files of ``decisions_dir``.

    Decision files are ``{game_id}.parquet``; option files are ``{game_id}.options.parquet``.
    """
    return _artifact_files("decisions", settings)


def load_decisions(game_id: int, settings: Settings) -> pl.DataFrame:
    """The decisions table of a game, from ``decisions_dir`` (no per-file fallback)."""
    return _artifact_table(game_id, "decisions", f"{game_id}.parquet", settings)


def load_decision_options(game_id: int, settings: Settings) -> pl.DataFrame:
    """The per-option table of a game's decisions, from ``decisions_dir``."""
    return _artifact_table(game_id, "decisions", f"{game_id}.options.parquet", settings)


def curve_files(settings: Settings) -> tuple[list[Path], list[Path]]:
    """(curve, summary) parquet files of ``artifact_dir("curves")``.

    Curve files are ``{game_id}.parquet``; summary files are ``{game_id}.summary.parquet``.
    """
    return _artifact_files("curves", settings)


def load_curves(game_id: int, settings: Settings) -> pl.DataFrame:
    """The per-frame advantage curves of a game's shots (no per-file fallback)."""
    return _artifact_table(game_id, "curves", f"{game_id}.parquet", settings)


def load_curve_summaries(game_id: int, settings: Settings) -> pl.DataFrame:
    """The one-row-per-shot curve summaries of a game (no per-file fallback)."""
    return _artifact_table(game_id, "curves", f"{game_id}.summary.parquet", settings)


def load_players_cards(settings: Settings) -> pl.DataFrame:
    """The flat player cards (one row per shooter plus ``LIGA``), from ``artifact_dir``."""
    return _artifact_table(None, "players", PLAYERS_FILE, settings)


def load_teams_cards(settings: Settings) -> pl.DataFrame:
    """The flat team cards, from ``artifact_dir("players")``."""
    return _artifact_table(None, "players", TEAMS_FILE, settings)
