import shutil
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from ventaja.cli import app
from ventaja.config import FPS, Settings
from ventaja.data import load as load_module
from ventaja.data.duck import connect
from ventaja.data.load import (
    load_curves,
    load_decisions,
    load_frames,
    load_plays,
    load_roster,
    play_files,
)
from ventaja.decision.align import Aligner
from ventaja.decision.frames import (
    FRAME_SCHEMA,
    PLAY_SCHEMA,
    ROSTER_SCHEMA,
    _update_roster,
    build_frames,
    build_plays,
    snapshot_from_frame,
)
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
    assert sorted(p.name for p in out.iterdir()) == ["114243.parquet", "plays", "roster.parquet"]
    assert CliRunner().invoke(app, ["frames", "build"]).exit_code == 2


def test_build_frames_out_dir(fixture_frames_built: Settings, tmp_path: Path) -> None:
    path = build_frames(GAME_ID, fixture_frames_built, out_dir=tmp_path)
    assert path == tmp_path / "114243.parquet"
    assert pl.read_parquet(path).equals(load_frames(GAME_ID, fixture_frames_built))


def test_roster_written_and_deduplicated(fixture_frames_built: Settings, tmp_path: Path) -> None:
    build_frames(GAME_ID, fixture_frames_built, out_dir=tmp_path)
    build_frames(GAME_ID, fixture_frames_built, out_dir=tmp_path)  # rebuild: no duplicates
    roster = pl.read_parquet(tmp_path / "roster.parquet")
    assert dict(roster.schema) == ROSTER_SCHEMA
    frames = load_frames(GAME_ID, fixture_frames_built)
    players = set(frames["player_id"].drop_nulls())
    assert set(roster["player_id"]) == players
    assert roster["player_id"].is_unique().all()
    assert roster["name"].null_count() == 0 and roster["team"].null_count() == 0


def test_roster_is_not_a_main_table(fixture_frames_built: Settings, tmp_path: Path) -> None:
    settings = Settings(data_dir=fixture_frames_built.data_dir, build_dir=tmp_path)
    (tmp_path / "frames").mkdir()
    build_frames(GAME_ID, fixture_frames_built, out_dir=tmp_path / "frames")
    assert [p.name for p in load_module.frame_files(settings)] == ["114243.parquet"]
    assert load_roster(settings).height > 0


def test_load_roster_missing_hints_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(load_module, "ARTIFACTS_DIR", tmp_path)
    settings = Settings(data_dir=tmp_path / "raw", build_dir=tmp_path / "build")
    with pytest.raises(DataNotFoundError, match="frames build"):
        load_roster(settings)


def test_roster_dedups_player_listed_with_two_teams(
    fixture_frames_built: Settings, tmp_path: Path
) -> None:
    frames = load_frames(GAME_ID, fixture_frames_built)
    twice = frames.filter(pl.col("player_id").is_not_null()).head(1)
    traded = twice.with_columns(pl.col("team_id") + 1)
    _update_roster(pl.concat([frames, traded]), fixture_frames_built, tmp_path)  # fresh build
    roster = pl.read_parquet(tmp_path / "roster.parquet")
    assert roster["player_id"].is_unique().all()


def test_build_plays_covers_the_possession(fixture_curves_built: Settings) -> None:
    path = build_plays(GAME_ID, fixture_curves_built)
    plays = pl.read_parquet(path)
    assert dict(plays.schema) == PLAY_SCHEMA
    decisions = _valued(fixture_curves_built)
    curves = load_curves(GAME_ID, fixture_curves_built)
    assert set(plays["shot_id"]) == set(curves["shot_id"]) & set(decisions["shot_id"])
    one = plays.filter(pl.col("shot_id") == SHOT_ID)
    release = decisions.filter(pl.col("shot_id") == SHOT_ID)["release_frame"][0]
    first = curves.filter(pl.col("shot_id") == SHOT_ID)["frame_idx"].min()
    assert one["frame_idx"].min() == first
    assert one["frame_idx"].max() <= release + FPS
    assert abs(one.filter(pl.col("frame_idx") == release)["t"][0]) < 1e-6
    per_frame = one.group_by("frame_idx").len()
    assert per_frame["len"].max() <= 11
    assert set(one["side"]) == {"offense", "defense", "ball"}
    ball = one.filter(pl.col("side") == "ball")
    assert ball["player_id"].null_count() == ball.height
    assert load_plays(GAME_ID, fixture_curves_built).height == plays.height


def test_build_plays_decision_frame_is_inside_the_play(fixture_curves_built: Settings) -> None:
    plays = pl.read_parquet(build_plays(GAME_ID, fixture_curves_built))
    ranges = {
        k[0]: (v["frame_idx"].min(), v["frame_idx"].max())
        for k, v in plays.partition_by("shot_id", as_dict=True).items()
    }
    assert ranges
    for shot_id, decision, release in (
        _valued(fixture_curves_built)
        .select("shot_id", "decision_frame", "release_frame")
        .iter_rows()
    ):
        if shot_id in ranges:
            first, last = ranges[shot_id]
            assert first <= decision <= release <= last, shot_id


def test_build_plays_cuts_the_next_possession(fixture_curves_built: Settings) -> None:
    plays = pl.read_parquet(build_plays(GAME_ID, fixture_curves_built))
    aligner = Aligner(GAME_ID, fixture_curves_built)
    spilled = 0
    for shot_id, release in (
        _valued(fixture_curves_built).select("shot_id", "release_frame").iter_rows()
    ):
        frames = plays.filter(pl.col("shot_id") == shot_id)["frame_idx"].unique()
        if frames.is_empty():
            continue
        possession = aligner.snapshot_for_shot(shot_id, decision=True).possession_id
        tail = list(aligner.window(frames.min(), release + FPS))
        other = {s.frame_idx for s in tail if s.possession_id != possession}
        spilled += bool(other)
        assert not other & set(frames.to_list()), shot_id  # no frame of another possession
        kept = {s.frame_idx for s in tail if s.possession_id == possession}
        decision = _valued(fixture_curves_built).filter(pl.col("shot_id") == shot_id)[
            "decision_frame"
        ][0]
        assert set(frames.to_list()) == kept | {decision}, shot_id
    assert spilled > 0  # the fixture has a shot whose tail leaves the possession


def test_build_plays_needs_curves(
    fixture_curves_built: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(load_module, "ARTIFACTS_DIR", tmp_path / "no-artifacts")
    build = tmp_path / "build"
    shutil.copytree(
        fixture_curves_built.build_dir, build, ignore=shutil.ignore_patterns("curves", "plays")
    )
    settings = Settings(data_dir=fixture_curves_built.data_dir, build_dir=build)
    with pytest.raises(DataNotFoundError, match="curves build"):
        build_plays(GAME_ID, settings)


def test_frames_build_cli_writes_plays_unless_skipped(
    fixture_curves_built: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(fixture_curves_built.data_dir))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(fixture_curves_built.build_dir))
    runner = CliRunner()
    out = tmp_path / "frames"
    result = runner.invoke(app, ["frames", "build", "--game", str(GAME_ID), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "plays:" in result.output
    assert (tmp_path / "plays" / f"{GAME_ID}.parquet").exists()
    other = tmp_path / "other"
    result = runner.invoke(
        app, ["frames", "build", "--game", str(GAME_ID), "--out", str(other), "--no-plays"]
    )
    assert result.exit_code == 0, result.output
    assert (other / f"{GAME_ID}.parquet").exists()
    assert not (other / "plays").exists() and not (tmp_path / "other" / "plays").exists()


def test_packaged_plays_are_bounded(tmp_path: Path) -> None:
    clean = Settings(data_dir=tmp_path / "raw", build_dir=tmp_path / "build")
    files = play_files(clean)
    assert len(files) == 10 and sum(p.stat().st_size for p in files) <= 30_000_000
    plays = load_plays(191313, clean)
    assert plays.filter(pl.col("shot_id") == "shot-191313-1-31").height > 11 * 25 * 3
