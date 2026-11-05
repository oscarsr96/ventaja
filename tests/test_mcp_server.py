"""The MCP server over the in-memory protocol: tools, errors and the glossary resource."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult

from ventaja.config import Settings
from ventaja.mcp.server import (
    GLOSSARY_URI,
    TOOL_NAMES,
    call_tool,
    create_server,
    render_glossary,
)
from ventaja.mcp.service import AskService
from ventaja.value.params import MCP_MAX_LIMIT, PROFILE_MIN_SHOTS

SHOT = "shot-114243-1-0"


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    tmp = tmp_path_factory.mktemp("mcp-server")
    return Settings(data_dir=tmp / "raw", build_dir=tmp / "build")


@pytest.fixture(scope="module")
def server(settings: Settings) -> MCPServer:
    return create_server(settings)


async def _call(server: MCPServer, name: str, args: dict[str, Any]) -> CallToolResult:
    async with Client(server) as client:
        return await client.call_tool(name, args)


def test_lists_the_six_tools_with_schemas(server: MCPServer) -> None:
    async def run() -> None:
        async with Client(server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert tuple(tools) == TOOL_NAMES
            assert all(t.description and t.output_schema for t in tools.values())
            limit = tools["rank_players"].input_schema["properties"]["limit"]
            assert limit["maximum"] == MCP_MAX_LIMIT and limit["minimum"] == 1
            for tool in tools.values():
                props = tool.input_schema.get("properties", {})
                assert all(p.get("description") for p in props.values()), tool.name

    asyncio.run(run())


def test_every_tool_answers_over_the_protocol(server: MCPServer) -> None:
    explained = asyncio.run(_call(server, "explain_shot", {"shot_id": SHOT}))
    shooter = str(explained.structured_content["shooter"]["player_id"])  # type: ignore[index]
    cases: dict[str, dict[str, Any]] = {
        "list_games": {},
        "rank_players": {"team": "Breogan", "clock": "6-0"},
        "player_profile": {"player": "Russell"},
        "find_shots": {"player": "Spissu", "game": 191313},
        "explain_shot": {"shot_id": SHOT},
        "what_if": {"shot_id": SHOT, "moves": [{"player": shooter, "x": -42.0, "y": 0.0}]},
    }
    assert tuple(cases) == TOOL_NAMES
    for name, args in cases.items():
        result = asyncio.run(_call(server, name, args))
        assert not result.is_error, (name, result.content)
        assert result.structured_content, name


def test_errors_are_tool_errors_not_crashes(server: MCPServer) -> None:
    ambiguous = asyncio.run(_call(server, "player_profile", {"player": "a"}))
    assert ambiguous.is_error and "players match" in ambiguous.content[0].text  # type: ignore[union-attr]
    bad_limit = asyncio.run(_call(server, "find_shots", {"limit": MCP_MAX_LIMIT + 1}))
    assert bad_limit.is_error
    excluded = asyncio.run(_call(server, "explain_shot", {"shot_id": "shot-114243-9-9"}))
    assert excluded.is_error and "shot-114243-9-9" in excluded.content[0].text  # type: ignore[union-attr]
    bad_arg = asyncio.run(_call(server, "rank_players", {"clock": "9-9"}))
    assert bad_arg.is_error and "clock must be one of" in bad_arg.content[0].text  # type: ignore[union-attr]


def test_glossary_resource_is_rendered_from_params(server: MCPServer) -> None:
    async def run() -> str:
        async with Client(server) as client:
            return (await client.read_resource(GLOSSARY_URI)).contents[0].text  # type: ignore[union-attr]

    text = asyncio.run(run())
    assert text == render_glossary()
    assert str(PROFILE_MIN_SHOTS) in text and "$" not in text and "ADR-0009" in text


def test_call_tool_validates_and_dispatches(settings: Settings) -> None:
    service = AskService(settings)
    assert call_tool(service, "list_games", {}) == service.list_games()
    out = call_tool(service, "rank_players", {"limit": "3"})
    assert len(out.players) <= 3  # type: ignore[union-attr]
    with pytest.raises(KeyError):
        call_tool(service, "nope", {})
    with pytest.raises(ValueError, match="limit"):
        call_tool(service, "find_shots", {"limit": MCP_MAX_LIMIT + 1})
    with pytest.raises(ValueError, match="bogus"):
        call_tool(service, "find_shots", {"bogus": 1})


def test_server_from_clean_settings_needs_nothing_else(tmp_path: Path) -> None:
    create_server(Settings(data_dir=tmp_path / "raw", build_dir=tmp_path / "build"))
