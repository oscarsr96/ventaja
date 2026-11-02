"""Player and team cards (layer 3): build, flat parquet artifacts and player lookup.

The card models live in ``model/card.py``.

``players.parquet`` holds one row per shooter with at least one valued decision plus the league
row (``player_id = 0``, ``name = "LIGA"``, null team), so the ranking and the phrase have the
league at hand. Every card scalar is a column; the dict blocks are flattened with the prefixes
``clock_{bucket}_{n,cost}``, ``alt_{type}_{n,cost}``, ``season_*``, ``tracked_*`` and ``shift_*``.
"""

import unicodedata
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from ventaja.config import Settings
from ventaja.data.build import _write_parquet_atomic
from ventaja.data.load import (
    decision_files,
    load_aggregates,
    load_curve_summaries,
    load_decision_options,
    load_decisions,
    load_meta,
)
from ventaja.errors import DataNotFoundError
from ventaja.model.card import PlayerCard, TeamCard
from ventaja.profile.aggregate import league_row, player_table, team_table
from ventaja.profile.phrase import profile_phrase
from ventaja.profile.season import (
    MAIN_ZONES,
    SEASON_INT_KEYS,
    SEASON_KEYS,
    season_profile,
    tracked_zone_mix,
    zone_shift,
)
from ventaja.value.model import ValueModel
from ventaja.value.params import ALT_TYPES, CLOCK_BUCKETS

__all__ = [
    "LEAGUE_ID",
    "LEAGUE_NAME",
    "PLAYERS_SCHEMA",
    "TEAMS_SCHEMA",
    "PlayerCard",
    "TeamCard",
    "build_players",
    "card_of",
    "find_player",
    "fold_name",
    "flatten_card",
    "league_season_shares",
    "team_card_of",
]

LEAGUE_ID = 0
LEAGUE_NAME = "LIGA"
BUCKETS: tuple[str, ...] = tuple(label for label, _, _ in CLOCK_BUCKETS)

_INT, _FLOAT, _STR = pl.Int64(), pl.Float64(), pl.String()
_METRICS: dict[str, pl.DataType] = {
    "n_shots": _INT,
    "n_readable": _INT,
    "n_low_confidence": _INT,
    "n_clock_known": _INT,
    "n_with_summary": _INT,
    "n_during": _INT,
    "n_late_held": _INT,
    "good_read_share": _FLOAT,
    "mean_shot_value": _FLOAT,
    "mean_best_alt_value": _FLOAT,
    "mean_cost": _FLOAT,
    "total_cost": _FLOAT,
    "mean_confidence": _FLOAT,
    "ignored_alt": _STR,
    "late_held_share": _FLOAT,
    "mean_lag_held": _FLOAT,
    "during_share": _FLOAT,
}
_BLOCKS: dict[str, pl.DataType] = {
    **{k: v for b in BUCKETS for k, v in ((f"clock_{b}_n", _INT), (f"clock_{b}_cost", _FLOAT))},
    **{k: v for a in ALT_TYPES for k, v in ((f"alt_{a}_n", _INT), (f"alt_{a}_cost", _FLOAT))},
}
_TRACKED_KEYS = (*(f"tracked_zone_share_{z}" for z in MAIN_ZONES), "tracked_zone_share_other")
_SHIFT_KEYS = tuple(f"shift_{z}" for z in MAIN_ZONES)
_STAMPS: dict[str, pl.DataType] = {"built_at": _STR, "model_trained_at": _STR}
_GAMES = pl.List(pl.Int64())

PLAYERS_SCHEMA: dict[str, pl.DataType] = {
    "player_id": _INT,
    "name": _STR,
    "team_id": _INT,
    "team": _STR,
    "games": _GAMES,
    **_METRICS,
    **_BLOCKS,
    **{k: _INT if k in SEASON_INT_KEYS else _FLOAT for k in SEASON_KEYS},
    **dict.fromkeys(_TRACKED_KEYS, _FLOAT),
    "tracked_attempts": _INT,
    **dict.fromkeys(_SHIFT_KEYS, _FLOAT),
    "phrase_es": _STR,
    "phrase_en": _STR,
    **_STAMPS,
}
TEAMS_SCHEMA: dict[str, pl.DataType] = {
    "team_id": _INT,
    "team": _STR,
    "n_players": _INT,
    "players": _GAMES,
    "games": _GAMES,
    **_METRICS,
    **_BLOCKS,
    **_STAMPS,
}


def _metrics_of(agg: dict[str, Any], stamps: dict[str, str]) -> dict[str, Any]:
    """Card metric fields (and stamps) from a ``player_table``/``team_table``/``league_row`` row."""
    out = {k: agg[k] for k in _METRICS} | stamps
    out["clock"] = {b: (agg[f"n_{b}"], agg[f"cost_{b}"]) for b in BUCKETS}
    out["alternatives"] = {a: (agg[f"n_alt_{a}"], agg[f"cost_alt_{a}"]) for a in ALT_TYPES}
    return out


def _flat_metrics(card: PlayerCard | TeamCard) -> dict[str, Any]:
    out: dict[str, Any] = {k: getattr(card, k) for k in _METRICS}
    for b, (n, cost) in card.clock.items():
        out[f"clock_{b}_n"], out[f"clock_{b}_cost"] = n, cost
    for a, (n, cost) in card.alternatives.items():
        out[f"alt_{a}_n"], out[f"alt_{a}_cost"] = n, cost
    return out


def _metrics_from_flat(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: row[k] for k in (*_METRICS, *_STAMPS, "games")}
    out["clock"] = {b: (row[f"clock_{b}_n"], row[f"clock_{b}_cost"]) for b in BUCKETS}
    out["alternatives"] = {a: (row[f"alt_{a}_n"], row[f"alt_{a}_cost"]) for a in ALT_TYPES}
    return out


def flatten_card(card: PlayerCard | TeamCard) -> dict[str, Any]:
    """The flat row of a card, in ``PLAYERS_SCHEMA``/``TEAMS_SCHEMA`` column order."""
    flat = _flat_metrics(card)
    stamps = {"built_at": card.built_at, "model_trained_at": card.model_trained_at}
    if isinstance(card, TeamCard):
        head = {k: getattr(card, k) for k in ("team_id", "team", "n_players", "players", "games")}
        row = head | flat | stamps
        return {k: row[k] for k in TEAMS_SCHEMA}
    head = {k: getattr(card, k) for k in ("player_id", "name", "team_id", "team", "games")}
    tail = {"phrase_es": card.phrase_es, "phrase_en": card.phrase_en} | stamps
    row = head | flat | card.season | card.tracked_zone | card.zone_shift | tail
    return {k: row[k] for k in PLAYERS_SCHEMA}


def card_of(player_id: int, players: pl.DataFrame) -> PlayerCard:
    """Rebuild a ``PlayerCard`` (dict blocks included) from the flat ``players`` table."""
    hit = players.filter(pl.col("player_id") == player_id)
    if hit.height == 0:
        raise DataNotFoundError(f"player {player_id} not found in the player cards")
    row = hit.row(0, named=True)
    return PlayerCard(
        **_metrics_from_flat(row),
        **{k: row[k] for k in ("player_id", "name", "team_id", "team", "phrase_es", "phrase_en")},
        season={k: row[k] for k in SEASON_KEYS},
        tracked_zone={k: row[k] for k in (*_TRACKED_KEYS, "tracked_attempts")},
        zone_shift={k: row[k] for k in _SHIFT_KEYS},
    )


def team_card_of(team_id: int, teams: pl.DataFrame) -> TeamCard:
    """Rebuild a ``TeamCard`` from the flat ``teams`` table."""
    hit = teams.filter(pl.col("team_id") == team_id)
    if hit.height == 0:
        raise DataNotFoundError(f"team {team_id} not found in the team cards")
    row = hit.row(0, named=True)
    keys = ("team_id", "team", "n_players", "players")
    return TeamCard(**_metrics_from_flat(row), **{k: row[k] for k in keys})


def league_season_shares(shots_agg: pl.DataFrame) -> dict[str, float | None]:
    """League catch-and-shoot and contested shares of season attempts (per-team rows only)."""
    rows = shots_agg.filter(pl.col("team_id").is_not_null())
    att = float(rows["attempts"].sum())
    return {
        "season_cns_share": float(rows["cns_attempts"].sum()) / att if att else None,
        "season_contested_share": float(rows["contested_attempts"].sum()) / att if att else None,
    }


def fold_name(text: str) -> str:
    """Lower case without accents (NFKD with the combining marks stripped)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _team_names(games_meta: pl.DataFrame | None) -> dict[int, str]:
    if games_meta is None:
        return {}
    names: dict[int, str] = {}
    for r in games_meta.iter_rows(named=True):
        names[r["home_team_id"]] = r["home_team_name"]
        names[r["away_team_id"]] = r["away_team_name"]
    return names


def _directory(
    players: pl.DataFrame, games_meta: pl.DataFrame | None
) -> list[tuple[int, str, str]]:
    """(id, name, team) of every player of ``players``: a cards table or ``meta/players``."""
    if "name" in players.columns:
        cards = players.filter(pl.col("player_id") != LEAGUE_ID)
        return [(i, n, t or "") for i, n, t in cards.select("player_id", "name", "team").rows()]
    teams = _team_names(games_meta)
    first = players.sort("game_id").unique(subset="player_id", keep="first", maintain_order=True)
    return [
        (
            r["player_id"],
            f"{r['first_name']} {r['last_name']}",
            teams.get(r["team_id"], str(r["team_id"])),
        )
        for r in first.iter_rows(named=True)
    ]


def find_player(
    query: str, players_meta: pl.DataFrame, games_meta: pl.DataFrame | None = None
) -> list[tuple[int, str, str]]:
    """Players matching ``query``: an exact id first, else a substring of "First Last".

    The substring match ignores case and accents. ``players_meta`` is ``meta/players`` (team
    names from ``games_meta`` when given, else the team id) or the player cards table (the
    ``LIGA`` row is never returned). Sorted by name.
    """
    directory = _directory(players_meta, games_meta)
    q = query.strip()
    if q.isdigit():
        exact = [r for r in directory if r[0] == int(q)]
        if exact:
            return exact
    folded = fold_name(q)
    hits = [r for r in directory if folded in fold_name(r[1])]
    return sorted(hits, key=lambda r: (fold_name(r[1]), r[0]))


def _concat(frames: list[pl.DataFrame]) -> pl.DataFrame:
    return pl.concat(frames, how="vertical_relaxed")


def _optional(load: Callable[[], pl.DataFrame]) -> pl.DataFrame | None:
    try:
        return load()
    except DataNotFoundError:
        return None


def _write(
    cards: Sequence[PlayerCard | TeamCard], schema: dict[str, pl.DataType], path: Path
) -> None:
    _write_parquet_atomic(pl.DataFrame([flatten_card(c) for c in cards], schema=schema), path)


def build_players(
    settings: Settings, *, out_dir: Path | None = None, model: ValueModel | None = None
) -> tuple[Path, Path]:
    """Build ``players.parquet`` and ``teams.parquet`` from every game with decisions.

    Decisions, curve summaries and options of the games in ``artifact_dir("decisions")`` are
    concatenated. Players are the shooters with at least one valued decision; name and team come
    from ``meta/players`` (the id as name and no team without it), team names from
    ``meta/games``. The season block needs the shots aggregate; drives are optional.
    ``model_trained_at`` is ``model.trained_at`` (default: the versioned model). Written
    atomically to ``out_dir`` (default: the build's ``players/``).
    """
    games = [int(p.stem) for p in decision_files(settings)[0]]
    if not games:
        raise DataNotFoundError("no decisions found; run `ventaja decisions build --all` first")
    decisions = _concat([load_decisions(g, settings) for g in games])
    summaries = _concat([load_curve_summaries(g, settings) for g in games])
    options = _concat([load_decision_options(g, settings) for g in games])
    shots_agg = load_aggregates("shots", settings)
    drives_agg = _optional(lambda: load_aggregates("drives", settings))
    meta = _optional(lambda: load_meta("players", settings))
    team_names = _team_names(_optional(lambda: load_meta("games", settings)))
    stamps = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model_trained_at": (model if model is not None else ValueModel.default()).trained_at,
    }

    valued = decisions.filter(pl.col("rule") != "excluded")
    shot_games = valued.group_by("shooter_id").agg(pl.col("game_id").unique().sort())
    games_of = dict(shot_games.rows())
    roster: dict[int, tuple[str, int]] = {}
    if meta is not None:
        mine = meta.join(
            valued.select("game_id", "shooter_id").unique(),
            left_on=["game_id", "player_id"],
            right_on=["game_id", "shooter_id"],
        )
        for r in mine.sort("game_id").iter_rows(named=True):
            roster.setdefault(r["player_id"], (f"{r['first_name']} {r['last_name']}", r["team_id"]))

    league = league_row(decisions, summaries) | league_season_shares(shots_agg)
    cards = [
        PlayerCard(
            **_metrics_of(league, stamps),
            games=sorted(games),
            player_id=LEAGUE_ID,
            name=LEAGUE_NAME,
            team_id=None,
            team=None,
            season=dict.fromkeys(SEASON_KEYS) | league_season_shares(shots_agg),
            tracked_zone=dict.fromkeys((*_TRACKED_KEYS, "tracked_attempts")),
            zone_shift=dict.fromkeys(_SHIFT_KEYS),
            phrase_es=None,
            phrase_en=None,
        )
    ]
    for agg in player_table(decisions, summaries).iter_rows(named=True):
        pid = agg["player_id"]
        season = season_profile(pid, shots_agg, drives_agg)
        tracked = tracked_zone_mix(pid, options)
        shift = zone_shift(season, tracked)
        flat = agg | season | tracked | shift
        name, team_id = roster.get(pid, (str(pid), None))
        cards.append(
            PlayerCard(
                **_metrics_of(agg, stamps),
                games=games_of[pid],
                player_id=pid,
                name=name,
                team_id=team_id,
                team=None if team_id is None else team_names.get(team_id),
                season=season,
                tracked_zone=dict(tracked),
                zone_shift=shift,
                phrase_es=profile_phrase(flat, league, lang="es"),
                phrase_en=profile_phrase(flat, league, lang="en"),
            )
        )

    teams: list[TeamCard] = []
    if meta is not None:
        members = meta.select("game_id", "team_id", pl.col("player_id").alias("shooter_id"))
        on_team = valued.join(
            members.unique(subset=["game_id", "shooter_id"]), on=["game_id", "shooter_id"]
        )
        for agg in team_table(decisions, summaries, meta).iter_rows(named=True):
            tid = agg["team_id"]
            mine = on_team.filter(pl.col("team_id") == tid)
            teams.append(
                TeamCard(
                    **_metrics_of(agg, stamps),
                    games=sorted(mine["game_id"].unique().to_list()),
                    team_id=tid,
                    team=team_names.get(tid),
                    n_players=agg["n_players"],
                    players=sorted(mine["shooter_id"].unique().to_list()),
                )
            )

    out = out_dir if out_dir is not None else settings.players_parquet().parent
    players_path, teams_path = out / "players.parquet", out / "teams.parquet"
    _write(cards, PLAYERS_SCHEMA, players_path)
    _write(teams, TEAMS_SCHEMA, teams_path)
    return players_path, teams_path
