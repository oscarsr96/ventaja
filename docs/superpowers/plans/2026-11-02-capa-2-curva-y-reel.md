# Capa 2: curva de ventaja por posesión y reel de clips — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Para cada tiro valorado de los 10 partidos, calcular frame a frame el valor de la mejor opción del jugador con balón durante la posesión (la curva de ventaja), resumirla en un titular ("la ventaja duró 1,6 s; el tiro llegó 1,2 s tarde"), y generar clips animados con pista y curva, más los rankings de peores decisiones y mejores lecturas.

**Architecture:** Tres módulos nuevos sobre la capa 1: `decision/handler.py` (quién tiene el balón en cada frame, desde `touches`), `decision/curve.py` (curva y resumen: reutiliza `option_rows`, `viability` y el modelo sin cambios) y `viz/clip.py` (clip con dos paneles: pista arriba, curva abajo, reutilizando `draw_half_court`, `select_frames` y la lógica de dibujo de `animate.py`). Las curvas de los 10 partidos se versionan en `artifacts/curves/` (mismo patrón que `artifacts/decisions/`); el reel (`reel.py`) solo lee artefactos y renderiza. Ningún módulo aguas abajo de `align.py` lee tracking crudo.

**Tech Stack:** Lo de la capa 1 (Python 3.12, uv, Polars, pydantic, matplotlib/Pillow). Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-11-01-ventaja-design.md` (sección 2 superficies A y C, sección 5.4 agregaciones, sección 6 fila 3, sección 7 figuras, sección 9 riesgo de confianza). Planes previos: `2026-11-01-capa-1-valoracion.md`. ADRs vigentes: 0003 (frame de decisión), 0004 (modelo y viabilidad), 0005 (regla de carril).

## Global Constraints

- Todo lo de las capas 0 y 1: Python `>=3.12`, uv, `src/ventaja/`, MIT, pies, 25 fps, aro ofensivo en `(-40.7, 0.0)`, código en inglés, ADRs en castellano, commits convencionales con las dos líneas de atribución de la sesión, mypy strict y ruff limpios, salida de tests sin avisos.
- **Toda constante de la capa vive en `src/ventaja/value/params.py`** y cambia solo con un ADR (ADR-0006 para esta capa).
- **El modelo y la tabla de decisiones no cambian.** La curva valora con el mismo `ValueModel.default()`, los mismos `Priors` y la misma `viability`; la única extrapolación nueva (valorar al jugador con balón en frames donde no tiró) se declara en ADR-0006 y en el README.
- **Superficie A** (spec §2): "curva del valor de la mejor opción frame a frame durante la posesión, con el pico de ventaja y el instante del tiro. Titular tipo *la ventaja duró 1,6 s; el tiro llegó 1,2 s tarde*".
- **Superficie C** (spec §2): "clips animados autogenerados de cualquier tiro (los 3 s previos, valores en pantalla) y rankings de peores decisiones y mejores lecturas en los 10 partidos".
- **Riesgo §9**: las decisiones de baja confianza se marcan; los rankings excluyen `confidence < MIN_RANK_CONFIDENCE`.
- **Artefactos derivados versionados** (spec §4): `artifacts/curves/` junto a `artifacts/decisions/`, regenerables con un comando, nunca editados a mano; los GIF y PNG del reel no se commitean salvo las figuras del README.
- Hechos medidos (2026-11-02): valorar un frame (`option_rows` + `predict_proba` de 5 filas) cuesta 0,7 ms; `Aligner.window` de una posesión de 320 frames, 0,3 s; una posesión tiene varias `chances` (rebote ofensivo), `shots.chance_id` las enlaza; 13 de 216 chances del partido 114243 tienen `frontcourt_frame` nulo; el span `frontcourt_frame → end_frame` tiene mediana 179 frames (p75 307, máx 506); los `touches` cubren el balón en mano (entre dos toques el balón vuela); el fixture solo tiene tracking 75 frames antes y 25 después de cada uno de sus 20 tiros.
- Artefactos vigentes: `decisions/{game}.parquet` (`shot_id, game_id, shooter_id, decision_frame, release_frame, rule, reason, shot_clock, shot_value, best_alt_player_id, best_alt_type, best_alt_value, cost, good_read (nullable), confidence`) y `decisions/{game}.options.parquet`.

## Review Focus

1. **Chance sin `frontcourt_frame`** (13/216 en 114243): la curva arranca en `chance.start_frame`; nunca excepción. Test en Tarea 2.
2. **Frames sin tracking dentro del span** (48 % de frames vacíos): la curva tiene huecos; el resumen trabaja con las filas que hay y, con menos de `CURVE_MIN_ROWS` filas, da veredicto `no_window` en vez de romper. Test en Tarea 2.
3. **Balón en vuelo** (frame entre dos toques): no hay jugador con balón → no hay fila de curva ese frame, no se interpola. Test en Tarea 1.
4. **Tiro excluido o sin tracking** (`rule == "excluded"`): `possession_curve` devuelve `None` y `build_curves` lo salta contando el motivo; el reel nunca intenta un clip de un excluido. Test en Tareas 2 y 5.
5. **Decisión de baja confianza** (`confidence < 0.8`, 13 casos en los 10 partidos): aparece en la tabla de curvas pero no en los rankings; el `index.md` del reel dice cuántas se excluyeron. Test en Tarea 5.

---

## Estructura de ficheros

```
src/ventaja/
  value/params.py          # + CURVE_STEP_FRAMES, ADVANTAGE_TOLERANCE, CURVE_MIN_ROWS, MIN_RANK_CONFIDENCE, CLIP_BEFORE_S, CLIP_AFTER_S
  model/decision.py        # + CurveSummary (pydantic)
  decision/handler.py      # BallHandler: handler_at(frame) desde touches
  decision/curve.py        # possession_curve(), summarize_curve(), headline(), build_curves()
  decision/align.py        # + Aligner.chance_of_shot(shot_id), Aligner.touches_of(possession_id)
  data/load.py             # + artifact_dir(kind, settings) generaliza decisions_dir; load_curves(), load_curve_summaries()
  data/duck.py             # + vistas curves, curve_summaries
  viz/clip.py              # render_clip() pista + curva; plot_curve()
  viz/animate.py           # _draw_frame reutilizado por clip.py (sin duplicar)
  reel.py                  # rankings(), build_reel()
  cli.py                   # + curves build|show|plot ; clip ; reel rankings|build
artifacts/curves/{game}.parquet, {game}.summary.parquet
docs/decisions/0006-curva-de-ventaja-y-reel.md
docs/figures/curve-<shot_id>.png              # candidata a figura 2
docs/reel/2026-11/index.md                    # rankings con titulares (GIFs ignorados por git)
tests/test_handler.py test_curve.py test_clip.py test_reel.py
```

---

### Task 1: Jugador con balón por frame y chance del tiro

**Files:**
- Create: `src/ventaja/decision/handler.py`, `tests/test_handler.py`
- Modify: `src/ventaja/decision/align.py`

**Interfaces:**
- Consumes: `Aligner.__init__` ya carga `touches` (tarea 3 de la capa 1); `touches` columnas `id, possession_id, start_frame, end_frame, player_id`; `shots.chance_id`; `chances` columnas `id, possession_id, start_frame, frontcourt_frame (nullable), end_frame, start_shot_clock`.
- Produces:
  - `handler.BallHandler(touches: pl.DataFrame)` construido con los toques de una posesión; `handler_at(frame_idx: int) -> int | None` (id del jugador cuyo toque contiene el frame, `start_frame <= f <= end_frame`; `None` entre toques); `spans() -> list[tuple[int, int, int]]` (start, end, player_id) ordenados.
  - `Aligner.touches_of(possession_id: str) -> pl.DataFrame` (toques de la posesión ordenados por `start_frame`).
  - `Aligner.chance_of_shot(shot_id: str) -> dict[str, Any]` (fila de `chances` con `id == shot.chance_id`; `DataNotFoundError` si no existe). `Aligner` carga `chances` en `__init__` como ya hace con `touches`.

- [ ] **Step 1: Tests**

```python
def test_handler_follows_touches(built_fixture):
    a = Aligner(114243, built_fixture)
    h = BallHandler(a.touches_of("possession-114243-1-2"))
    assert h.handler_at(3860) == 35028          # dentro de touch-114243-1-16 (3852-3895)
    assert h.handler_at(3840) == 28247          # touch-114243-1-15 (3835-3850)
    assert h.handler_at(3851) is None           # balón en vuelo entre dos toques (Review Focus 3)
    assert h.spans()[-1] == (3852, 3895, 35028)

def test_chance_of_shot(built_fixture):
    c = Aligner(114243, built_fixture).chance_of_shot("shot-114243-1-0")
    assert c["id"] == "chance-114243-1-3" and c["possession_id"] == "possession-114243-1-2"

def test_chance_of_unknown_shot_raises(built_fixture): ...  # DataNotFoundError
```

- [ ] **Step 2: Ejecutar → FAIL**
- [ ] **Step 3: Implementar**
- [ ] **Step 4: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy` → PASS**
- [ ] **Step 5: Commit** `feat: ball handler per frame and chance lookup`

---

### Task 2: Curva de ventaja y resumen

**Files:**
- Create: `src/ventaja/decision/curve.py`, `tests/test_curve.py`
- Modify: `src/ventaja/value/params.py`, `src/ventaja/model/decision.py`

**Interfaces:**
- Consumes: `BallHandler`, `Aligner.chance_of_shot`, `Aligner.touches_of`, `Aligner.window(start, end)` (snapshots con velocidades), `Aligner.decision_frame`, `option_rows(snapshot, shooter_id, priors)` (sin `shot_zone`/`shot_three`: el tiro del jugador con balón se valora desde donde está), `ValueModel.predict_proba`, `cost.viability(pass_distance, lane_blocked, shot_clock)`, `Decision` (de `decide`).
- `params.py`: `CURVE_STEP_FRAMES = 5` (5 Hz), `ADVANTAGE_TOLERANCE = 0.10` (pts: una opción cuenta como "la ventaja" mientras no cae más de esto bajo el pico), `CURVE_MIN_ROWS = 3`.
- `model/decision.py`: `CurveSummary(shot_id, game_id, n_rows: int, span_start: int, span_end: int, peak_frame: int | None, peak_value: float | None, window_start: int | None, window_end: int | None, advantage_seconds: float, release_lag_seconds: float | None, value_at_decision: float | None, verdict: Literal["on_time", "late", "early", "no_window"])` (frozen pydantic).
- Produces:
  - `curve.possession_curve(aligner, shot_id, priors, model) -> pl.DataFrame | None`: `None` si `aligner.decision_frame(shot_id).rule == "excluded"`. Span: desde `chance.frontcourt_frame` (o `chance.start_frame` si nulo) hasta `shot.start_frame` (suelta) inclusive. Una fila por frame del span que (a) es múltiplo de `CURVE_STEP_FRAMES` contado desde el frame de suelta hacia atrás (de modo que la suelta siempre está en la curva), (b) tiene tracking y (c) tiene jugador con balón. Columnas: `shot_id, game_id, frame_idx, t_to_release` (s, negativo antes de la suelta), `handler_id, shot_clock, handler_shot_value` (valor del tiro hipotético del jugador con balón desde su posición), `best_value` (máximo `adjusted_value` de las 5 opciones), `best_player_id, best_option_type` ("shot"|"pass"), `best_alt_type` (null si la mejor es tirar), `n_viable` (pases con `viability > 0`). El `adjusted_value` de un pase es `value × viability`; el del tiro es `value`.
  - `curve.summarize_curve(curve: pl.DataFrame, decision: Decision) -> CurveSummary`: `peak` = fila con `best_value` máximo (empate → la más temprana); ventana = tramo contiguo de filas alrededor del pico con `best_value >= peak_value − ADVANTAGE_TOLERANCE`; `advantage_seconds = (window_end − window_start + CURVE_STEP_FRAMES) / 25`; `release_lag_seconds = (decision.decision_frame − window_end) / 25` si el frame de decisión es posterior a la ventana (`late`), `(decision.decision_frame − window_start) / 25` (negativo) si es anterior (`early`), `0.0` si cae dentro (`on_time`); `value_at_decision` = `best_value` de la fila más cercana a `decision.decision_frame`; con `n_rows < CURVE_MIN_ROWS` → `no_window`, campos opcionales nulos, `advantage_seconds = 0.0`.
  - `curve.headline(summary: CurveSummary, lang: Literal["es", "en"] = "es") -> str`: `on_time` → "La ventaja duró {a:.1f} s y el tiro llegó a tiempo"; `late` → "La ventaja duró {a:.1f} s; el tiro llegó {lag:.1f} s tarde"; `early` → "El tiro salió {−lag:.1f} s antes del pico de ventaja"; `no_window` → "Sin curva suficiente ({n} frames)". Versión inglesa equivalente.

- [ ] **Step 1: Tests**

```python
def test_curve_rows_and_release_present(built_fixture, fixture_priors, trained_fixture_model):
    a = Aligner(114243, built_fixture)
    c = possession_curve(a, "shot-114243-1-0", fixture_priors, trained_fixture_model)
    assert c is not None and c["frame_idx"].max() == 3895 and (c["frame_idx"] % 5 == 3895 % 5).all()
    assert c.filter(pl.col("frame_idx") == 3895)["handler_id"][0] == 35028
    assert c["best_value"].is_between(0.0, 3.0).all() and (c["best_value"] >= c["handler_shot_value"]).all()

def test_curve_skips_ball_in_flight(built_fixture, ...):  # Review Focus 3: 3851 no está aunque sea múltiplo del paso
def test_curve_none_for_excluded_shot(built_fixture, ...):  # un tip del fixture → None (Review Focus 4)
def test_curve_starts_at_chance_start_when_no_frontcourt_frame(built_fixture, ...):
    # elegir en el fixture (o construir con monkeypatch de chance_of_shot) una chance con frontcourt_frame nulo (Review Focus 1)

def test_summary_late():
    curve = pl.DataFrame({"frame_idx": [100,105,110,115,120,125], "best_value": [0.8,1.2,1.25,1.2,0.9,0.85], ...})
    s = summarize_curve(curve, decision_with(decision_frame=125, shot_value=0.85))
    assert (s.window_start, s.window_end) == (105, 115) and s.advantage_seconds == pytest.approx(0.6)
    assert s.verdict == "late" and s.release_lag_seconds == pytest.approx(0.4)
def test_summary_on_time(): ...     # decision_frame dentro de la ventana → lag 0.0
def test_summary_early(): ...       # decision_frame antes del pico → lag negativo, verdict early
def test_summary_no_window(): ...   # 2 filas → no_window, advantage 0.0 (Review Focus 2)
def test_headline_es_en(): ...      # los cuatro veredictos en ambos idiomas
```

Helper `decision_with(**overrides)` en `tests/helpers.py` que construye una `Decision` sintética válida.

- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Commit** `feat: advantage curve per possession with summary and headline`

---

### Task 3: Artefactos de curvas, carga, vistas y CLI

**Files:**
- Create: `artifacts/curves/{10 partidos}.parquet` y `{10}.summary.parquet`, `docs/decisions/0006-curva-de-ventaja-y-reel.md`
- Modify: `src/ventaja/decision/curve.py`, `src/ventaja/data/load.py`, `src/ventaja/data/duck.py`, `src/ventaja/config.py`, `src/ventaja/cli.py`, `tests/test_curve.py`, `tests/test_realdata.py`

**Interfaces:**
- Consumes: `possession_curve`, `summarize_curve`, `load_decisions(game_id, settings)` (para iterar los tiros valorados y recuperar `Decision`-like filas), `decide` no se vuelve a llamar: el resumen usa `decision_frame` y `shot_value` de la tabla de decisiones.
- Produces:
  - `Settings.curves_parquet(game_id)` = `build_dir/curves/{game}.parquet`, `Settings.curve_summaries_parquet(game_id)` = `build_dir/curves/{game}.summary.parquet`.
  - `load.artifact_dir(kind: Literal["decisions", "curves"], settings) -> Path` (generaliza `decisions_dir`: build dir si contiene algún `[0-9]*.parquet` de ese tipo, si no `ARTIFACTS_DIR / kind`; `decisions_dir` pasa a delegar). `load.load_curves(game_id, settings)`, `load.load_curve_summaries(game_id, settings)` (`DataNotFoundError` con hint `ventaja curves build`).
  - `duck.connect` añade vistas `curves` y `curve_summaries` (mismo patrón de exclusión `*.summary.parquet` que `*.options.parquet`).
  - `curve.build_curves(game_id, settings, *, model=None, priors=None, out_dir: Path | None = None) -> tuple[Path, Path]`: para cada fila de `load_decisions` con `rule != "excluded"`, curva + resumen; esquemas explícitos `CURVE_SCHEMA`, `SUMMARY_SCHEMA`; la tabla resumen lleva una fila por tiro valorado con los campos de `CurveSummary` más `headline_es`, `headline_en`; escritura atómica.
  - CLI: `ventaja curves build [--game ID ...|--all] [--out DIR]` (imprime por partido: tiros, curvas, veredictos on_time/late/early/no_window, mediana de `advantage_seconds`); `ventaja curves show SHOT_ID` (cabecera con el titular y la tabla de la curva: `t_to_release, handler, shot_clock, handler_shot_value, best_value, best (jugador/tipo)`).
- [ ] **Step 1: Tests** — `test_build_curves_fixture` (fixture: 16 tiros valorados → 16 filas de resumen, curvas con ≥ 1 fila cada una, veredictos en el `Literal`), `test_load_curves_falls_back_to_artifacts` (build vacío → artefactos del repo, un partido real), `test_curves_cli_show` (fixture; exit 0 y el titular en la salida).
- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Construir los artefactos reales**: `VENTAJA_DATA_DIR=... VENTAJA_BUILD_DIR=... uv run ventaja curves build --all --out artifacts/curves` y también sin `--out` (el build dir y los artefactos deben coincidir). Expected: 20 ficheros, < 5 MB en total, < 15 min; si tarda más, el implementador lo reporta y NO cambia `CURVE_STEP_FRAMES` (se decide por ADR). Reportar: distribución de veredictos, mediana y p90 de `advantage_seconds`, mediana de `release_lag_seconds` en los `late`, correlación entre `cost` y `release_lag_seconds`, y los 5 tiros con mayor retraso.
- [ ] **Step 6: `tests/test_realdata.py`**: test `realdata` que carga los 10 resúmenes y exige: una fila por tiro valorado (1 351), `advantage_seconds >= 0`, `verdict` válido, y que el `value_at_decision` de cada tiro coincide con `max(shot_value, best_alt_value)` de la tabla de decisiones con tolerancia 1e-6 cuando `rule == "gather"` y la fila de la curva es exactamente el frame de decisión (documentar la tolerancia real medida si no es exacta: la curva no pasa `shot_zone`/`shot_three` a la fila del tirador, así que el valor del tiro hipotético difiere del tiro real; en ese caso comparar solo `best_alt_value` con el mejor pase de la curva).
- [ ] **Step 7: ADR-0006** (contexto: superficie A; método: span de la chance, paso de 5 frames, jugador con balón por toques, valoración con el modelo de la capa 1 sin reentrenar y la extrapolación que supone; definición de pico, ventana con tolerancia 0,10 y los tres veredictos; constantes; cifras reales del paso 5; alternativas descartadas: interpolar el balón en vuelo, valorar a todos los atacantes en vez del jugador con balón; consecuencias: artefactos `curves/`, coste de cómputo).
- [ ] **Step 8: Commit** `feat: curves artifacts, loaders, SQL views and CLI (ADR-0006)` (código) y `chore: build curves of the ten games` (artefactos).

---

### Task 4: Clip con pista y curva, y figura de la curva

**Files:**
- Create: `src/ventaja/viz/clip.py`, `tests/test_clip.py`, `docs/figures/curve-shot-114243-1-0.png` (o el tiro que mejor comunique: ver paso 5)
- Modify: `src/ventaja/viz/animate.py` (exponer `_draw_frame` como `draw_frame` y `select_frames`, sin duplicar), `src/ventaja/value/params.py` (`CLIP_BEFORE_S = 3.0`, `CLIP_AFTER_S = 1.0`), `src/ventaja/cli.py`

**Interfaces:**
- Consumes: `render_shot_gif` (su dibujo de frames), `draw_half_court`, `load_curves`, `load_curve_summaries`, `load_decisions`/`load_decision_options` (para reconstruir `Decision` + `options` desde artefactos: añadir `cost.decision_from_tables(shot_id, decisions, options) -> Decision` en `decision/cost.py`, usado también por el reel), `headline`.
- Produces:
  - `clip.plot_curve(ax, curve: pl.DataFrame, summary: CurveSummary, decision: Decision, *, marker_frame: int | None = None) -> None`: línea de `best_value` contra `t_to_release`, línea punteada de `handler_shot_value`, banda sombreada de la ventana de ventaja, línea vertical en el frame de decisión y otra en la suelta, marcador móvil opcional; ejes en inglés ("seconds to release", "expected points"); escala y fija `0-2 pts`.
  - `clip.render_clip(aligner, decision, curve, summary, out: Path, *, before_s=CLIP_BEFORE_S, after_s=CLIP_AFTER_S, fps=12, labels=None) -> Path`: figura de dos paneles (pista 6×6,4 arriba como hoy, curva 6×2 abajo), el marcador de la curva avanza con el frame, título = titular en castellano + `shot_id`, mismo congelado de 1 s en el frame de decisión que `render_shot_gif`; GIF con `PillowWriter`.
  - `clip.curve_figure(curve, summary, decision, out: Path) -> Path`: solo el panel de la curva a 150 dpi (candidata a figura 2 del README).
  - CLI: `ventaja clip SHOT_ID --out FILE.gif [--fps 12]` (lee decisiones, opciones y curvas desde artefactos o build; `VentajaError` → exit 1); `ventaja curves plot SHOT_ID --out FILE.png`.

- [ ] **Step 1: Tests** — `test_render_clip_writes_gif` (fixture, `before_s=1.0, after_s=0.2, fps=6`, fichero > 10 KB y `Image.open(...).n_frames >= 2`), `test_curve_figure_writes_png`, `test_decision_from_tables_roundtrip` (sobre el fixture: `decide(...)` y `decision_from_tables(...)` dan las mismas `shot_value`, `cost` y 5 opciones), `test_clip_cli_errors_on_excluded_shot` (exit 1 con motivo).
- [ ] **Step 2 → 4:** FAIL, implementar, PASS (backend `Agg`, importación perezosa de pyplot como en `animate.py`; sin avisos de matplotlib).
- [ ] **Step 5: Figura**: generar `ventaja curves plot` para `shot-114243-1-0` y para los 3 tiros con mayor `release_lag_seconds` del paso 5 de la Tarea 3; mirar los PNG con la herramienta de lectura de imágenes, elegir el que mejor cuente "el momento perdido" (una ventana clara y un tiro tardío) y commitear solo ese como `docs/figures/curve-<shot_id>.png`; anotar el elegido en el informe.
- [ ] **Step 6: Commit** `feat: possession clip with court and advantage curve`

---

### Task 5: Rankings y reel

**Files:**
- Create: `src/ventaja/reel.py`, `tests/test_reel.py`, `docs/reel/2026-11/index.md`
- Modify: `src/ventaja/value/params.py` (`MIN_RANK_CONFIDENCE = 0.8`), `src/ventaja/cli.py`, `.gitignore` (`docs/reel/*/*.gif`)

**Interfaces:**
- Consumes: `load_decisions`, `load_curve_summaries`, `load_meta("players")` y `load_meta("games")` (nombres y equipos), `decision_from_tables`, `render_clip`, `headline`.
- Produces:
  - `reel.rankings(settings, game_ids: list[int], *, n: int = 10) -> tuple[pl.DataFrame, pl.DataFrame]`: `(worst, best)`. Filtro común: `rule != "excluded"`, `confidence >= MIN_RANK_CONFIDENCE`, `good_read` no nulo. `worst` = mayor `cost` (desc); `best` = `good_read == True` con mayor `margin = shot_value − best_alt_value` (desc). Columnas: `rank, shot_id, game_id, game_label` ("HOME–AWAY"), `shooter` (nombre), `team` (nombre), `period, shot_clock, rule, shot_value, best_alt_value, best_alt_type, best_alt_player` (nombre), `cost` (o `margin`), `verdict, advantage_seconds, release_lag_seconds, headline_es`. Devuelve también en un atributo del resultado o como tercer elemento el número de decisiones excluidas por confianza (elige: tercer elemento `excluded_low_confidence: int`; firma final `-> tuple[pl.DataFrame, pl.DataFrame, int]`).
  - `reel.build_reel(settings, game_ids, *, n: int = 10, out_dir: Path, fps: int = 12) -> Path`: renderiza un clip por fila de ambos rankings (`{rank:02d}-worst-{shot_id}.gif`, `{rank:02d}-best-{shot_id}.gif`) y escribe `out_dir/index.md` (castellano): cabecera (partidos, fecha, modelo `trained_at`, `n`, cuántas decisiones quedaron fuera por confianza), sección "Peores decisiones" y "Mejores lecturas", cada una con una tabla (rank, partido, jugador, reloj, tiro, mejor alternativa, coste/margen, titular) y debajo la lista de GIFs embebidos. Devuelve la ruta del `index.md`.
  - CLI: `ventaja reel rankings [--game|--all] [--n 10]` (imprime las dos tablas; exit 0); `ventaja reel build [--game|--all] [--n 10] --out DIR`.

- [ ] **Step 1: Tests**

```python
def test_rankings_filters_and_orders(fixture_curves_built):  # fixture con curvas construidas (fixture de sesión en conftest)
    worst, best, n_low = rankings(settings, [114243], n=5)
    assert worst["cost"].is_sorted(descending=True) and (worst["confidence"] >= 0.8).all()
    assert (best["good_read"] == True).all() and best["margin"].is_sorted(descending=True)
    assert n_low >= 0 and "headline_es" in worst.columns

def test_rankings_exclude_low_confidence():  # tabla sintética con una decisión a confidence 0.5 → fuera y contada (Review Focus 5)
def test_build_reel_writes_index_and_gifs(fixture_curves_built, tmp_path):  # n=2, fps=6 → 4 gifs y un index.md con dos secciones
def test_reel_never_renders_excluded():  # sintético: una fila excluded nunca llega a render (Review Focus 4)
```

- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Reel real**: `VENTAJA_DATA_DIR=... VENTAJA_BUILD_DIR=... uv run ventaja reel build --all --n 10 --out docs/reel/2026-11` (20 GIFs, no se commitean; `index.md` sí). Reportar los dos top-10 y el tiempo. Mirar dos GIFs con la herramienta de imágenes y describir lo que se ve.
- [ ] **Step 6: Commit** `feat: decision rankings and auto-generated reel`

---

### Task 6: Cierre de la capa

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `.github/workflows/ci.yml`, `tests/test_realdata.py`, `docs/decisions/0006-curva-de-ventaja-y-reel.md` (cifras finales del reel)

- [ ] **Step 1: README** (inglés, ≤ 800 palabras en esta capa; tope final 1 000): sección "Lost moments" con la definición en dos frases (curva, pico, ventana, veredicto), la figura `docs/figures/curve-<shot_id>.png` como figura 2 provisional (la figura 1 sigue siendo el visor de decisión; el README de entrega decidirá cuál de las dos queda), los comandos `ventaja curves show`, `ventaja clip`, `ventaja reel rankings`, y las cifras reales de veredictos (porcentaje on_time/late/early) en una frase; nota de que `artifacts/curves/` viene en el repo y cómo regenerarlo.
- [ ] **Step 2: CLAUDE.md**: comandos nuevos; `artifacts/curves/` en la regla de artefactos derivados; `value/params.py` sigue siendo el único sitio de constantes (capa 2 incluida).
- [ ] **Step 3: CI**: job `pipeline` añade `uv run ventaja curves build --game 114243`, `uv run ventaja clip shot-114243-1-0 --out /tmp/clip.gif`, `uv run ventaja reel rankings --game 114243 --n 3`; `pipeline-all` añade `uv run ventaja curves build --all --out /tmp/curves` (no sobreescribe los artefactos) y `uv run ventaja reel rankings --all`.
- [ ] **Step 4: Calidad completa + `uv run pytest -m realdata`** con las variables de datos reales → verde.
- [ ] **Step 5: Commit** `docs: close layer 2`; tras el merge a `main`, el controlador etiqueta `capa-2-cerrada`.

---

## Self-review

- **Cobertura del spec**: A (curva, pico, instante del tiro, titular) → T2, T3, T4; C (clips de cualquier tiro con los 3 s previos y valores en pantalla, rankings de peores decisiones y mejores lecturas) → T4, T5; §5.4 agregación por reloj/alternativa → sigue en capa 3 (ficha), pero `rankings` ya expone `best_alt_type` y `shot_clock`; §7 figura 2 → T4 paso 5; §9 confianza → T5 (`MIN_RANK_CONFIDENCE`); §4 artefactos versionados → T3; "cada capa se cierra con tests, ADR y comando CLI" → T3 (ADR-0006) y T6.
- **Nombres consistentes**: `BallHandler.handler_at`, `Aligner.chance_of_shot`, `Aligner.touches_of`, `possession_curve`, `summarize_curve`, `headline`, `CurveSummary`, `build_curves`, `artifact_dir`, `load_curves`, `load_curve_summaries`, `decision_from_tables`, `plot_curve`, `render_clip`, `curve_figure`, `rankings`, `build_reel` se usan igual en todas las tareas. `rankings` devuelve `(worst, best, excluded_low_confidence)`.
- **Review Focus**: 1 → T2 (`frontcourt_frame` nulo); 2 → T2 (`no_window`); 3 → T1 y T2 (balón en vuelo); 4 → T2 (`None`) y T5 (nunca se renderiza); 5 → T5.
- **Proporción**: el plan fija constantes, firmas, columnas y tests; los cuerpos quedan al implementador salvo las definiciones que el spec exige explícitas (pico, ventana, veredictos, titular).
- **Decisiones propias que un revisor debe ver**: el jugador con balón se valora con un tiro hipotético desde su posición (no con `shot_zone`/`shot_three`), por lo que `value_at_decision` de la curva no coincide exactamente con `shot_value` de la tabla de decisiones salvo en el mejor pase; la curva arranca en `frontcourt_frame` (no en el inicio de la posesión) para no valorar el contraataque como "ventaja"; `ADVANTAGE_TOLERANCE = 0.10` pts es una elección a validar con cifras reales en ADR-0006.
