# App unificada ("ventaja app") — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One local page (`uv run ventaja app`) that opens on a shot with its whiteboard and advantage curve, and also offers players, games, the six MCP tools as forms, and an about page — all from the packaged artifacts, with no build step.

**Architecture:** A new `ventaja/web/` package: `web/app.py` (FastAPI) keeps the whiteboard routes verbatim and adds `/api/ask/*`, `/api/curve`, `/api/reel`, `/api/featured`, `/api/about` and `/docs/decisions/*`, all answered by one shared `AskService` (and its `Board`). `web/static/` holds the shell (`index.html`, `app.css`), a hash router (`app.js`) and one ES module per view (`board.js` extracted from today's page without behaviour changes, `shot.js`, `curve.js`, `players.js`, `games.js`, `ask.js`, `about.js`). `ventaja/board/app.py` is removed; `ventaja/board/engine.py` is untouched.

**Tech Stack:** Python ≥ 3.12, FastAPI + uvicorn (existing), pydantic v2, polars, the `mcp` SDK for the tool schemas; HTML/CSS/vanilla ES modules (no bundler, no npm, no CDN); pytest with `TestClient`.

**Spec:** `docs/superpowers/specs/2026-11-06-app-unificada-design.md` (binding; parent `docs/superpowers/specs/2026-11-01-ventaja-design.md`; ADR-0009, ADR-0010).

## Global Constraints

- Code, docstrings, UI strings in English; ADR in Spanish.
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` (strict) and `uv run pytest` (warnings are errors) pass after every task.
- Conventional commits ending with the two attribution lines the session provides.
- No new runtime dependency. No JavaScript build, framework, npm package or CDN script. `<script type="module">` only; every file under `web/static/` ≤ 600 lines.
- Everything works from a clean clone with `uv sync` (empty build dir ⇒ packaged `artifacts/`), no API key, no tracking download.
- Any number shown on the page comes from an API response; the page never computes values, rankings or phrases.
- `decide_snapshot` (through `Board`) is the only valuation path; `AskService` the only source of rankings, profiles, shots, explanations and featured lists; the six MCP tools do not change (the parity test `test_wrappers_and_dispatcher_share_one_signature` keeps passing).
- The whiteboard keeps every current capability (drag, recompute, undo, reset, 2D/2.5D toggle, clamping, `--game` filter on its shot list); its API routes keep their paths, payloads and status codes.
- README ≤ 1000 words and exactly 2 figures.

## Review Focus

1. A `#shot=` in the URL that does not exist (or an excluded shot) must show a readable message and fall back to the default shot, not a blank page or a console error. → test in Task 3 (API: 404 body) and the controller's browser check.
2. `POST /api/ask/{tool}` with bad arguments (wrong type, limit 0, ambiguous name) must return 400 with the service's message and never a traceback; an unknown tool 404. → tests in Task 2.
3. `/docs/decisions/{name}` must never serve a file outside `docs/decisions/` (`..`, absolute paths, other extensions). → test in Task 2.
4. A shot whose curve window is null (verdict `none`/`no_window`) must still render the curve (two lines, decision marker, no shaded band). → test in Task 2 (`window: null` in the API) and Task 4 (curve.js handles null).
5. A clean clone without `docs/reel/` built clips must show the "render it with…" line, not a broken image. → tests in Task 2 (`/api/reel` empty) and Task 3 (shot.js branch).

---

### Task 1: Service additions — `featured`, public `board`, server with injected service

**Files:**
- Modify: `src/ventaja/mcp/service.py`, `src/ventaja/mcp/models.py`, `src/ventaja/mcp/server.py`
- Test: `tests/test_mcp_service.py`, `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `reel.rank_tables(decisions, summaries, players, games, *, n)` → `(worst, best, late, low)` DataFrames with columns `rank, shot_id, ..., cost | margin | lost_value` (names fall back to ids when `players`/`games` are `None`; the service never uses those name columns); `MIN_RANK_CONFIDENCE`; existing `AskService` state (`decisions`, `summaries`) and `_shot_summary`-style builders used by `find_shots`.
- Produces:
  - `models.py`: `FeaturedShot(rank: int, metric: float, shot: ShotSummary)`; `Featured(default_shot: str | None, worst: list[FeaturedShot], best: list[FeaturedShot], late: list[FeaturedShot], low_confidence: int)`.
  - `service.py`: `AskService.featured(self, n: int = 10) -> Featured` — calls `rank_tables(self.decisions, self.summaries, None, None, n=n)`, builds each `ShotSummary` with the same builder `find_shots` uses (so names, headline, verdict match), `metric` = `cost` / `margin` / `lost_value` rounded to 3 decimals, `default_shot` = `worst[0].shot.shot_id` or `None` when `worst` is empty; `n < 1` → `ValueError`. Also `@property board(self) -> Board` (public, lazy, same instance `what_if` uses).
  - `server.py`: `create_server(settings, *, model=None, priors=None, service: AskService | None = None) -> MCPServer` (an injected service is used as is); `def tool_schemas(server: MCPServer) -> list[dict[str, Any]]` returning `[{"name", "description", "input_schema"}, ...]` in `TOOL_NAMES` order, computed synchronously via `asyncio.run(server.list_tools())` (if the SDK's `list_tools` is a coroutine) — pure, no I/O beyond the server object.

- [ ] **Step 1: Write the failing tests**

```python
def test_featured_matches_reel_rules(service: AskService) -> None:
    feat = service.featured(n=5)
    worst, best, late, low = rank_tables(service.decisions, service.summaries, None, None, n=5)
    assert [f.shot.shot_id for f in feat.worst] == worst["shot_id"].to_list()
    assert [f.shot.shot_id for f in feat.best] == best["shot_id"].to_list()
    assert [f.shot.shot_id for f in feat.late] == late["shot_id"].to_list()
    assert feat.default_shot == worst["shot_id"][0] == "shot-191313-1-31"
    assert feat.worst[0].metric == round(worst["cost"][0], 3) and feat.low_confidence == low
    assert all(f.shot.shooter.name for f in feat.worst + feat.best + feat.late)
    with pytest.raises(ValueError):
        service.featured(n=0)

def test_board_property_is_shared_with_what_if(service: AskService) -> None:
    board = service.board
    service.what_if("shot-114243-1-0", [])
    assert service.board is board

def test_server_accepts_an_injected_service(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "raw", build_dir=tmp_path / "build")
    service = AskService(settings)
    server = create_server(settings, service=service)
    schemas = tool_schemas(server)
    assert [s["name"] for s in schemas] == list(TOOL_NAMES)
    assert all(s["description"] and s["input_schema"]["type"] == "object" for s in schemas)
    assert schemas[1]["input_schema"]["properties"]["limit"]["maximum"] == MCP_MAX_LIMIT
```

- [ ] **Step 2: Run them** → FAIL (`featured` / `tool_schemas` undefined).
- [ ] **Step 3: Implement** the models, `featured`, the `board` property (replace the private `_board` usage in `what_if`), the `service=` parameter and `tool_schemas`.
- [ ] **Step 4: Run the suite** → PASS (the parity test unchanged).
- [ ] **Step 5: Commit** — `feat: featured shots, public board and injectable service for the web app`

---

### Task 2: `ventaja/web/app.py` — routes, `ventaja app`, tests moved

**Files:**
- Create: `src/ventaja/web/__init__.py`, `src/ventaja/web/app.py`, `src/ventaja/cli/app.py`, `tests/test_web_app.py`
- Move: `src/ventaja/board/static/index.html` → `src/ventaja/web/static/index.html` (unchanged in this task; Task 3 splits it), `tests/test_board_app.py` → `tests/test_web_app.py` (every existing test kept, imports updated)
- Delete: `src/ventaja/board/app.py`, `src/ventaja/cli/board.py`
- Modify: `src/ventaja/cli/__init__.py`, `tests/test_cli_split.py`, `CLAUDE.md` (commands)

**Interfaces:**
- Consumes: Task 1 (`AskService.featured`, `.board`, `create_server(service=)`, `tool_schemas`); `call_tool`, `render_glossary`, `TOOL_NAMES` (`mcp/server.py`); `load_people` (`data/people.py`); `load_curves`, `load_curve_summaries`, `load_decisions`, `ARTIFACTS_DIR` (`data/load.py`); `FPS` (`config.py`); `court_payload`, `Board` (`board/engine.py`); `__version__`.
- Produces:
  - `web/app.py`: `create_app(settings, *, model=None, priors=None, games: Sequence[int] | None = None) -> FastAPI` — same guard as today (`VentajaError` naming `ventaja frames build` when no frames); builds one `AskService` (wrapped so a `DataNotFoundError` becomes `VentajaError`), `board = service.board`, `server = create_server(settings, service=service)`, `schemas = tool_schemas(server)` once; mounts `StaticFiles` at `/static` from `web/static/`; `GET /` serves `static/index.html`; `REPO_ROOT = ARTIFACTS_DIR.parent`; mounts `/reel` from `REPO_ROOT / "docs" / "reel"` only if that directory exists.
  - Whiteboard routes verbatim from today's `board/app.py` (`/api/court`, `/api/shots?game=` with the `games` filter, `/api/shot/{id}`, `POST /api/shot/{id}/evaluate`, the 422 handler, `Move`, `EvaluateRequest`, `_evaluate`).
  - `GET /api/ask/schema` → `schemas`.
  - `POST /api/ask/{tool}` (body: JSON object of arguments, default `{}`) → `call_tool(service, tool, body)` dumped (`model_dump()` or list of dumps); unknown tool → 404 `{"error": "unknown tool 'x'; tools: ..."}`; `DataNotFoundError` → 404; other `VentajaError`, `ValueError`, pydantic `ValidationError` → 400; body always `{"error": str(exc)}`.
  - `GET /api/ask/glossary` → `PlainTextResponse(render_glossary(), media_type="text/markdown")`.
  - `GET /api/curve/{shot_id}` → `{"shot_id", "rows": [{"t": t_to_release, "frame": frame_idx, "handler_id", "handler_shot_value", "best_pass_value", "best_value", "n_viable"}...] sorted by frame, "summary": {verdict, advantage_seconds, release_lag_seconds, window_handler_id, held_to_decision, headline_en, shot_value, window_peak_value}, "decision_t": (decision_frame - release_frame) / FPS, "release_t": 0.0, "window": [(window_start - release_frame)/FPS, (window_end - release_frame)/FPS] or null when either is null, "handlers": {str(player_id): jersey-or-fallback}}` for the handler ids in the rows (fallback = last two digits of the id, as the board does); 404 `{"error": ...}` when the shot has no curve rows; `summary` is `null` when the summary row is missing.
  - `GET /api/reel` → `{"dir": "<name>" | null, "clips": {shot_id: "/reel/<name>/<file>.gif"}}` from the lexicographically last `docs/reel/*/` directory that contains `*.gif`; a file name `{rank:02d}-{kind}-{shot_id}.gif` maps its `shot_id`; first file wins on duplicates; `{"dir": null, "clips": {}}` when nothing exists.
  - `GET /api/featured?n=10` → `service.featured(n).model_dump()`; `n` validated `1..50` (400 otherwise).
  - `GET /api/about` → `{"version": __version__, "games": len(service.games), "valued_shots": <count of rule != excluded>, "players": <carded players excluding LIGA>, "model_trained_at", "built_at"}` (stamps from `service.players` first row).
  - `GET /docs/decisions/{name}` → `PlainTextResponse` of `REPO_ROOT/docs/decisions/<name>` when `name` matches `^\d{4}-[a-z0-9-]+\.md$` and the resolved path is inside that directory and exists; 404 otherwise (no listing).
  - `cli/app.py`: `def app(host="127.0.0.1", port=BOARD_PORT, game: GameOption=None, no_open=False)` with help `"Serve the ventaja app: shot, whiteboard, curve, players, games and the MCP tools in one page."`; registered as `app.command("app")`; `app.command("board")` registers the same function object under the alias with help `"Alias of `ventaja app` (kept for the whiteboard users)."` — if typer cannot register one function twice with different help, define `board()` as a one-line wrapper. Both lazy-import uvicorn and `create_app`; the browser-opening thread is moved from `cli/board.py` unchanged.

- [ ] **Step 1: Move the tests** (`git mv tests/test_board_app.py tests/test_web_app.py`, update `from ventaja.board.app import create_app` → `from ventaja.web.app import create_app`, the static path in `test_index_page_static_contract`, and the CLI invocations `["board", ...]` → keep them for the alias and add the same for `["app", ...]`), then **write the failing tests** for the new routes:

```python
def test_ask_schema_lists_six_tools(client: TestClient) -> None:
    schemas = client.get("/api/ask/schema").json()
    assert [s["name"] for s in schemas] == list(TOOL_NAMES)

def test_ask_matches_the_service(client: TestClient, service: AskService) -> None:
    body = {"team": "Breogan", "clock": "6-0"}
    assert client.post("/api/ask/rank_players", json=body).json() == service.rank_players(**body).model_dump()
    games = client.post("/api/ask/list_games", json={}).json()
    assert isinstance(games, list) and len(games) == 10

@pytest.mark.parametrize("tool, body, status, needle", [
    ("nope", {}, 404, "unknown tool"),
    ("rank_players", {"limit": 0}, 400, "limit"),
    ("player_profile", {"player": "a"}, 400, "players match"),
    ("explain_shot", {"shot_id": "shot-114243-9-9"}, 404, "not found"),
    ("what_if", {"shot_id": "shot-114243-1-0", "moves": [{"player": "1", "x": "nan", "y": 0}]}, 400, "x"),
])
def test_ask_errors_are_json(client: TestClient, tool: str, body: dict[str, Any], status: int, needle: str) -> None:
    r = client.post(f"/api/ask/{tool}", json=body)
    assert r.status_code == status and needle in r.json()["error"] and "Traceback" not in r.text

def test_glossary_is_markdown(client: TestClient) -> None:
    r = client.get("/api/ask/glossary")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown") and "# Ventaja glossary" in r.text

def test_curve_payload(client: TestClient) -> None:
    c = client.get("/api/curve/shot-191313-1-31").json()
    assert c["rows"] and c["rows"][0]["t"] < 0 and c["summary"]["verdict"] == "during"
    assert c["decision_t"] < 0 and c["window"] is not None and c["window"][0] <= c["window"][1]
    assert all(str(r["handler_id"]) in c["handlers"] for r in c["rows"])
    none_shot = next(s for s in client.post("/api/ask/find_shots", json={"verdict": "none", "limit": 1}).json()["shots"])
    assert client.get(f"/api/curve/{none_shot['shot_id']}").json()["window"] is None
    assert client.get("/api/curve/shot-114243-9-9").status_code == 404

def test_curve_without_summary_row(tmp_path: Path) -> None:
    # build dir with the packaged decisions and one game's curves but no summary file (as tests/test_mcp_service.py does)
    ...
    assert app_client.get("/api/curve/shot-114243-1-0").json()["summary"] is None

def test_reel_lists_clips_or_nothing(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    r = client.get("/api/reel").json()
    assert set(r) == {"dir", "clips"}
    if r["dir"]:
        assert all(v.startswith(f"/reel/{r['dir']}/") and v.endswith(".gif") for v in r["clips"].values())
    monkeypatch.setattr("ventaja.web.app.REPO_ROOT", tmp_path)   # no docs/reel here
    app2 = TestClient(create_app(clean_settings))
    assert app2.get("/api/reel").json() == {"dir": None, "clips": {}}

def test_featured_and_about(client: TestClient, service: AskService) -> None:
    f = client.get("/api/featured", params={"n": 3}).json()
    assert f["default_shot"] == "shot-191313-1-31" and len(f["worst"]) == 3
    assert client.get("/api/featured", params={"n": 0}).status_code == 400
    a = client.get("/api/about").json()
    assert a["games"] == 10 and a["valued_shots"] == 1351 and a["model_trained_at"] and a["version"]

@pytest.mark.parametrize("name, status", [("0009-pizarra.md", 200), ("0099-nope.md", 404), ("../README.md", 404), ("0009-pizarra.txt", 404)])
def test_docs_route_is_confined(client: TestClient, name: str, status: int) -> None:
    assert client.get(f"/docs/decisions/{name}").status_code == status

def test_cli_app_and_board_alias(runner: CliRunner) -> None:
    assert "ventaja app" in runner.invoke(cli_app, ["board", "--help"]).stdout
```

(The `client` fixture of this module uses the packaged artifacts: `create_app(Settings(data_dir=tmp/raw, build_dir=tmp/build))`; the moved whiteboard tests keep their fixture-built settings.)

- [ ] **Step 2: Run** → FAIL (`ventaja.web` missing).
- [ ] **Step 3: Implement** `web/app.py` (move the whiteboard code verbatim), `cli/app.py`, registrations, deletions; update `tests/test_cli_split.py` (`EXPECTED_TOP_LEVEL` gains `"app"`, help snapshot lines for `app` and `board`); CLAUDE.md commands (`uv run ventaja app`, `board` alias).
- [ ] **Step 4: Run the suite** → PASS; `uv run ventaja app --no-open --port 8768` serves `/` and `/api/featured` (curl both, then stop it).
- [ ] **Step 5: Commit** — `feat: ventaja app server with ask, curve, reel, featured, about and docs routes`

---

### Task 3: Shell, router, whiteboard extraction and the Shot view

**Files:**
- Create: `src/ventaja/web/static/app.css`, `app.js`, `board.js`, `shot.js`
- Modify: `src/ventaja/web/static/index.html` (becomes the shell), `tests/test_web_app.py` (`test_index_page_static_contract` → structure test)

**Interfaces:**
- Consumes: the routes of Task 2; today's `index.html` JavaScript (functions `drawCourt`, `initSvg`, `buildPlayers`, `drawBoard`, `toFeet`, `startDrag/onDrag/endDrag`, `evaluate`, `loadShot`, `renderHeader`, `renderTable`, `renderHeadline`, the 2.5D matrix and toggle).
- Produces:
  - `index.html` (shell, ≤ 120 lines): `<nav>` with five links (`#shot`, `#players`, `#games`, `#ask`, `#about`, English labels `Shot · Players · Games · Ask · About`), one `<section data-view="...">` per view (hidden unless active), `<link rel="stylesheet" href="/static/app.css">`, `<script type="module" src="/static/app.js">`. No inline script.
  - `app.js`: hash router. State `{view, shot, player, game, ask}` parsed from `location.hash` (`#shot=shot-…`, `#players&player=58474`, `#games&game=191313`, `#ask=rank_players`); `export function navigate(patch)` updates the hash; `export async function api(path, {method, body})` → JSON or throws `Error(json.error)`; `export const fmt = {num(x, d), pct(x)}`; on load, imports every view module and calls `mount(sectionEl)` once, then `update(state)` on each hash change for the active view. Also `?shot=` in the query is accepted as `#shot=` (backwards compatibility with the README link).
  - `board.js`: `export function mountBoard(host, {onPayload})` and `export function showShot(shotId)`, `export function getState()`; the body is today's whiteboard code moved as is (same constants, matrix, drag handlers, throttle, undo/reset, `localStorage` key); the only changes: it no longer owns the header/table/headline (it calls `onPayload(payload)` after every render) and it reads the shot from `showShot` instead of its own selects. The game/shot `<select>`s and the Reset/Undo/view buttons stay in the board host.
  - `shot.js`: `mount(section)` builds the layout: left `board` host; right column with header (today's `renderHeader` moved here), headline, a `<div id="curve">` host (Task 4 fills it), the options table (today's `renderTable`), the clip block (`/api/reel`: `<img>` when `clips[shot]` exists else the line `Clip not built: run \`ventaja clip {shot} --out {shot}.gif\` (needs the tracking data).`), a "Featured" `<select>` with the three lists (`/api/featured`, labels `Worst decisions · Best reads · Lost moments`, each option `#rank shooter — metric`), and "Other shots in this game" (`/api/shots?game=` sorted by cost, click → `navigate({shot})`). `update(state)`: when `state.shot` is empty, use `featured.default_shot`; unknown/excluded shot (404 from `/api/shot/`) → status line `Shot {id} is not available: {message}` and fall back to the default shot.
  - `app.css`: today's styles moved out of `index.html` plus the nav and the two-column layout (≥ 1100 px) / single column (< 1100 px); nothing fancy.

- [ ] **Step 1: Write the failing structure test** (replace `test_index_page_static_contract`):

```python
def test_static_files_are_wired_and_small(client: TestClient) -> None:
    html = client.get("/").text
    assert '<script type="module" src="/static/app.js">' in html and "/static/app.css" in html
    assert "<script>" not in html
    for name in ("app.js", "board.js", "shot.js", "curve.js", "players.js", "games.js", "ask.js", "about.js", "app.css"):
        r = client.get(f"/static/{name}")
        assert r.status_code == 200, name
        assert r.headers["content-type"].startswith("text/javascript" if name.endswith(".js") else "text/css")
        assert len(r.text.splitlines()) <= 600, name
    for view in ("shot", "players", "games", "ask", "about"):
        assert f'data-view="{view}"' in html
```

(Modules not yet written in this task may be stubs exporting `mount`/`update` no-ops; Tasks 4–5 fill them.)

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the shell, router, `board.js` (extract, do not rewrite), `shot.js`, `app.css`, stub modules for the other views. Check `node --check` on each file if `node` exists.
- [ ] **Step 4: Run the suite** → PASS. Report to the controller for the browser check (drag/recompute/undo/reset/toggle in the new shell, featured selector, other shots, bad `#shot=`).
- [ ] **Step 5: Commit** — `feat: app shell, hash router and the Shot view with the extracted whiteboard`

---

### Task 4: Curve, Players and Games views

**Files:**
- Create/replace: `src/ventaja/web/static/curve.js`, `players.js`, `games.js`

**Interfaces:**
- Consumes: `/api/curve/{shot}` (Task 2 shape), `/api/ask/rank_players`, `/api/ask/player_profile`, `/api/ask/find_shots`, `/api/ask/list_games`, `/api/shots?game=`; `api`, `navigate`, `fmt` from `app.js`; the `#curve` host from `shot.js`.
- Produces:
  - `curve.js`: `export async function showCurve(host, shotId)` → inline SVG (`viewBox` fixed, e.g. `0 0 640 240`): x = `t` from `min(rows.t)` to `max(rows.t, 0)`, y = value from 0 to `max(2.5, max values)`; shaded band for `window` when not null; dashed vertical line at `decision_t` labelled `decision`, solid at `0` labelled `release`; line A `handler_shot_value` (shooter colour), line B `best_pass_value` (dark), gaps where a value is null; small labels with the handler jersey at each handler change; the headline (`summary.headline_en`) above; one line below: `The curve values the real possession; moves on the board do not change it.` Null summary → draw without band and headline.
  - `players.js`: `mount`/`update`: filter bar (team `<select>` from `list_games` teams, clock band `<select>` with `any/24-14/14-6/6-0`, min shots `<input type=number min=1>`, metric `<select>`), ranking table (rank, player, team, n_shots, n_readable, the three metrics, band n/cost when a band is set) with the league row pinned at the bottom; click a row → `navigate({view: 'players', player: id})` → profile panel (identity, games, totals, clock bands table, alternatives table, season block vs league, phrase, caution) and the player's shots (`find_shots({player: id, limit: 50})`, click → `navigate({view: 'shot', shot})`). When `clock` is set the metric select is forced to `mean_cost` and says why (the service's rule).
  - `games.js`: table of `list_games` (date, home, score, away, valued shots); click → shots of the game from `/api/shots?game=` sorted by cost (shooter, team, period, clock, cost, good_read, headline), click → shot view.

- [ ] **Step 1: Write the failing test** (structure only; the behaviour is checked in the browser): extend `test_static_files_are_wired_and_small` expectations — nothing new to assert beyond the file list; instead add a data test guarding the curve contract the JS relies on:

```python
def test_curve_rows_are_sorted_and_cover_release(client: TestClient) -> None:
    c = client.get("/api/curve/shot-191313-1-31").json()
    ts = [r["t"] for r in c["rows"]]
    assert ts == sorted(ts) and ts[-1] >= -0.3 and c["decision_t"] >= ts[0]
```

- [ ] **Step 2: Run** → PASS or FAIL depending on Task 2's sort; make it pass.
- [ ] **Step 3: Implement** the three modules (≤ 600 lines each; `node --check`).
- [ ] **Step 4: Run the suite** → PASS. Report for the browser check (curve on Spissu and on a `none` shot; players filter by Breogán + 6-0; profile; games → shot).
- [ ] **Step 5: Commit** — `feat: advantage curve, players and games views`

---

### Task 5: Ask and About views, CI and clean-clone step

**Files:**
- Create/replace: `src/ventaja/web/static/ask.js`, `about.js`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `/api/ask/schema`, `/api/ask/{tool}`, `/api/ask/glossary`, `/api/about`, `/docs/decisions/{name}`.
- Produces:
  - `ask.js`: a form per tool generated from `input_schema` (`string` → text input, `integer`/`number` → number input with min/max from the schema, `boolean` → checkbox with an "unset" state, `enum` → select, `array` of objects (`moves`) → a textarea with JSON and a hint); description under the title; submit → `POST /api/ask/{tool}` → pretty JSON in a `<pre>` (collapsible); errors shown in red from `error`. A fixed block `Connect an AI client` with the `claude mcp add ventaja -- uv run --directory <repo> ventaja mcp serve` line and the Claude Desktop JSON (both as copyable code), and a `Glossary` link that loads `/api/ask/glossary` into a panel (render Markdown headings and lists minimally, or show as preformatted text — builder's choice).
  - `about.js`: the ten-line description (from the README's first paragraph, kept in sync by hand), the four surfaces, `about` numbers (games, valued shots, players, model trained at, built at, version), and a list of ADRs (`0001` … `0011`) that load into a panel from `/docs/decisions/`.
  - CI `pipeline` job, after the MCP steps:
    ```yaml
    - run: |
        VENTAJA_BUILD_DIR=/tmp/empty-build uv run ventaja app --no-open --port 8765 &
        for i in $(seq 1 60); do curl -sf http://127.0.0.1:8765/api/court >/dev/null && break; sleep 1; done
        curl -sf http://127.0.0.1:8765/ >/dev/null
        curl -sf http://127.0.0.1:8765/api/featured | grep -q default_shot
        curl -sf http://127.0.0.1:8765/api/ask/schema | grep -q what_if
        curl -sf http://127.0.0.1:8765/api/curve/shot-191313-1-31 | grep -q decision_t
        kill %1
    ```

- [ ] **Step 1: Run the structure test** (files exist from Task 3 stubs) — write the real modules.
- [ ] **Step 2: Implement** `ask.js`, `about.js`, the CI step; run the CI block locally with a free port.
- [ ] **Step 3: Run the suite** → PASS. Report for the browser check (every tool form, including `what_if` with a JSON move; an error; the glossary; About with ADR-0009 loaded).
- [ ] **Step 4: Commit** — `feat: Ask and About views; CI smoke test of the app`

---

### Task 6: Close — ADR-0011, README, CLAUDE.md

**Files:**
- Create: `docs/decisions/0011-app-unificada.md`
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: ADR-0011** (Spanish; shape of ADR-0009/0010): why one app; FastAPI + ES modules without build; "page, CLI and MCP answer alike" and how (`AskService` shared, schemas from the `MCPServer`); the default shot by the reel's rule; `featured()` not being an MCP tool; the whiteboard extracted untouched; clips shown only if built; ADRs/GIFs served from the repo root (installed-package limit); error codes; the per-file 600-line rule; `board` alias. Alternatives rejected: separate pages per surface; a static published showcase; a JS framework; an LLM in the page.
- [ ] **Step 2: README** — rename `## Whiteboard` to `## App` (command `uv run ventaja app`, one paragraph: what opens, the views, the whiteboard inside it, `ventaja board` alias; keep the figure and update its caption if the controller recaptures it; keep the ADR-0009 link and add ADR-0011); `## Ask the court` stays. Final check: `wc -w README.md` ≤ 1000, `grep -c '!\[' README.md` == 2.
- [ ] **Step 3: CLAUDE.md** — commands (`app`, `board` alias), the `web/` structure, the per-file 600-line rule, "any visible number comes from the API", the regeneration note unchanged.
- [ ] **Step 4: Full gate** → green. **Step 5: Commit** — `docs: ADR-0011, README and CLAUDE.md for the unified app`

---

### Task 7 (controller): browser checks, figure, clean clone

- [ ] Chrome: open `http://127.0.0.1:8765/` with no hash → Spissu's shot with board + curve + headline + table + clip; drag, recompute, undo, reset, toggle; `#shot=shot-114243-9-9` → message and fallback; players (Breogán, 6-0 → Russell first), profile, games → shot; ask forms incl. `what_if`; about with an ADR; console clean; widths 1100 px and 390 px.
- [ ] Recapture `docs/figures/board-shot-114243-3-108.jpg` inside the app (Olinde dragged into the restricted area), update the caption numbers, commit.
- [ ] Clean clone: `git clone`, `uv sync`, `uv run ventaja app --no-open` with an empty build dir, curl `/`, `/api/featured`, `/api/ask/schema`, `/api/curve/shot-191313-1-31`.
- [ ] Final whole-branch review (opus), fix wave, merge `--no-ff`, tag `app-unificada`, ask before push.
