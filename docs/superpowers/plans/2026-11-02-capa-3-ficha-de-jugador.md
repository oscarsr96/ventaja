# Capa 3: ficha de jugador — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Para cada jugador con al menos un tiro valorado en los 10 partidos, una ficha con el valor de sus tiros frente al de su mejor opción, el coste de decisión por tramo de reloj y por alternativa ignorada, los momentos perdidos, el cruce con su perfil de temporada en los agregados de SkillCorner y una frase de perfil generada por reglas; más la agregación por equipo y un ranking.

**Architecture:** Un paquete nuevo `profile/` con cuatro módulos puros (agregación de decisiones y curvas, cruce con la temporada, frase por reglas, ficha pydantic y construcción de artefactos) que solo leen las tablas versionadas de las capas 1 y 2 y los agregados; nada recalcula tracking. Antes, `cli.py` (736 líneas) se trocea en un paquete `cli/` por subcomando, sin cambiar ningún comando. Las tres deudas de la capa 2 que tocan los rankings entran como tarea propia. Artefactos nuevos: `artifacts/players.parquet` y `artifacts/teams.parquet`, con el mismo patrón de carga y vistas SQL.

**Tech Stack:** Lo de las capas anteriores. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-11-01-ventaja-design.md` (§2 "Ficha de jugador", §5.4 agregación, §6 fila 4, §9 riesgo "juicio injusto al jugador"). ADRs vigentes 0003-0007. Decisión de Óscar (2026-11-02): **mínimo 1 tiro valorado para tener ficha**.

## Global Constraints

- Todo lo de las capas 0-2: Python `>=3.12`, uv, `src/ventaja/`, MIT, código en inglés, ADRs en castellano, commits convencionales con las dos líneas de atribución, mypy strict y ruff limpios, tests sin avisos. Toda constante de la capa en `src/ventaja/value/params.py`, cambiable solo con ADR (ADR-0008).
- **Spec §2, ficha**: "valor de sus tiros vs. valor de la mejor opción, coste de decisión por reloj, alternativa que más ignora, frase de perfil. Cruza el frame del tracking con el perfil de temporada del jugador desde los agregados."
- **Spec §5.4**: coste agregado "por jugador, equipo, tramo de reloj (24-14, 14-6, 6-0 s) y tipo de alternativa ignorada (corte al aro, esquina abierta, extra pass, poste)".
- **Spec §9**: "la ficha siempre muestra el desglose por reloj y el descuento de viabilidad; el lenguaje de la frase de perfil es descriptivo, no acusatorio".
- **Decisión de Óscar**: la ficha existe desde 1 tiro valorado. Las afirmaciones de tendencia de la frase exigen un mínimo de apoyo (`PROFILE_MIN_SHOTS = 8`); por debajo, la frase lo dice y no afirma tendencias. El ranking admite `--min-shots` con valor por defecto 1 y muestra siempre `n`.
- Hechos medidos (2026-11-02): 190 jugadores con ≥ 1 tiro valorado; mediana 6 tiros; 18 con ≥ 15; 1 con ≥ 30 (máximo 30). `best_alt_type` en las 1 351 decisiones: extra_pass 757, open_corner 242, other 173, post 78, rim_cut 53, nulo 48 (sin pase viable). Agregados: `shots` 326 filas × 308 columnas (`player_id, team_id` nulo en filas `total`, `games_played, attempts, mades, three_attempts, three_mades, two_*, cns_* (catch and shoot), od_* (off the dribble), contested_*, zone_{restricted_area,paint_non_ra,mid_range,corner_3,above_break_3}_{attempts,mades}`, `cl_{open,light,average,plus,blocked}_{attempts,mades}`, `avg_attempts_distance`, `assisted_mades`), `drives` 301 filas (`total_drives, end_type_kickout_count, end_type_pullup_count, end_type_shot_near_basket_count, end_type_turnover_count, ...`). Un jugador traspasado tiene una fila por equipo más la `total`.
- Tablas de entrada: `decisions` (`shot_id, game_id, shooter_id, decision_frame, release_frame, rule, reason, shot_clock (nullable), shot_value, best_alt_player_id, best_alt_type, best_alt_value, cost, good_read (nullable), confidence`), `curve_summaries` (`shot_id, game_id, verdict, advantage_seconds, release_lag_seconds, window_handler_id, window_peak_value, held_to_decision, shot_value, ...`), `meta/players` (`game_id, team_id, player_id, first_name, last_name, jersey`), `meta/games`.

## Review Focus

1. **Jugador con 1 tiro**: la ficha existe, ningún tramo de reloj o alternativa divide por cero (los vacíos son nulos, no 0.0), y la frase declara la muestra pequeña. Test en Tareas 2 y 4.
2. **Jugador sin fila en los agregados** (no tiró en la temporada según SkillCorner, o id sin alias): la ficha existe con el bloque de temporada nulo y la frase omite la comparación. Test en Tarea 3.
3. **Jugador traspasado** (dos filas de equipo en los agregados): se suman las filas con `team_id` no nulo; `team` en la ficha es el equipo con el que jugó en los 10 partidos (de `meta/players`), no el de los agregados. Test en Tarea 3.
4. **Búsqueda por nombre ambigua o sin resultado** (`ventaja player show "García"`): lista los candidatos con id y equipo, exit 1; nunca elige uno al azar. Test en Tarea 5.
5. **Filas con `good_read` o `shot_clock` nulos**: cuentan en `n_shots`, se excluyen del tramo de reloj o de la proporción de buenas lecturas correspondiente, y la ficha muestra cuántas quedaron fuera. Test en Tarea 2.

---

## Estructura de ficheros

```
src/ventaja/
  cli/__init__.py            # app + add_typer de cada módulo (sustituye a cli.py)
  cli/_common.py             # GameOption/AllOption, _game_of_shot, settings/errores compartidos
  cli/data.py cli/validate.py cli/model.py cli/decisions.py cli/curves.py cli/review.py cli/reel.py cli/snapshot.py cli/player.py
  value/params.py            # + CLOCK_BUCKETS, PROFILE_MIN_SHOTS, PROFILE_* umbrales, LATE_MIN_CLOCK
  profile/__init__.py
  profile/aggregate.py       # player_table(), team_table(), league_row()
  profile/season.py          # season_profile(), tracked_zone_mix()
  profile/phrase.py          # profile_phrase(card, league, lang)
  profile/card.py            # PlayerCard, TeamCard (pydantic); build_players(); card_of()
  data/load.py               # artifact_dir(kind) admite "players"; load_players_cards(), load_teams_cards()
  data/duck.py               # vistas player_cards, team_cards
  reel.py                    # momentos perdidos: orden por valor perdido, filtro de reloj
artifacts/players.parquet, artifacts/teams.parquet
docs/decisions/0008-ficha-de-jugador.md
tests/test_cli_split.py test_profile_aggregate.py test_season.py test_phrase.py test_card.py test_reel.py (ampliado)
```

---

### Task 1: Trocear `cli.py` en un paquete `cli/`

**Files:**
- Create: `src/ventaja/cli/__init__.py`, `src/ventaja/cli/_common.py`, un módulo por sub-typer existente (`data.py`, `validate.py`, `model.py`, `decisions.py`, `curves.py`, `review.py`, `reel.py`, `snapshot.py` para los comandos sueltos `sql`, `snapshot`, `clip`), `tests/test_cli_split.py`
- Delete: `src/ventaja/cli.py`
- Modify: `pyproject.toml` (`ventaja = "ventaja.cli:app"` sigue válido con el paquete)

**Interfaces:**
- Produces: `ventaja.cli.app` (mismo objeto typer), `cli._common` con `GameOption`, `AllOption`, `game_of_shot(shot_id) -> int`, `settings_or_exit() -> Settings`, `run_or_exit(fn)` (captura `VentajaError` → mensaje `error: ...` en stderr y exit 1, el patrón que hoy se repite en cada comando). Ningún comando, opción, texto de ayuda ni código de salida cambia.

- [ ] **Step 1: Test** `test_cli_split.py`: `test_every_command_still_registered` (la lista de `app.registered_groups` + comandos de cada grupo contiene exactamente `data pull|status|build`, `validate score|decisions`, `model train|report`, `decisions build|show`, `curves build|show|plot`, `review sample`, `reel rankings|build`, `sql`, `snapshot`, `clip`), `test_help_texts_unchanged` (`--help` de `ventaja`, `ventaja decisions` y `ventaja reel` contienen las mismas líneas de comandos que antes: capturar el texto actual ANTES de trocear y pegarlo como esperado).
- [ ] **Step 2 → 4:** FAIL (el paquete no existe), mover el código módulo a módulo sin reescribirlo, todos los tests existentes de CLI siguen pasando; `uv run ventaja --help` idéntico.
- [ ] **Step 5: Commit** `refactor: split cli.py into a cli package`

---

### Task 2: Agregación por jugador, equipo y liga

**Files:**
- Create: `src/ventaja/profile/__init__.py`, `src/ventaja/profile/aggregate.py`, `tests/test_profile_aggregate.py`
- Modify: `src/ventaja/value/params.py`

**Interfaces:**
- `params.py`: `CLOCK_BUCKETS = (("24-14", 14.0, 24.0), ("14-6", 6.0, 14.0), ("6-0", 0.0, 6.0))` (nombre, mínimo exclusivo salvo el último que incluye 0, máximo inclusivo; coincide con `validate.decisions`), `ALT_TYPES = ("rim_cut", "open_corner", "extra_pass", "post", "other")`.
- `aggregate.player_table(decisions: pl.DataFrame, summaries: pl.DataFrame) -> pl.DataFrame`: una fila por `shooter_id` sobre `rule != "excluded"`. Columnas: `player_id, n_shots, n_readable` (good_read no nulo), `good_read_share` (nulo si `n_readable == 0`), `mean_shot_value, mean_best_alt_value` (sobre legibles), `mean_cost` (sobre legibles; el coste de los no legibles es 0 y no entra), `total_cost`, `n_clock_known`, por tramo `cost_{bucket}` (media; nulo si vacío) y `n_{bucket}`, por alternativa `n_alt_{type}` (decisiones con `cost > ADVANTAGE_TOLERANCE` y ese `best_alt_type`) y `cost_alt_{type}` (media), `ignored_alt` (el `alt_type` con mayor `n_alt_*`; nulo si todos 0), `n_late_held` (resúmenes `late & held_to_decision`), `late_held_share` (sobre `n_shots` con resumen), `mean_lag_held` (media de `release_lag_seconds` en ellos), `n_during` y `during_share`, `mean_confidence`, `n_low_confidence` (`confidence < MIN_RANK_CONFIDENCE`).
- `aggregate.team_table(decisions, summaries, players_meta: pl.DataFrame) -> pl.DataFrame`: lo mismo por `team_id` (el equipo del tirador en ese partido según `meta/players`), más `n_players`.
- `aggregate.league_row(decisions, summaries) -> dict[str, float | None]`: las mismas métricas sobre todo.
- Reglas: los nulos nunca se rellenan con 0; una media sobre cero filas es nula.

- [ ] **Step 1: Tests** sintéticos con DataFrames pequeños: `test_player_table_counts_and_means` (dos jugadores, uno con 3 tiros y uno con 1; comprobar `n_shots`, `good_read_share`, `mean_cost`, `cost_24-14` nulo cuando no hay tiros en el tramo, `ignored_alt`), `test_null_good_read_and_clock_excluded_but_counted` (Review Focus 5), `test_single_shot_player_has_no_division_by_zero` (Review Focus 1: todas las medias vacías son `None`, ninguna excepción), `test_team_table_uses_meta_team` (jugador con dos partidos en equipos distintos cuenta en cada uno), `test_league_row_matches_decisions_mean` (sobre el fixture construido: `league_row()["mean_cost"] == decisions.filter(good_read no nulo)["cost"].mean()`).
- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Commit** `feat: decision aggregates per player, team and league`

---

### Task 3: Cruce con la temporada

**Files:**
- Create: `src/ventaja/profile/season.py`, `tests/test_season.py`

**Interfaces:**
- Consumes: `load_aggregates("shots", settings)`, `load_aggregates("drives", settings)` (si falta `drives` → bloque de drives nulo, sin error), `load_decision_options` (filas `option_type == "shot"` para la mezcla de zonas en los 10 partidos), `Priors` no se usa (la ficha muestra tasas crudas de temporada, no encogidas; se dice en el ADR).
- `season.season_profile(player_id: int, shots_agg: pl.DataFrame, drives_agg: pl.DataFrame | None) -> dict[str, float | int | None]`: suma de las filas con `team_id` no nulo del jugador (Review Focus 3); claves: `season_games, season_attempts, season_fg` (mades/attempts), `season_three_share` (three_attempts/attempts), `season_cns_share` (cns_attempts/attempts), `season_contested_share` (contested_attempts/attempts), `season_open_fg` (cl_open), `season_zone_share_{zone}` para las cinco zonas, `season_avg_distance`, `season_drives, season_drive_kickout_share, season_drive_pullup_share` (de `drives`; nulos si no hay fila). Jugador ausente → todas las claves con `None` (Review Focus 2). Ninguna división por cero: denominador 0 → `None`.
- `season.tracked_zone_mix(player_id: int, options: pl.DataFrame) -> dict[str, float | None]`: `tracked_zone_share_{zone}` sobre las filas `shot` del jugador en las decisiones, mismas cinco zonas (las zonas `backcourt`/`far` se agrupan en `other`), y `tracked_attempts`.
- `season.zone_shift(season: dict, tracked: dict) -> dict[str, float | None]`: `shift_{zone} = tracked − season` cuando ambos existen.

- [ ] **Step 1: Tests**: `test_season_profile_sums_team_rows_not_total` (sintético: jugador con dos filas de equipo y una `total`; `season_attempts` = suma de las dos, no el triple), `test_missing_player_gives_nulls`, `test_zero_denominators_give_none`, `test_tracked_zone_mix_on_fixture` (fixture: sumas de proporciones ≈ 1 para un tirador con ≥ 2 tiros), `test_zone_shift`.
- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Commit** `feat: season profile from SkillCorner aggregates`

---

### Task 4: Frase de perfil por reglas

**Files:**
- Create: `src/ventaja/profile/phrase.py`, `tests/test_phrase.py`
- Modify: `src/ventaja/value/params.py`

**Interfaces:**
- `params.py`: `PROFILE_MIN_SHOTS = 8` (tiros legibles para afirmar una tendencia), `PROFILE_COST_DELTA = 0.05` (pts sobre la media de la liga para "deja pasar opciones" / bajo para "lee bien"), `PROFILE_READ_DELTA = 0.08` (proporción de buenas lecturas sobre la liga), `PROFILE_LATE_SHARE = 0.25` (momentos perdidos en mano sobre tiros con curva), `PROFILE_ALT_MIN = 3` (decisiones para nombrar la alternativa que más ignora), `PROFILE_ZONE_SHIFT = 0.15` (cambio de mezcla de zonas respecto a la temporada que se menciona).
- `phrase.profile_phrase(row: Mapping[str, Any], league: Mapping[str, Any], *, lang: Literal["es", "en"] = "es") -> str`: una o dos frases, descriptivas y nunca acusatorias (spec §9), construidas por estas reglas en orden y unidas con "; " dentro de la primera frase:
  1. **Muestra**: si `n_readable < PROFILE_MIN_SHOTS` → la frase empieza por "Con {n} tiros valorados la muestra es pequeña" y SOLO añade la regla 5 (reloj) si hay ≥ 1 tiro en dos tramos; nada más.
  2. **Lectura global**: `good_read_share ≥ league + PROFILE_READ_DELTA` → "elige bien el tiro"; `mean_cost ≥ league + PROFILE_COST_DELTA` → "suele tener un pase mejor disponible"; si ninguna, "decide en la media de la liga".
  3. **Alternativa**: si `n_alt_{ignored_alt} ≥ PROFILE_ALT_MIN` → "la opción que más deja pasar es {nombre en castellano: el corte al aro / la esquina abierta / el pase extra / el poste / otra}".
  4. **Momentos perdidos**: `late_held_share ≥ PROFILE_LATE_SHARE` → "tiende a tirar cuando la ventaja ya se ha esfumado".
  5. **Reloj**: tramo con mayor `cost_{bucket}` entre los que tienen ≥ 2 tiros, si supera al menor en `PROFILE_COST_DELTA` → "su coste sube con {24-14 → mucho reloj / 14-6 → reloj medio / 6-0 → el reloj agotándose}".
  6. **Temporada** (segunda frase, solo si hay bloque de temporada): si algún `shift_{zone} ≥ PROFILE_ZONE_SHIFT` → "En estos partidos tira más desde {zona} que en su temporada"; si `season_cns_share ≥ 0.6` → "Es sobre todo un tirador tras recepción"; si `season_contested_share ≥ 0.5` → "La mayoría de sus tiros de temporada son con mano encima".
  Vocabulario castellano de zonas: zona restringida, pintura, media distancia, esquina, triple frontal. Versión inglesa equivalente. Nunca las palabras "malo", "error", "culpa", "egoísta".
- `phrase.ALT_NAMES_ES`, `ZONE_NAMES_ES`, `BUCKET_NAMES_ES` como diccionarios públicos (los reutiliza la ficha).

- [ ] **Step 1: Tests** sintéticos (una `row` y una `league` construidas a mano por caso): `test_small_sample_phrase` (n=3 → empieza por "Con 3 tiros valorados" y no contiene "deja pasar"), `test_good_reader`, `test_leaves_passes_and_names_alternative`, `test_late_tendency`, `test_clock_rule_picks_worst_bucket`, `test_season_sentence_zone_shift`, `test_no_season_block_no_second_sentence`, `test_banned_words_never_appear` (recorre 20 filas aleatorias con semilla y comprueba la lista prohibida), `test_english_variant`.
- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Commit** `feat: rule-based player profile phrase`

---

### Task 5: Ficha, artefactos, carga, vistas y CLI

**Files:**
- Create: `src/ventaja/profile/card.py`, `src/ventaja/cli/player.py`, `tests/test_card.py`, `artifacts/players.parquet`, `artifacts/teams.parquet`, `docs/decisions/0008-ficha-de-jugador.md`
- Modify: `src/ventaja/data/load.py`, `src/ventaja/data/duck.py`, `src/ventaja/config.py`, `src/ventaja/cli/__init__.py`, `tests/conftest.py`, `tests/test_realdata.py`

**Interfaces:**
- `model/decision.py` o `profile/card.py`: `PlayerCard(_Frozen)` con `player_id, name, team_id, team, games: list[int], n_shots, n_readable, n_low_confidence, good_read_share, mean_shot_value, mean_best_alt_value, mean_cost, total_cost, clock: dict[str, tuple[int, float | None]]` (tramo → (n, coste medio)), `alternatives: dict[str, tuple[int, float | None]]`, `ignored_alt: str | None, n_late_held, late_held_share, mean_lag_held, during_share, season: dict[str, float | int | None], tracked_zone: dict, zone_shift: dict, phrase_es, phrase_en, built_at`; `TeamCard` análogo sin temporada ni frase, con `n_players` y `players: list[int]`.
- `card.build_players(settings, *, out_dir: Path | None = None) -> tuple[Path, Path]`: concatena decisiones y resúmenes de los 10 partidos (`load_decisions`/`load_curve_summaries` vía `artifact_dir`), `player_table`, `team_table`, `league_row`, `season_profile` por jugador, frases; escribe `players.parquet` (una fila por jugador, columnas planas: los dict se aplanan con prefijos `clock_`, `alt_`, `season_`, `tracked_`, `shift_`; `games` como lista) y `teams.parquet`, esquemas explícitos, escritura atómica; `league_row` se guarda como fila con `player_id = 0` y `name = "LIGA"` en `players.parquet` (documentado) para que el ranking y la frase la tengan a mano.
- `card.card_of(player_id: int, players: pl.DataFrame) -> PlayerCard` (reconstruye los dict desde las columnas planas); `card.find_player(query: str, players_meta: pl.DataFrame) -> list[tuple[int, str, str]]` (id, nombre, equipo) por id exacto o subcadena de nombre sin tildes ni mayúsculas.
- `Settings.players_parquet()`, `teams_parquet()` = `build_dir/players/{players,teams}.parquet`; `load.artifact_dir` admite `"players"`; `load.load_players_cards(settings)`, `load_teams_cards(settings)`; `duck.connect` añade vistas `player_cards`, `team_cards`.
- CLI (`cli/player.py`, sub-typer `player`): `ventaja player build [--out DIR]`; `ventaja player show QUERY` (id o nombre; ficha en texto: cabecera, tabla por reloj, tabla por alternativa, momentos perdidos, bloque de temporada con las cinco zonas y el desplazamiento, frase; exit 1 con la lista de candidatos si la búsqueda es ambigua o vacía); `ventaja player rank [--min-shots 1] [--n 20] [--by mean_cost|good_read_share|late_held_share]` (tabla con `n` siempre visible); `ventaja player team TEAM_ID|NAME`.
- `tests/conftest.py`: fixture de sesión `fixture_players_built` (sobre `fixture_curves_built`: `build_players`).

- [ ] **Step 1: Tests**: `test_build_players_fixture` (una fila por tirador del fixture con ≥ 1 tiro valorado más la fila LIGA; `n_shots` suma 17; esquema explícito), `test_card_of_roundtrip` (dict ↔ columnas planas), `test_find_player_by_name_and_ambiguity` (Review Focus 4: "a" devuelve varios; "zzz" devuelve vacío), `test_player_show_cli` (exit 0; contiene la frase y la tabla por reloj; `show "zzz"` exit 1), `test_player_rank_cli_min_shots` (con `--min-shots 1` aparecen todos; con `--min-shots 100` ninguno pero exit 0 y aviso), `test_load_players_falls_back_to_artifacts`.
- [ ] **Step 2 → 4:** FAIL, implementar, PASS.
- [ ] **Step 5: Artefactos reales**: `<env> uv run ventaja player build --out artifacts` (los parquet van a `artifacts/players.parquet` y `artifacts/teams.parquet`; también sin `--out`). Reportar: jugadores, distribución de `n_shots`, fila LIGA, los 10 primeros por `mean_cost` con `n ≥ 8` y con `n ≥ 1`, los equipos ordenados por coste medio, 10 frases de ejemplo (incluida una de 1 tiro y la del jugador con más tiros) y cuántas frases disparan cada regla.
- [ ] **Step 6: `tests/test_realdata.py`**: 190 filas de jugador (+ LIGA), `n_shots` suma 1 351, ninguna media no nula fuera de rango, y `mean_cost` de LIGA igual a la media de `cost` sobre decisiones legibles (1e-6).
- [ ] **Step 7: ADR-0008** (contexto: spec §2/§5.4/§9 y la decisión de Óscar del mínimo de 1 tiro; decisión: métricas, tramos, qué se excluye (nulos), temporada con tasas crudas y no encogidas, reglas de la frase con sus umbrales y el vocabulario, fila LIGA; consecuencias: cifras reales del paso 5, honestidad sobre `n`, lo que NO afirma la ficha).
- [ ] **Step 8: Commits** `feat: player and team cards with season cross and CLI (ADR-0008)` y `chore: build player and team cards`.

---

### Task 6: Deudas de la capa 2 en el reel

**Files:**
- Modify: `src/ventaja/reel.py`, `src/ventaja/viz/reel_index.py`, `src/ventaja/value/params.py`, `tests/test_reel.py`, `docs/decisions/0006-curva-de-ventaja-y-reel.md` (enmienda), `docs/reel/2026-11/index.md` (regenerado)

**Interfaces:**
- `params.py`: `LATE_MIN_CLOCK = 2.5` (s de posesión en el frame de decisión por debajo de los cuales un "momento perdido" no entra en el ranking, porque la ventana se cierra por el reloj y no por el tirador).
- `rank_tables`: la tabla `late` añade `lost_value = window_peak_value − shot_value` y se ordena por `lost_value` desc, `release_lag_seconds` desc; filtra `shot_clock >= LATE_MIN_CLOCK` (nulos incluidos: un reloj desconocido no excluye). La tabla del índice muestra "Valor perdido" antes del retraso. Enmienda en ADR-0006 con las cifras (cuántos candidatos quedan, cuántos salen por reloj).
- [ ] **Step 1: Tests**: `test_late_ranking_orders_by_lost_value`, `test_late_ranking_filters_low_clock_but_keeps_null`.
- [ ] **Step 2 → 4:** FAIL, implementar, PASS; regenerar el reel (`<env> uv run ventaja reel build --all --n 10 --out docs/reel/2026-11`; commit solo `index.md`) y reportar el nuevo top-5 de momentos perdidos.
- [ ] **Step 5: Commit** `feat: lost moments ranked by lost value with a shot-clock floor`

---

### Task 7: Cierre de la capa

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `.github/workflows/ci.yml`

- [ ] **Step 1: README** (≤ 900 palabras contando bloques de código): sección "Player cards" con `ventaja player show "Spissu"` (salida abreviada de 8-10 líneas como ejemplo), `ventaja player rank --min-shots 8`, la nota de que las fichas existen desde 1 tiro y muestran `n`, y el párrafo de honestidad (10 partidos, mediana de 6 tiros por jugador; la frase solo afirma tendencias con ≥ 8 tiros). Enlace a ADR-0008.
- [ ] **Step 2: CLAUDE.md**: comandos nuevos, `artifacts/players.parquet` y `teams.parquet` en la regla de artefactos, el paquete `cli/`.
- [ ] **Step 3: CI**: `pipeline` añade `uv run ventaja player build --game 114243` NO (las fichas son de los 10 partidos): en su lugar `uv run ventaja player show 35028` y `uv run ventaja player rank --n 5` (leen los artefactos versionados); `pipeline-all` añade `uv run ventaja player build --out /tmp/players`.
- [ ] **Step 4: Calidad completa + realdata** → verde.
- [ ] **Step 5: Commit** `docs: close layer 3`; el controlador etiqueta `capa-3-cerrada` tras el merge.

---

## Self-review

- **Cobertura del spec**: §2 ficha (valor tiros vs mejor opción → T2 `mean_shot_value/mean_best_alt_value`; coste por reloj → T2; alternativa que más ignora → T2 `ignored_alt`; frase → T4; cruce con temporada → T3); §5.4 agregación por jugador, equipo, reloj y alternativa → T2; §9 desglose por reloj siempre visible y lenguaje descriptivo → T5 (`player show`) y T4 (lista prohibida); §4 artefactos versionados → T5; deudas de la capa 2 → T1 (cli) y T6 (reel).
- **Nombres consistentes**: `player_table`, `team_table`, `league_row`, `season_profile`, `tracked_zone_mix`, `zone_shift`, `profile_phrase`, `PlayerCard`, `TeamCard`, `build_players`, `card_of`, `find_player`, `load_players_cards`, `load_teams_cards`, `fixture_players_built`.
- **Review Focus**: 1 → T2 y T4; 2 → T3; 3 → T3; 4 → T5; 5 → T2.
- **Decisiones propias que un revisor debe ver**: la fila LIGA dentro de `players.parquet` con `player_id = 0`; tasas de temporada crudas (no encogidas) en la ficha; `PROFILE_MIN_SHOTS = 8` como mínimo de apoyo de las afirmaciones (la ficha existe desde 1 tiro por decisión de Óscar); `LATE_MIN_CLOCK = 2.5`; el orden por valor perdido en los momentos perdidos.
