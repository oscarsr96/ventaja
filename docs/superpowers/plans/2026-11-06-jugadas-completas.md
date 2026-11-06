# Jugadas completas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package every valued shot's full possession at 25 fps (`artifacts/plays/`), serve it as `/api/play/{shot_id}`, and play it in the Shot view with a timeline that moves the whiteboard figures and a cursor on the advantage curve.

**Architecture:** `decision/frames.py` gains `build_plays` (same oriented snapshots the clip renderer uses: `Aligner.window(start, end)`), written by `ventaja frames build`; `data/load.py` gains the `plays` artifact kind; `web/app.py` gains the play route; `web/static/play.js` drives `board.showFrame(frame | null)` and `curve.setCursor(t | null)`.

**Tech Stack:** Python ≥ 3.12, polars (zstd parquet, Float32), FastAPI, vanilla ES modules; pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-jugadas-completas-design.md` (binding; parents ADR-0009, ADR-0011).

## Global Constraints

- Code/UI English; ADR Spanish. ruff, ruff format, mypy strict, pytest (warnings as errors) green after every task; conventional commits with the session's two attribution lines.
- No new dependency, no JS build/framework/CDN; every file under `web/static/` ≤ 600 lines.
- The packaged plays total ≤ 30 MB (`artifacts/plays/*.parquet`), Float32 for coordinates/time, zstd.
- The whiteboard keeps every capability; dragging works exactly as today at the decision frame; `board.js` changes limited to `showFrame` and the playback guard in `startDrag`.
- Any number shown comes from an API response (times and clocks come from the play payload).
- Clean clone with `uv sync` works; without `plays/` the app degrades to today's behaviour with a visible hint.
- README ≤ 1000 words and exactly 2 figures.

## Review Focus

1. A shot whose possession has gaps in the tracking (empty frames) must play without figures jumping to the origin: missing entities keep their last position. → Task 3 (board.showFrame) and Task 1 (gaps are simply absent rows; test with the fixture's gaps).
2. `frames build` on a build without curves must fail with a message naming `ventaja curves build` (plays need the curve window), not a KeyError. → Task 1.
3. `/api/play` for an excluded or unknown shot → 404 `{"error"}`; for a valued shot without plays table → 404 with the `frames build` hint. → Task 2.
4. Leaving the Shot view while playing must stop the animation loop (no background `requestAnimationFrame`), and switching shots resets to the decision frame paused. → Task 3.
5. Dragging during playback must be refused (no move sent), and after "Decision" the user's previous moves are still there. → Task 3.

---

### Task 1: `artifacts/plays/` — builder, loaders, CLI, packaged files

**Files:**
- Modify: `src/ventaja/decision/frames.py`, `src/ventaja/data/load.py`, `src/ventaja/config.py`, `src/ventaja/cli/frames.py`, `CLAUDE.md`
- Create: `artifacts/plays/{game}.parquet` × 10 (generated with the real build)
- Test: `tests/test_frames.py`

**Interfaces:**
- Consumes: `Aligner(game_id, settings).window(start_frame, end_frame) -> list[Snapshot]` (oriented; frames without tracking absent; `Snapshot` has `frame_idx`, `shot_clock`, `offense`/`defense` lists of `PlayerPos(player_id, x, y, ...)`, `ball(x, y, z)`); `load_decisions` (`release_frame`, `rule`); `load_curves(game_id, settings)` (`shot_id`, `frame_idx`); `FPS`; `write_parquet_atomic`.
- Produces:
  - `config.py`: `plays_parquet(self, game_id) -> Path` = `build_dir / "plays" / f"{game_id}.parquet"`.
  - `frames.py`: `PLAY_SCHEMA` exactly: `shot_id String, frame_idx Int64, t Float32, shot_clock Float32, side String, player_id Int64, x Float32, y Float32, z Float32`; `build_plays(game_id, settings, *, out_dir=None) -> Path` — for each valued shot: `start = min(curve.frame_idx)` of the shot (a shot absent from the curves table is skipped), `end = release_frame + FPS`; rows from `aligner.window(start, end)`: offense, defense, ball per snapshot; `t = (frame_idx - release_frame) / FPS`; `shot_clock` from the snapshot; written with `compression="zstd"` to `out_dir or settings.plays_parquet(game_id).parent`; raises `DataNotFoundError` naming `ventaja curves build` when the curves table is missing.
  - `load.py`: `ArtifactKind` gains `"plays"` (per-game main tables, no secondary file, hint `frames build`); `play_files(settings) -> list[Path]`; `load_plays(game_id, settings) -> pl.DataFrame`.
  - `cli/frames.py`: `frames build` writes the plays after the frames of each game and echoes `plays: N shots, M rows -> path`; `--no-plays` flag skips it; `--out` applies to both (`{out}/plays/` is not used: plays go to `{out}/../plays`? No — keep it simple: `--out DIR` writes frames to `DIR` and plays to `DIR.parent / "plays"` only when `DIR.name == "frames"`, else to `DIR / "plays"`; document it in the help).

- [ ] **Step 1: Write the failing tests** (`tests/test_frames.py`, fixture `fixture_curves_built` + `build_frames` already used there):

```python
def test_build_plays_covers_the_possession(fixture_curves_built: Settings) -> None:
    path = build_plays(FIXTURE_GAME_ID, fixture_curves_built)
    plays = pl.read_parquet(path)
    assert plays.schema == PLAY_SCHEMA
    decisions = load_decisions(FIXTURE_GAME_ID, fixture_curves_built).filter(pl.col("rule") != "excluded")
    curves = load_curves(FIXTURE_GAME_ID, fixture_curves_built)
    assert set(plays["shot_id"]) == set(curves["shot_id"]) & set(decisions["shot_id"])
    one = plays.filter(pl.col("shot_id") == "shot-114243-1-0")
    release = decisions.filter(pl.col("shot_id") == "shot-114243-1-0")["release_frame"][0]
    assert one["frame_idx"].min() == curves.filter(pl.col("shot_id") == "shot-114243-1-0")["frame_idx"].min()
    assert one["frame_idx"].max() <= release + FPS
    assert abs(one.filter(pl.col("frame_idx") == release)["t"][0]) < 1e-6
    per_frame = one.group_by("frame_idx").len()
    assert per_frame["len"].max() <= 11 and set(one["side"]) == {"offense", "defense", "ball"}
    assert one.filter(pl.col("side") == "ball")["player_id"].null_count() == one.filter(pl.col("side") == "ball").height
    assert load_plays(FIXTURE_GAME_ID, fixture_curves_built).height == plays.height

def test_build_plays_needs_curves(built_fixture: Settings, trained_fixture_model: ValueModel) -> None:
    build_decisions(FIXTURE_GAME_ID, built_fixture, model=trained_fixture_model)   # decisions but no curves in this build dir
    with pytest.raises(DataNotFoundError, match="curves build"):
        build_plays(FIXTURE_GAME_ID, built_fixture)

def test_frames_build_cli_writes_plays_unless_skipped(fixture_curves_built: Settings, tmp_path: Path, monkeypatch) -> None:
    ... invoke ["frames", "build", "--game", "114243", "--out", str(tmp_path / "frames")] -> (tmp_path / "plays" / "114243.parquet").exists()
    ... invoke with "--no-plays" into another dir -> no plays file

def test_packaged_plays_are_bounded(tmp_path: Path) -> None:
    clean = Settings(data_dir=tmp_path / "raw", build_dir=tmp_path / "build")
    files = play_files(clean)
    assert len(files) == 10 and sum(p.stat().st_size for p in files) <= 30_000_000
    plays = load_plays(191313, clean)
    assert plays.filter(pl.col("shot_id") == "shot-191313-1-31").height > 11 * 25 * 3
```

(`test_build_plays_needs_curves` may need its own build dir: copy the fixture build without `curves/`; follow the pattern used by the existing `decisions_for_all_frames_for_one` helper.)

- [ ] **Step 2: Run** → FAIL (`build_plays` undefined).
- [ ] **Step 3: Implement**; then generate the packaged files with the real build:

```bash
VENTAJA_DATA_DIR=/Users/oscarsanchezrueda/Repos/opendata-basketball/data \
VENTAJA_BUILD_DIR=/private/tmp/claude-501/-Users-oscarsanchezrueda-Repos-opendata-basketball/ada63f13-68d2-422e-8a95-1432d393f67e/scratchpad/build \
uv run ventaja frames build --all --out artifacts/frames     # frames rewritten identically (check `git diff --stat artifacts/frames` is empty or only roster/games noise) and artifacts/plays/ created
du -sh artifacts/plays
```
If the frames files change (they should not: same inputs), restore them with `git checkout artifacts/frames` and keep only `artifacts/plays/`.

- [ ] **Step 4: Run the suite** → PASS. CLAUDE.md: regeneration order gains plays (`frames build` writes `artifacts/frames/` and `artifacts/plays/`, ≈ 25 MB, 25 fps, full possession).
- [ ] **Step 5: Commit** — `feat: package every valued shot's possession as artifacts/plays (25 fps)`

---

### Task 2: `GET /api/play/{shot_id}`

**Files:**
- Modify: `src/ventaja/web/app.py`, `.github/workflows/ci.yml` (one curl in the app smoke block), `tests/test_web_app.py`

**Interfaces:**
- Consumes: `load_plays`, `play_files` (Task 1); the service's decisions (`decision_frame`, `release_frame`, `rule`), `FPS`.
- Produces: `GET /api/play/{shot_id}` → `{"shot_id", "fps": 25, "t0", "t1", "decision_t", "release_t": 0.0, "frames": [{"t", "clock": float | null, "players": [[player_id, x, y], ...], "ball": [x, y, z] | null}, ...]}` sorted by `t`, floats rounded to 2 decimals (feet) / 2 decimals (seconds); 404 `{"error": "shot {id} not found in the decisions tables"}` for unknown ids, 404 `{"error": "shot {id} is excluded: {reason}"}` for excluded, 404 `{"error": "no play data for game {g}; run `ventaja frames build --game {g}` with the tracking"}` when the plays table is missing, 404 `{"error": "shot {id} has no play (no curve window)"}` when the table exists but the shot is absent. Plays tables cached per game in the app (dict), loaded on first use.

- [ ] **Step 1: Write the failing tests** (packaged-artifact client):

```python
def test_play_payload(pkg_client: TestClient) -> None:
    p = pkg_client.get("/api/play/shot-191313-1-31").json()
    assert p["fps"] == 25 and p["t0"] < p["decision_t"] < p["release_t"] == 0.0 < p["t1"]
    ts = [f["t"] for f in p["frames"]]
    assert ts == sorted(ts) and len(ts) > 25 * 3
    f = p["frames"][-1]
    assert len(f["players"]) == 10 and len(f["players"][0]) == 3 and (f["ball"] is None or len(f["ball"]) == 3)
    assert any(abs(f["t"] - p["decision_t"]) < 0.05 for f in p["frames"])

@pytest.mark.parametrize("shot_id, needle", [("shot-114243-9-9", "not found"), ("<an excluded id>", "is excluded")])
def test_play_404s(pkg_client: TestClient, shot_id: str, needle: str) -> None: ...

def test_play_without_table_hints_the_build(tmp_path: Path) -> None:
    # build dir with the packaged decisions + frames of one game but no plays/ → 404 mentioning "frames build"
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** the route; add `curl -sf http://127.0.0.1:8765/api/play/shot-114243-1-0 | grep -q decision_t` to the CI app block (the pipeline job builds frames+plays for 114243 before; the app block runs with the empty build dir, so it reads the packaged plays — fine).
- [ ] **Step 4: Run the suite** → PASS. **Step 5: Commit** — `feat: /api/play serves the packaged possession of a shot`

---

### Task 3: Player — `play.js`, `board.showFrame`, `curve.setCursor`, Shot view wiring

**Files:**
- Create: `src/ventaja/web/static/play.js`
- Modify: `src/ventaja/web/static/board.js` (only `showFrame` + a `playback` guard in `startDrag` + ball sizing by `z`), `curve.js` (`setCursor`), `shot.js` (mount the bar under the board host, call `loadPlay(shotId)` on shot change, stop on `update` to another view), `app.css`, `tests/test_web_app.py` (structure test gains `play.js`)

**Interfaces:**
- Consumes: `/api/play/{shot_id}` (Task 2 shape); `board.js` internals (`nodes`, `place`, `ballEl`, `payload`, `moves`, `drawBoard`); `curve.js` SVG scales.
- Produces:
  - `board.js`: `export function showFrame(frame)` — `frame = {t, players: [[id,x,y]], ball: [x,y,z]|null}` places each known `player_id` (`place(id, x, y)`), leaves unknown ids where they are, puts the ball at `(x, y)` with radius `0.8 + 0.25 * max(0, z - 3)` ft (feet of screen in 2D; the figures layer in 2.5D), hides the moved rings and the arrow, sets `playback = true`; `showFrame(null)` restores `drawBoard(payload)` (positions + user moves, rings, arrow) and `playback = false`. `startDrag` returns immediately when `playback` is true. `export function isPlayback()`.
  - `curve.js`: `export function setCursor(t)` — a vertical line at `sx(t)` on the current SVG; `setCursor(null)` removes it. No-op when no curve is drawn.
  - `play.js`: `export function mountPlay(host)` builds the bar: buttons `Play`/`Pause` (one toggling button), `Decision`, a `<input type="range" step="0.04">`, a label `t` (`−3.2 s`) and `clock` (`shot clock 14.0 s`, or `clock unknown`); `export async function loadPlay(shotId)` fetches the play (404 → the bar shows `No play data: run \`ventaja frames build\` with the tracking.` and disables controls), sets the range to `[t0, t1]`, seeks to `decision_t`, paused, `showFrame(null)`; `export function stop()` cancels the animation frame and calls `showFrame(null)` and `setCursor(null)`. Seeking to any `t ≠ decision_t` shows the nearest frame via `showFrame(frame)` and `setCursor(t)`; seeking to `decision_t` (or pressing Decision) calls `showFrame(null)` and `setCursor(decision_t)` so dragging works there. Playback: `requestAnimationFrame` loop advancing `t` by real elapsed time from `t0` (or the current position) to `t1`, then pauses at `t1`.
  - `shot.js`: calls `mountPlay` once under the board host; on each shot change `loadPlay(shot_id)`; on `update` with another view, or before loading a new shot, `stop()`.

- [ ] **Step 1: Extend the structure test** (`play.js` in the module list) — write first, FAIL.
- [ ] **Step 2: Implement**; `node --check` on every changed module; each file ≤ 600 lines (`board.js` is 363 today).
- [ ] **Step 3: Run the suite** → PASS. Report for the controller's Chrome check (play/pause/scrub/Decision on Spissu; drag refused during playback and working at Decision with earlier moves intact; cursor on the curve; a shot without play data; switching views stops the loop).
- [ ] **Step 4: Commit** — `feat: play the full possession on the whiteboard with a curve cursor`

---

### Task 4: Close — ADR-0012, README, CLAUDE.md

**Files:**
- Create: `docs/decisions/0012-jugadas-completas.md`
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: ADR-0012** (Spanish; shape of 0009/0011): why package plays now (Óscar's ask; clips optional); 25 fps and full possession (his choice, sizes measured: 25 / 13 / 5 MB); `PLAY_SCHEMA`; window = curve start → release + 1 s; `frames build` writes both; the route; the player and the playback/drag rule; limits (no interpolation of gaps, no per-frame valuation, ≈ 25 MB in git, excluded shots have no play). Alternatives rejected: 12.5/5 fps; last-8-seconds window; GIF clips in the repo; streaming the tracking.
- [ ] **Step 2: README** — in `## App`, one sentence: the Shot view plays the whole possession at 25 fps with a cursor on the advantage curve; dragging happens at the decision frame. Trim elsewhere to stay ≤ 1000 words; 2 figures unchanged. Check `wc -w` and `grep -c '!\['`.
- [ ] **Step 3: CLAUDE.md** — `frames build` writes plays (`--no-plays`), `artifacts/plays/` ≈ 25 MB regenerated with the tracking, `play.js` rules.
- [ ] **Step 4: Full gate** → green. **Step 5: Commit** — `docs: ADR-0012, README and CLAUDE.md for the full-possession player`

---

### Task 5 (controller): Chrome check, clean clone, final review, merge

- [ ] Chrome: Spissu play/pause/scrub/Decision; cursor; drag refused while playing, allowed at Decision with earlier moves; `#shot=` without play data (simulate with a build dir lacking plays) shows the hint; view switch stops the loop; console clean.
- [ ] Clean clone: `uv sync`, empty build dir, `/api/play/shot-191313-1-31` 200 and size.
- [ ] Final whole-branch review (opus), one fix wave, merge `--no-ff`, tag `jugadas-completas`, ask before push.
