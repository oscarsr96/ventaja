# ventaja

Basketball tracking analytics for the SkillCorner x PySport Analytics Cup.

> Working README. The submission README is written in week 7.

## Data

Raw SkillCorner data and the tidy parquet build live outside the repo, in two directories set by environment variables:

- `VENTAJA_DATA_DIR`: raw data in the SkillCorner layout (default `~/.cache/ventaja/raw`).
- `VENTAJA_BUILD_DIR`: tidy parquet build (default `~/.cache/ventaja/build`).

To reuse an existing clone of `github.com/SkillCorner/opendata-basketball`, point `VENTAJA_DATA_DIR` at its `data/` folder.

```bash
uv run ventaja data pull --game 114243     # or --all (~380 MB)
uv run ventaja data build --game 114243
uv run ventaja validate score --game 114243
uv run ventaja sql "select count(*) from shots"
uv run ventaja snapshot shot-114243-1-0
```

## Decisions

Layer 1 values each shot against the best viable pass at the decision frame: the cost of a decision is `max(0, best alternative - shot)` in expected points. Method and rationale: [ADR-0003](docs/decisions/0003-frame-de-decision.md) (decision frame) and [ADR-0004](docs/decisions/0004-modelo-de-valor-y-viabilidad.md) (value model and pass viability).

Across 10 games there are 1,459 shots, of which 1,351 are valued (108 excluded: 81 without a touch, 20 without a shot type, 7 tips). Leave-one-game-out validation gives logloss 0.649, Brier 0.229 and AUC 0.629, with a Pearson correlation of 0.52 against SkillCorner's `shotQuality`. The mean decision cost is 0.15 points and 51% of decisions are a good read.

`models/value_model.json` and `artifacts/decisions/` ship in the repo. They are derived artifacts: regenerate them, never edit them by hand.

```bash
uv run ventaja model train --all          # refit models/value_model.json
uv run ventaja decisions build --all      # rebuild artifacts/decisions/

uv run ventaja model report
uv run ventaja decisions show shot-114243-1-0
uv run ventaja validate decisions --game 114243
uv run ventaja review sample --all --n 20 --seed 7 --out docs/review/2026-11-sample
```

The sanity check `cost_falls_with_clock` currently fails and is deliberately not tuned; it is for the live review session described in [docs/review/README.md](docs/review/README.md).

## Development

```bash
uv sync
uv run pytest
```
