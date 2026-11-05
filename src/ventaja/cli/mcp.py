"""`ventaja mcp`: serve the ask service as MCP tools, or call one tool from the shell."""

import asyncio
import json
from typing import Annotated, Any

import typer

from ventaja.cli._common import run_or_exit, settings_or_exit
from ventaja.errors import VentajaError

app = typer.Typer(
    help="Serve ventaja as MCP tools, or call one tool from the shell.", no_args_is_help=True
)


@app.command()
def serve() -> None:
    """Serve the MCP server on stdio (configure it in Claude Desktop or Claude Code)."""
    from ventaja.mcp.server import create_server

    settings = settings_or_exit()
    run_or_exit(lambda: create_server(settings)).run("stdio")


def _arguments(raw: str) -> dict[str, Any]:
    """Parse the ARGS option as a JSON object, or exit 2."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.echo(f"error: ARGS is not valid JSON: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if not isinstance(parsed, dict):
        typer.echo("error: ARGS must be a JSON object", err=True)
        raise typer.Exit(code=2)
    return parsed


@app.command()
def call(
    tool: Annotated[str, typer.Argument(help="Tool name (see `ventaja mcp tools`).")],
    args: Annotated[str, typer.Argument(help="JSON object of arguments.")] = "{}",
) -> None:
    """Call one MCP tool with a JSON object of arguments and print its JSON result."""
    from ventaja.mcp.server import TOOL_NAMES, call_tool
    from ventaja.mcp.service import AskService

    if tool not in TOOL_NAMES:
        typer.echo(f"error: unknown tool {tool!r}; choose one of {', '.join(TOOL_NAMES)}", err=True)
        raise typer.Exit(code=2)
    arguments = _arguments(args)
    settings = settings_or_exit()
    service = run_or_exit(lambda: AskService(settings))
    try:
        result = call_tool(service, tool, arguments)
    except (VentajaError, ValueError) as exc:  # pydantic's ValidationError is a ValueError
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    payload = [r.model_dump() for r in result] if isinstance(result, list) else result.model_dump()
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@app.command()
def tools() -> None:
    """List the MCP tools with their input schema."""
    from mcp.client import Client

    from ventaja.mcp.server import create_server

    settings = settings_or_exit()
    server = run_or_exit(lambda: create_server(settings))

    async def _list() -> list[dict[str, Any]]:
        async with Client(server) as client:
            listing = await client.list_tools()
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in listing.tools
        ]

    for tool in asyncio.run(_list()):
        typer.echo(f"{tool['name']}\n{tool['description']}")
        typer.echo(json.dumps(tool["input_schema"], indent=2, ensure_ascii=False))
        typer.echo("")
