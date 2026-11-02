# Capa 4: la pizarra que responde — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Una página web local (`ventaja board`) que muestra el frame de decisión de cualquier tiro valorado con sus diez jugadores, deja arrastrar a cualquiera de ellos y recalcula al instante el valor de las cinco opciones, la mejor alternativa y el coste; funciona en un clon limpio solo con los artefactos empaquetados, sin descargar tracking.

**Architecture:** Un artefacto nuevo y pequeño, `artifacts/frames/{game}.parquet`, guarda el frame de decisión de cada tiro valorado (10 jugadores + balón con posición y velocidad, más el contexto de la posesión) y permite reconstruir un `Snapshot` sin tracking. El motor (`board/engine.py`) reutiliza `option_rows`, el modelo y `viability` de la capa 1 sobre ese `Snapshot` modificado. Un servidor FastAPI (`board/app.py`) expone tres rutas JSON y sirve una página HTML sin framework (`board/static/index.html`) que dibuja la pista en SVG y arrastra con eventos de puntero. Nada de la capa 1-3 cambia salvo extraer de `decide` la parte que trabaja sobre un `Snapshot`.

**Tech Stack:** Lo anterior más `fastapi` y `uvicorn` (open source, MIT/BSD); `httpx` ya está para los tests con `TestClient`. Sin JavaScript externo: SVG + JS vanilla inline.

**Spec:** `docs/superpowers/specs/2026-11-01-ventaja-design.md` (§2 "B. La pizarra que responde"; §4 "FastAPI + una página HTML sin framework"; §6 fila 5; no-objetivo "no hay frontend de producto"). Decisión de Óscar (2026-11-02): la pizarra funciona con los artefactos empaquetados.

## Global Constraints

- Todo lo de las capas 0-3 (Python `>=3.12`, uv, `src/ventaja/`, MIT, código en inglés, ADRs en castellano, commits convencionales con las dos líneas de atribución, mypy strict, ruff, tests sin avisos; constantes de la capa en `src/ventaja/value/params.py`, cambiables solo con ADR: ADR-0009).
- **Spec §2 B**: "app web donde se arrastra a un jugador del frame y los valores se recalculan al instante".
- **Spec §4**: "FastAPI + una página HTML sin framework"; **no-objetivo**: "no hay frontend de producto: la pizarra es una herramienta funcional, no una app pulida".
- **Anti-objetivo**: el repo arranca en un entorno limpio. `ventaja board` debe funcionar desde un clon con solo `uv sync`: modelo, decisiones, curvas y el nuevo artefacto de frames vienen en el repo.
- **Método intacto**: los valores de la pizarra salen de las mismas funciones que la tabla de decisiones (`option_rows`, `ValueModel.predict_proba`, `viability`, `classify_alternative`); con cero movimientos, la pizarra reproduce exactamente la fila de `decisions` (test).
- Hechos (2026-11-02): 1 351 tiros valorados; el frame de decisión tiene siempre 10 jugadores y balón; `Snapshot` lleva `game_id, frame_idx, wall_clock, period, game_clock, shot_clock (nullable), possession_id, chance_id, off_team_id, def_team_id, offense, defense, ball`; `PlayerPos` lleva `player_id, team_id, x, y, speed, is_detected, pred_error, vx, vy`; `BallPos` `x, y, z, speed, is_detected, vx, vy`. `decide` (cost.py:97-) obtiene el snapshot del `Aligner` y llama a `option_rows(snapshot, shooter_id, priors, **shot_kwargs(shot))`. Pista: `HALF_LENGTH = 45.93`, `COURT_WIDTH = 49.21`, aro en `(-40.7, 0)`, mitad ofensiva `x ≤ 0`. Las opciones empaquetadas no guardan a los defensores ni velocidades: por eso hace falta el artefacto de frames (≈ 1 351 × 11 filas, < 1 MB).

## Review Focus

1. **Cero movimientos reproduce la decisión**: `evaluate` sobre el frame sin tocar devuelve `shot_value`, `best_alt_value`, `cost` y las cinco `adjusted_value` idénticas a `artifacts/decisions` (1e-6). Test en Tarea 2 (fixture) y realdata.
2. **Arrastrar al tirador**: el tiro se valora desde la nueva posición (zona por geometría, no la zona real del evento), y la página lo dice. Test en Tarea 2.
3. **Posición fuera de la pista o en pista trasera** (x > 0, |y| > 24,6): el servidor la recorta a la pista y responde 200 con la posición corregida; nunca 500. Test en Tarea 3.
4. **Tiro sin frame** (excluido, o `shot_id` desconocido): 404 con mensaje; la lista de tiros solo ofrece los valorados. Test en Tarea 3.
5. **Modelo y artefactos ausentes** (clon sin `artifacts/frames`): `ventaja board` falla al arrancar con un mensaje que nombra `ventaja frames build`, no con un traceback en la primera petición. Test en Tarea 3.

---

## Estructura de ficheros

```
src/ventaja/
  config.py                  # + frames_parquet(game_id)
  data/load.py               # artifact_dir admite "frames"; frame_files(), load_frames(game_id)
  data/duck.py               # + vista frames
  decision/frames.py         # FRAME_SCHEMA, build_frames(), snapshot_from_frame(rows) -> Snapshot
  decision/cost.py           # decide() delega en decide_snapshot(snapshot, shot, priors, model)
  board/__init__.py
  board/engine.py            # Board: load(shot_id) -> BoardState; move(); evaluate(); to_payload()
  board/app.py               # create_app(settings) -> FastAPI; rutas /, /api/shots, /api/shot/{id}, /api/shot/{id}/evaluate, /api/court
  board/static/index.html    # SVG de la pista + JS vanilla (arrastre, tabla, cabecera)
  cli/frames.py              # ventaja frames build [--game|--all] [--out]
  cli/board.py               # ventaja board [--host 127.0.0.1] [--port 8765] [--game ...] [--no-open]
  value/params.py            # + BOARD_PORT, BOARD_MAX_MOVES, BOARD_MOVED_VELOCITY
artifacts/frames/{10}.parquet
docs/decisions/0009-pizarra.md
tests/test_frames.py test_board_engine.py test_board_app.py
```

---

### Task 1: Artefacto de frames de decisión

**Files:**
- Create: `src/ventaja/decision/frames.py`, `src/ventaja/cli/frames.py`, `tests/test_frames.py`, `artifacts/frames/{10 partidos}.parquet`
- Modify: `src/ventaja/config.py`, `src/ventaja/data/load.py`, `src/ventaja/data/duck.py`, `src/ventaja/cli/__init__.py`, `tests/conftest.py`, `tests/test_realdata.py`

**Interfaces:**
- `FRAME_SCHEMA`: una fila por entidad y tiro: `shot_id, game_id, frame_idx, period, wall_clock, game_clock, shot_clock (nullable), possession_id, chance_id (nullable), off_team_id, def_team_id, side ("offense"|"defense"|"ball"), player_id (nullable), team_id (nullable), x, y, z (nullable; balón), speed, is_detected, pred_error (nullable; balón), vx (nullable), vy (nullable)`. 11 filas por tiro valorado.
- `frames.build_frames(game_id, settings, *, out_dir=None) -> Path`: para cada fila de `load_decisions` con `rule != "excluded"`, `aligner.snapshot_for_shot(shot_id, decision=True)` → filas; escritura atómica con esquema explícito.
- `frames.snapshot_from_frame(rows: pl.DataFrame) -> Snapshot`: reconstruye el `Snapshot` de un tiro (las 11 filas); lanza `VentajaError` si no hay exactamente 10 jugadores y 1 balón.
- `Settings.frames_parquet(game_id)`; `load.artifact_dir("frames")` (tabla principal `{game}.parquet`, sin secundaria), `load.frame_files(settings) -> list[Path]`, `load.load_frames(game_id, settings) -> pl.DataFrame` (hint `ventaja frames build --game N`); vista DuckDB `frames`.
- CLI `ventaja frames build [--game ID ...|--all] [--out DIR]` (imprime por partido: tiros, filas).
- `tests/conftest.py`: fixture de sesión `fixture_frames_built` sobre `fixture_curves_built` (`build_frames`).

- [ ] **Step 1: Tests**: `test_build_frames_fixture` (17 tiros valorados → 187 filas; esquema == `FRAME_SCHEMA`), `test_snapshot_roundtrip` (para `shot-114243-1-0`: `snapshot_from_frame(load_frames(...).filter(shot_id))` es igual, campo a campo, a `Aligner.snapshot_for_shot(decision=True)`), `test_snapshot_from_frame_rejects_short_frame` (10 filas → `VentajaError`), `test_load_frames_falls_back_to_artifacts`, `test_frames_cli_build`.
- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Artefactos reales**: `<env> uv run ventaja frames build --all --out artifacts/frames` y sin `--out`; reportar filas (esperado 14 861), tamaño total, tiempo. Test realdata: 1 351 tiros × 11 filas; para 20 tiros al azar (semilla 7) el snapshot reconstruido coincide con el del `Aligner`.
- [ ] **Step 6: Commits** `feat: decision-frame artifacts for the whiteboard` y `chore: build decision frames of the ten games`.

---

### Task 2: Motor de la pizarra

**Files:**
- Create: `src/ventaja/board/__init__.py`, `src/ventaja/board/engine.py`, `tests/test_board_engine.py`
- Modify: `src/ventaja/decision/cost.py` (extraer `decide_snapshot`), `src/ventaja/value/params.py`

**Interfaces:**
- `cost.decide_snapshot(snapshot: Snapshot, shot: Mapping[str, Any], priors, model) -> Decision`: el cuerpo actual de `decide` a partir del snapshot (option rows, proba, viabilidad, mejor alternativa, coste, confianza); `decide` pasa a obtener el snapshot y delegar. `shot` necesita `id, game_id, shooter_id, start_frame, region, three` y el `DecisionFrame` (frame y regla) — pasar `decision_frame: int, rule: Rule` como kwargs. Ningún test de la capa 1 cambia salvo el import.
- `params.py`: `BOARD_MAX_MOVES = 10` (jugadores que una petición puede mover), `BOARD_MOVED_VELOCITY = 0.0` (velocidad que se asigna a un jugador arrastrado: colocado, no en carrera; la proyección de pase queda en su sitio), `BOARD_PORT = 8765`.
- `engine.BoardState(_Frozen)`: `shot_id, game_id, shooter_id, decision_frame, release_frame, rule, shot_clock, original: Decision, snapshot: Snapshot, moves: dict[int, tuple[float, float]]`.
- `engine.Board(settings, *, model=None, priors=None)`: carga `ValueModel.default()`/`Priors` una vez; `shots(game_id: int | None = None) -> pl.DataFrame` (tiros valorados con `shot_id, game_id, shooter_id, shooter, team, period, shot_clock, cost, good_read, headline_es` desde decisiones + resúmenes + meta); `load(shot_id) -> BoardState` (frames + decisiones; `DataNotFoundError` si no hay frame); `move(state, player_id, x, y) -> BoardState` (recorta a la pista: `x ∈ [−HALF_LENGTH, 0]`, `|y| ≤ COURT_WIDTH/2`; nuevo `PlayerPos` con `vx = vy = BOARD_MOVED_VELOCITY`, `speed = 0`; el balón se mueve con el tirador si el movido es el tirador); `evaluate(state) -> Decision` (= `decide_snapshot` sobre el snapshot modificado; si el tirador fue movido, el tiro se valora desde su posición: `shot_zone=None, shot_three=None`; si no, con la zona y los puntos reales del tiro); `payload(state, evaluated: Decision) -> dict` (JSON-serializable: pista, jugadores con `player_id, team_id, side, x, y, jersey, name, is_shooter, moved`, balón, opciones con las columnas de `format_option_table`, `shot_value, best_alt_player_id, best_alt_value, cost, good_read`, y `delta_cost` respecto a `original`).

- [ ] **Step 1: Tests** (con `fixture_frames_built`, `trained_fixture_model`, `fixture_priors`): `test_evaluate_without_moves_matches_decisions` (Review Focus 1: las cinco `adjusted_value`, `shot_value`, `best_alt_value`, `cost` iguales a la fila de `decisions`/`decision_options` a 1e-6), `test_move_clamps_to_court` (Review Focus 3), `test_move_shooter_revalues_from_position` (Review Focus 2: mover al tirador a (−41, 0) sube su `shot_value` y la zona pasa a `restricted_area`), `test_move_defender_changes_pass_value` (acercar al defensor más cercano a un receptor abierto baja su `adjusted_value` o lo marca `lane_blocked`), `test_moved_player_has_zero_velocity`, `test_decide_delegates` (capa 1: `decide` sigue dando lo mismo que antes sobre el fixture).
- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Commit** `feat: whiteboard engine on decision-frame snapshots`

---

### Task 3: Servidor FastAPI

**Files:**
- Create: `src/ventaja/board/app.py`, `src/ventaja/cli/board.py`, `tests/test_board_app.py`
- Modify: `pyproject.toml` (añadir `fastapi`, `uvicorn`), `src/ventaja/cli/__init__.py`

**Interfaces:**
- `app.create_app(settings: Settings, *, model=None, priors=None) -> FastAPI`: construye el `Board` al crear la app (falla con `DataNotFoundError` → `VentajaError` claro si faltan artefactos: Review Focus 5). Rutas:
  - `GET /` → `index.html` (estático, `text/html`).
  - `GET /api/court` → constantes de la pista (`half_length, width, hoop, three_point_radius, ra_radius, key_half_width, key_x_max, corner_y, corner_x_max`).
  - `GET /api/shots?game=ID` → lista de tiros valorados (de `Board.shots`), ordenada por `cost` desc.
  - `GET /api/shot/{shot_id}` → `payload` sin movimientos (404 JSON `{"detail": ...}` si no hay frame: Review Focus 4).
  - `POST /api/shot/{shot_id}/evaluate` con body `{"moves": [{"player_id": int, "x": float, "y": float}, ...]}` (pydantic; máximo `BOARD_MAX_MOVES`; `player_id` desconocido → 422) → `payload` con los movimientos aplicados en orden; las posiciones recortadas se devuelven corregidas (200).
- CLI `ventaja board [--host 127.0.0.1] [--port BOARD_PORT] [--game ID ...] [--no-open]`: crea la app, imprime la URL, abre el navegador (`webbrowser.open`) salvo `--no-open`, y arranca `uvicorn` (`log_level="warning"`). `--game` limita la lista de tiros.
- Tests con `fastapi.testclient.TestClient` sobre `create_app(fixture_frames_built, model=..., priors=...)`: `test_index_served`, `test_court`, `test_shots_list_only_valued`, `test_shot_payload_matches_engine`, `test_evaluate_moves_and_clamps` (Review Focus 3), `test_unknown_shot_404` (Review Focus 4), `test_too_many_moves_422`, `test_create_app_without_frames_raises` (Review Focus 5: build dir vacío y `ARTIFACTS_DIR` parcheado a un tmp → `VentajaError` con `ventaja frames build` en el mensaje).

- [ ] **Step 1 → 4:** FAIL, implementar, PASS (`uv add fastapi uvicorn`; mypy: fastapi está tipado; añadir override solo si hace falta).
- [ ] **Step 5: Commit** `feat: whiteboard FastAPI server and ventaja board command`

---

### Task 4: Página de la pizarra

**Files:**
- Create: `src/ventaja/board/static/index.html` (HTML + CSS + JS inline, sin dependencias externas)
- Modify: `tests/test_board_app.py` (comprobaciones estáticas), `pyproject.toml` (incluir `board/static/*` en el paquete: `[tool.uv.build-backend]` o `package-data`; comprobar que `uv build` lo incluye)

**Interfaces (comportamiento de la página):**
- Al cargar: `GET /api/court` y `GET /api/shots` → selector de tiros (texto `shot_id · tirador · equipo · coste`, filtro por partido); al elegir uno, `GET /api/shot/{id}` y dibujo.
- Pista en SVG, orientación de ataque (aro a la izquierda como en los GIFs), líneas de `court.py`; atacantes como círculos rellenos coloreados por `adjusted_value` con la misma escala fija 0,6-1,5 (viridis aproximado por un gradiente de 5 paradas definido en JS), defensores grises, balón naranja, tirador con borde negro, flecha del tirador a la mejor alternativa, dorsal dentro del círculo.
- Arrastre con Pointer Events (funciona con ratón y táctil) de cualquier jugador; al soltar (y, con debounce de 150 ms, durante el arrastre) `POST /api/shot/{id}/evaluate` con todos los movimientos acumulados; se redibuja con la respuesta (colores, flecha, tabla, cabecera). Botón "Reiniciar" y "Deshacer último".
- Cabecera: tirador, regla, reloj, `shot_value → best_alt_value`, coste original y coste actual con `delta` en verde/rojo; si el tirador se movió, aviso "el tiro se valora desde la nueva posición".
- Tabla de las cinco opciones (dorsal, nombre, tipo, zona, P, valor, viabilidad, valor ajustado, alternativa) con `*` y `>` como en la CLI.
- Sin framework ni fuentes externas; ≤ 600 líneas; funciona offline.
- [ ] **Step 1: Tests estáticos** en `test_board_app.py`: el HTML servido contiene `id="court"`, `fetch('/api/shots')`, `pointerdown`, `/evaluate`; no contiene `<script src=` externo.
- [ ] **Step 2: Implementar** y comprobar a mano con `uv run ventaja board --no-open` + `curl` de las rutas; el implementador NO tiene navegador: describe el flujo y deja la verificación visual al controlador (que la hará con el navegador antes del cierre).
- [ ] **Step 3: Commit** `feat: whiteboard page with draggable players`

---

### Task 5: Cierre de la capa

**Files:**
- Create: `docs/decisions/0009-pizarra.md`
- Modify: `README.md`, `CLAUDE.md`, `.github/workflows/ci.yml`

- [ ] **Step 1: ADR-0009** (Spanish): por qué un artefacto de frames (los artefactos de opciones no guardan defensores ni velocidades); qué guarda y cuánto pesa; el motor reutiliza las funciones de la capa 1 y reproduce la tabla de decisiones con cero movimientos; reglas de la pizarra: jugador arrastrado con velocidad 0 (colocado), tirador movido valorado desde su posición, recorte a la pista, máximo de movimientos; límites conocidos (no se recalculan las curvas ni el frame de decisión; la defensa no se mueve sola).
- [ ] **Step 2: README** (≤ 1 000 palabras): sección "Whiteboard" con `uv run ventaja board`, dos frases sobre qué se puede hacer, nota de que funciona desde los artefactos empaquetados y enlace al ADR-0009. Trimar donde haga falta.
- [ ] **Step 3: CLAUDE.md**: comandos `frames build`, `board`; `artifacts/frames/` en la regla de artefactos; constantes nuevas.
- [ ] **Step 4: CI**: `pipeline` añade `uv run ventaja frames build --game 114243` y un test de humo del servidor ya cubierto por pytest (nada más); `pipeline-all` añade `uv run ventaja frames build --all --out /tmp/frames`.
- [ ] **Step 5: Calidad completa + realdata** → verde.
- [ ] **Step 6: Commit** `docs: close layer 4`; el controlador hace la verificación visual con el navegador, etiqueta `capa-4-cerrada` tras el merge.

---

## Self-review

- **Cobertura del spec**: §2 B (arrastrar y recalcular al instante) → T2, T3, T4; §4 FastAPI + HTML sin framework → T3, T4; no-objetivo "no frontend de producto" → T4 (SVG + JS inline, ≤ 600 líneas); anti-objetivo "arranca en limpio" → T1 (artefacto empaquetado) y Review Focus 5; §4 "la librería como única fuente de verdad para que B y D sean finos" → `decide_snapshot` extraído en T2 y reutilizado por la capa 5.
- **Nombres consistentes**: `build_frames`, `snapshot_from_frame`, `load_frames`, `frame_files`, `decide_snapshot`, `Board`, `BoardState`, `create_app`, `fixture_frames_built`.
- **Review Focus**: 1 → T2; 2 → T2; 3 → T2/T3; 4 → T3; 5 → T3.
- **Decisiones propias que un revisor debe ver**: velocidad 0 para el jugador arrastrado; el balón sigue al tirador; el tirador movido se valora por geometría; no se recalcula la curva ni el frame de decisión al mover (sería otra capa de cómputo y no lo pide el spec).
