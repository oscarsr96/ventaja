"""Tests for the court drawing, the possession animator and the review kit."""

import warnings
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from ventaja.cli import app
from ventaja.config import Settings
from ventaja.decision.align import Aligner
from ventaja.decision.cost import decide
from ventaja.value.model import ValueModel
from ventaja.value.priors import Priors
from ventaja.viz.animate import render_shot_gif, select_frames
from ventaja.viz.court import draw_half_court
from ventaja.viz.kit import allocate, review_kit
from ventaja.viz.text import format_option_table

GAME_ID = 114243
SHOT_ID = "shot-114243-1-0"


def test_draw_half_court_sets_offense_half() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    draw_half_court(ax)
    assert ax.get_xlim() == (-47.0, 0.0)
    assert ax.get_ylim() == (-25.0, 25.0)
    assert ax.get_aspect() == 1.0
    assert not ax.axison
    assert len(ax.patches) >= 5  # hoop, RA, key, free-throw circle, three-point arc
    plt.close(fig)


def test_format_option_table_marks_shooter_and_best_alternative(
    built_fixture: Settings, fixture_priors: Priors, trained_fixture_model: ValueModel
) -> None:
    d = decide(Aligner(GAME_ID, built_fixture), SHOT_ID, fixture_priors, trained_fixture_model)
    assert d is not None
    names = {d.shooter_id: "Ana Shooter"}
    table = format_option_table(
        d.options, shooter_id=d.shooter_id, best_alt_player_id=d.best_alt_player_id, names=names
    )
    lines = table.splitlines()
    assert len(lines) == 1 + len(d.options)
    assert "player_id" in lines[0] and "name" in lines[0]
    assert sum(line.startswith("*") for line in lines) == 1
    assert sum(line.startswith(">") for line in lines) == 1
    assert "Ana Shooter" in next(line for line in lines if line.startswith("*"))
    plain = format_option_table(d.options, shooter_id=d.shooter_id, best_alt_player_id=None)
    assert "name" not in plain.splitlines()[0]
    assert not any(line.startswith(">") for line in plain.splitlines())


def test_allocate_is_proportional_with_a_floor_of_one() -> None:
    counts = {"gather": 9, "last_dribble": 3, "touch_start": 4}
    assert allocate(counts, 3) == {"gather": 1, "last_dribble": 1, "touch_start": 1}
    big = allocate({"gather": 700, "last_dribble": 200, "touch_start": 100}, 20)
    assert big == {"gather": 14, "last_dribble": 4, "touch_start": 2}
    assert allocate({"gather": 2, "last_dribble": 0, "touch_start": 1}, 10) == {
        "gather": 2,
        "last_dribble": 0,
        "touch_start": 1,
    }
    assert sum(allocate({"gather": 50, "last_dribble": 1, "touch_start": 1}, 3).values()) == 3


def test_select_frames_keeps_one_possession_and_the_decision_frame(
    built_fixture: Settings,
) -> None:
    aligner = Aligner(GAME_ID, built_fixture)
    window = aligner.window(3885 - 75, 3895 + 25)
    frames = select_frames(window, 3885, fps=5)
    assert 3885 in [s.frame_idx for s in frames]
    assert len({s.possession_id for s in frames}) == 1
    assert all((s.frame_idx - 3885) % 5 == 0 for s in frames)


def test_render_shot_gif_writes_file(
    built_fixture: Settings,
    fixture_priors: Priors,
    trained_fixture_model: ValueModel,
    tmp_path: Path,
) -> None:
    a = Aligner(GAME_ID, built_fixture)
    d = decide(a, SHOT_ID, fixture_priors, trained_fixture_model)
    assert d is not None
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = render_shot_gif(a, d, tmp_path / "x.gif", before_s=1.0, after_s=0.2, fps=6)
    assert out.exists() and out.stat().st_size > 10_000
    shown = select_frames(a.window(d.decision_frame - 25, d.release_frame + 5), 3885, fps=6)
    durations = []
    with Image.open(out) as gif:
        for i in range(getattr(gif, "n_frames", 1)):
            gif.seek(i)
            durations.append(gif.info["duration"])
    # every selected frame once, the decision frame 6 times (held 1 s); Pillow may merge
    # identical consecutive frames into one longer frame, so compare total duration
    expected_ms = (len(shown) - 1 + 6) * 1000 / 6
    assert abs(sum(durations) - expected_ms) < 0.05 * expected_ms


def test_review_kit_writes_markdown_and_gifs(
    built_fixture: Settings,
    fixture_priors: Priors,
    trained_fixture_model: ValueModel,
    tmp_path: Path,
) -> None:
    out = review_kit(
        built_fixture,
        [GAME_ID],
        n=3,
        seed=1,
        out_dir=tmp_path,
        model=trained_fixture_model,
        priors=fixture_priors,
        before_s=0.4,
        after_s=0.1,
        fps=5,
    )
    assert out == tmp_path / "review.md"
    md = out.read_text()
    assert md.count("Frame de decisión") == 3 and len(list(tmp_path.glob("*.gif"))) == 3
    assert md.count("Opciones valoradas: ok / mal → ") == 3
    assert md.count("Comentario: ") == 3
    assert "seed 1" in md
    for rule in ("gather", "last_dribble", "touch_start"):
        assert f"regla {rule}" in md
    sections = [line for line in md.splitlines() if line.startswith("## ")]
    assert [s.split(". ")[0] for s in sections] == ["## 1", "## 2", "## 3"]
    for s in sections:
        assert f"![{s.split(' ')[-1]}]({s.split(' ')[-1]}.gif)" in md
    again = review_kit(
        built_fixture,
        [GAME_ID],
        n=3,
        seed=1,
        out_dir=tmp_path / "again",
        model=trained_fixture_model,
        priors=fixture_priors,
        before_s=0.4,
        after_s=0.1,
        fps=5,
    )
    assert sections == [line for line in again.read_text().splitlines() if line.startswith("## ")]


def test_cli_review_sample(
    built_fixture: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(built_fixture.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(built_fixture.build_dir))
    result = CliRunner().invoke(
        app, ["review", "sample", "--game", str(GAME_ID), "--n", "1", "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert str(tmp_path / "review.md") in result.output and "1 GIF" in result.output


def test_cli_review_sample_reports_errors(
    fixture_settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(fixture_settings.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(tmp_path / "empty"))
    result = CliRunner().invoke(
        app, ["review", "sample", "--game", str(GAME_ID), "--out", str(tmp_path / "o")]
    )
    assert result.exit_code == 1 and "error:" in result.output
