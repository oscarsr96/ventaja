import re

from typer.testing import CliRunner

from ventaja.cli import app

EXPECTED_COMMANDS = {
    "data": {"pull", "status", "build"},
    "validate": {"score", "decisions"},
    "model": {"train", "report"},
    "decisions": {"build", "show"},
    "curves": {"build", "show", "plot"},
    "frames": {"build"},
    "review": {"sample"},
    "reel": {"rankings", "build"},
    "player": {"build", "show", "rank", "team"},
    "mcp": {"serve", "call", "tools"},
}
EXPECTED_TOP_LEVEL = {"sql", "snapshot", "clip", "board"}

# Command lines of `--help`, captured before cli.py was split into a package.
ROOT_HELP = [
    "sql Run SQL against the built parquet files through DuckDB.",
    "snapshot Print the offense-oriented snapshot at a shot's frame; the shooter is marked *.",
    "clip Animate a shot's possession (court) with its advantage curve underneath, as a GIF.",
    "data Download, inspect and build SkillCorner data.",
    "validate Check the event model against official data.",
    "model Train and inspect the value model.",
    "decisions Build and inspect shot decision costs.",
    "curves Build and inspect possession advantage curves.",
    "frames Build the decision frames the whiteboard draws.",
    "review Prepare the live review of decisions.",
    "reel Rank decisions and build the reel of clips.",
    "mcp Serve ventaja as MCP tools, or call one tool from the shell.",
]
DECISIONS_HELP = [
    "build Value every shot against its pass options and write the decisions tables.",
    "show Print a shot's decision and its five options (* shooter, > best alternative).",
]
REEL_HELP = [
    "rankings Print the worst decisions, the best reads and the lost moments (late, held).",
    "build Render one clip per ranked shot (three rankings) and write index.md.",
]


def _name(command: object) -> str:
    name = getattr(command, "name", None)
    if name:
        return str(name)
    callback = getattr(command, "callback")  # noqa: B009
    return str(callback.__name__).replace("_", "-")


def test_every_command_still_registered() -> None:
    top = {_name(c) for c in app.registered_commands}
    assert top == EXPECTED_TOP_LEVEL
    groups = {g.name: g.typer_instance for g in app.registered_groups}
    assert set(groups) == set(EXPECTED_COMMANDS)
    for group, expected in EXPECTED_COMMANDS.items():
        instance = groups[group]
        assert instance is not None
        assert {_name(c) for c in instance.registered_commands} == expected


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_BOX = re.compile(r"[│╭╮╰╯─]")
_PLAIN_ENV = {"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200", "FORCE_COLOR": "0"}


def _normalise(text: str) -> str:
    """Strip ANSI escapes and box drawing, and collapse whitespace."""
    return re.sub(r"\s+", " ", _BOX.sub(" ", _ANSI.sub("", text))).strip()


def _flat(args: list[str]) -> str:
    result = CliRunner().invoke(app, args, env=_PLAIN_ENV)
    assert result.exit_code == 0
    return _normalise(result.output)


def test_help_texts_unchanged() -> None:
    for args, lines in (
        (["--help"], ROOT_HELP),
        (["decisions", "--help"], DECISIONS_HELP),
        (["reel", "--help"], REEL_HELP),
    ):
        text = _flat(args)
        for line in lines:
            assert _normalise(line) in text, line
