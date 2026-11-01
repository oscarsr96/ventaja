# ventaja

Basketball tracking analytics for the SkillCorner x PySport Analytics Cup.

## Stack

Python >=3.12, managed with `uv`. Layout `src/ventaja/`. polars, duckdb, pydantic v2, httpx, typer. Quality: ruff, mypy (strict), pytest. License MIT.

## Commands

- `uv run pytest`
- `uv run ruff check .` and `uv run ruff format --check .`
- `uv run mypy`
- `uv run ventaja data pull --game 114243` (or `--all`), `uv run ventaja data build --game 114243`
- `uv run ventaja validate score --game 114243`
- `uv run ventaja sql "select count(*) from shots"`
- `uv run ventaja snapshot shot-114243-1-0`

## Conventions

- Code, docstrings and README in English. ADRs in Spanish (`docs/decisions/`).
- Conventional commits: `chore:`, `feat:`, `test:`, `docs:`.
- Each layer is closed with tests + an ADR + a CLI command.

- All geometry is in offense orientation; `left_hoop` is read only in `decision/align.py` (ADR-0001).

## References

- Spec: `docs/superpowers/specs/2026-11-01-ventaja-design.md`
- Plan: `docs/superpowers/plans/2026-11-01-capa-0-esqueleto-y-datos.md`
