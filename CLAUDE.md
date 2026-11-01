# ventaja

Basketball tracking analytics for the SkillCorner x PySport Analytics Cup.

## Stack

Python >=3.12, managed with `uv`. Layout `src/ventaja/`. polars, duckdb, pydantic v2, httpx, typer. Quality: ruff, mypy (strict), pytest. License MIT.

## Commands

- `uv run pytest`
- `uv run ruff check .` and `uv run ruff format --check .`
- `uv run mypy`

## Conventions

- Code, docstrings and README in English. ADRs in Spanish (`docs/decisions/`).
- Conventional commits: `chore:`, `feat:`, `test:`, `docs:`.
- Each layer is closed with tests + an ADR + a CLI command.

## References

- Spec and plan: `docs/`
