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
- `uv run ventaja snapshot shot-114243-1-0` (add `--decision` to draw the decision frame)
- `uv run ventaja validate decisions --game 114243` (or `--all`; `--allow-fail cost_falls_with_clock` as in CI)
- `uv run ventaja model train --all` (or `--game N`; `--out PATH`, `--figure PATH`), `uv run ventaja model report`
- `uv run ventaja decisions build --all --out artifacts/decisions` (default `--out`: the build's `decisions/`), `uv run ventaja decisions show shot-114243-1-0`
- `uv run ventaja curves build --all --out artifacts/curves` (default `--out`: the build's `curves/`), `uv run ventaja curves show shot-114243-1-0`
- `uv run ventaja curves plot shot-114243-1-0 --out curve.png`, `uv run ventaja clip shot-114243-1-0 --out clip.gif` (`--fps`, `--before`, `--after`; the clip needs the game built with `data build`)
- `uv run ventaja review sample --all --n 20 --seed 7 --out docs/review/2026-11-sample`
- `uv run ventaja reel rankings --all --n 10`, `uv run ventaja reel build --all --n 10 --out docs/reel/2026-11` (`--fps`; GIFs are gitignored, `index.md` is committed)
- Real-data tests: `VENTAJA_REALDATA_DIR=<raw dir> VENTAJA_REALDATA_BUILD_DIR=<scratch build dir> uv run pytest -m realdata`

## Conventions

- Code, docstrings and README in English. ADRs in Spanish (`docs/decisions/`).
- Conventional commits: `chore:`, `feat:`, `test:`, `docs:`.
- Each layer is closed with tests + an ADR + a CLI command.

- All geometry is in offense orientation; `left_hoop` is read only in `decision/align.py` (ADR-0001).
- Every constant of layers 1 and 2 (curve, clip, rankings, reel) lives in `src/ventaja/value/params.py` and changes only via an ADR.
- A raw shot clock of 0.0 is the clock switched off: `Aligner` reads it as `None` (unknown), unless a countdown reached it within the previous `SHOT_CLOCK_EXPIRY_LOOKBACK` = 25 frames, in which case it has expired and stays 0.0 (ADR-0007).
- `models/` and `artifacts/` are derived, versioned artifacts: regenerate them in this order with `ventaja model train --all`, `ventaja decisions build --all --out artifacts/decisions` and `ventaja curves build --all --out artifacts/curves` (`artifacts/curves/` depends on both), never edit them by hand.

## References

- Spec: `docs/superpowers/specs/2026-11-01-ventaja-design.md`
- Plan: `docs/superpowers/plans/2026-11-01-capa-0-esqueleto-y-datos.md`
