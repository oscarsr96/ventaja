"""The ask service: pure queries over the packaged artifacts, no MCP imports.

It loads the decisions, curve summaries, player and team cards, games and people once and
answers games, rankings and player profiles with ids that always travel with their names.
"""

from typing import Any

import polars as pl

from ventaja.config import Settings
from ventaja.data.load import (
    curve_files,
    decision_files,
    load_curve_summaries,
    load_decisions,
    load_games,
    load_players_cards,
    load_roster,
    load_teams_cards,
)
from ventaja.data.people import People, load_people
from ventaja.decision.curve import SUMMARY_SCHEMA
from ventaja.errors import AmbiguousQueryError, DataNotFoundError
from ventaja.mcp.models import (
    Alternative,
    ClockBand,
    GameInfo,
    GameSide,
    Metrics,
    PlayerProfile,
    PlayerRef,
    RankedPlayer,
    Ranking,
    TeamRef,
)
from ventaja.profile.card import LEAGUE_ID, card_of, fold_name
from ventaja.value.model import ValueModel
from ventaja.value.params import (
    ALT_TYPES,
    CLOCK_BUCKETS,
    MCP_DEFAULT_LIMIT,
    MCP_MAX_LIMIT,
    PROFILE_MIN_SHOTS,
)
from ventaja.value.priors import Priors

__all__ = ["CLOCK_BANDS", "RANK_KEYS", "AskService"]

RANK_KEYS = ("mean_cost", "good_read_share", "late_held_share")
CLOCK_BANDS = tuple(label for label, _, _ in CLOCK_BUCKETS)
_MAX_CANDIDATES = 20


def _round(x: float | None) -> float | None:
    """Round a float to 3 decimals (null stays null)."""
    return None if x is None else round(x, 3)


class AskService:
    """Answers questions about games, players and teams from the packaged artifacts."""

    def __init__(
        self,
        settings: Settings,
        *,
        model: ValueModel | None = None,
        priors: Priors | None = None,
    ) -> None:
        self.settings = settings
        self.model = model
        self.priors = priors
        decision_paths, _ = decision_files(settings)
        self.decisions = (
            pl.concat(
                [load_decisions(int(p.stem), settings) for p in decision_paths],
                how="vertical_relaxed",
            )
            if decision_paths
            else pl.DataFrame(schema={"game_id": pl.Int64, "rule": pl.String})
        )
        _, summary_paths = curve_files(settings)
        self.summaries = (
            pl.concat(
                [load_curve_summaries(int(p.name.split(".")[0]), settings) for p in summary_paths],
                how="vertical_relaxed",
            )
            if summary_paths
            else pl.DataFrame(schema=SUMMARY_SCHEMA)
        )
        self.players = load_players_cards(settings)
        self.teams = load_teams_cards(settings)
        self.games = load_games(settings)
        self.people: People = load_people(settings)
        self._known_players = self._carded_or_rostered()

    def _carded_or_rostered(self) -> set[int]:
        ids = {int(i) for i in self.players["player_id"] if i != LEAGUE_ID}
        try:
            ids |= {int(i) for i in load_roster(self.settings)["player_id"]}
        except DataNotFoundError:
            pass
        return ids

    # -- references ---------------------------------------------------------------------

    def _team_ref(self, team_id: int | None, name: str | None = None) -> TeamRef | None:
        if team_id is None:
            return None
        return TeamRef(team_id=team_id, name=name or self.people.teams.get(team_id))

    def _player_ref(self, player_id: int, name: str | None = None) -> PlayerRef:
        team_id = self.people.player_team.get(player_id)
        return PlayerRef(
            player_id=player_id,
            name=name or self.people.names.get(player_id),
            team=self._team_ref(team_id),
        )

    # -- resolvers ----------------------------------------------------------------------

    def resolve_player(self, query: str) -> int:
        """Player id from an exact id or a name fragment (case and accent insensitive).

        Raises ``AmbiguousQueryError`` listing candidates when 0 or more than 1 players match.
        """
        q = query.strip()
        if q.isdigit() and int(q) in self._known_players:
            return int(q)
        folded = fold_name(q)
        names = {i: self.people.names.get(i, str(i)) for i in self._known_players}
        hits = [i for i, n in names.items() if folded in fold_name(n)]
        if len(hits) == 1:
            return hits[0]
        shown = sorted(hits or names, key=lambda i: (fold_name(names[i]), i))
        lines = [f"  {i} — {names[i]} — {self._team_name_of(i)}" for i in shown[:_MAX_CANDIDATES]]
        if len(shown) > _MAX_CANDIDATES:
            lines.append(f"  … and {len(shown) - _MAX_CANDIDATES} more")
        raise AmbiguousQueryError("\n".join([f"{len(hits)} players match {query!r}:", *lines]))

    def _team_name_of(self, player_id: int) -> str:
        team_id = self.people.player_team.get(player_id)
        return self.people.teams.get(team_id, "?") if team_id is not None else "?"

    def resolve_team(self, query: str) -> int:
        """Team id from an exact id or a name fragment; lists every team when not unique."""
        q = query.strip()
        teams = self.people.teams
        if q.isdigit() and int(q) in teams:
            return int(q)
        folded = fold_name(q)
        hits = [i for i, n in teams.items() if folded in fold_name(n)]
        if len(hits) == 1:
            return hits[0]
        lines = [
            f"  {i} — {n}"
            for i, n in sorted(teams.items(), key=lambda kv: (fold_name(kv[1]), kv[0]))
        ]
        raise AmbiguousQueryError("\n".join([f"{len(hits)} teams match {query!r}:", *lines]))

    # -- games --------------------------------------------------------------------------

    def list_games(self) -> list[GameInfo]:
        """Games with decisions sorted by id, with the number of valued shots of each."""
        valued = dict(
            self.decisions.filter(pl.col("rule") != "excluded")
            .group_by("game_id")
            .agg(pl.len())
            .rows()
        )
        out: list[GameInfo] = []
        for g in self.games.sort("game_id").iter_rows(named=True):
            out.append(
                GameInfo(
                    game_id=g["game_id"],
                    date=g["date"],
                    home=GameSide(
                        team_id=g["home_team_id"], name=g["home_team"], score=g["home_score"]
                    ),
                    away=GameSide(
                        team_id=g["away_team_id"], name=g["away_team"], score=g["away_score"]
                    ),
                    valued_shots=int(valued.get(g["game_id"], 0)),
                )
            )
        return out

    # -- rankings -----------------------------------------------------------------------

    @staticmethod
    def _metrics(row: dict[str, Any], clock: str | None) -> Metrics:
        band = (
            ClockBand(
                band=clock, n=row[f"clock_{clock}_n"], cost=_round(row[f"clock_{clock}_cost"])
            )
            if clock
            else None
        )
        return Metrics(
            n_shots=row["n_shots"],
            n_readable=row["n_readable"],
            mean_cost=_round(row["mean_cost"]),
            good_read_share=_round(row["good_read_share"]),
            late_held_share=_round(row["late_held_share"]),
            clock=band,
        )

    def rank_players(
        self,
        *,
        team: str | None = None,
        clock: str | None = None,
        min_shots: int = 1,
        by: str = "mean_cost",
        limit: int = MCP_DEFAULT_LIMIT,
    ) -> Ranking:
        """Players ranked by ``by`` (highest first), optionally of one team or one clock band.

        Raises ``ValueError`` on an invalid argument.
        """
        if by not in RANK_KEYS:
            raise ValueError(f"by must be one of {', '.join(RANK_KEYS)}; got {by!r}")
        if clock is not None and clock not in CLOCK_BANDS:
            raise ValueError(f"clock must be one of {', '.join(CLOCK_BANDS)}; got {clock!r}")
        if clock is not None and by != "mean_cost":
            raise ValueError(
                "clock rankings only support by='mean_cost' "
                "(cards keep no per-band read or lag shares)"
            )
        if not 1 <= limit <= MCP_MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MCP_MAX_LIMIT}; got {limit}")
        if min_shots < 1:
            raise ValueError(f"min_shots must be at least 1; got {min_shots}")

        cards = self.players.filter(pl.col("player_id") != LEAGUE_ID)
        if team is not None:
            cards = cards.filter(pl.col("team_id") == self.resolve_team(team))
        count, key = (f"clock_{clock}_n", f"clock_{clock}_cost") if clock else ("n_shots", by)
        rows = cards.filter(pl.col(count) >= min_shots).sort(
            [key, "n_shots", "player_id"], descending=[True, True, False], nulls_last=True
        )
        players = [
            RankedPlayer(
                rank=rank,
                player=self._player_ref(r["player_id"], r["name"]),
                metrics=self._metrics(r, clock),
            )
            for rank, r in enumerate(rows.head(limit).iter_rows(named=True), start=1)
        ]
        league = self.players.filter(pl.col("player_id") == LEAGUE_ID).row(0, named=True)
        return Ranking(
            by=by,
            clock=clock,
            min_shots=min_shots,
            players=players,
            league=self._metrics(league, clock),
        )

    # -- profiles -----------------------------------------------------------------------

    def player_profile(self, player: str) -> PlayerProfile:
        """The card of one player (by id or name fragment) with the league for reference."""
        card = card_of(self.resolve_player(player), self.players)
        league = self.players.filter(pl.col("player_id") == LEAGUE_ID).row(0, named=True)
        ref = self._player_ref(card.player_id, card.name)
        if card.team_id is not None:
            ref = ref.model_copy(update={"team": self._team_ref(card.team_id, card.team)})
        return PlayerProfile(
            player=ref,
            games=card.games,
            n_shots=card.n_shots,
            n_readable=card.n_readable,
            mean_shot_value=_round(card.mean_shot_value),
            mean_best_alt_value=_round(card.mean_best_alt_value),
            mean_cost=_round(card.mean_cost),
            good_read_share=_round(card.good_read_share),
            late_held_share=_round(card.late_held_share),
            mean_lag_held=_round(card.mean_lag_held),
            clock=[
                ClockBand(band=b, n=card.clock[b][0], cost=_round(card.clock[b][1]))
                for b in CLOCK_BANDS
            ],
            ignored_alternative=card.ignored_alt,
            alternatives=[
                Alternative(type=a, n=card.alternatives[a][0], cost=_round(card.alternatives[a][1]))
                for a in ALT_TYPES
            ],
            season={
                k.removeprefix("season_"): _round(v) if isinstance(v, float) else v
                for k, v in card.season.items()
            },
            league=self._metrics(league, None),
            phrase=card.phrase_en,
            caution=(
                f"Fewer than {PROFILE_MIN_SHOTS} readable shots: treat tendencies as anecdotal."
                if card.n_readable < PROFILE_MIN_SHOTS
                else None
            ),
        )
