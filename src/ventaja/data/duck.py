"""DuckDB connection with one view per built parquet table."""

import duckdb

from ventaja.config import Settings
from ventaja.data.build import AGGREGATE_TABLES, EVENT_TABLES
from ventaja.data.load import (
    PLAYERS_FILE,
    TEAMS_FILE,
    artifact_dir,
    curve_files,
    decision_files,
    frame_files,
)

META_TABLES: tuple[str, ...] = ("games", "players", "matches")


def _quote(path: object) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _create_view(con: duckdb.DuckDBPyConnection, name: str, files: list[str], union: bool) -> None:
    if not files:
        return
    listing = ", ".join(_quote(f) for f in sorted(files))
    options = ", union_by_name=true" if union else ""
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet([{listing}]{options})")


def connect(settings: Settings, *, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB with a view per built table (events, tracking, meta, aggregates).

    Tables without any built parquet get no view; ``decisions`` and ``decision_options``
    read ``decisions_dir`` (the build's decisions, else the packaged
    ``artifacts/decisions/``); ``curves`` and ``curve_summaries`` likewise read
    ``artifact_dir("curves")``; ``frames`` reads ``artifact_dir("frames")``; ``player_cards``
    and ``team_cards`` read ``artifact_dir("players")``. Views are the only objects created;
    ``read_only`` is kept for API stability (the connection is in-memory and nothing is
    persisted either way).
    """
    del read_only
    con = duckdb.connect()
    build = settings.build_dir
    for table in EVENT_TABLES:
        files = [str(p) for p in (build / "events").glob(f"*/{table}.parquet")]
        _create_view(con, table, files, union=True)
    tracking = [str(p) for p in (build / "tracking").glob("*.parquet")]
    _create_view(con, "tracking", tracking, union=True)
    for table in META_TABLES:
        _create_view(con, table, [str(p) for p in build.glob(f"meta/{table}.parquet")], union=False)
    for name in AGGREGATE_TABLES:
        files = [str(p) for p in build.glob(f"aggregates/{name}.parquet")]
        _create_view(con, f"agg_{name}", files, union=False)
    decisions, options = decision_files(settings)
    _create_view(con, "decisions", [str(p) for p in decisions], union=True)
    _create_view(con, "decision_options", [str(p) for p in options], union=True)
    curves, summaries = curve_files(settings)
    _create_view(con, "curves", [str(p) for p in curves], union=True)
    _create_view(con, "curve_summaries", [str(p) for p in summaries], union=True)
    _create_view(con, "frames", [str(p) for p in frame_files(settings)], union=True)
    cards = artifact_dir("players", settings)
    for view, name in (("player_cards", PLAYERS_FILE), ("team_cards", TEAMS_FILE)):
        _create_view(con, view, [str(p) for p in cards.glob(name)], union=False)
    return con
