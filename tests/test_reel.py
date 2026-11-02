"""Tests for the decision rankings and the auto-generated reel."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from ventaja import reel as reel_module
from ventaja.cli import app
from ventaja.config import Settings
from ventaja.decision.cost import DECISION_SCHEMA
from ventaja.decision.curve import SUMMARY_SCHEMA
from ventaja.reel import build_reel, rank_tables, rankings
from ventaja.value.params import MIN_RANK_ADVANTAGE, MIN_RANK_CONFIDENCE

GAME_ID = 114243


# --- synthetic tables ----------------------------------------------------------------------


def _decision(shot_id: str, **kw: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "shot_id": shot_id,
        "game_id": 1,
        "shooter_id": 10,
        "decision_frame": 500,
        "release_frame": 510,
        "rule": "gather",
        "reason": None,
        "shot_clock": 12.0,
        "shot_value": 0.9,
        "best_alt_player_id": 11,
        "best_alt_type": "open_corner",
        "best_alt_value": 1.2,
        "cost": 0.3,
        "good_read": False,
        "confidence": 1.0,
    }
    return row | kw


def _summary(shot_id: str, **kw: Any) -> dict[str, Any]:
    row: dict[str, Any] = {c: None for c in SUMMARY_SCHEMA}
    row |= {
        "shot_id": shot_id,
        "game_id": 1,
        "n_rows": 20,
        "shot_value": 0.9,
        "advantage_seconds": 0.0,
        "verdict": "none",
        "held_to_decision": False,
        "headline_es": f"titular {shot_id}",
        "headline_en": f"headline {shot_id}",
        "skipped_off_court": 0,
    }
    return row | kw


def _late(shot_id: str, lag: float, advantage: float = 1.0, held: bool = True) -> dict[str, Any]:
    return _summary(
        shot_id,
        verdict="late",
        held_to_decision=held,
        advantage_seconds=advantage,
        release_lag_seconds=lag,
        window_start=400,
        window_end=450,
        window_handler_id=10,
        window_peak_value=1.4,
    )


PLAYERS = pl.DataFrame(
    {
        "game_id": [1, 1],
        "team_id": [7, 7],
        "player_id": [10, 11],
        "first_name": ["Ana", "Bea"],
        "last_name": ["Uno", "Dos"],
        "jersey": ["4", "5"],
    }
)
GAMES = pl.DataFrame(
    {
        "game_id": [1],
        "home_team_id": [7],
        "home_team_name": ["Locales"],
        "away_team_id": [8],
        "away_team_name": ["Visitantes"],
    }
)


def _synthetic() -> tuple[pl.DataFrame, pl.DataFrame]:
    decisions = pl.DataFrame(
        [
            _decision("shot-1-1-0", cost=0.5),
            _decision("shot-1-1-1", cost=0.9, confidence=0.5),  # low confidence: out, counted
            _decision("shot-1-1-2", cost=2.0, rule="excluded", reason="no_type"),  # never
            _decision("shot-1-2-3", cost=0.0, good_read=True, best_alt_value=0.4),  # margin 0.5
            _decision("shot-1-2-4", cost=0.0, good_read=True, best_alt_value=0.7),  # margin 0.2
            _decision("shot-1-3-5", cost=0.0, good_read=None, best_alt_value=None),  # no pass
            _decision("shot-1-4-6", cost=0.1),
        ],
        schema=DECISION_SCHEMA,
    )
    summaries = pl.DataFrame(
        [
            _late("shot-1-1-0", lag=0.6),
            _late("shot-1-1-1", lag=3.0),
            _late("shot-1-2-3", lag=0.2, held=False),  # not held: out of the late ranking
            _late("shot-1-2-4", lag=0.4, advantage=MIN_RANK_ADVANTAGE / 2),  # too short
            _late("shot-1-4-6", lag=1.4),
            _summary("shot-1-3-5"),
        ],
        schema=SUMMARY_SCHEMA,
    )
    return decisions, summaries


def test_rankings_exclude_low_confidence() -> None:
    decisions, summaries = _synthetic()
    worst, best, late, n_low = rank_tables(decisions, summaries, PLAYERS, GAMES, n=10)
    assert n_low == 1
    for table in (worst, best, late):
        assert "shot-1-1-1" not in table["shot_id"].to_list()
        assert "shot-1-1-2" not in table["shot_id"].to_list()  # excluded
        assert "shot-1-3-5" not in table["shot_id"].to_list()  # good_read null
    assert worst["shot_id"].to_list()[:2] == ["shot-1-1-0", "shot-1-4-6"]
    assert worst["rank"].to_list() == list(range(1, worst.height + 1))
    assert best["shot_id"].to_list() == ["shot-1-2-3", "shot-1-2-4"]
    assert best["margin"].to_list() == pytest.approx([0.5, 0.2])
    assert late["shot_id"].to_list() == ["shot-1-4-6", "shot-1-1-0"]  # by lag desc
    row = worst.row(0, named=True)
    assert row["shooter"] == "Ana Uno" and row["best_alt_player"] == "Bea Dos"
    assert row["team"] == "Locales" and row["game_label"] == "Locales–Visitantes"
    assert row["period"] == 1 and row["headline_es"] == "titular shot-1-1-0"
    assert late.row(0, named=True)["window_handler"] == "Ana Uno"
    assert late["window_peak_value"].to_list() == pytest.approx([1.4, 1.4])
    top1 = rank_tables(decisions, summaries, PLAYERS, GAMES, n=1)
    assert [t.height for t in top1[:3]] == [1, 1, 1]


def test_rank_tables_without_names() -> None:
    decisions, summaries = _synthetic()
    worst, _, _, _ = rank_tables(decisions, summaries, None, None, n=3)
    row = worst.row(0, named=True)
    assert row["shooter"] == "10" and row["best_alt_player"] == "11"
    assert row["game_label"] == "1"


def test_reel_never_renders_excluded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    decisions, summaries = _synthetic()
    rendered: list[str] = []

    def fake_render(_aligner: Any, decision: Any, *_a: Any, **kw: Any) -> Path:
        rendered.append(decision.shot_id)
        out: Path = _a[2]
        out.write_bytes(b"GIF89a")
        return out

    def fake_decision(shot_id: str, table: pl.DataFrame, _options: Any) -> Any:
        row = table.filter(pl.col("shot_id") == shot_id).row(0, named=True)
        assert row["rule"] != "excluded"
        return SimpleNamespace(shot_id=shot_id, decision_frame=row["decision_frame"])

    monkeypatch.setattr(reel_module, "load_decisions", lambda g, s: decisions)
    monkeypatch.setattr(reel_module, "load_curve_summaries", lambda g, s: summaries)
    monkeypatch.setattr(reel_module, "load_decision_options", lambda g, s: None)
    monkeypatch.setattr(reel_module, "load_curves", lambda g, s: pl.DataFrame())
    monkeypatch.setattr(reel_module, "players_table", lambda s: PLAYERS)
    monkeypatch.setattr(reel_module, "_games_table", lambda s: GAMES)
    monkeypatch.setattr(reel_module, "Aligner", lambda g, s: object())
    monkeypatch.setattr(reel_module, "decision_from_tables", fake_decision)
    monkeypatch.setattr(reel_module, "curve_of_shot", lambda sid, c, s: (c, None))
    monkeypatch.setattr(reel_module, "render_clip", fake_render)
    settings = Settings(data_dir=tmp_path, build_dir=tmp_path / "build")
    index = build_reel(settings, [1], n=10, out_dir=tmp_path / "reel", fps=6)
    assert "shot-1-1-2" not in rendered and "shot-1-1-1" not in rendered
    assert sorted(set(rendered)) == ["shot-1-1-0", "shot-1-2-3", "shot-1-2-4", "shot-1-4-6"]
    assert "shot-1-1-2" not in index.read_text()


def test_late_clip_before_seconds() -> None:
    from ventaja.reel import late_before_s

    assert late_before_s(decision_frame=500, window_start=490) == 3.0  # the default floor
    assert late_before_s(decision_frame=500, window_start=400) == pytest.approx(5.0)
    assert late_before_s(decision_frame=500, window_start=0) == 8.0  # the cap


# --- fixture game --------------------------------------------------------------------------


def test_rankings_filters_and_orders(fixture_curves_built: Settings) -> None:
    worst, best, late, n_low = rankings(fixture_curves_built, [GAME_ID], n=5)
    assert 0 < worst.height <= 5
    assert worst["cost"].is_sorted(descending=True)
    assert (worst["confidence"] >= MIN_RANK_CONFIDENCE).all()
    assert (best["good_read"] == True).all()  # noqa: E712
    assert best["margin"].is_sorted(descending=True)
    assert (late["held_to_decision"] == True).all()  # noqa: E712
    assert (late["advantage_seconds"] >= MIN_RANK_ADVANTAGE).all()
    assert late["release_lag_seconds"].is_sorted(descending=True)
    assert n_low >= 0
    for table in (worst, best, late):
        assert "headline_es" in table.columns and (table["rule"] != "excluded").all()


def test_build_reel_writes_index_and_gifs(fixture_curves_built: Settings, tmp_path: Path) -> None:
    out = tmp_path / "reel"
    worst, best, late, _ = rankings(fixture_curves_built, [GAME_ID], n=2)
    index = build_reel(fixture_curves_built, [GAME_ID], n=2, out_dir=out, fps=6)
    assert index == out / "index.md"
    gifs = sorted(p.name for p in out.glob("*.gif"))
    assert len(gifs) == worst.height + best.height + late.height
    assert sum("-worst-" in g for g in gifs) == worst.height
    text = index.read_text()
    for heading in ("## Peores decisiones", "## Mejores lecturas", "## Momentos perdidos"):
        assert heading in text
    for g in gifs:
        assert f"]({g})" in text


def test_reel_cli(
    fixture_curves_built: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(fixture_curves_built.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(fixture_curves_built.build_dir))
    result = CliRunner().invoke(app, ["reel", "rankings", "--game", str(GAME_ID), "--n", "3"])
    assert result.exit_code == 0, result.output
    assert "Peores decisiones" in result.output and "Momentos perdidos" in result.output
    none = CliRunner().invoke(app, ["reel", "rankings"])
    assert none.exit_code == 2
