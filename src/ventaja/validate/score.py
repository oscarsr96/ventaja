"""Rebuild each game's final score from shots and free throws and compare it to the official."""

from collections.abc import Iterable

import polars as pl

from ventaja.config import Settings
from ventaja.data.load import load_events, load_game, load_matches
from ventaja.errors import DataNotFoundError, VentajaError
from ventaja.model.core import Score


def reconstruct_score(game_id: int, settings: Settings) -> Score:
    """Points scored per team from made shots (2 or 3) and made free throws (1)."""
    shots = load_events(game_id, "shots", settings)
    free_throws = load_events(game_id, "free_throws", settings)
    points = (
        pl.concat(
            [
                shots.filter(pl.col("outcome")).select(
                    "off_team_id",
                    pl.when(pl.col("three")).then(3).otherwise(2).alias("points"),
                ),
                free_throws.filter(pl.col("outcome")).select("off_team_id", points=pl.lit(1)),
            ]
        )
        .group_by("off_team_id")
        .agg(pl.col("points").sum())
    )
    by_team: dict[int, int] = dict(
        zip(points["off_team_id"].to_list(), points["points"].to_list(), strict=True)
    )
    game = load_game(game_id, settings)
    known = {game.home.team_id, game.away.team_id}
    unknown = sorted(set(by_team) - known)
    if unknown:
        raise VentajaError(f"game {game_id}: events reference unknown team id(s) {unknown}")
    return Score(home=by_team.get(game.home.team_id, 0), away=by_team.get(game.away.team_id, 0))


def check_scores(
    game_ids: Iterable[int], settings: Settings
) -> list[tuple[int, Score, Score, bool]]:
    """Per game: (id, reconstructed score, official score, whether they match)."""
    official = {
        m.game_id: Score(home=m.home_score, away=m.away_score) for m in load_matches(settings)
    }
    rows: list[tuple[int, Score, Score, bool]] = []
    for game_id in game_ids:
        if game_id not in official:
            raise DataNotFoundError(f"game {game_id} not found in matches.json")
        got = reconstruct_score(game_id, settings)
        rows.append((game_id, got, official[game_id], got == official[game_id]))
    return rows
