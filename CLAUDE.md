# ventaja

Basketball tracking analytics for the SkillCorner x PySport Analytics Cup.

## Stack

Python >=3.12, managed with `uv`. Layout `src/ventaja/`. polars, duckdb, pydantic v2, httpx, typer, fastapi, uvicorn, mcp. Quality: ruff, mypy (strict), pytest. License MIT.

## Commands

- `uv run pytest`
- `uv run ruff check .` and `uv run ruff format --check .`
- `uv run mypy`
- `uv run ventaja data pull --game 114243` (or `--all`), `uv run ventaja data build --game 114243`
- `uv run ventaja validate score --game 114243`
- `uv run ventaja sql "select count(*) from shots"`
- `uv run ventaja snapshot shot-114243-1-0` (add `--decision` to draw the decision frame)
- `uv run ventaja validate decisions --game 114243` (or `--all`; `--allow-fail cost_falls_with_clock` as in CI)
- `uv run ventaja model train --all` (or `--game N`; `--out PATH`, `--figure PATH`), `uv run ventaja model report`
- `uv run ventaja decisions build --all --out artifacts/decisions` (default `--out`: the build's `decisions/`), `uv run ventaja decisions show shot-114243-1-0`
- `uv run ventaja curves build --all --out artifacts/curves` (default `--out`: the build's `curves/`), `uv run ventaja curves show shot-114243-1-0`
- `uv run ventaja curves plot shot-114243-1-0 --out curve.png`, `uv run ventaja clip shot-114243-1-0 --out clip.gif` (`--fps`, `--before`, `--after`; the clip needs the game built with `data build`)
- `uv run ventaja review sample --all --n 20 --seed 7 --out docs/review/2026-11-sample`
- `uv run ventaja reel rankings --all --n 10`, `uv run ventaja reel build --all --n 10 --out docs/reel/2026-11` (`--fps`; GIFs are gitignored, `index.md` is committed)
- `uv run ventaja player build --out artifacts` (default `--out`: the build's `players/`), `uv run ventaja player show "Russell"` (`--lang en`), `uv run ventaja player rank --min-shots 8`, `uv run ventaja player team "Madrid"`
- `uv run ventaja frames build --all` (or `--game N`; `--out artifacts/frames`, default `--out`: the build's `frames/`; also writes `roster.parquet`)
- `uv run ventaja app` (`--host 127.0.0.1`, `--port 8765`, `--game ID` repeatable, `--no-open`): the unified app (shot, whiteboard, curve, players, games, MCP tools), runs from the packaged artifacts; `ventaja board` is an alias
- `uv run ventaja mcp serve`: the MCP server over stdio, from the packaged artifacts; `uv run ventaja mcp call TOOL '{...}'` prints a tool's JSON (e.g. `rank_players '{"team": "Breogan", "clock": "6-0"}'`); `uv run ventaja mcp tools` lists the six tools with their input schema
- Real-data tests: `VENTAJA_REALDATA_DIR=<raw dir> VENTAJA_REALDATA_BUILD_DIR=<scratch build dir> uv run pytest -m realdata`

## Conventions

- Code, docstrings and README in English. ADRs in Spanish (`docs/decisions/`).
- Conventional commits: `chore:`, `feat:`, `test:`, `docs:`.
- Each layer is closed with tests + an ADR + a CLI command.

- All geometry is in offense orientation; `left_hoop` is read only in `decision/align.py` (ADR-0001).
- Every constant of layers 1 and 2 (curve, clip, rankings, reel) lives in `src/ventaja/value/params.py` and changes only via an ADR.
- A raw shot clock of 0.0 is the clock switched off: `Aligner` reads it as `None` (unknown), unless a countdown reached it within the previous `SHOT_CLOCK_EXPIRY_LOOKBACK` = 25 frames, in which case it has expired and stays 0.0 (ADR-0007).
- CLI lives in the `src/ventaja/cli/` package: one module per sub-app, shared helpers in `cli/_common.py`.
- Layer 3 constants (`PROFILE_MIN_SHOTS` = 8, `LATE_MIN_CLOCK` = 2.5 s, ...) live in `value/params.py`; the phrase rules and thresholds live in `value/params.py` and `profile/phrase.py` and change only via an ADR.
- `models/` and `artifacts/` are derived, versioned artifacts: regenerate them in this order with `ventaja model train --all` (writes `models/value_model.json` and `models/priors.parquet`, the per-player shot aggregate the priors are built from), `ventaja decisions build --all --out artifacts/decisions`, `ventaja curves build --all --out artifacts/curves` (`artifacts/curves/` depends on both), `ventaja player build --out artifacts` (`artifacts/players.parquet`, `teams.parquet` and `games.parquet` (teams, date and score of each game with decisions) depend on the decisions, the curves, `meta/` and the aggregates) and `ventaja frames build --all --out artifacts/frames` (`artifacts/frames/` and its `roster.parquet` depend on the decisions and the tracking), never edit them by hand.
- Layer 4 constants (`BOARD_MAX_MOVES` = 10, `BOARD_MOVED_VELOCITY` = 0.0, `BOARD_PORT` = 8765) live in `value/params.py`. The board runs inside the unified app (ADR-0011): `web/app.py` (FastAPI, one shared `AskService` and its `board`, tool schemas taken once from the `MCPServer`) serves `web/static/` (`index.html` shell, `app.css`, `app.js` hash router, `board.js`, `curve.js`, `shot.js`, `players.js`, `games.js`, `ask.js`, `about.js`): dependency-free ES modules (SVG + vanilla JS, no build), the board draws a 2.5D isometric view by default. Every file in `web/static/` stays at 600 lines or fewer. Any visible number comes from the API; the page never computes values, rankings or phrases. `decide_snapshot` in `decision/cost.py` is the single valuation entry point (ADR-0009, ADR-0011).
- Layer 5 constants (`MCP_DEFAULT_LIMIT` = 10, `MCP_MAX_LIMIT` = 50) live in `value/params.py`. `mcp/service.py` never imports `mcp`; `mcp/server.py` stays thin and the shell twin `mcp call` goes through the same `call_tool`. `decide_snapshot` stays the only valuation entry point (`what_if` goes through `Board`). `mcp/glossary.md` is a `string.Template` filled from `params.py` (ADR-0010).

## References

- Spec: `docs/superpowers/specs/2026-11-01-ventaja-design.md`
- Plan: `docs/superpowers/plans/2026-11-01-capa-0-esqueleto-y-datos.md`
