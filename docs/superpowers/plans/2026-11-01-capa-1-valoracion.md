# Capa 1: valoración de opciones y coste de decisión — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Para cada tiro de los 10 partidos, fijar el frame de decisión, valorar en puntos esperados el tiro y las cuatro alternativas de pase, calcular el coste de decisión, y dejar listo el kit de la sesión de validación en vivo con Óscar (20 posesiones animadas).

**Architecture:** Cuatro módulos nuevos encadenados sobre `Snapshot`: `decision/frame.py` (qué frame se juzga), `value/` (zonas, priors de temporada, features por opción, modelo de probabilidad), `decision/cost.py` (viabilidad del pase y coste) y `viz/animate.py` (animador mínimo). El modelo es una regresión logística con pocas features documentadas, entrenada con validación dejando un partido fuera; sus coeficientes se versionan en `models/` y la tabla de decisiones de los 10 partidos en `artifacts/decisions/`, como artefactos derivados (spec sección 4). Nada aguas arriba de `align.py` lee `left_hoop`.

**Tech Stack:** Lo de la capa 0 más numpy, scikit-learn (regresión logística, métricas) y matplotlib (calibración y GIFs). Todo open source.

**Spec:** `docs/superpowers/specs/2026-11-01-ventaja-design.md` (sección 5 completa, sección 6 fila 2, sección 4 "artefactos derivados"). Plan previo: `docs/superpowers/plans/2026-11-01-capa-0-esqueleto-y-datos.md`.

## Global Constraints

- Todo lo de la capa 0: Python `>=3.12`, uv, `src/ventaja/`, MIT, pies, 25 fps, aro ofensivo en `(-40.7, 0.0)` en orientación de ataque, ids canónicos, código en inglés y ADRs en castellano, commits convencionales con las líneas de atribución de la sesión.
- **Modelo interpretable**: regresión logística sobre features documentadas; prohibidas las redes neuronales (spec 4). Se publica calibración e importancia de features.
- **Valor de una opción** = `P(anotar | features) × puntos del tiro` en puntos esperados (spec 5.3). Los tiros libres no entran en esta capa.
- **Coste de decisión** = `max(0, valor(mejor alternativa viable) − valor(tiro tomado))` (spec 5.4); cuando el tiro era la mejor opción se marca `good_read`.
- **Frame de decisión** por tipo de tiro (spec 5.1, decisión de Óscar): tiros en salto → inicio del gesto; finalizaciones tras bote → fin del último bote del toque, o inicio del toque si no botó; palmeos y tiros sin tipo → excluidos del coste pero valorados como opciones de otros.
- **Posición proyectada** para opciones de pase: posición actual + velocidad × tiempo de vuelo estimado, con tope (spec 5.2).
- **Descuento de viabilidad** explícito, función simple con parámetros visibles, no aprendida; anulación por reloj de posesión bajo un umbral (spec 5.3).
- Umbrales y constantes de esta capa viven en un solo sitio (`src/ventaja/value/params.py`) y se documentan en ADR-0003 y ADR-0004.
- Hechos medidos sobre los 10 partidos (2026-11-01) que el plan usa: 1 459 tiros; `complexShotType`: layup 486, dribblePullUp 277, catchAndShoot 230, offMove 141, floater 71, hook 69, dunk 42, tip 38, stepback 30, None 26, postFadeaway 16, lob 11, shakeAndRaise 10, heave 9, leaner 3; 81 tiros sin `touch_id`; `releaseTime` = segundos desde el inicio del toque (mediana 1,8 s; jumper 1,12; layup 2,2); en finalizaciones, del último bote a la suelta median 1,2 s (p10 0,8, p90 2,4) y 268 de 682 no botan; la velocidad derivada por diferencia de posiciones entre frames consecutivos difiere de `speed` en 0,08 ft/s de mediana (p90 0,29). Regiones de tiro: `ra` 381, `key` 369, wing/middle three 405, corner three 102, `*two` 164, `backcourt` 9, `far` 3, None 26. Acierto global 41,5 %, 36,7 % de triples. `shots.shot_quality` es el xFG propio de SkillCorner en escala 0-100.
- Columnas del agregado de tiros usadas para priors: `player_id`, `team_id` (nulo en filas `total`), `attempts`, `mades`, `zone_{restricted_area,paint_non_ra,mid_range,corner_3,above_break_3}_{attempts,mades}`, `cl_{open,light,average,plus,blocked}_{attempts,mades}`.

## Review Focus

1. **Tiro sin `touch_id`, palmeo o sin tipo** (81 + 38 + 26 casos): queda `excluded` con motivo, no rompe el build de decisiones, y su tirador sigue apareciendo como opción en los tiros de sus compañeros. Test en Tarea 3.
2. **Frame de decisión sin tracking** (corte de realización): se busca hacia delante hasta +10 frames; si no hay, `excluded` con motivo `no_tracking`; nunca `NoTrackingError` sin capturar en `decisions build`. Test en Tarea 3 y Tarea 7.
3. **Jugador sin fila en los agregados o con 0 intentos en una zona**: el prior cae al de la liga en esa zona, nunca división por cero ni `None`. Test en Tarea 4.
4. **`shot_clock` nulo en el frame** (1 de 1 459 tiros): la viabilidad no anula las opciones; se trata como desconocido. Test en Tarea 7.
5. **Velocidad no calculable** (faltan frames vecinos): `vx`/`vy` nulos, sin proyección, `moving_to_hoop = 0`, sin excepción. Test en Tarea 2 y Tarea 5.

---

## Estructura de ficheros

```
src/ventaja/
  data/build.py            # + build_meta(game_id), build_aggregates()
  data/load.py             # + load_meta(table), load_aggregates(name)
  data/duck.py             # + vistas games, players, matches, agg_shots, agg_drives, agg_picks, decisions
  model/snapshot.py        # PlayerPos/BallPos + vx, vy (nullable)
  model/decision.py        # DecisionFrame, Option, Decision (pydantic)
  decision/align.py        # Aligner: ventana ±2 frames para velocidad; snapshot_for_shot(decision_frame=...)
  decision/frame.py        # decision_frame(shot, touches, dribbles, tracking_frames) -> DecisionFrame
  decision/cost.py         # viability(), classify_alternative(), decide(shot_id) -> Decision, build_decisions(game_id)
  value/__init__.py
  value/params.py          # TODAS las constantes de la capa (ADR-0003/0004)
  value/zones.py           # zone_of(x, y) -> Zone; is_three(x, y); region_to_zone(region)
  value/priors.py          # Priors: league_rate(zone), player_rate(player_id, zone) con shrinkage
  value/features.py        # option_rows(snapshot, shooter_id, priors) -> pl.DataFrame (una fila por opción)
  value/model.py           # ValueModel: fit/predict/save/load (JSON), train_logo(), calibration_table()
  viz/__init__.py
  viz/court.py             # draw_half_court(ax)
  viz/animate.py           # render_shot_gif(aligner, decision, out) ; review kit
  cli.py                   # + model train|report ; decisions build|show ; review sample ; validate decisions
models/value_model.json    # artefacto versionado: coeficientes, escala, features, métricas LOGO
artifacts/decisions/{game_id}.parquet   # artefacto versionado: tabla de decisiones de los 10 partidos
docs/decisions/0003-frame-de-decision.md
docs/decisions/0004-modelo-de-valor-y-viabilidad.md
docs/figures/calibration.png
docs/review/README.md      # guion de la sesión en vivo
tests/test_build_meta.py test_velocity.py test_frame.py test_zones.py test_priors.py
      test_features.py test_model.py test_cost.py test_animate.py test_validate_decisions.py
```

Layout del build (añadido): `{build_dir}/meta/{games,players,matches}.parquet`, `{build_dir}/aggregates/{shots,drives,picks}.parquet`, `{build_dir}/decisions/{game_id}.parquet`.

---

### Task 1: `build_meta` y agregados a parquet (ruling de la revisión final de la capa 0)

**Files:**
- Modify: `src/ventaja/data/build.py`, `src/ventaja/data/load.py`, `src/ventaja/data/duck.py`, `src/ventaja/config.py`, `src/ventaja/cli.py`, `tests/conftest.py`, `scripts/make_fixture.py`
- Create: `tests/test_build_meta.py`, `tests/fixtures/114243/aggregates/acb_shotsaggregates_20252026.csv` (copia íntegra, 326 filas, ~300 KB; drives y picks no se copian)

**Interfaces:**
- Produces:
  - `Settings.meta_parquet(table: str) -> Path` (`build_dir/meta/{table}.parquet`), `Settings.aggregates_parquet(name: str) -> Path` (`build_dir/aggregates/{name}.parquet`), `Settings.decisions_parquet(game_id: int) -> Path`.
  - `build.build_meta(game_id: int, settings: Settings) -> dict[str, Path]`: escribe/actualiza `games` (una fila por partido: `game_id, date, season, home_team_id, home_team_name, away_team_id, away_team_name`), `players` (`game_id, team_id, player_id, first_name, last_name, jersey`, ids canónicos) y `matches` (desde `matches.json`, todas las filas: `game_id, date_time, home_team_id, away_team_id, home_score, away_score`). `games` y `players` se acumulan por partido: se leen las filas existentes, se eliminan las del `game_id` y se añaden las nuevas (idempotente).
  - `build.build_aggregates(settings: Settings) -> dict[str, Path]`: los CSV presentes en `data_dir/aggregates/` → parquet `shots`, `drives`, `picks` con `player_id` canónico y `team_id` nulo preservado; si falta un CSV se omite sin error y se informa.
  - `load.load_meta(table: str, settings) -> pl.DataFrame`, `load.load_aggregates(name: str, settings) -> pl.DataFrame` (ambos `DataNotFoundError` con hint `ventaja data build`).
  - `duck.connect` añade vistas `games`, `players`, `matches`, `agg_shots`, `agg_drives`, `agg_picks` y `decisions` (sobre `build_dir/decisions/*.parquet`) cuando existen ficheros.
  - `ventaja data build` llama también a `build_meta` por partido y a `build_aggregates` una vez.
  - `tests/conftest.py`: `built_fixture` ejecuta además `build_meta` y `build_aggregates`.
  - `scripts/make_fixture.py`: copia `aggregates/acb_shotsaggregates_20252026.csv` íntegro.

- [ ] **Step 1: Tests**

```python
def test_build_meta_games_players_matches(fixture_settings):
    out = build_meta(114243, fixture_settings)
    games = pl.read_parquet(out["games"]); players = pl.read_parquet(out["players"])
    assert games.height == 1 and games["home_team_id"][0] == 1330
    assert players.height == 24 and players["team_id"].n_unique() == 2
    assert pl.read_parquet(out["matches"]).select("home_score", "away_score").row(0) == (83, 68)

def test_build_meta_is_idempotent(fixture_settings):
    build_meta(114243, fixture_settings); out = build_meta(114243, fixture_settings)
    assert pl.read_parquet(out["players"]).height == 24

def test_build_aggregates_shots_only_in_fixture(fixture_settings):
    out = build_aggregates(fixture_settings)
    assert set(out) == {"shots"}
    agg = pl.read_parquet(out["shots"])
    assert agg.height == 326 and agg.filter(pl.col("team_id").is_null()).height == 10   # filas 'total'

def test_duck_has_meta_and_aggregate_views(built_fixture):
    con = connect(built_fixture)
    assert con.sql("select count(*) from players").fetchall()[0][0] == 24
    assert con.sql("select count(*) from agg_shots").fetchall()[0][0] == 326
```

Comprobar el número real de filas `total` del CSV antes de fijar el `10` (contar `team_id` vacío); ajustar la aserción al valor real.

- [ ] **Step 2: Ejecutar → FAIL**  
- [ ] **Step 3: Implementar** (regenerar el fixture con `make_fixture.py` actualizado)  
- [ ] **Step 4: `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy` → PASS**  
- [ ] **Step 5: Commit** `feat: build game metadata and season aggregates to parquet`

---

### Task 2: Velocidad en `Snapshot`

**Files:**
- Modify: `src/ventaja/model/snapshot.py`, `src/ventaja/decision/align.py`
- Create: `tests/test_velocity.py`

**Interfaces:**
- Produces: `PlayerPos.vx: float | None`, `PlayerPos.vy: float | None`, `BallPos.vx/vy: float | None` (ft/s, orientación de ataque). `Aligner.snapshot(frame_idx)` y `window` los rellenan por **diferencia central** con los frames `frame_idx − 2` y `frame_idx + 2` (`(x₊₂ − x₋₂) × 25 / 4`); si falta alguno de los dos, se usa diferencia hacia delante o atrás con el vecino a distancia 1 ó 2 que exista; si no hay ningún vecino, `None`. La rotación se aplica a los vecinos con el mismo `left_hoop` de la posesión del frame central. `PlayerPos.speed_vec` propiedad `hypot(vx, vy)` o `None`.
- `Aligner._frame_rows` pasa a leer `[frame_idx − 2, frame_idx + 2]` en una sola `collect()`; `window(start, end)` lee `[start − 2, end + 2]` una vez.

- [ ] **Step 1: Tests**

```python
def test_velocity_matches_tracking_speed(built_fixture):
    s = Aligner(114243, built_fixture).snapshot_for_shot("shot-114243-1-0")
    for p in s.offense + s.defense:
        assert p.vx is not None and abs(math.hypot(p.vx, p.vy) - p.speed) < 1.0   # ft/s

def test_velocity_is_oriented_like_positions(built_fixture):
    # mismo frame con left_hoop False: la velocidad hacia el aro ofensivo (x negativa) de un jugador que se
    # acerca al aro debe ser negativa en vx. Elegir el jugador con mayor |vx| y comprobar signo coherente
    # con el desplazamiento de x entre window(f-2, f+2)[0] y [-1].
    ...

def test_velocity_none_when_no_neighbours(built_fixture):
    a = Aligner(114243, built_fixture)
    lone = primer frame con tracking cuyos ±2 vecinos no tienen tracking (buscar en el parquet)
    s = a.snapshot(lone)
    assert all(p.vx is None for p in s.offense + s.defense)   # si no existe tal frame: pytest.skip con motivo
```

- [ ] **Step 2: Ejecutar → FAIL**  
- [ ] **Step 3: Implementar**  
- [ ] **Step 4: Calidad → PASS** (los tests de la capa 0 siguen pasando)  
- [ ] **Step 5: Commit** `feat: per-player velocity in Snapshot by central difference`

---

### Task 3: Frame de decisión

**Files:**
- Create: `src/ventaja/value/__init__.py`, `src/ventaja/value/params.py`, `src/ventaja/model/decision.py`, `src/ventaja/decision/frame.py`, `tests/test_frame.py`, `docs/decisions/0003-frame-de-decision.md`
- Modify: `src/ventaja/decision/align.py` (`snapshot_for_shot(shot_id, *, decision: bool = False)`), `src/ventaja/cli.py` (`ventaja snapshot --decision`)

**Interfaces:**
- `params.py` (constantes de esta tarea): `GATHER_FRAMES = 10` (0,4 s), `NO_TRACKING_LOOKAHEAD = 10`, `JUMP_SHOT_TYPES = ("catchAndShoot", "dribblePullUp", "offMove", "stepback", "shakeAndRaise", "postFadeaway", "leaner", "heave")`, `FINISH_TYPES = ("layup", "dunk", "hook", "lob", "floater")`, `EXCLUDED_TYPES = ("tip",)`.
- `model/decision.py`: `DecisionFrame(shot_id: str, frame_idx: int | None, rule: Literal["gather", "last_dribble", "touch_start", "excluded"], reason: str | None)` (frozen pydantic).
- `frame.decision_frame(shot: dict, touch: dict | None, dribble_frames: list[int], has_tracking: Callable[[int], bool]) -> DecisionFrame`:
  - sin `touch_id`, `complex_shot_type` nulo o en `EXCLUDED_TYPES` → `excluded`, `reason` ∈ {`no_touch`, `no_type`, `tip`}.
  - tipo en `JUMP_SHOT_TYPES` → `max(start_frame − GATHER_FRAMES, touch.start_frame)`, regla `gather`.
  - tipo en `FINISH_TYPES` → último frame de bote `≤ start_frame`; si no hay, `touch.start_frame`; reglas `last_dribble` / `touch_start`.
  - tipo no listado → `excluded`, `reason = "unknown_type:<tipo>"`.
  - si `not has_tracking(frame)`: avanzar hasta `NO_TRACKING_LOOKAHEAD` frames; si ninguno tiene tracking → `excluded`, `reason = "no_tracking"`.
- `Aligner.decision_frame(shot_id) -> DecisionFrame` (usa `touches` y `dribbles` del partido, cargados en `__init__`) y `snapshot_for_shot(shot_id, *, decision=False)`: con `decision=True` usa el frame de decisión; si está `excluded` lanza `VentajaError` con el motivo.
- CLI: `ventaja snapshot SHOT_ID --decision` imprime el frame usado y la regla.

- [ ] **Step 1: Tests** (con `built_fixture`; comprobar los valores concretos en los datos del fixture antes de escribirlos)

```python
def test_gather_rule_for_pull_up(built_fixture):
    d = Aligner(114243, built_fixture).decision_frame("shot-114243-1-0")   # dribblePullUp, start 3895
    assert d.rule == "gather" and d.frame_idx == 3895 - 10

def test_last_dribble_rule_for_layup(built_fixture):
    # elegir en el fixture el primer layup con botes en su toque y calcular a mano el último frame de bote
    ...; assert d.rule == "last_dribble" and d.frame_idx == <último bote>

def test_touch_start_rule_for_layup_without_dribble(built_fixture): ...

def test_excluded_rules():
    assert decision_frame({"complex_shot_type": "tip", "touch_id": "t", "start_frame": 100}, {...}, [], lambda f: True).reason == "tip"
    assert decision_frame({"complex_shot_type": "layup", "touch_id": None, "start_frame": 100}, None, [], lambda f: True).reason == "no_touch"

def test_no_tracking_lookahead():
    has = lambda f: f >= 105
    d = decision_frame({"complex_shot_type": "catchAndShoot", "touch_id": "t", "start_frame": 110}, {"start_frame": 90}, [], has)
    assert d.frame_idx == 105
    assert decision_frame({...start_frame 110...}, {"start_frame": 90}, [], lambda f: False).reason == "no_tracking"

def test_decision_snapshot_cli(built_fixture, monkeypatch): ... # exit 0 y "gather" en la salida
```

- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: ADR-0003** (contexto: 44 % de finalizaciones en el aire en la suelta; decisión de Óscar; constantes y sus justificaciones con las cifras de Global Constraints; alternativa descartada: medir siempre en la suelta).
- [ ] **Step 6: Commit** `feat: decision frame per shot type (ADR-0003)`

---

### Task 4: Zonas de pista y priors de temporada

**Files:**
- Create: `src/ventaja/value/zones.py`, `src/ventaja/value/priors.py`, `tests/test_zones.py`, `tests/test_priors.py`
- Modify: `src/ventaja/value/params.py`, `src/ventaja/geometry/court.py` (constantes FIBA que falten)

**Interfaces:**
- `zones.Zone = Literal["restricted_area", "paint_non_ra", "mid_range", "corner_3", "above_break_3", "backcourt", "far"]`.
- Constantes (pies, FIBA, en `court.py`): `RA_RADIUS = 4.10`, `KEY_HALF_WIDTH = 8.04`, `KEY_X_MAX = -26.90` (línea de tiros libres: baseline + 19,03), `CORNER_Y = 21.65`, `CORNER_X_MAX = -36.02` (donde el arco de 22,15 corta `|y| = 21.65`), `FAR_DISTANCE = 35.0`.
- `zones.is_three(x, y) -> bool`: `(abs(y) >= CORNER_Y and x <= CORNER_X_MAX) or distance_to_hoop(x, y) >= THREE_POINT_RADIUS`, siempre con `x <= 0`.
- `zones.zone_of(x, y) -> Zone`: `backcourt` si `x > 0`; `far` si distancia `> FAR_DISTANCE`; `corner_3` si `is_three` y `x <= CORNER_X_MAX`; `above_break_3` si `is_three`; `restricted_area` si distancia `<= RA_RADIUS`; `paint_non_ra` si `abs(y) <= KEY_HALF_WIDTH and x <= KEY_X_MAX`; si no, `mid_range`.
- `zones.region_to_zone(region: str | None) -> Zone | None`: `ra→restricted_area`, `key→paint_non_ra`, `*two→mid_range`, `*corner three→corner_3`, `*wing three|middle three→above_break_3`, `backcourt`, `far`.
- `zones.points(zone) -> int` (3 para `corner_3`/`above_break_3`, 2 resto).
- `priors.Priors` construido con `Priors.from_settings(settings)` (lee `agg_shots`, suma por `player_id` las filas con `team_id` no nulo): `league_rate(zone) -> float`, `player_rate(player_id, zone) -> float` = `(mades + K_SHRINK × league_rate) / (attempts + K_SHRINK)` con `K_SHRINK = 20` en `params.py`; jugador ausente o zona sin intentos → `league_rate`. También `player_contest_rate(player_id, level)` con la misma fórmula sobre `cl_*` (para la Tarea 6).

- [ ] **Step 1: Tests**

```python
def test_zone_of_known_points():
    assert zone_of(-40.7, 0.0) == "restricted_area"
    assert zone_of(-30.0, 0.0) == "paint_non_ra"
    assert zone_of(-25.0, 10.0) == "mid_range"
    assert zone_of(-42.0, 23.0) == "corner_3"
    assert zone_of(-18.0, 0.0) == "above_break_3"
    assert zone_of(5.0, 0.0) == "backcourt"

def test_zone_agrees_with_event_region(built_fixture):
    shots = load_events(114243, "shots", built_fixture).drop_nulls(["loc_x", "region"])
    agree = sum(zone_of(x, y) == region_to_zone(r) for x, y, r in shots.select("loc_x", "loc_y", "region").iter_rows())
    assert agree / shots.height >= 0.95

def test_prior_shrinks_toward_league(built_fixture):
    p = Priors.from_settings(built_fixture)
    league = p.league_rate("above_break_3")
    assert 0.25 < league < 0.45
    assert p.player_rate(999999, "above_break_3") == league           # jugador desconocido
    best = jugador con más intentos de triple en agg_shots
    assert abs(p.player_rate(best, "above_break_3") - league) < abs(raw_rate(best) - league) + 1e-9

def test_prior_zero_attempts_zone(built_fixture): ...  # jugador con 0 intentos en corner_3 → league_rate
```

- [ ] **Step 2 → 4:** FAIL, implementar, PASS. Anotar el porcentaje de acuerdo zona/región observado en el informe.
- [ ] **Step 5: Commit** `feat: court zones and shrunken season priors`

---

### Task 5: Features por opción

**Files:**
- Create: `src/ventaja/value/features.py`, `tests/test_features.py`
- Modify: `src/ventaja/value/params.py`, `src/ventaja/model/decision.py`

**Interfaces:**
- `params.py`: `PASS_SPEED = 40.0` (ft/s), `FLIGHT_MIN = 0.2`, `FLIGHT_MAX = 1.0` (s), `PROJECTION_CAP = 10.0` (ft), `LANE_WIDTH = 3.0` (ft, distancia de un defensor al segmento pasador→receptor para considerarlo en la línea), `LANE_END_MARGIN = 2.0` (ft, los extremos del segmento no cuentan), `BETWEEN_WIDTH = 3.0` (ft, defensor entre jugador y aro).
- `features.OPTION_FEATURES: tuple[str, ...]` = (`dist_hoop`, `dist_hoop_sq`, `angle_abs` (rad, 0 = frontal), `is_three`, `nearest_def_dist`, `def_between`, `closing_speed` (ft/s, componente de la velocidad del defensor más cercano hacia el jugador, positiva si se acerca), `moving_to_hoop` (ft/s, componente de la velocidad del jugador hacia el aro), `prior_zone` (de `Priors.player_rate`), `shot_clock_low` (1 si `shot_clock < 4`), `shot_clock`).
- `features.option_rows(snapshot: Snapshot, shooter_id: int, priors: Priors) -> pl.DataFrame`: cinco filas con columnas `option_player_id`, `option_type` (`"shot"` | `"pass"`), `zone`, `points`, `x`, `y` (posición evaluada: real para el tirador, **proyectada** para los compañeros), `pass_distance` (0 para el tirador), `lane_blocked` (bool; False para el tirador), `projected_dx`, `projected_dy`, más `OPTION_FEATURES`. Proyección: `t = clamp(pass_distance / PASS_SPEED, FLIGHT_MIN, FLIGHT_MAX)`, desplazamiento `(vx·t, vy·t)` limitado a `PROJECTION_CAP`; sin velocidad → sin desplazamiento. `nearest_def_dist` y `def_between` se calculan sobre la posición proyectada con las posiciones actuales de los defensores. `lane_blocked`: algún defensor a menos de `LANE_WIDTH` del segmento pasador→posición proyectada, descontando `LANE_END_MARGIN` en ambos extremos.
- `features.shot_rows(aligner: Aligner, priors: Priors) -> pl.DataFrame`: para cada tiro del partido con frame de decisión no excluido, las cinco filas de `option_rows` más `shot_id`, `game_id`, `decision_frame`, `rule`, y para la fila `shot` del tirador las etiquetas `outcome`, `three` del evento.

- [ ] **Step 1: Tests**

```python
def test_option_rows_shape_and_shooter_row(built_fixture):
    a = Aligner(114243, built_fixture); pri = Priors.from_settings(built_fixture)
    s = a.snapshot_for_shot("shot-114243-1-0", decision=True)
    rows = option_rows(s, 35028, pri)
    assert rows.height == 5 and rows.filter(pl.col("option_type") == "shot").height == 1
    shooter = rows.filter(pl.col("option_player_id") == 35028).row(0, named=True)
    assert shooter["pass_distance"] == 0 and shooter["lane_blocked"] is False
    assert abs(shooter["dist_hoop"] - distance_to_hoop(s.player(35028).x, s.player(35028).y)) < 1e-6

def test_projection_moves_cutter_toward_hoop():
    # Snapshot sintético: compañero en (-30, 0) con vx=-10, vy=0 → posición evaluada x < -30, desplazamiento ≤ cap
    ...

def test_projection_without_velocity_is_identity(): ...   # vx/vy None → x,y iguales

def test_lane_blocked_detects_defender_on_segment():
    # pasador (-10, 0), receptor (-30, 0), defensor (-20, 1) → blocked; defensor (-20, 5) → libre
    ...

def test_shot_rows_covers_non_excluded_shots(built_fixture):
    df = shot_rows(Aligner(114243, built_fixture), Priors.from_settings(built_fixture))
    n_valid = número de tiros con frame de decisión no excluido y con tracking en el fixture (≤ 20)
    assert df.filter(pl.col("option_type") == "shot").height == n_valid
    assert df["prior_zone"].is_between(0.0, 1.0).all()
```

Los snapshots sintéticos se construyen directamente con `Snapshot(...)` (pydantic); añadir un helper `make_snapshot(offense=[...], defense=[...])` en `tests/helpers.py`.

- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Commit** `feat: option features with projected pass positions and lane check`

---

### Task 6: Modelo de valor

**Files:**
- Create: `src/ventaja/value/model.py`, `tests/test_model.py`, `models/value_model.json`, `docs/figures/calibration.png`
- Modify: `pyproject.toml` (añadir `numpy`, `scikit-learn`, `matplotlib`), `src/ventaja/cli.py` (`model train`, `model report`)

**Interfaces:**
- `model.ValueModel` (dataclass): `features: tuple[str, ...]`, `coef: list[float]`, `intercept: float`, `mean: list[float]`, `scale: list[float]`, `metrics: dict[str, float]`, `trained_on: list[int]` (game ids). Métodos: `predict_proba(df: pl.DataFrame) -> pl.Series` (estandariza con `mean/scale`, logística), `value(df) -> pl.Series` (= `proba × points`), `save(path)`, `load(path)` (JSON), `feature_table() -> pl.DataFrame` (feature, coef estandarizado, odds ratio).
- `model.fit(df: pl.DataFrame) -> ValueModel`: regresión logística `sklearn.linear_model.LogisticRegression(C=1.0, max_iter=1000)` sobre las filas `option_type == "shot"` con etiqueta `outcome`, features `OPTION_FEATURES` estandarizadas; se guardan `mean/scale` y coeficientes, **no** el objeto sklearn.
- `model.train_logo(df) -> tuple[ValueModel, pl.DataFrame]`: leave-one-game-out: para cada `game_id` entrena con el resto y predice ese; devuelve el modelo final (todos los partidos) y la tabla de predicciones fuera de muestra (`shot_id, game_id, proba, outcome, points, shot_quality`). Métricas en `metrics`: `logloss`, `brier`, `auc`, `n_shots`, `corr_with_skillcorner` (correlación de Pearson entre `proba` y `shot_quality / 100`).
- `model.calibration_table(preds, bins=10) -> pl.DataFrame` (`bin, n, mean_pred, mean_outcome`) y `model.plot_calibration(table, path)`.
- `model.DEFAULT_MODEL_PATH = Path(__file__).parents[3] / "models" / "value_model.json"` (resuelta desde el paquete; si no existe, `DataNotFoundError` con hint `ventaja model train`). `ValueModel.default()` carga ese fichero.
- CLI: `ventaja model train [--game ...|--all]` construye `shot_rows` por partido, entrena LOGO, guarda `models/value_model.json` y `docs/figures/calibration.png`, imprime métricas; `ventaja model report` imprime métricas y `feature_table()` del modelo guardado.

- [ ] **Step 1: Tests**

```python
def test_fit_and_roundtrip(tmp_path):
    df = sintético: 400 filas option_type shot, features aleatorias, outcome ~ Bernoulli(sigmoid(-0.1*dist_hoop + 2*prior_zone))
    m = fit(df); m.save(tmp_path / "m.json"); m2 = ValueModel.load(tmp_path / "m.json")
    assert (m.predict_proba(df) - m2.predict_proba(df)).abs().max() < 1e-9
    assert m.feature_table().filter(pl.col("feature") == "dist_hoop")["coef"][0] < 0

def test_value_is_proba_times_points(): ...

def test_train_logo_on_fixture_runs(built_fixture):
    df = shot_rows(...)  # un solo partido: LOGO degenera a entrenar y predecir el mismo partido; el test solo comprueba la forma
    m, preds = train_logo(df)
    assert set(["logloss", "brier", "auc", "n_shots"]) <= set(m.metrics) and preds.height == df.filter(option_type=="shot").height

def test_calibration_table_bins(): ...  # 10 bins, suma de n == total
```

- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Entrenar con los 10 partidos reales** (requiere el build completo; usar `VENTAJA_DATA_DIR=~/Repos/opendata-basketball/data` y un `VENTAJA_BUILD_DIR` con los 10 partidos construidos):
  `uv run ventaja model train --all` → `models/value_model.json` y `docs/figures/calibration.png`. Expected: `logloss < 0.68` (mejor que la tasa base 0,415 → 0,678), `auc > 0.62`, `corr_with_skillcorner > 0.4`. Si no se alcanzan, se entrega igual con los números reales en el informe y en el ADR-0004: el mérito está en el marco, no en el AUC (spec 9).
- [ ] **Step 6: Commit** `feat: logistic value model with leave-one-game-out validation` (incluye `models/value_model.json` y la figura)

---

### Task 7: Viabilidad, coste de decisión y tabla `decisions`

**Files:**
- Create: `src/ventaja/decision/cost.py`, `tests/test_cost.py`, `artifacts/decisions/{10 ficheros}.parquet`, `docs/decisions/0004-modelo-de-valor-y-viabilidad.md`
- Modify: `src/ventaja/value/params.py`, `src/ventaja/model/decision.py`, `src/ventaja/cli.py` (`decisions build|show`), `src/ventaja/data/duck.py` (vista `decisions` ya prevista en T1)

**Interfaces:**
- `params.py`: `SHOT_CLOCK_MIN_PASS = 2.0` (s), `LANE_BLOCKED_FACTOR = 0.4`, `PASS_DISTANCE_SOFT = 30.0`, `PASS_DISTANCE_HARD = 60.0` (ft), `OPEN_DEF_DIST = 6.0` (ft, para clasificar "abierto"), `CUT_SPEED = 4.0` (ft/s hacia el aro para "corte").
- `cost.viability(pass_distance: float, lane_blocked: bool, shot_clock: float | None) -> float`: `0.0` si `shot_clock is not None and shot_clock < SHOT_CLOCK_MIN_PASS`; si no, `d = 1.0 − clamp((pass_distance − PASS_DISTANCE_SOFT) / (PASS_DISTANCE_HARD − PASS_DISTANCE_SOFT), 0, 1)`, multiplicado por `LANE_BLOCKED_FACTOR` si `lane_blocked`. Para la opción `shot` siempre `1.0`.
- `cost.classify_alternative(row) -> Literal["rim_cut", "open_corner", "extra_pass", "post", "other"]`: `rim_cut` si `zone ∈ {restricted_area, paint_non_ra}` y `moving_to_hoop >= CUT_SPEED`; `open_corner` si `zone == corner_3` y `nearest_def_dist >= OPEN_DEF_DIST`; `post` si `zone == paint_non_ra` y `moving_to_hoop < CUT_SPEED`; `extra_pass` si `zone ∈ {above_break_3, mid_range}` y `nearest_def_dist >= OPEN_DEF_DIST`; si no, `other`.
- `model/decision.py`: `Option(player_id, option_type, zone, points, x, y, proba, value, viability, adjusted_value, alternative_type, features: dict[str, float])`, `Decision(shot_id, game_id, shooter_id, decision_frame, rule, shot_clock, shot_value, best_alt_player_id: int | None, best_alt_type: str | None, best_alt_value: float | None, cost: float, good_read: bool, confidence: float, options: list[Option])`. `confidence` = fracción de los 10 jugadores con `is_detected` en el frame.
- `cost.decide(aligner, shot_id, priors, model) -> Decision | None` (`None` si el tiro está excluido): `adjusted_value = value × viability`; mejor alternativa = máximo `adjusted_value` entre las filas `pass`; `cost = max(0, best_alt − shot_value)`; `good_read = best_alt <= shot_value`.
- `cost.build_decisions(game_id, settings, *, model=None) -> Path`: todas las decisiones del partido (excluidos como filas con `rule = "excluded"`, `reason`, y el resto nulo) a `settings.decisions_parquet(game_id)`, columnas planas de `Decision` sin `options` más `reason`.
- CLI: `ventaja decisions build [--game|--all]`; `ventaja decisions show SHOT_ID` imprime cabecera (frame, regla, reloj, coste) y la tabla de las cinco opciones (jugador, tipo, zona, P, valor, viabilidad, valor ajustado, tipo de alternativa) con el tirador marcado y la mejor alternativa marcada.

- [ ] **Step 1: Tests**

```python
def test_viability_rules():
    assert viability(10, False, 12.0) == 1.0
    assert viability(10, True, 12.0) == 0.4
    assert viability(45, False, 12.0) == pytest.approx(0.5)
    assert viability(10, False, 1.5) == 0.0
    assert viability(10, False, None) == 1.0            # Review Focus 4

def test_classify_alternative_cases(): ...   # un caso por categoría

def test_decide_on_fixture_shot(built_fixture, trained_fixture_model):
    d = decide(Aligner(114243, built_fixture), "shot-114243-1-0", priors, model)
    assert d is not None and len(d.options) == 5 and d.cost >= 0
    assert d.good_read == (d.best_alt_value is None or d.best_alt_value <= d.shot_value)

def test_decide_excluded_returns_none(built_fixture, trained_fixture_model): ...  # un tip del fixture

def test_build_decisions_has_one_row_per_shot(built_fixture, trained_fixture_model):
    df = pl.read_parquet(build_decisions(114243, built_fixture, model=model))
    assert df.height == 159 and df.filter(pl.col("rule") == "excluded")["reason"].is_not_null().all()
```

`trained_fixture_model` es una fixture de `conftest.py` que entrena `fit(shot_rows(...))` sobre el fixture una vez por sesión (modelo de juguete, solo para tests).

- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Construir y versionar las decisiones reales**: con el build de los 10 partidos y el modelo de la Tarea 6, `uv run ventaja decisions build --all` y copiar los 10 parquet a `artifacts/decisions/`. Añadir `ventaja decisions build --from-artifacts` no: en su lugar, `load_decisions(game_id, settings)` busca primero `settings.decisions_parquet` y, si no existe, `artifacts/decisions/{game_id}.parquet` del paquete (misma convención que `DEFAULT_MODEL_PATH`).
- [ ] **Step 6: ADR-0004** (modelo: features, por qué logística, métricas LOGO reales, correlación con `shot_quality` de SkillCorner; viabilidad: fórmula y constantes; artefactos versionados: qué, dónde, cómo regenerar).
- [ ] **Step 7: Commit** `feat: pass viability, decision cost and decisions table (ADR-0004)`

---

### Task 8: Validación de cara automática (`ventaja validate decisions`)

**Files:**
- Create: `src/ventaja/validate/decisions.py`, `tests/test_validate_decisions.py`
- Modify: `src/ventaja/cli.py`, `tests/test_realdata.py`

**Interfaces:**
- `validate.decisions.checks(decisions: pl.DataFrame, options: pl.DataFrame | None = None) -> list[tuple[str, bool, str]]` (nombre, ok, detalle) con, al menos (spec 5.5):
  1. `cost_falls_with_clock`: coste medio por tramo `24-14 > 14-6 > 6-0`.
  2. `rim_open_beats_contested_three`: valor medio de opciones `restricted_area` con `nearest_def_dist >= 6` > valor medio de opciones `above_break_3` con `nearest_def_dist < 3`.
  3. `prior_moves_value`: para una opción sintética, subir `prior_zone` de 0,30 a 0,45 sube `proba`.
  4. `excluded_share_below_15pct`: fracción de tiros excluidos (sin contar `no_tracking`) ≤ 0,15.
- CLI `ventaja validate decisions [--game|--all]`: una línea por check, exit 1 si alguno falla.
- `tests/test_realdata.py`: nuevo test `realdata` que construye decisiones de los 10 partidos y exige los cuatro checks en verde.

- [ ] **Step 1: Tests** sobre el fixture (checks 3 y 4 deben pasar; 1 y 2 pueden no ser significativos con 20 tiros: el test del fixture solo comprueba que devuelven un bool y detalle sin excepción) y un test sintético para cada check con datos que lo hagan fallar.
- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Ejecutar sobre los 10 partidos reales** y pegar el resultado en el informe. Expected: 4 checks ok. Si el 1 o el 2 fallan, **no se ajustan constantes para forzarlos**: se documenta en el ADR-0004 y se lleva a la sesión con Óscar.
- [ ] **Step 6: Commit** `feat: sanity checks for decisions`

---

### Task 9: Animador mínimo y kit de la sesión de revisión

**Files:**
- Create: `src/ventaja/viz/__init__.py`, `src/ventaja/viz/court.py`, `src/ventaja/viz/animate.py`, `tests/test_animate.py`, `docs/review/README.md`
- Modify: `src/ventaja/cli.py` (`review sample`)

**Interfaces:**
- `viz.court.draw_half_court(ax: matplotlib.axes.Axes) -> None`: media pista en orientación de ataque con las constantes de `court.py` (aro, RA, zona, arco de tres, esquinas), aspecto 1:1, `x ∈ [-47, 0]`, `y ∈ [-25, 25]`.
- `viz.animate.render_shot_gif(aligner: Aligner, decision: Decision, out: Path, *, before_s: float = 3.0, after_s: float = 1.0, fps: int = 12) -> Path`: frames de `aligner.window(decision_frame − before_s×25, start_frame + after_s×25)` submuestreados a `fps`; ataque en color por valor ajustado de su opción (escala fija 0,6-1,5 pts, colormap `viridis`), defensa gris, balón naranja, tirador con borde; en el frame de decisión se dibuja la flecha a la mejor alternativa y se congela 1 s; título con `shot_id`, regla, reloj y coste. Salida GIF con `matplotlib.animation.PillowWriter`.
- `viz.animate.review_kit(settings, game_ids, n: int, seed: int, out_dir: Path) -> Path`: muestrea `n` tiros no excluidos con `random.Random(seed)` estratificados por regla (`gather` / `last_dribble` / `touch_start` en proporción a su frecuencia), renderiza un GIF por tiro y escribe `out_dir/review.md` con una sección por tiro: GIF, tabla de opciones (como `decisions show`), y tres líneas en blanco `Frame de decisión: ok / mal → `, `Opciones valoradas: ok / mal → `, `Comentario: `.
- CLI: `ventaja review sample [--game|--all] [--n 20] [--seed 7] --out DIR`.
- `docs/review/README.md` (castellano): guion de la sesión en vivo de la semana del 9-15 de noviembre: objetivo (spec 5.5), cómo se generó la muestra, qué mirar en cada posesión (¿el frame es el momento de decidir? ¿las opciones mejor valoradas coinciden con lo que ve un entrenador? ¿la proyección del cortador es razonable?), cómo se registran las discrepancias (en `review.md`) y qué pasa después (si son sistemáticas, cambian constantes en `params.py` o reglas en `frame.py` antes de abrir la capa 2).

- [ ] **Step 1: Tests**

```python
def test_render_shot_gif_writes_file(built_fixture, trained_fixture_model, tmp_path):
    a = Aligner(114243, built_fixture); d = decide(a, "shot-114243-1-0", priors, model)
    out = render_shot_gif(a, d, tmp_path / "x.gif", before_s=1.0, after_s=0.2, fps=6)
    assert out.exists() and out.stat().st_size > 10_000

def test_review_kit_writes_markdown_and_gifs(built_fixture, trained_fixture_model, tmp_path):
    out = review_kit(built_fixture, [114243], n=3, seed=1, out_dir=tmp_path)
    md = (tmp_path / "review.md").read_text()
    assert md.count("Frame de decisión") == 3 and len(list(tmp_path.glob("*.gif"))) == 3
```

Usar el backend `Agg` de matplotlib en tests y CLI (`matplotlib.use("Agg")` antes de importar `pyplot`).

- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Generar el kit real**: `uv run ventaja review sample --all --n 20 --seed 7 --out docs/review/2026-11-sample` (los GIFs **no** se commitean: añadir `docs/review/*/*.gif` a `.gitignore`; sí se commitea `review.md`).
- [ ] **Step 6: Commit** `feat: minimal possession animator and live review kit`

---

### Task 10: Cierre de la capa

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `.github/workflows/ci.yml`

- [ ] **Step 1: README** (inglés): sección "Decisions" con `ventaja model report`, `ventaja decisions show shot-114243-1-0`, `ventaja validate decisions --game 114243`, `ventaja review sample`; nota de que `models/value_model.json` y `artifacts/decisions/` vienen en el repo y cómo regenerarlos; las métricas LOGO reales en una frase.
- [ ] **Step 2: CLAUDE.md**: comandos nuevos; regla "toda constante de la capa 1 vive en `value/params.py` y cambia solo con un ADR".
- [ ] **Step 3: CI**: el job `pipeline` añade `uv run ventaja decisions build --game 114243`, `uv run ventaja validate decisions --game 114243` y `uv run ventaja decisions show shot-114243-1-0` (usan el modelo versionado); `pipeline-all` añade `ventaja model train --all` y `ventaja validate decisions --all` para detectar deriva semanal (no sobreescribe el modelo versionado: `--out /tmp/model.json`; añadir esa opción a `model train`).
- [ ] **Step 4: Calidad completa + `uv run pytest -m realdata` con las variables de datos reales** → verde.
- [ ] **Step 5: Commit** `docs: close layer 1` y, tras el merge a `main`, etiqueta `capa-1-cerrada` (la pone el controlador, no el implementador).

---

## Self-review

- **Cobertura del spec**: 5.1 frame de decisión → T3; 5.2 opciones y features con proyección → T2 (velocidad), T4 (zonas, priors), T5; 5.3 valor, modelo regularizado con prior, validación LOGO, descuento de viabilidad explícito → T6, T7; 5.4 coste, truncado en cero, `good_read`, agregación por reloj y tipo de alternativa → T7 (columnas) y T8 (check por reloj); 5.5 validación de cara: marcador ya hecho en capa 0, animar 20 posesiones y revisar con Óscar → T9 (kit; la sesión es un hito humano, no una tarea), sanidad → T8; sección 4 artefactos versionados → T6 (`models/`) y T7 (`artifacts/decisions/`); ruling `build_meta` → T1; sección 9 riesgos (muestra pequeña, error de tracking) → `confidence` en T7, honestidad en ADR-0004. La agregación por jugador (ficha) es capa 3 y queda fuera.
- **Nombres consistentes**: `Priors.player_rate/league_rate`, `option_rows`, `shot_rows`, `OPTION_FEATURES`, `ValueModel.predict_proba/value/default`, `fit`, `train_logo`, `viability`, `classify_alternative`, `decide`, `build_decisions`, `Decision`, `Option`, `DecisionFrame`, `render_shot_gif`, `review_kit`, `trained_fixture_model` se usan igual en todas las tareas.
- **Review Focus**: 1 → T3 (`excluded` con motivo) y T7 (filas excluidas en la tabla); 2 → T3 (`no_tracking`) y T7 (`decide` devuelve `None`); 3 → T4; 4 → T7 (`viability(..., None) == 1.0`); 5 → T2 (`None`) y T5 (proyección identidad).
- **Proporción**: el plan fija constantes, firmas y tests; los cuerpos quedan al implementador salvo las fórmulas que el spec exige explícitas (viabilidad, prior, proyección).
