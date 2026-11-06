"""The ask service: pure queries over the packaged artifacts, no MCP imports.

It loads the decisions, curve summaries, player and team cards, games and people once and
answers games, rankings and player profiles with ids that always travel with their names.
"""

from typing import Any, Literal, overload

import polars as pl

from ventaja.board.engine import Board
from ventaja.config import Settings
from ventaja.data.load import (
    curve_files,
    decision_files,
    load_curve_summaries,
    load_decision_options,
    load_decisions,
    load_frames,
    load_games,
    load_players_cards,
    load_roster,
    load_teams_cards,
)
from ventaja.data.people import People, load_people
from ventaja.decision.cost import decision_from_tables
from ventaja.decision.curve import SUMMARY_SCHEMA
from ventaja.errors import AmbiguousQueryError, DataNotFoundError, VentajaError
from ventaja.mcp.models import (
    Alternative,
    AppliedMove,
    BestAlternative,
    ClockBand,
    CurveSummaryOut,
    Featured,
    FeaturedShot,
    GameInfo,
    GameSide,
    Metrics,
    Move,
    OptionOut,
    PlacedPlayer,
    PlayerProfile,
    PlayerRef,
    RankedPlayer,
    Ranking,
    ShotExplanation,
    ShotList,
    ShotSummary,
    ShotTaken,
    TeamRef,
    Valuation,
    WhatIf,
)
from ventaja.model.decision import Decision
from ventaja.model.snapshot import PlayerPos
from ventaja.profile.card import LEAGUE_ID, card_of, fold_name
from ventaja.reel import rank_tables
from ventaja.value.clock import clock_bucket_expr
from ventaja.value.model import ValueModel
from ventaja.value.params import (
    ALT_TYPES,
    BOARD_MAX_MOVES,
    CLOCK_BUCKETS,
    MCP_DEFAULT_LIMIT,
    MCP_MAX_LIMIT,
    PROFILE_MIN_SHOTS,
)
from ventaja.value.priors import Priors

__all__ = [
    "CLOCK_BANDS",
    "RANK_KEYS",
    "VERDICTS",
    "AskService",
    "ClockBandName",
    "RankKey",
    "VerdictName",
]

RANK_KEYS = ("mean_cost", "good_read_share", "late_held_share")
CLOCK_BANDS = tuple(label for label, _, _ in CLOCK_BUCKETS)
VERDICTS = ("late", "during", "none", "no_window")
# The schema-facing twins of the tuples above (a test keeps them identical).
RankKey = Literal["mean_cost", "good_read_share", "late_held_share"]
ClockBandName = Literal["24-14", "14-6", "6-0"]
VerdictName = Literal["late", "during", "none", "no_window"]
_MAX_CANDIDATES = 20


@overload
def _round(x: float) -> float: ...
@overload
def _round(x: None) -> None: ...
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
        self._board: Board | None = None

    @property
    def board(self) -> Board:
        """The what-if board, built on first use and shared by every caller."""
        if self._board is None:
            self._board = Board(self.settings, model=self.model, priors=self.priors)
        return self._board

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
        player_id = self.resolve_player(player)
        if self.players.filter(pl.col("player_id") == player_id).height == 0:
            name = self.people.names.get(player_id)
            raise DataNotFoundError(
                f"player {player_id} ({name}) has no valued shots in the ten tracked games"
            )
        card = card_of(player_id, self.players)
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

    # -- shots --------------------------------------------------------------------------

    def _periods(self, game_id: int) -> dict[str, int | None]:
        """Period of each shot of a game (its ball row in the decision frames)."""
        try:
            frames = load_frames(game_id, self.settings)
        except DataNotFoundError:
            return {}
        ball = frames.filter(pl.col("side") == "ball").unique(subset="shot_id", keep="first")
        return dict(zip(ball["shot_id"], ball["period"], strict=True))

    def _best_alternative(
        self, player_id: int | None, alt_type: str | None, value: float | None
    ) -> BestAlternative | None:
        if player_id is None or alt_type is None or value is None:
            return None
        return BestAlternative(
            player=self._player_ref(player_id), type=alt_type, value=_round(value)
        )

    def _valuation(self, decision: Decision) -> Valuation:
        best_id, best_type = decision.best_alt_player_id, decision.best_alt_type
        options = [
            OptionOut(
                player=self._player_ref(o.player_id),
                option_type=o.option_type,
                zone=o.zone,
                points=o.points,
                proba=_round(o.proba),
                value=_round(o.value),
                viability=_round(o.viability),
                adjusted_value=_round(o.adjusted_value),
                alternative_type=o.alternative_type,
                lane_blocked=o.lane_blocked,
                is_shot=o.option_type == "shot",
                is_best_alternative=(
                    o.option_type == "pass"
                    and best_id is not None
                    and o.player_id == best_id
                    and o.alternative_type == best_type
                ),
            )
            for o in decision.options
        ]
        return Valuation(
            shot_value=_round(decision.shot_value),
            best_alternative=self._best_alternative(
                decision.best_alt_player_id, decision.best_alt_type, decision.best_alt_value
            ),
            cost=_round(decision.cost),
            good_read=decision.good_read,
            options=options,
        )

    def find_shots(
        self,
        *,
        player: str | None = None,
        team: str | None = None,
        opponent: str | None = None,
        game: int | None = None,
        clock: str | None = None,
        verdict: str | None = None,
        good_read: bool | None = None,
        min_cost: float | None = None,
        limit: int = MCP_DEFAULT_LIMIT,
    ) -> ShotList:
        """Valued shots matching every given filter, costliest first.

        ``team`` is the shooter's team and ``opponent`` the other team of the shot's game.
        Raises ``ValueError`` on an invalid argument.
        """
        if verdict is not None and verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}; got {verdict!r}")
        if clock is not None and clock not in CLOCK_BANDS:
            raise ValueError(f"clock must be one of {', '.join(CLOCK_BANDS)}; got {clock!r}")
        if not 1 <= limit <= MCP_MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MCP_MAX_LIMIT}; got {limit}")

        summaries = self.summaries.select(
            "shot_id", "verdict", "headline_en", "window_handler_id"
        ).unique(subset="shot_id", keep="first")
        sides = self.games.select(
            "game_id", pl.col("home_team_id").alias("_home"), pl.col("away_team_id").alias("_away")
        )
        shooter_team = self.people.player_team
        shots = (
            self.decisions.filter(pl.col("rule") != "excluded")
            .join(summaries, on="shot_id", how="left")
            .join(sides, on="game_id", how="left")
            .with_columns(
                _team=pl.col("shooter_id").replace_strict(shooter_team, default=None),
            )
            .with_columns(
                _opponent=pl.when(pl.col("_team") == pl.col("_home"))
                .then(pl.col("_away"))
                .when(pl.col("_team") == pl.col("_away"))
                .then(pl.col("_home"))
            )
        )
        if player is not None:
            shots = shots.filter(pl.col("shooter_id") == self.resolve_player(player))
        if team is not None:
            shots = shots.filter(pl.col("_team") == self.resolve_team(team))
        if opponent is not None:
            shots = shots.filter(pl.col("_opponent") == self.resolve_team(opponent))
        if game is not None:
            shots = shots.filter(pl.col("game_id") == game)
        if clock is not None:
            shots = shots.filter(clock_bucket_expr(CLOCK_BANDS.index(clock)))
        if verdict is not None:
            shots = shots.filter(pl.col("verdict") == verdict)
        if good_read is not None:
            shots = shots.filter(pl.col("good_read") == good_read)
        if min_cost is not None:
            shots = shots.filter(pl.col("cost") >= min_cost)

        shots = shots.sort(["cost", "shot_id"], descending=[True, False])
        periods: dict[int, dict[str, int | None]] = {}
        out: list[ShotSummary] = []
        for r in shots.head(limit).iter_rows(named=True):
            if r["game_id"] not in periods:
                periods[r["game_id"]] = self._periods(r["game_id"])
            out.append(self._shot_summary(r, periods))
        return ShotList(total=shots.height, shots=out)

    def _shot_summary(
        self, r: dict[str, Any], periods: dict[int, dict[str, int | None]]
    ) -> ShotSummary:
        """A ``ShotSummary`` from a decisions row joined with ``verdict`` and ``headline_en``."""
        if r["game_id"] not in periods:
            periods[r["game_id"]] = self._periods(r["game_id"])
        return ShotSummary(
            shot_id=r["shot_id"],
            game_id=r["game_id"],
            period=periods[r["game_id"]].get(r["shot_id"]),
            shot_clock=_round(r["shot_clock"]),
            shooter=self._player_ref(r["shooter_id"]),
            shot_value=_round(r["shot_value"]),
            best_alternative=self._best_alternative(
                r["best_alt_player_id"], r["best_alt_type"], r["best_alt_value"]
            ),
            cost=_round(r["cost"]),
            good_read=r["good_read"],
            verdict=r["verdict"],
            headline=r["headline_en"],
        )

    def featured(self, n: int = 10) -> Featured:
        """The ``n`` costliest, best-read and costliest-late-hold shots (the reel's rules).

        Raises ``ValueError`` when ``n`` is below 1.
        """
        if n < 1:
            raise ValueError(f"n must be at least 1; got {n}")
        tables = rank_tables(self.decisions, self.summaries, None, None, n=n)
        worst, best, late, low = tables
        summaries = self.summaries.select(
            "shot_id", "verdict", "headline_en", "window_handler_id"
        ).unique(subset="shot_id", keep="first")
        rows = {
            r["shot_id"]: r
            for r in self.decisions.join(summaries, on="shot_id", how="left").iter_rows(named=True)
        }
        periods: dict[int, dict[str, int | None]] = {}

        def build(table: pl.DataFrame, metric: str) -> list[FeaturedShot]:
            return [
                FeaturedShot(
                    rank=int(t["rank"]),
                    metric=round(float(t[metric]), 3),
                    shot=self._shot_summary(rows[t["shot_id"]], periods),
                )
                for t in table.iter_rows(named=True)
            ]

        worst_out = build(worst, "cost")
        return Featured(
            default_shot=worst_out[0].shot.shot_id if worst_out else None,
            worst=worst_out,
            best=build(best, "margin"),
            late=build(late, "lost_value"),
            low_confidence=int(low),
        )

    def _valued_row(self, shot_id: str) -> dict[str, Any]:
        """The decisions row of a valued shot; says why when the shot is unknown or excluded."""
        hit = self.decisions.filter(pl.col("shot_id") == shot_id)
        if hit.height == 0:
            raise DataNotFoundError(f"shot {shot_id} not found in the decisions tables")
        row = hit.row(0, named=True)
        if row["rule"] == "excluded":
            raise VentajaError(f"shot {shot_id} is excluded: {row['reason']}")
        return row

    def explain_shot(self, shot_id: str) -> ShotExplanation:
        """The options at the decision frame of one valued shot, with its curve and clip command.

        Raises ``DataNotFoundError`` for an unknown shot and ``VentajaError`` for an excluded one.
        """
        row = self._valued_row(shot_id)
        game_id = row["game_id"]
        decision = decision_from_tables(
            shot_id, self.decisions, load_decision_options(game_id, self.settings)
        )
        valuation = self._valuation(decision)
        taken = next(o for o in decision.options if o.option_type == "shot")
        summary = self.summaries.filter(pl.col("shot_id") == shot_id)
        curve = None
        if summary.height:
            c = summary.row(0, named=True)
            holder = c["window_handler_id"]
            curve = CurveSummaryOut(
                verdict=c["verdict"],
                advantage_seconds=_round(c["advantage_seconds"]),
                release_lag_seconds=_round(c["release_lag_seconds"]),
                held_to_decision=c["held_to_decision"],
                advantage_holder=None if holder is None else self._player_ref(holder),
                headline=c["headline_en"],
            )
        return ShotExplanation(
            shot_id=shot_id,
            game_id=game_id,
            period=self._periods(game_id).get(shot_id),
            shot_clock=_round(decision.shot_clock),
            rule=decision.rule,
            confidence=_round(decision.confidence),
            shooter=self._player_ref(decision.shooter_id),
            shot=ShotTaken(zone=taken.zone, points=taken.points, value=_round(taken.value)),
            options=valuation.options,
            best_alternative=valuation.best_alternative,
            cost=valuation.cost,
            good_read=valuation.good_read,
            curve=curve,
            clip_command=f"ventaja clip {shot_id} --out {shot_id}.gif",
        )

    # -- what if ------------------------------------------------------------------------

    def what_if(self, shot_id: str, moves: list[Move]) -> WhatIf:
        """Value a valued shot again after moving players of its decision frame.

        Positions are in feet, offense orientation, clamped to the half court. Raises
        ``ValueError`` for too many moves, ``DataNotFoundError`` for an unknown or excluded
        shot and ``AmbiguousQueryError`` for a player who is not one of the ten on the frame.
        """
        if len(moves) > BOARD_MAX_MOVES:
            raise ValueError(f"at most {BOARD_MAX_MOVES} moves")
        self._valued_row(shot_id)
        board = self.board
        state = board.load(shot_id)
        before = state.original
        applied: list[AppliedMove] = []
        for m in moves:
            player_id = self._frame_player(state.snapshot.offense, state.snapshot.defense, m.player)
            state = board.move(state, player_id, m.x, m.y)
            x, y = state.moves[player_id]
            applied.append(
                AppliedMove(player=self._player_ref(player_id), x=_round(x), y=_round(y))
            )
        after = board.evaluate(state)
        sides = (("offense", state.snapshot.offense), ("defense", state.snapshot.defense))
        return WhatIf(
            shot_id=shot_id,
            before=self._valuation(before),
            after=self._valuation(after),
            delta_cost=_round(after.cost - before.cost),
            moves=applied,
            players=[
                PlacedPlayer(
                    player=self._player_ref(p.player_id),
                    side=side,
                    x=_round(p.x),
                    y=_round(p.y),
                    is_shooter=p.player_id == state.shooter_id,
                    moved=p.player_id in state.moves,
                )
                for side, group in sides
                for p in group
            ],
        )

    def _frame_player(self, offense: list[PlayerPos], defense: list[PlayerPos], query: str) -> int:
        """Player id among the ten of a frame: exact id, else a folded name fragment."""
        names = {p.player_id: self.people.names.get(p.player_id, str(p.player_id)) for p in offense}
        names |= {
            p.player_id: self.people.names.get(p.player_id, str(p.player_id)) for p in defense
        }
        side = {p.player_id: "offense" for p in offense} | {p.player_id: "defense" for p in defense}
        q = query.strip()
        if q.isdigit() and int(q) in names:
            return int(q)
        folded = fold_name(q)
        hits = [i for i, n in names.items() if folded in fold_name(n)]
        if len(hits) == 1:
            return hits[0]
        lines = [
            f"  {i} — {names[i]} — {side[i]}" for i in sorted(names, key=lambda i: (side[i], i))
        ]
        raise AmbiguousQueryError(
            "\n".join([f"{len(hits)} players on the frame match {query!r}:", *lines])
        )
