# Capa 0: esqueleto y datos — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un paquete `ventaja` instalable que descarga los datos de SkillCorner, los convierte a parquet, los expone en Polars y DuckDB, alinea cualquier evento con su frame de tracking orientado al ataque, y demuestra que el modelo de datos es correcto reconstruyendo el marcador de los 10 partidos.

**Architecture:** Tres capas de datos: *raw* (ficheros de SkillCorner tal cual, en un directorio con el mismo layout que su repo), *build* (parquet tidy por tabla y partido, generado por `ventaja data build`) y *acceso* (Polars para código, DuckDB para SQL, ambos sobre el parquet). Encima, un único punto de alineación evento-frame (`Snapshot`) que ya devuelve las coordenadas orientadas al ataque, de modo que ninguna capa posterior tiene que saber de `leftHoop`.

**Tech Stack:** Python 3.12, uv, Polars, DuckDB, pydantic v2, httpx, typer, pytest, ruff, mypy, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-01-ventaja-design.md` (secciones 3, 4, 6 y 8).

## Global Constraints

- Python `>=3.12`; gestor `uv`; layout `src/ventaja/`; licencia MIT en `LICENSE.md`.
- Solo dependencias open source. Nada de datos externos a SkillCorner.
- Los datos brutos **no** se commitean; los fixtures de test sí (recorte de un partido, < 2 MB comprimido).
- Todo comando de CLI debe funcionar en un entorno limpio tras `uv sync`.
- Unidades: pies; 25 fps; origen en el centro de la pista; **en coordenadas orientadas al ataque el aro ofensivo está en `(-40.7, 0.0)`** (ajustado sobre 1 433 tiros con error medio 0,03 ft).
- Ids de jugador siempre canónicos tras cargar (`player_id_aliases.csv`).
- Idioma del código, docstrings y README: inglés. Idioma de ADRs y planes: castellano.
- Commits frecuentes, mensajes convencionales (`feat:`, `test:`, `docs:`, `chore:`), con las líneas de atribución de la sesión.

## Review Focus

1. **Frame sin tracking** (48 % de los frames están vacíos: `homePlayers == []`, `ball == {}`): pedir un `Snapshot` ahí debe lanzar `NoTrackingError` con el frame y el partido en el mensaje, nunca un `KeyError` o un snapshot con listas vacías. Test en Tarea 9.
2. **Tiro con `location` nulo** (3 de 159 en el partido 114243): la validación de orientación lo salta y el `Snapshot` del tiro sigue funcionando (la posición viene del tracking). Test en Tarea 8.
3. **Descarga incompleta o corrupta**: si el fichero local existe pero su tamaño no coincide con `Content-Length`, se vuelve a descargar; un `.jsonl.gz` truncado da un error claro en `build`, no un traceback de `gzip`. Tests en Tareas 3 y 6.
4. **Ids duplicados de jugador**: una consulta por `canonical_player_id` tiene que devolver los eventos de los dos ids originales. Test en Tarea 5.
5. **`VENTAJA_DATA_DIR` apuntando al clon de SkillCorner** (`~/Repos/opendata-basketball/data`): debe funcionar sin descargar nada, y `build` no debe escribir dentro de ese directorio (va a `VENTAJA_BUILD_DIR`). Test en Tarea 2.

---

## Estructura de ficheros

```
ventaja/
  pyproject.toml            # metadatos, deps, scripts, ruff, mypy, pytest
  uv.lock
  LICENSE.md  README.md  CLAUDE.md  .gitignore
  .github/workflows/ci.yml  # lint+types+tests en cada push; job pipeline con 1 partido; cron semanal con 10
  docs/decisions/0001-orientacion-del-tracking.md
  docs/decisions/0002-raw-build-y-artefactos.md
  scripts/make_fixture.py   # genera tests/fixtures/114243 desde los datos brutos
  src/ventaja/
    __init__.py             # __version__
    config.py               # Settings: data_dir, build_dir, FPS, GAME_IDS, URLs
    errors.py               # VentajaError, NoTrackingError, DataNotFoundError, CorruptFileError
    cli.py                  # typer: data pull|build|status, sql, snapshot, validate score
    data/
      __init__.py
      catalog.py            # lista de ficheros por partido y URL de cada uno
      pull.py               # descarga con httpx, verificación de tamaño
      build.py              # raw -> parquet (eventos, game_data, tracking largo)
      load.py               # parquet -> Polars / modelos pydantic; alias de jugadores
      duck.py               # conexión DuckDB con vistas sobre el parquet
    model/
      __init__.py
      core.py               # Game, Team, Player, Shot, Possession, Score
      snapshot.py           # PlayerPos, BallPos, Snapshot
    geometry/
      __init__.py
      court.py              # constantes de pista, orient_to_offense, distance_to_hoop
    decision/
      __init__.py
      align.py              # snapshot(), snapshot_for_shot(), window()
    validate/
      __init__.py
      score.py              # reconstruct_score(), check_scores()
  tests/
    conftest.py             # fixtures: settings apuntando a tests/fixtures, build en tmp_path
    fixtures/114243/        # game_data.json, dynamic_events.json, tracking excerpt .jsonl.gz, matches.json, aliases.csv
    test_config.py  test_pull.py  test_build_events.py  test_build_tracking.py
    test_load.py  test_duck.py  test_court.py  test_align.py  test_score.py  test_cli.py
```

Layout del directorio *raw* (`data_dir`), idéntico al repo de SkillCorner para que el clon sirva tal cual:

```
{data_dir}/matches.json
{data_dir}/player_id_aliases.csv
{data_dir}/aggregates/acb_{shots,drives,picks}aggregates_20252026.csv
{data_dir}/matches/{game_id}/{game_id}_game_data.json
{data_dir}/matches/{game_id}/{game_id}_dynamic_events.json
{data_dir}/matches/{game_id}/{game_id}_tracking_data.jsonl.gz
```

Layout del directorio *build* (`build_dir`):

```
{build_dir}/events/{game_id}/{table}.parquet      # 20 tablas de dynamic_events
{build_dir}/tracking/{game_id}.parquet            # formato largo, una fila por jugador o balón y frame
```

---

### Task 1: Esqueleto del repo, calidad y CI

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `LICENSE.md`, `README.md`, `CLAUDE.md`, `src/ventaja/__init__.py`, `src/ventaja/cli.py`, `tests/test_cli.py`, `.github/workflows/ci.yml`, `docs/decisions/0000-plantilla.md`

**Interfaces:**
- Produces: comando `ventaja` (typer app `app` en `cli.py`), `ventaja.__version__ == "0.1.0"`.

- [ ] **Step 1: Inicializar el proyecto con uv**

```bash
cd ~/Repos/ventaja
uv init --package --name ventaja --python 3.12 --no-readme
uv add polars duckdb "pydantic>=2" httpx typer
uv add --dev pytest pytest-cov ruff mypy
```

En `pyproject.toml`: `[project.scripts] ventaja = "ventaja.cli:app"`; `requires-python = ">=3.12"`; `license = "MIT"`; `[tool.ruff] line-length = 100, select = ["E","F","I","UP","B"]`; `[tool.mypy] strict = true, packages = ["ventaja"]`; `[tool.pytest.ini_options] testpaths = ["tests"]`.

- [ ] **Step 2: Escribir el test de humo de la CLI**

```python
# tests/test_cli.py
from typer.testing import CliRunner
from ventaja import __version__
from ventaja.cli import app

def test_version_flag_prints_version():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
```

- [ ] **Step 3: Ejecutar el test y verificar que falla**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL (ImportError de `ventaja.cli`).

- [ ] **Step 4: Implementar `app = typer.Typer(name="ventaja", no_args_is_help=True)` con callback `--version` en `src/ventaja/cli.py` y `__version__ = "0.1.0"` en `__init__.py`**

- [ ] **Step 5: Ejecutar test, ruff y mypy**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: todo en verde.

- [ ] **Step 6: Ficheros de proyecto**

`LICENSE.md`: texto MIT con "Copyright (c) 2026 Óscar Sánchez Rueda". `.gitignore`: `.venv/`, `__pycache__/`, `.superpowers/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `dist/`, `*.egg-info`, `.env`. `README.md`: título, una frase, sección "Development" con `uv sync` y `uv run pytest`; marcado como *working README, the submission README is written in week 7*. `CLAUDE.md`: stack, comandos (`uv run pytest`, `uv run ruff check .`, `uv run mypy`), convención de commits, regla "cada capa se cierra con tests + ADR + comando de CLI", enlace al spec y al plan. `docs/decisions/0000-plantilla.md`: cabecera `# ADR-NNNN: título`, secciones Contexto, Decisión, Consecuencias, media página máximo.

- [ ] **Step 7: Workflow de CI**

`.github/workflows/ci.yml` con un job `quality` (ubuntu-latest, `astral-sh/setup-uv@v5`, `uv sync --all-extras --dev`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`). Triggers: `push`, `pull_request`. El job `pipeline` se añade en la Tarea 11.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "chore: project skeleton with uv, typer CLI, ruff, mypy and CI"
```

---

### Task 2: Configuración y catálogo de ficheros

**Files:**
- Create: `src/ventaja/config.py`, `src/ventaja/errors.py`, `src/ventaja/data/__init__.py`, `src/ventaja/data/catalog.py`, `tests/test_config.py`, `tests/conftest.py`

**Interfaces:**
- Produces:
  - `config.Settings` (pydantic `BaseSettings` no: usar `pydantic.BaseModel` + lectura explícita de `os.environ` para no añadir `pydantic-settings`): campos `data_dir: Path`, `build_dir: Path`; classmethod `Settings.from_env() -> Settings` con defaults `~/.cache/ventaja/raw` y `~/.cache/ventaja/build`, sobrescribibles por `VENTAJA_DATA_DIR` y `VENTAJA_BUILD_DIR`.
  - `config.FPS: int = 25`, `config.GAME_IDS: tuple[int, ...]` con los 10 ids `(114086, 114099, 114169, 114234, 114243, 178442, 179612, 184439, 188630, 191313)`, `config.SEASON = "2025-2026"`.
  - `catalog.RemoteFile(relpath: str, url: str, lfs: bool)` (dataclass frozen) y `catalog.files_for(game_ids: Iterable[int] | None, *, tracking: bool = True) -> list[RemoteFile]`: incluye siempre `matches.json`, `player_id_aliases.csv` y los 3 CSV de agregados; por partido, `game_data`, `dynamic_events` y, si `tracking`, el `.jsonl.gz`.
  - URLs: base raw `https://raw.githubusercontent.com/SkillCorner/opendata-basketball/main/data/` para todo salvo tracking; tracking por `https://media.githubusercontent.com/media/SkillCorner/opendata-basketball/main/data/` (`lfs=True`). Ambas verificadas con HTTP 200 el 2026-11-01.
  - `errors.VentajaError(Exception)`, `DataNotFoundError`, `CorruptFileError`, `NoTrackingError`, todas subclases de `VentajaError`.
  - `Settings.raw_path(relpath: str) -> Path` y `Settings.events_parquet(game_id: int, table: str) -> Path`, `Settings.tracking_parquet(game_id: int) -> Path` según el layout de la sección de estructura.

- [ ] **Step 1: Escribir los tests**

```python
# tests/test_config.py
def test_defaults_point_to_user_cache(monkeypatch):
    monkeypatch.delenv("VENTAJA_DATA_DIR", raising=False)
    monkeypatch.delenv("VENTAJA_BUILD_DIR", raising=False)
    s = Settings.from_env()
    assert s.data_dir == Path.home() / ".cache" / "ventaja" / "raw"
    assert s.build_dir == Path.home() / ".cache" / "ventaja" / "build"

def test_env_overrides_and_build_dir_is_outside_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(tmp_path / "clone" / "data"))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(tmp_path / "build"))
    s = Settings.from_env()
    assert s.data_dir == tmp_path / "clone" / "data"
    assert not s.build_dir.is_relative_to(s.data_dir)

def test_catalog_for_one_game_has_eight_files_and_lfs_only_for_tracking():
    files = files_for([114243])
    assert len(files) == 5 + 3
    lfs = [f for f in files if f.lfs]
    assert [f.relpath for f in lfs] == ["matches/114243/114243_tracking_data.jsonl.gz"]
    assert lfs[0].url.startswith("https://media.githubusercontent.com/media/SkillCorner/opendata-basketball/main/data/")

def test_catalog_without_tracking_skips_lfs():
    assert not any(f.lfs for f in files_for([114243], tracking=False))

def test_catalog_all_games_defaults_to_ten():
    assert sum(f.lfs for f in files_for(None)) == 10
```

`tests/conftest.py`: fixture `fixture_settings(tmp_path) -> Settings` con `data_dir = Path(__file__).parent / "fixtures" / "114243"` y `build_dir = tmp_path / "build"` (los fixtures se crean en la Tarea 4; el conftest ya puede existir).

- [ ] **Step 2: Ejecutar y verificar que fallan**

Run: `uv run pytest tests/test_config.py -v` → FAIL (ImportError).

- [ ] **Step 3: Implementar `config.py`, `errors.py`, `data/catalog.py` según Interfaces**

- [ ] **Step 4: Ejecutar tests, ruff, mypy** → PASS.

- [ ] **Step 5: Commit** `feat: settings, error types and remote file catalog`

---

### Task 3: Descarga de datos (`ventaja data pull` / `status`)

**Files:**
- Create: `src/ventaja/data/pull.py`, `tests/test_pull.py`
- Modify: `src/ventaja/cli.py`

**Interfaces:**
- Consumes: `catalog.files_for`, `Settings`.
- Produces:
  - `pull.pull(files: Iterable[RemoteFile], settings: Settings, *, client: httpx.Client | None = None, progress: Callable[[str, int, int], None] | None = None) -> list[Path]`. Para cada fichero: destino `settings.raw_path(f.relpath)`; si existe y su tamaño coincide con `Content-Length` de un `HEAD`, se salta; si no, descarga en streaming a `destino.tmp` y renombra al final (atómico). Devuelve rutas.
  - `pull.status(settings: Settings, game_ids: Iterable[int] | None = None) -> list[tuple[RemoteFile, bool]]` (presente o no, sin red).
  - CLI: `ventaja data pull [--game ID ...] [--all] [--no-tracking]` (sin `--game` ni `--all` descarga solo los ficheros comunes); `ventaja data status`.

- [ ] **Step 1: Tests con `httpx.MockTransport`, sin red**

```python
# tests/test_pull.py
def _transport(payload: bytes):
    def handler(request):
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(payload))})
        return httpx.Response(200, content=payload)
    return httpx.MockTransport(handler)

def test_pull_writes_file_atomically(tmp_path):
    settings = Settings(data_dir=tmp_path / "raw", build_dir=tmp_path / "build")
    f = RemoteFile("matches.json", "https://x/matches.json", lfs=False)
    with httpx.Client(transport=_transport(b"[]")) as c:
        [path] = pull([f], settings, client=c)
    assert path.read_bytes() == b"[]"
    assert not path.with_suffix(".json.tmp").exists()

def test_pull_skips_when_size_matches(tmp_path):
    ...  # escribe el fichero con el tamaño correcto; el handler cuenta GETs; assert GETs == 0

def test_pull_redownloads_when_size_differs(tmp_path):
    ...  # fichero local de 1 byte, payload de 2 → GETs == 1 y contenido nuevo

def test_status_reports_missing_without_network(tmp_path):
    settings = Settings(data_dir=tmp_path, build_dir=tmp_path / "b")
    rows = status(settings, [114243])
    assert all(present is False for _, present in rows)
```

- [ ] **Step 2: Ejecutar → FAIL**

- [ ] **Step 3: Implementar `pull.py` y los subcomandos `data pull` / `data status` en `cli.py`** (grupo `data = typer.Typer()`, `app.add_typer(data, name="data")`). Progreso por `typer.echo` de una línea por fichero.

- [ ] **Step 4: Ejecutar tests, ruff, mypy** → PASS.

- [ ] **Step 5: Prueba manual contra la red, un solo fichero pequeño**

Run: `VENTAJA_DATA_DIR=/tmp/ventaja-raw uv run ventaja data pull` (solo comunes) → imprime 5 ficheros, `ls /tmp/ventaja-raw/matches.json` existe.

- [ ] **Step 6: Commit** `feat: data pull and status commands`

---

### Task 4: Fixture de test recortado del partido 114243

**Files:**
- Create: `scripts/make_fixture.py`, `tests/fixtures/114243/{matches.json, player_id_aliases.csv, matches/114243/114243_game_data.json, matches/114243/114243_dynamic_events.json, matches/114243/114243_tracking_data.jsonl.gz}`, `tests/test_fixture.py`

**Interfaces:**
- Produces: un `data_dir` válido con el layout de SkillCorner, pero cuyo tracking contiene **solo los frames en `[startFrame - 75, startFrame + 25]` de los 20 primeros tiros** del partido (3 s antes, 1 s después), más los frames vacíos que caigan en esas ventanas. Los eventos van completos (3,4 MB sin comprimir es aceptable). `matches.json` reducido al partido 114243. Agregados: **no** se incluyen (no los usa la capa 0).
- Constante `FIXTURE_SHOT_COUNT = 20` en `tests/conftest.py`.

- [ ] **Step 1: Test que describe el fixture**

```python
# tests/test_fixture.py
def test_fixture_tracking_is_a_small_excerpt(fixture_settings):
    path = fixture_settings.raw_path("matches/114243/114243_tracking_data.jsonl.gz")
    assert path.stat().st_size < 2_000_000
    with gzip.open(path, "rt") as fh:
        n = sum(1 for _ in fh)
    assert 1_500 < n < 3_000

def test_fixture_events_are_complete(fixture_settings):
    events = json.loads(fixture_settings.raw_path("matches/114243/114243_dynamic_events.json").read_text())
    assert len(events["shots"]) == 159
    assert len(events) == 20
```

- [ ] **Step 2: Escribir `scripts/make_fixture.py`** con firma `main(source_data_dir: Path, out_dir: Path, game_id: int = 114243, n_shots: int = 20, before: int = 75, after: int = 25) -> None`, ejecutable con `uv run python scripts/make_fixture.py ~/Repos/opendata-basketball/data tests/fixtures/114243`. Lee los tiros ordenados por `startFrame`, calcula las ventanas, hace streaming del gz y escribe solo las líneas cuyo `frameIdx` cae en alguna ventana. Copia `game_data`, `dynamic_events`, `player_id_aliases.csv`; filtra `matches.json`.

- [ ] **Step 3: Generar el fixture y ejecutar el test** → PASS. Comprobar `du -sh tests/fixtures` < 5 MB.

- [ ] **Step 4: Commit** `test: trimmed fixture of game 114243 and generator script`

---

### Task 5: Modelos de dominio y carga de eventos a parquet

**Files:**
- Create: `src/ventaja/model/__init__.py`, `src/ventaja/model/core.py`, `src/ventaja/data/build.py`, `src/ventaja/data/load.py`, `tests/test_build_events.py`, `tests/test_load.py`
- Modify: `src/ventaja/cli.py` (subcomando `data build`)

**Interfaces:**
- Consumes: `Settings`, fixture.
- Produces:
  - `model/core.py` (pydantic v2, `frozen=True`): `Player(player_id: int, first_name: str, last_name: str, jersey: str)`, `Team(team_id: int, name: str, players: list[Player])`, `Game(game_id: int, date: datetime, season: str, home: Team, away: Team)`, `Score(home: int, away: int)`, `Match(game_id: int, date_time: datetime, home_team_id: int, away_team_id: int, home_score: int, away_score: int)`.
  - `build.EVENT_TABLES: tuple[str, ...]` con las 20 claves de `dynamic_events.json` (`chance_players, chances, closeouts, dribbles, drives, fouls, free_throws, handoffs, isolations, matchups, off_ball_screens, passes, picks, possessions, posts, rebounds, shots, timeouts, touches, turnovers`).
  - `build.build_events(game_id: int, settings: Settings) -> dict[str, Path]`: lee el JSON y escribe un parquet por tabla con **nombres de columna en snake_case** (`startFrame → start_frame`, `shooterId → shooter_id`, `offTeamId → off_team_id`, `leftHoop → left_hoop`, …), `location` como dos columnas `loc_x`, `loc_y` (nulas si `location` es nulo) y `end_loc` igual (`end_loc_x`, `end_loc_y`); listas de ids (`off_player_ids`) como `list[int64]`; `game_id` siempre presente. Ids de jugador **ya canónicos** (ver `load_aliases`). Idempotente: sobreescribe.
  - `load.load_aliases(settings) -> dict[int, int]` (player_id → canonical_player_id, solo las filas donde difieren).
  - `load.canonical(player_id: int, aliases: dict[int, int]) -> int`.
  - `load.load_matches(settings) -> list[Match]`; `load.load_game(game_id, settings) -> Game`.
  - `load.load_events(game_id: int, table: str, settings: Settings) -> pl.DataFrame` (lanza `DataNotFoundError` con el consejo "run `ventaja data build --game N`" si falta el parquet).
  - CLI: `ventaja data build [--game ID ...] [--all]` llama a `build_events` y, tras la Tarea 6, a `build_tracking`.

- [ ] **Step 1: Tests**

```python
# tests/test_build_events.py
def test_build_events_writes_twenty_parquets_in_snake_case(fixture_settings):
    out = build_events(114243, fixture_settings)
    assert set(out) == set(EVENT_TABLES)
    shots = pl.read_parquet(out["shots"])
    assert {"start_frame", "shooter_id", "off_team_id", "loc_x", "loc_y", "shot_clock"} <= set(shots.columns)
    assert shots.height == 159
    assert shots.filter(pl.col("loc_x").is_null()).height == 3

def test_build_events_applies_player_aliases(fixture_settings, tmp_path):
    # añadir al CSV de alias del fixture una fila que mapee el shooter del primer tiro (35028) a 999999
    # en una copia del data_dir en tmp_path; construir; comprobar que shots.shooter_id no contiene 35028 y sí 999999
    ...

# tests/test_load.py
def test_load_game_reads_rosters(fixture_settings):
    g = load_game(114243, fixture_settings)
    assert g.home.name == "BAXI Manresa" and g.away.name == "Coviran Granada"
    assert len(g.home.players) == 12 and len(g.away.players) == 12

def test_load_matches_reads_scores(fixture_settings):
    [m] = load_matches(fixture_settings)
    assert (m.home_score, m.away_score) == (83, 68)

def test_load_events_before_build_raises_with_hint(fixture_settings):
    with pytest.raises(DataNotFoundError, match="ventaja data build"):
        load_events(114243, "shots", fixture_settings)
```

- [ ] **Step 2: Ejecutar → FAIL**

- [ ] **Step 3: Implementar `model/core.py`, `build.build_events`, `load.py` y `data build` en la CLI.** Conversión a snake_case con una función `to_snake(name: str) -> str` (regex `(?<!^)(?=[A-Z])` → `_` y lower). Construcción de DataFrames con `pl.from_dicts(rows, infer_schema_length=None)` tras aplanar `location`/`endLoc`. Aplicar alias a toda columna cuyo nombre termine en `_id` y a las listas `off_player_ids`/`def_player_ids`, salvo `game_id`, `team_id`, `off_team_id`, `def_team_id` y los ids de evento (`id`, `chance_id`, `possession_id`, `touch_id`, `foul_id`, `shot_id`, `last_chance_id`).

- [ ] **Step 4: Ejecutar tests, ruff, mypy** → PASS.

- [ ] **Step 5: Commit** `feat: domain models, event parquet build and loaders`

---

### Task 6: Tracking a formato largo en parquet

**Files:**
- Create: `tests/test_build_tracking.py`
- Modify: `src/ventaja/data/build.py`, `src/ventaja/data/load.py`, `src/ventaja/cli.py`

**Interfaces:**
- Produces:
  - `build.build_tracking(game_id: int, settings: Settings) -> Path`: lee el `.jsonl.gz` en streaming (módulo `gzip` + `json`, o `orjson` si se añade como dependencia; decisión del constructor) y escribe `settings.tracking_parquet(game_id)` con esquema:
    `game_id: i64, frame_idx: i64, wall_clock: i64, game_clock: f64, game_clock_stopped: bool, period: i64, shot_clock: f64 (nullable), side: enum{"home","away","ball"}, player_id: i64 (nullable; nulo para el balón), jersey: str (nullable), x: f64, y: f64, z: f64, speed: f64, is_detected: bool, pred_error: f64`.
    **Los frames vacíos no producen filas.** Ids canónicos. Escritura por lotes de 50 000 frames para no cargar 1,6 M de filas de golpe (decisión del constructor si usa `pl.DataFrame` por lote + `pq.ParquetWriter`, o un `LazyFrame` con `sink_parquet`).
  - Un gz truncado (fin de fichero prematuro) lanza `CorruptFileError` con la ruta y el consejo de volver a ejecutar `ventaja data pull`.
  - `load.load_tracking(game_id: int, settings: Settings) -> pl.LazyFrame` (`scan_parquet`), `DataNotFoundError` con consejo si falta.
  - `load.frame_range(game_id, settings) -> tuple[int, int]` (min y max `frame_idx` con datos).

- [ ] **Step 1: Tests**

```python
def test_build_tracking_long_format_skips_empty_frames(fixture_settings):
    path = build_tracking(114243, fixture_settings)
    df = pl.read_parquet(path)
    assert set(df.columns) == {"game_id","frame_idx","wall_clock","game_clock","game_clock_stopped","period","shot_clock","side","player_id","jersey","x","y","z","speed","is_detected","pred_error"}
    per_frame = df.group_by("frame_idx").len()
    assert per_frame["len"].unique().to_list() == [11]           # 5 + 5 + balón, nunca 0
    assert df.filter(pl.col("side") == "ball")["player_id"].is_null().all()

def test_build_tracking_truncated_gzip_raises_corrupt(fixture_settings, tmp_path):
    # copiar el data_dir del fixture a tmp_path y truncar el gz a la mitad de bytes
    with pytest.raises(CorruptFileError, match="ventaja data pull"):
        build_tracking(114243, settings_en_tmp)

def test_load_tracking_is_lazy_and_frame_range_matches_excerpt(fixture_settings):
    build_tracking(114243, fixture_settings)
    lf = load_tracking(114243, fixture_settings)
    assert isinstance(lf, pl.LazyFrame)
    lo, hi = frame_range(114243, fixture_settings)
    assert lo >= 3895 - 75  # primer tiro del fixture
```

- [ ] **Step 2: Ejecutar → FAIL**

- [ ] **Step 3: Implementar; conectar a `ventaja data build`** (eventos y tracking; `--events-only` para saltar tracking).

- [ ] **Step 4: Ejecutar tests, ruff, mypy** → PASS.

- [ ] **Step 5: Prueba de rendimiento manual con el partido completo**

Run: `VENTAJA_DATA_DIR=~/Repos/opendata-basketball/data VENTAJA_BUILD_DIR=/tmp/ventaja-build time uv run ventaja data build --game 114243`
Expected: termina en menos de 60 s y el parquet pesa menos de 60 MB. Anotar los números en el ADR-0002.

- [ ] **Step 6: Commit** `feat: tracking build to long-format parquet`

---

### Task 7: DuckDB con vistas sobre el build (`ventaja sql`)

**Files:**
- Create: `src/ventaja/data/duck.py`, `tests/test_duck.py`
- Modify: `src/ventaja/cli.py`

**Interfaces:**
- Produces:
  - `duck.connect(settings: Settings, *, read_only: bool = True) -> duckdb.DuckDBPyConnection` en memoria, con una vista por tabla de eventos (`shots`, `possessions`, …) sobre `read_parquet('{build_dir}/events/*/{table}.parquet', union_by_name=true)` y una vista `tracking` sobre `read_parquet('{build_dir}/tracking/*.parquet')`. Si no hay ningún parquet de una tabla, la vista no se crea (no falla).
  - CLI: `ventaja sql "SELECT ..."` imprime el resultado como tabla (`duckdb` `.show()` o Polars `__repr__`); `--csv` para salida CSV.

- [ ] **Step 1: Tests**

```python
def test_duck_views_over_built_parquet(fixture_settings):
    build_events(114243, fixture_settings); build_tracking(114243, fixture_settings)
    con = connect(fixture_settings)
    assert con.sql("select count(*) from shots").fetchone()[0] == 159
    assert con.sql("select count(distinct frame_idx) from tracking").fetchone()[0] > 1000

def test_duck_join_shot_to_tracking_frame(fixture_settings):
    con = connect(fixture_settings)
    n = con.sql("""
        select count(*) from shots s
        join tracking t on t.frame_idx = s.start_frame and t.player_id = s.shooter_id
    """).fetchone()[0]
    assert n == 20   # los 20 tiros del fixture tienen a su tirador en el frame

def test_cli_sql_prints_rows(fixture_settings, monkeypatch):
    ...  # monkeypatch VENTAJA_* y CliRunner().invoke(app, ["sql", "select 1 as one"]) → "one" en output
```

- [ ] **Step 2: Ejecutar → FAIL**  
- [ ] **Step 3: Implementar**  
- [ ] **Step 4: Tests, ruff, mypy → PASS**  
- [ ] **Step 5: Commit** `feat: duckdb views and sql command`

---

### Task 8: Geometría de pista y orientación al ataque

**Files:**
- Create: `src/ventaja/geometry/__init__.py`, `src/ventaja/geometry/court.py`, `tests/test_court.py`, `docs/decisions/0001-orientacion-del-tracking.md`

**Interfaces:**
- Produces (todo en pies):
  - `court.HOOP: tuple[float, float] = (-40.7, 0.0)`; `court.COURT_LENGTH = 91.86`; `court.COURT_WIDTH = 49.21`; `court.HALF_LENGTH = 45.93`; `court.THREE_POINT_RADIUS = 22.15` (6,75 m); `court.FPS = 25` reexportado de config.
  - `court.orient_to_offense(x: float, y: float, left_hoop: bool) -> tuple[float, float]`: identidad si `left_hoop`, `(-x, -y)` si no. Fundamento: verificado sobre 156 tiros con `location` del partido 114243, los 156 cuadran a < 4 ft (0 fallos) con esta regla.
  - `court.orient_frame(df: pl.DataFrame, left_hoop: bool) -> pl.DataFrame` (vectorizado sobre columnas `x`, `y`).
  - `court.distance_to_hoop(x: float, y: float) -> float`.

- [ ] **Step 1: Tests**

```python
def test_orient_identity_when_left_hoop():
    assert orient_to_offense(10.0, -3.0, True) == (10.0, -3.0)

def test_orient_rotates_180_when_right_hoop():
    assert orient_to_offense(10.0, -3.0, False) == (-10.0, 3.0)

def test_distance_to_hoop_at_rim_is_zero():
    assert distance_to_hoop(*HOOP) == 0.0

def test_shot_distance_field_matches_hoop_constant(fixture_settings):
    shots = load_events(114243, "shots", fixture_settings).drop_nulls("loc_x")
    computed = shots.select(((pl.col("loc_x") - HOOP[0])**2 + (pl.col("loc_y") - HOOP[1])**2).sqrt().alias("d"))
    assert (computed["d"] - shots["distance"]).abs().max() < 0.5

def test_oriented_shooter_position_matches_event_location(fixture_settings):
    # para los 20 tiros del fixture con loc no nula: posición del tirador en tracking en start_frame,
    # orientada con left_hoop de su posesión, dista < 4 ft de (loc_x, loc_y)
    ...
```

- [ ] **Step 2: Ejecutar → FAIL**  
- [ ] **Step 3: Implementar `court.py`**  
- [ ] **Step 4: Tests, ruff, mypy → PASS**

- [ ] **Step 5: Escribir ADR-0001** (contexto: el tracking va en orientación de cámara y los eventos en orientación de ataque; decisión: toda geometría del proyecto se hace en orientación de ataque, la rotación se aplica una sola vez en `Snapshot`; consecuencia: nada aguas arriba de `align.py` debe leer `left_hoop`).

- [ ] **Step 6: Commit** `feat: court geometry and offense orientation (ADR-0001)`

---

### Task 9: Alineación evento-frame: `Snapshot`

**Files:**
- Create: `src/ventaja/model/snapshot.py`, `src/ventaja/decision/__init__.py`, `src/ventaja/decision/align.py`, `tests/test_align.py`
- Modify: `src/ventaja/cli.py` (subcomando `snapshot`)

**Interfaces:**
- Consumes: `load_tracking`, `load_events(…, "possessions")`, `load_events(…, "shots")`, `orient_to_offense`.
- Produces:
  - `snapshot.PlayerPos(player_id: int, team_id: int, x: float, y: float, speed: float, is_detected: bool, pred_error: float)`, `snapshot.BallPos(x: float, y: float, z: float, speed: float, is_detected: bool)`, `snapshot.Snapshot(game_id: int, frame_idx: int, wall_clock: int, period: int, game_clock: float, shot_clock: float | None, possession_id: str, chance_id: str | None, off_team_id: int, def_team_id: int, offense: list[PlayerPos], defense: list[PlayerPos], ball: BallPos)`; coordenadas **ya orientadas al ataque**; método `player(player_id) -> PlayerPos` (KeyError si no está); propiedad `teammates_of(player_id) -> list[PlayerPos]`.
  - `align.Aligner(game_id: int, settings: Settings)`: carga una vez posesiones, chances y tiros del partido y mantiene el `LazyFrame` de tracking. Métodos:
    - `possession_at(frame_idx: int) -> pl.Series | None` (fila de `possessions` con `start_frame <= f <= end_frame`).
    - `snapshot(frame_idx: int) -> Snapshot`: lanza `NoTrackingError(f"game {game_id} has no tracking at frame {frame_idx}")` si no hay filas; lanza `VentajaError` si el frame no cae en ninguna posesión (no se puede orientar).
    - `snapshot_for_shot(shot_id: str) -> Snapshot` (usa `start_frame` del tiro; en la capa 1 se sustituirá por el frame de decisión).
    - `window(start: int, end: int) -> list[Snapshot]` (frames con datos dentro de `[start, end]`, en orden).
  - CLI: `ventaja snapshot SHOT_ID` imprime el snapshot como tabla (jugador, equipo, x, y, speed) con el tirador marcado.

- [ ] **Step 1: Tests**

```python
def test_snapshot_for_shot_has_five_and_five_oriented(fixture_settings, built_fixture):
    a = Aligner(114243, fixture_settings)
    s = a.snapshot_for_shot("shot-114243-1-0")
    assert len(s.offense) == 5 and len(s.defense) == 5
    assert s.off_team_id == 1319 and s.def_team_id == 1330
    shooter = s.player(35028)
    assert abs(shooter.x - (-23.53)) < 4 and abs(shooter.y - (-6.66)) < 4   # location del evento
    assert s.shot_clock == pytest.approx(13.88, abs=0.05)

def test_snapshot_on_empty_frame_raises_no_tracking(fixture_settings, built_fixture):
    a = Aligner(114243, fixture_settings)
    empty = primer frame_idx dentro del rango del fixture sin filas en tracking (buscar con Polars en el test)
    with pytest.raises(NoTrackingError, match=str(empty)):
        a.snapshot(empty)

def test_window_returns_consecutive_frames_in_order(fixture_settings, built_fixture):
    a = Aligner(114243, fixture_settings)
    w = a.window(3895 - 25, 3895)
    assert [s.frame_idx for s in w] == sorted(s.frame_idx for s in w)
    assert 1 <= len(w) <= 26

def test_teammates_of_excludes_player(fixture_settings, built_fixture):
    s = Aligner(114243, fixture_settings).snapshot_for_shot("shot-114243-1-0")
    assert len(s.teammates_of(35028)) == 4 and all(p.player_id != 35028 for p in s.teammates_of(35028))
```

`built_fixture` es una fixture de `conftest.py` (scope `session`) que ejecuta `build_events` y `build_tracking` una vez en el `build_dir` temporal.

- [ ] **Step 2: Ejecutar → FAIL**  
- [ ] **Step 3: Implementar `snapshot.py`, `align.py` y `ventaja snapshot`**  
- [ ] **Step 4: Tests, ruff, mypy → PASS**  
- [ ] **Step 5: Commit** `feat: event-to-frame alignment with offense-oriented Snapshot`

---

### Task 10: Validación del marcador (`ventaja validate score`)

**Files:**
- Create: `src/ventaja/validate/__init__.py`, `src/ventaja/validate/score.py`, `tests/test_score.py`
- Modify: `src/ventaja/cli.py`

**Interfaces:**
- Consumes: `load_events(…, "shots" | "free_throws")`, `load_game`, `load_matches`.
- Produces:
  - `score.reconstruct_score(game_id: int, settings: Settings) -> Score`: puntos = `shots` con `outcome == True` valen 3 si `three` y 2 si no; `free_throws` con `outcome == True` valen 1; se suman por `off_team_id` y se asignan a home/away según `Game`. Verificado el 2026-11-01: cuadra en los 10 partidos.
  - `score.check_scores(game_ids: Iterable[int], settings: Settings) -> list[tuple[int, Score, Score, bool]]` (reconstruido, oficial de `matches.json`, ok).
  - CLI: `ventaja validate score [--game ID ...] [--all]` imprime una fila por partido y **sale con código 1 si alguno no cuadra**.

- [ ] **Step 1: Tests**

```python
def test_reconstruct_score_matches_official(fixture_settings, built_fixture):
    assert reconstruct_score(114243, fixture_settings) == Score(home=83, away=68)

def test_check_scores_flags_mismatch(fixture_settings, built_fixture, monkeypatch):
    monkeypatch.setattr(score, "reconstruct_score", lambda g, s: Score(home=0, away=0))
    [(gid, got, official, ok)] = check_scores([114243], fixture_settings)
    assert not ok and official == Score(home=83, away=68)

def test_cli_validate_score_exit_code(fixture_settings, built_fixture, monkeypatch):
    ...  # exit_code == 0 con datos reales; == 1 con el monkeypatch anterior
```

- [ ] **Step 2: Ejecutar → FAIL**  
- [ ] **Step 3: Implementar**  
- [ ] **Step 4: Tests, ruff, mypy → PASS**

- [ ] **Step 5: Validación de los 10 partidos reales**

Run: `VENTAJA_DATA_DIR=~/Repos/opendata-basketball/data VENTAJA_BUILD_DIR=/tmp/ventaja-build uv run ventaja data build --all --events-only && uv run ventaja validate score --all`
Expected: 10 filas `ok`, exit 0.

- [ ] **Step 6: Commit** `feat: score reconstruction validation command`

---

### Task 11: Pipeline en CI, ADR-0002 y cierre de la capa

**Files:**
- Modify: `.github/workflows/ci.yml`, `README.md`, `CLAUDE.md`
- Create: `docs/decisions/0002-raw-build-y-artefactos.md`

- [ ] **Step 1: Job `pipeline` en CI**

Job `pipeline` (needs `quality`): `uv sync`, `uv run ventaja data pull --game 114243`, `uv run ventaja data build --game 114243`, `uv run ventaja validate score --game 114243`, `uv run ventaja snapshot shot-114243-1-0`. Cache de `~/.cache/ventaja/raw` con `actions/cache@v4` clave `skillcorner-raw-114243-v1`. Job `pipeline-all` solo en `schedule: cron "0 6 * * 1"` (lunes 06:00 UTC) y `workflow_dispatch`, con `--all`.

- [ ] **Step 2: ADR-0002** (contexto: datos brutos de 350 MB en LFS de terceros, cuota no controlada; decisión: separar raw de build, parquet tidy como formato interno, y versionar en el repo los artefactos derivados que se generen en capas posteriores; consecuencia: `ventaja data build` es idempotente y rápido, y cualquier capa lee parquet, nunca JSON). Incluir los tiempos medidos en la Tarea 6.

- [ ] **Step 3: Actualizar `README.md`** (sección "Data": los tres comandos `pull`, `build`, `validate score`; variables de entorno; cómo apuntar al clon local) y `CLAUDE.md` (comandos de la capa 0 y regla de orientación del ADR-0001).

- [ ] **Step 4: Push y comprobar CI en verde**

Run: `gh repo create oscarsanchezrueda/ventaja --public --source . --push` (si aún no existe el remoto), luego `gh run watch`.
Expected: jobs `quality` y `pipeline` en verde.

- [ ] **Step 5: Etiqueta de cierre de capa**

```bash
git tag -a capa-0 -m "Capa 0 cerrada: esqueleto y datos" && git push --tags
```

---

## Self-review

- **Cobertura del spec (sección 6, fila "0. Esqueleto + datos")**: repo y CI (T1, T11), `ventaja data pull` (T3), carga con DuckDB/Polars (T5-T7), modelos pydantic (T5, T9), alineación evento-frame (T9), marcador reconstruido en los 10 partidos (T10). Rotación por `leftHoop` (T8-T9), ids canónicos (T5-T6), flujo de IA visible: `CLAUDE.md` y ADRs (T1, T8, T11). Fuera de alcance deliberado: agregados de temporada (no los usa la capa 0; se cargan en la capa 3), velocidad vectorial (capa 1).
- **Consistencia de nombres**: `Settings.from_env`, `files_for`, `pull`, `status`, `build_events`, `build_tracking`, `load_events`, `load_tracking`, `load_game`, `load_matches`, `load_aliases`, `connect`, `orient_to_offense`, `HOOP`, `Aligner.snapshot/snapshot_for_shot/window`, `reconstruct_score`, `check_scores`, `Score` se usan con la misma firma en todas las tareas.
- **Review Focus**: 1 → T9; 2 → T8 y T5 (3 nulos); 3 → T3 y T6; 4 → T5; 5 → T2 y la prueba manual de T10.
