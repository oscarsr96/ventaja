"""Decision rankings (worst, best, lost moments) and the auto-generated reel (ADR-0006).

``rank_tables`` is the pure part: it ranks the valued decisions of some games from their
tables. ``rankings`` loads those tables; ``build_reel`` renders one possession clip per
ranked shot and writes a Spanish ``index.md`` (``viz/reel_index.py``).
"""

from pathlib import Path
from typing import Any

import polars as pl

from ventaja.config import FPS, Settings
from ventaja.data.load import (
    load_curve_summaries,
    load_curves,
    load_decision_options,
    load_decisions,
    load_meta,
)
from ventaja.decision.align import Aligner
from ventaja.decision.cost import decision_from_tables
from ventaja.decision.curve import headline
from ventaja.errors import DataNotFoundError, VentajaError
from ventaja.model.decision import CurveSummary
from ventaja.value.model import ValueModel
from ventaja.value.params import (
    CLIP_BEFORE_S,
    MIN_RANK_ADVANTAGE,
    MIN_RANK_CONFIDENCE,
    REEL_LATE_LEAD_S,
    REEL_LATE_MAX_BEFORE_S,
)
from ventaja.viz.clip import curve_of_shot, render_clip
from ventaja.viz.kit import jersey_labels, players_table
from ventaja.viz.reel_index import SECTIONS, UNAVAILABLE, write_index

__all__ = [
    "SECTIONS",
    "build_reel",
    "late_before_s",
    "rank_tables",
    "rankings",
    "skipped_clips",
]

Rankings = tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, int]

_BASE = [
    "rank",
    "shot_id",
    "game_id",
    "game_label",
    "shooter",
    "team",
    "period",
    "shot_clock",
    "rule",
    "shot_value",
    "best_alt_value",
    "best_alt_type",
    "best_alt_player",
]
_TAIL = [
    "verdict",
    "advantage_seconds",
    "release_lag_seconds",
    "headline_es",
    "confidence",
    "good_read",
    "held_to_decision",
    "decision_frame",
    "window_start",
    "window_handler",
]
_SUMMARY_COLUMNS = [
    "shot_id",
    "verdict",
    "advantage_seconds",
    "release_lag_seconds",
    "headline_es",
    "held_to_decision",
    "window_start",
    "window_handler_id",
    "window_peak_value",
    "n_rows",
    "span_start",
    "span_end",
    "peak_frame",
    "peak_value",
    "window_end",
    "value_at_decision",
]


def _names(players: pl.DataFrame | None) -> pl.DataFrame:
    """``(game_id, player_id) -> name, team_id`` (empty when there is no players table)."""
    schema = {"game_id": pl.Int64, "player_id": pl.Int64, "name": pl.String, "team_id": pl.Int64}
    if players is None:
        return pl.DataFrame(schema=schema)
    return players.select(
        "game_id",
        "player_id",
        name=pl.concat_str("first_name", pl.lit(" "), "last_name"),
        team_id="team_id",
    ).unique(["game_id", "player_id"], keep="first")


def _teams(games: pl.DataFrame | None) -> tuple[pl.DataFrame, pl.DataFrame]:
    """``(game_id, team_id) -> team`` and ``game_id -> game_label`` ("HOME–AWAY")."""
    if games is None:
        return (
            pl.DataFrame(schema={"game_id": pl.Int64, "team_id": pl.Int64, "team": pl.String}),
            pl.DataFrame(schema={"game_id": pl.Int64, "game_label": pl.String}),
        )
    teams = pl.concat(
        [
            games.select("game_id", team_id=f"{side}_team_id", team=f"{side}_team_name")
            for side in ("home", "away")
        ]
    )
    labels = games.select(
        "game_id", game_label=pl.concat_str("home_team_name", pl.lit("–"), "away_team_name")
    )
    return teams, labels


def _name_of(df: pl.DataFrame, names: pl.DataFrame, id_col: str, out: str) -> pl.DataFrame:
    """Join a player's name onto ``df`` by ``(game_id, id_col)``; the id when unknown."""
    hit = names.select("game_id", pl.col("player_id").alias(id_col), pl.col("name").alias(out))
    joined = df.join(hit, on=["game_id", id_col], how="left")
    return joined.with_columns(pl.coalesce(out, pl.col(id_col).cast(pl.String)).alias(out))


def _named_headlines(df: pl.DataFrame) -> pl.Series:
    """``headline_es`` with a late window of another handler named (``window_handler``).

    The stored headline names that handler by id (``build_curves`` has no names); every other
    headline is kept as stored.
    """
    out: list[str | None] = []
    for row in df.iter_rows(named=True):
        if row["verdict"] != "late" or row["window_handler_id"] == row["shooter_id"]:
            out.append(row["headline_es"])
            continue
        summary = CurveSummary.model_validate({f: row[f] for f in CurveSummary.model_fields})
        out.append(
            headline(
                summary, "es", shooter_id=row["shooter_id"], handler_name=row["window_handler"]
            )
        )
    return pl.Series("headline_es", out, dtype=pl.String)


def rank_tables(
    decisions: pl.DataFrame,
    summaries: pl.DataFrame,
    players: pl.DataFrame | None,
    games: pl.DataFrame | None,
    *,
    n: int,
) -> Rankings:
    """``(worst, best, late, excluded_low_confidence)`` from the decision and curve tables.

    Common filter: ``rule != "excluded"`` and ``confidence >= MIN_RANK_CONFIDENCE``;
    ``excluded_low_confidence`` counts the non-excluded decisions that fail the second.
    ``worst`` and ``best`` also need ``good_read`` not null (some pass was viable).
    ``worst``: largest ``cost``. ``best``: ``good_read`` with the largest ``margin =
    shot_value - best_alt_value``. ``late`` (lost moments): curve verdict ``late`` with
    ``held_to_decision`` and ``advantage_seconds >= MIN_RANK_ADVANTAGE``, by
    ``release_lag_seconds``; no viable pass is needed at the decision (the advantage has
    often closed by then). Each holds the top ``n`` (ties by ``shot_id``) with a 1-based
    ``rank``; names fall back to ids without metadata tables, and ``headline_es`` names the
    handler of a late window that is not the shooter's. Raises ValueError if ``n < 1``.
    """
    if n < 1:
        raise ValueError(f"n must be at least 1, got {n}")
    valued = decisions.filter(pl.col("rule") != "excluded")
    trusted = pl.col("confidence").fill_null(0.0) >= MIN_RANK_CONFIDENCE
    low = valued.filter(~trusted).height
    names = _names(players)
    teams, labels = _teams(games)
    df = (
        valued.filter(trusted)
        .join(summaries.select(_SUMMARY_COLUMNS), on="shot_id", how="left")
        .with_columns(
            period=pl.col("shot_id").str.split("-").list.get(2).cast(pl.Int64),
            margin=pl.col("shot_value") - pl.col("best_alt_value"),
        )
    )
    df = _name_of(df, names, "shooter_id", "shooter")
    df = _name_of(df, names, "best_alt_player_id", "best_alt_player")
    df = _name_of(df, names, "window_handler_id", "window_handler")
    df = df.with_columns(_named_headlines(df))
    shooter_team = names.select("game_id", shooter_id="player_id", team_id="team_id")
    df = (
        df.join(shooter_team, on=["game_id", "shooter_id"], how="left")
        .join(teams, on=["game_id", "team_id"], how="left")
        .join(labels, on="game_id", how="left")
        .with_columns(
            team=pl.coalesce("team", pl.col("team_id").cast(pl.String), pl.lit("—")),
            game_label=pl.coalesce("game_label", pl.col("game_id").cast(pl.String)),
        )
    )

    def top(frame: pl.DataFrame, by: str, columns: list[str]) -> pl.DataFrame:
        ranked = frame.sort([by, "shot_id"], descending=[True, False]).head(n)
        ranked = ranked.with_columns(rank=pl.int_range(1, ranked.height + 1, dtype=pl.Int64))
        return ranked.select(_BASE + columns + _TAIL)

    readable = df.filter(pl.col("good_read").is_not_null())
    worst = top(readable, "cost", ["cost"])
    best = top(readable.filter(pl.col("good_read")), "margin", ["margin"])
    late = top(
        df.filter(
            (pl.col("verdict") == "late")
            & pl.col("held_to_decision").fill_null(False)
            & (pl.col("advantage_seconds") >= MIN_RANK_ADVANTAGE)
        ),
        "release_lag_seconds",
        ["cost", "window_peak_value"],
    )
    return worst, best, late, low


def _games_table(settings: Settings) -> pl.DataFrame | None:
    try:
        return load_meta("games", settings)
    except DataNotFoundError:
        return None


def rankings(settings: Settings, game_ids: list[int], *, n: int = 10) -> Rankings:
    """``rank_tables`` over the decisions and curve summaries of ``game_ids``."""
    decisions = pl.concat([load_decisions(g, settings) for g in game_ids])
    summaries = pl.concat([load_curve_summaries(g, settings) for g in game_ids])
    return rank_tables(decisions, summaries, players_table(settings), _games_table(settings), n=n)


def late_before_s(*, decision_frame: int, window_start: int) -> float:
    """Seconds a lost-moment clip shows before the decision: back to the window, plus a lead."""
    lead = (decision_frame - window_start) / FPS + REEL_LATE_LEAD_S
    return min(REEL_LATE_MAX_BEFORE_S, max(CLIP_BEFORE_S, lead))


def _render_row(
    t: dict[str, Any],
    row: dict[str, Any],
    kind: str,
    out: Path,
    fps: int,
    labels: dict[int, str] | None,
) -> None:
    """Render one ranked shot's clip from its game's cached tables and aligner."""
    decision = decision_from_tables(row["shot_id"], t["decisions"], t["options"])
    curve, summary = curve_of_shot(row["shot_id"], t["curves"], t["summaries"])
    before_s = CLIP_BEFORE_S
    if kind == "late" and row["window_start"] is not None:
        before_s = late_before_s(
            decision_frame=row["decision_frame"], window_start=row["window_start"]
        )
    render_clip(
        t["aligner"],
        decision,
        curve,
        summary,
        out,
        before_s=before_s,
        fps=fps,
        labels=labels,
        handler_name=row["window_handler"],
    )


def skipped_clips(index: Path) -> int:
    """How many ranked shots of a written reel have no clip."""
    return sum(line.startswith(UNAVAILABLE) for line in index.read_text().splitlines())


def build_reel(
    settings: Settings, game_ids: list[int], *, n: int = 10, out_dir: Path, fps: int = 12
) -> Path:
    """Render one clip per row of the three rankings and write ``out_dir/index.md``.

    Clips are ``{rank:02d}-{worst|best|late}-{shot_id}.gif``; lost-moment clips start early
    enough to show the window (``late_before_s``), the others use the clip defaults. One
    ``Aligner`` per game is shared by every section. A clip that fails with a VentajaError
    (no tracking, missing curve, ...) is listed without a GIF, with the reason, and counted
    in the header (``skipped_clips``); ``index.md`` is always written. Returns its path.
    """
    worst, best, late, low = rankings(settings, game_ids, n=n)
    players = players_table(settings)
    tables: dict[int, dict[str, Any]] = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    gifs: dict[tuple[str, str], str] = {}
    failures: dict[tuple[str, str], str] = {}
    for kind, table in (("worst", worst), ("best", best), ("late", late)):
        for row in table.iter_rows(named=True):
            if row["rule"] == "excluded":  # rank_tables never yields one; never render it
                continue
            g = row["game_id"]
            if g not in tables:
                tables[g] = {
                    "aligner": Aligner(g, settings),
                    "decisions": load_decisions(g, settings),
                    "options": load_decision_options(g, settings),
                    "curves": load_curves(g, settings),
                    "summaries": load_curve_summaries(g, settings),
                }
            name = f"{row['rank']:02d}-{kind}-{row['shot_id']}.gif"
            try:
                _render_row(tables[g], row, kind, out_dir / name, fps, jersey_labels(players, g))
            except VentajaError as exc:
                failures[(kind, row["shot_id"])] = str(exc)
                continue
            gifs[(kind, row["shot_id"])] = name
    try:
        trained_at = ValueModel.default().trained_at or "—"
    except DataNotFoundError:
        trained_at = "—"
    path = out_dir / "index.md"
    labels = _teams(_games_table(settings))[1]
    games = [
        next(iter(labels.filter(pl.col("game_id") == g)["game_label"]), str(g)) for g in game_ids
    ]
    path.write_text(
        write_index(
            {"worst": worst, "best": best, "late": late},
            gifs,
            failures,
            game_ids=game_ids,
            game_labels=games,
            trained_at=trained_at,
            n=n,
            excluded_low_confidence=low,
        )
    )
    return path
