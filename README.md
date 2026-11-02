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

Across 10 games there are 1,459 shots, of which 1,351 are valued (108 excluded: 81 without a touch, 20 without a shot type, 7 tips). The taken shot is valued with the zone and points of the shot event; each pass as a catch-and-shoot at the receiver's projected spot, discounted when a defender blocks the lane (ADR-0005: near either end, or mid-lane against a covered receiver or a driving passer). Leave-one-game-out validation gives logloss 0.642, Brier 0.226 and AUC 0.654, with a Pearson correlation of 0.58 against SkillCorner's `shotQuality`; `ventaja model report` adds a per-zone comparison with observed and league rates. The mean decision cost is 0.19 points. In 40 shots (under 2 s of shot clock) no pass is viable, so there is no read; of the other 1,311, 41% are a good read. A raw shot clock of 0.0 means the clock is off (end of period) and is read as unknown ([ADR-0007](docs/decisions/0007-reloj-de-posesion-apagado.md)).

`models/value_model.json` and `artifacts/decisions/` ship in the repo. They are derived artifacts: regenerate them, never edit them by hand. Both resolve relative to the repo, so run ventaja from a clone with `uv` (a non-editable install is not supported yet). Decisions are read from one directory: the build's `decisions/` if it holds any, else `artifacts/decisions/`, never a mix.

```bash
uv run ventaja model train --all          # refit models/value_model.json
uv run ventaja decisions build --all --out artifacts/decisions

uv run ventaja model report
uv run ventaja decisions show shot-114243-1-0
uv run ventaja validate decisions --all --allow-fail cost_falls_with_clock
uv run ventaja review sample --all --n 20 --seed 7 --out docs/review/2026-11-sample
```

On the 10 games, `cost_falls_with_clock` fails (mean cost 0.163, 0.204 and 0.193 for 24-14, 14-6 and 6-0 s). It is deliberately not tuned (ADR-0004): it is a diagnostic for the live review session ([docs/review/README.md](docs/review/README.md)), so CI passes it with `--allow-fail` while the other three checks block.

## Development

```bash
uv sync
uv run pytest
```
