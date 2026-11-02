from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from ventaja.cli import app
from ventaja.config import Settings
from ventaja.data import load as load_module
from ventaja.data.duck import connect
from ventaja.data.load import load_decisions, load_frames
from ventaja.decision.align import Aligner
from ventaja.decision.frames import FRAME_SCHEMA, build_frames, snapshot_from_frame
from ventaja.errors import DataNotFoundError, VentajaError

GAME_ID = 114243
SHOT_ID = "shot-114243-1-0"
VALUED_SHOTS = 17


def _valued(settings: Settings) -> pl.DataFrame:
    return load_decisions(GAME_ID, settings).filter(pl.col("rule") != "excluded")


def test_build_frames_fixture(fixture_frames_built: Settings) -> None:
    frames = load_frames(GAME_ID, fixture_frames_built)
    valued = _valued(fixture_frames_built)
    assert valued.height == VALUED_SHOTS
    assert frames.height == 11 * VALUED_SHOTS == 187
    assert dict(frames.schema) == FRAME_SCHEMA
    assert sorted(frames["shot_id"].unique()) == sorted(valued["shot_id"])
    counts = frames.group_by("shot_id").agg(
        n=pl.len(),
        offense=(pl.col("side") == "offense").sum(),
        defense=(pl.col("side") == "defense").sum(),
        ball=(pl.col("side") == "ball").sum(),
    )
    assert (counts["n"] == 11).all() and (counts["ball"] == 1).all()
    assert (counts["offense"] == 5).all() and (counts["defense"] == 5).all()
    ball = frames.filter(pl.col("side") == "ball")
    assert ball["player_id"].null_count() == ball.height == ball["team_id"].null_count()
    assert ball["pred_error"].null_count() == ball.height and ball["z"].null_count() == 0
    players = frames.filter(pl.col("side") != "ball")
    assert players["z"].null_count() == players.height
    assert players["player_id"].null_count() == 0


def test_snapshot_roundtrip(fixture_frames_built: Settings) -> None:
    aligner = Aligner(GAME_ID, fixture_frames_built)
    frames = load_frames(GAME_ID, fixture_frames_built)
    assert SHOT_ID in set(frames["shot_id"])  # the first shot of the fixture is valued
    for shot_id in frames["shot_id"].unique():
        rebuilt = snapshot_from_frame(frames.filter(pl.col("shot_id") == shot_id))
        expected = aligner.snapshot_for_shot(shot_id, decision=True)
        assert rebuilt == expected
        assert rebuilt.model_dump() == expected.model_dump()


def test_snapshot_from_frame_rejects_short_frame(fixture_frames_built: Settings) -> None:
    rows = load_frames(GAME_ID, fixture_frames_built).filter(pl.col("shot_id") == SHOT_ID)
    with pytest.raises(VentajaError, match="10 players"):
        snapshot_from_frame(rows.head(10))
    with pytest.raises(VentajaError):
        snapshot_from_frame(rows.filter(pl.col("side") != "ball"))
    with pytest.raises(VentajaError):
        snapshot_from_frame(rows.vstack(rows.filter(pl.col("side") == "ball")))


def test_load_frames_falls_back_to_artifacts(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, build_dir=tmp_path / "build")
    assert load_module.artifact_dir("frames", settings) == load_module.ARTIFACTS_DIR / "frames"
    frames = load_frames(191313, settings)
    assert frames.height > 0 and set(frames["game_id"]) == {191313}
    assert dict(frames.schema) == FRAME_SCHEMA
    files = load_module.frame_files(settings)
    assert len(files) == 10 and all(p.suffix == ".parquet" for p in files)
    with pytest.raises(DataNotFoundError, match="ventaja frames build --game 1"):
        load_frames(1, settings)


def test_frames_view_and_build_dir_wins(fixture_frames_built: Settings) -> None:
    con = connect(fixture_frames_built)
    assert con.sql("select count(*) from frames").fetchall() == [(187,)]
    assert load_module.frame_files(fixture_frames_built) == [
        fixture_frames_built.frames_parquet(GAME_ID)
    ]


def test_frames_cli_build(
    fixture_frames_built: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(fixture_frames_built.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(fixture_frames_built.build_dir))
    out = tmp_path / "cli"
    result = CliRunner().invoke(app, ["frames", "build", "--game", "114243", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "game 114243: 17 shots, 187 rows" in result.output
    assert [p.name for p in out.iterdir()] == ["114243.parquet"]
    assert CliRunner().invoke(app, ["frames", "build"]).exit_code == 2


def test_build_frames_out_dir(fixture_frames_built: Settings, tmp_path: Path) -> None:
    path = build_frames(GAME_ID, fixture_frames_built, out_dir=tmp_path)
    assert path == tmp_path / "114243.parquet"
    assert pl.read_parquet(path).equals(load_frames(GAME_ID, fixture_frames_built))
