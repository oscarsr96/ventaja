"""The MCP server: registers the ask service as six tools and the glossary as a resource.

Thin by design: argument validation, error mapping and the glossary live here; every answer
comes from ``AskService``. ``call_tool`` is the one validated dispatcher, used by each tool
wrapper and by the ``ventaja mcp call`` command.
"""

from collections.abc import Callable, Mapping
from importlib.resources import files
from string import Template
from typing import Annotated, Any, cast

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, validate_call

from ventaja.config import Settings
from ventaja.errors import VentajaError
from ventaja.mcp.models import (
    GameInfo,
    Move,
    PlayerProfile,
    Ranking,
    ShotExplanation,
    ShotList,
    WhatIf,
)
from ventaja.mcp.service import CLOCK_BANDS, RANK_KEYS, VERDICTS, AskService
from ventaja.value.model import ValueModel
from ventaja.value.params import (
    ADVANTAGE_TOLERANCE,
    BOARD_MAX_MOVES,
    CURVE_MIN_ROWS,
    GATHER_FRAMES,
    LANE_BLOCKED_FACTOR,
    LATE_MIN_CLOCK,
    MCP_DEFAULT_LIMIT,
    MCP_MAX_LIMIT,
    MIN_RANK_CONFIDENCE,
    PASS_DISTANCE_HARD,
    PASS_DISTANCE_SOFT,
    PROFILE_MIN_SHOTS,
    SHOT_CLOCK_EXPIRY_LOOKBACK,
    SHOT_CLOCK_MIN_PASS,
)
from ventaja.value.priors import Priors

__all__ = ["GLOSSARY_URI", "TOOL_NAMES", "call_tool", "create_server", "render_glossary"]

TOOL_NAMES = (
    "list_games",
    "rank_players",
    "player_profile",
    "find_shots",
    "explain_shot",
    "what_if",
)
GLOSSARY_URI = "ventaja://glossary"

INSTRUCTIONS = (
    "Decision analytics on basketball shots: 10 ACB games with tracking data plus 2025-26 "
    "season aggregates. Answer only with numbers returned by these tools; never invent or "
    "estimate a value. Read the ventaja://glossary resource before explaining the method "
    "(option value, decision cost, advantage verdicts, shot-clock bands, limits). Ids always "
    "travel with names. If a player or team is not in list_games, say the data does not "
    "cover them instead of guessing."
)

_Player = Annotated[
    str, Field(description="Player id or a name fragment (accents and case ignored)")
]
_PlayerFilter = Annotated[str | None, Field(description="Shooter, by id or name fragment")]
_Team = Annotated[str | None, Field(description="Team id or name fragment")]
_Clock = Annotated[
    str | None,
    Field(description=f"Shot-clock band of the decision: {', '.join(CLOCK_BANDS)} (seconds left)"),
]
_ShotId = Annotated[str, Field(description="Shot id such as shot-114243-1-0 (from find_shots)")]
_Limit = Annotated[
    int,
    Field(ge=1, le=MCP_MAX_LIMIT, description=f"Most rows to return (default {MCP_DEFAULT_LIMIT})"),
]
_MinShots = Annotated[int, Field(ge=1, description="Fewest readable shots a player needs")]
_By = Annotated[str, Field(description=f"Ranking key, highest first: {', '.join(RANK_KEYS)}")]
_Opponent = Annotated[str | None, Field(description="Opponent team id or name fragment")]
_Game = Annotated[int | None, Field(description="Game id from list_games")]
_Verdict = Annotated[str | None, Field(description=f"Advantage verdict: {', '.join(VERDICTS)}")]
_GoodRead = Annotated[bool | None, Field(description="True keeps good reads, false the others")]
_MinCost = Annotated[float | None, Field(description="Fewest points of decision cost")]
_Moves = Annotated[
    list[Move],
    Field(
        description=(
            f"At most {BOARD_MAX_MOVES} moves: a player of the decision frame (id or name) to "
            "x, y in feet on the half court, offense orientation"
        )
    ),
]
_STRICT = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


# Parameter contracts of the tools. The MCP wrappers in ``create_server`` use the same aliases
# and defaults (the SDK reads their signature); a test checks the two stay identical.
@validate_call(config=_STRICT)
def _list_games(service: AskService) -> list[GameInfo]:
    return service.list_games()


@validate_call(config=_STRICT)
def _rank_players(
    service: AskService,
    team: _Team = None,
    clock: _Clock = None,
    min_shots: _MinShots = 1,
    by: _By = "mean_cost",
    limit: _Limit = MCP_DEFAULT_LIMIT,
) -> Ranking:
    return service.rank_players(team=team, clock=clock, min_shots=min_shots, by=by, limit=limit)


@validate_call(config=_STRICT)
def _player_profile(service: AskService, player: _Player) -> PlayerProfile:
    return service.player_profile(player)


@validate_call(config=_STRICT)
def _find_shots(
    service: AskService,
    player: _PlayerFilter = None,
    team: _Team = None,
    opponent: _Opponent = None,
    game: _Game = None,
    clock: _Clock = None,
    verdict: _Verdict = None,
    good_read: _GoodRead = None,
    min_cost: _MinCost = None,
    limit: _Limit = MCP_DEFAULT_LIMIT,
) -> ShotList:
    return service.find_shots(
        player=player,
        team=team,
        opponent=opponent,
        game=game,
        clock=clock,
        verdict=verdict,
        good_read=good_read,
        min_cost=min_cost,
        limit=limit,
    )


@validate_call(config=_STRICT)
def _explain_shot(service: AskService, shot_id: _ShotId) -> ShotExplanation:
    return service.explain_shot(shot_id)


@validate_call(config=_STRICT)
def _what_if(
    service: AskService,
    shot_id: _ShotId,
    moves: _Moves,
) -> WhatIf:
    return service.what_if(shot_id, moves)


_DISPATCH: dict[str, Callable[..., Any]] = {
    "list_games": _list_games,
    "rank_players": _rank_players,
    "player_profile": _player_profile,
    "find_shots": _find_shots,
    "explain_shot": _explain_shot,
    "what_if": _what_if,
}


def call_tool(
    service: AskService, name: str, arguments: Mapping[str, Any]
) -> BaseModel | list[BaseModel]:
    """Validate ``arguments`` against the tool's parameters and run it on ``service``.

    Raises ``KeyError`` for an unknown tool, ``ValueError`` (pydantic's ``ValidationError``
    included) for invalid arguments and ``VentajaError`` for unanswerable questions.
    """
    return cast(BaseModel | list[BaseModel], _DISPATCH[name](service, **arguments))


def render_glossary() -> str:
    """The glossary with the thresholds taken from ``value/params.py``."""
    text = files("ventaja.mcp").joinpath("glossary.md").read_text(encoding="utf-8")
    return Template(text).substitute(
        PROFILE_MIN_SHOTS=PROFILE_MIN_SHOTS,
        GATHER_FRAMES=GATHER_FRAMES,
        SHOT_CLOCK_MIN_PASS=SHOT_CLOCK_MIN_PASS,
        PASS_DISTANCE_SOFT=PASS_DISTANCE_SOFT,
        PASS_DISTANCE_HARD=PASS_DISTANCE_HARD,
        LANE_BLOCKED_FACTOR=LANE_BLOCKED_FACTOR,
        CURVE_MIN_ROWS=CURVE_MIN_ROWS,
        SHOT_CLOCK_EXPIRY_LOOKBACK=SHOT_CLOCK_EXPIRY_LOOKBACK,
        LATE_MIN_CLOCK=LATE_MIN_CLOCK,
        CLOCK_BANDS=", ".join(CLOCK_BANDS),
        BOARD_MAX_MOVES=BOARD_MAX_MOVES,
        ADVANTAGE_TOLERANCE=ADVANTAGE_TOLERANCE,
        MIN_RANK_CONFIDENCE=MIN_RANK_CONFIDENCE,
    )


def _run(service: AskService, name: str, arguments: Mapping[str, Any]) -> Any:
    try:
        return call_tool(service, name, arguments)
    except (VentajaError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


def create_server(
    settings: Settings, *, model: ValueModel | None = None, priors: Priors | None = None
) -> MCPServer:
    """The ``ventaja`` MCP server over the packaged artifacts (no key, env var or download)."""
    service = AskService(settings, model=model, priors=priors)
    server = MCPServer("ventaja", instructions=INSTRUCTIONS)

    @server.tool(description="List the games with decisions: date, teams, score and valued shots.")
    def list_games() -> list[GameInfo]:
        return cast(list[GameInfo], _run(service, "list_games", {}))

    @server.tool(
        description=(
            "Rank players by decision quality (highest first), optionally of one team or one "
            "shot-clock band. Includes the league row for comparison."
        )
    )
    def rank_players(
        team: _Team = None,
        clock: _Clock = None,
        min_shots: _MinShots = 1,
        by: _By = "mean_cost",
        limit: _Limit = MCP_DEFAULT_LIMIT,
    ) -> Ranking:
        return cast(
            Ranking,
            _run(
                service,
                "rank_players",
                {"team": team, "clock": clock, "min_shots": min_shots, "by": by, "limit": limit},
            ),
        )

    @server.tool(description="The decision card of one player with the league row for reference.")
    def player_profile(player: _Player) -> PlayerProfile:
        return cast(PlayerProfile, _run(service, "player_profile", {"player": player}))

    @server.tool(
        description="Find valued shots matching every given filter, costliest decision first."
    )
    def find_shots(
        player: _PlayerFilter = None,
        team: _Team = None,
        opponent: _Opponent = None,
        game: _Game = None,
        clock: _Clock = None,
        verdict: _Verdict = None,
        good_read: _GoodRead = None,
        min_cost: _MinCost = None,
        limit: _Limit = MCP_DEFAULT_LIMIT,
    ) -> ShotList:
        args = {
            "player": player,
            "team": team,
            "opponent": opponent,
            "game": game,
            "clock": clock,
            "verdict": verdict,
            "good_read": good_read,
            "min_cost": min_cost,
            "limit": limit,
        }
        return cast(ShotList, _run(service, "find_shots", args))

    @server.tool(
        description=(
            "Explain one valued shot: the options at the decision frame, the best alternative, "
            "the advantage curve and the command that renders its clip."
        )
    )
    def explain_shot(shot_id: _ShotId) -> ShotExplanation:
        return cast(ShotExplanation, _run(service, "explain_shot", {"shot_id": shot_id}))

    @server.tool(
        description="Value a shot again after moving players on its decision frame (what if)."
    )
    def what_if(
        shot_id: _ShotId,
        moves: _Moves,
    ) -> WhatIf:
        return cast(
            WhatIf,
            _run(
                service, "what_if", {"shot_id": shot_id, "moves": [m.model_dump() for m in moves]}
            ),
        )

    @server.resource(GLOSSARY_URI, mime_type="text/markdown", description="How to read the numbers")
    def glossary() -> str:
        return render_glossary()

    return server
