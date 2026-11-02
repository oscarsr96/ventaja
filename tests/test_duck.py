from pathlib import Path

import polars as pl
from typer.testing import CliRunner

from ventaja.cli import app
from ventaja.config import Settings
from ventaja.data import load as load_module
from ventaja.data.duck import connect


def test_duck_views_over_built_parquet(built_fixture: Settings) -> None:
    con = connect(built_fixture)
    assert con.sql("select count(*) from shots").fetchall()[0][0] == 159
    assert con.sql("select count(distinct frame_idx) from tracking").fetchall()[0][0] == 1944


def test_duck_join_shot_to_tracking_frame(built_fixture: Settings) -> None:
    con = connect(built_fixture)
    n = con.sql(
        """
        select count(*) from shots s
        join tracking t on t.frame_idx = s.start_frame and t.player_id = s.shooter_id
        """
    ).fetchall()[0][0]
    assert n == 20


def test_duck_missing_tables_are_skipped(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(load_module, "ARTIFACTS_DIR", tmp_path / "no-artifacts")
    con = connect(Settings(data_dir=tmp_path, build_dir=tmp_path / "empty"))
    assert con.sql("select count(*) from duckdb_views() where not internal").fetchall()[0][0] == 0


def test_duck_union_by_name_handles_null_dtype(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, build_dir=tmp_path / "build")
    for game_id, shot_id in ((1, pl.Series("shot_id", [None, None], dtype=pl.Null)), (2, None)):
        path = settings.events_parquet(game_id, "fouls")
        path.parent.mkdir(parents=True)
        shots = shot_id if shot_id is not None else pl.Series("shot_id", ["a", "b"])
        pl.DataFrame({"game_id": [game_id, game_id], "shot_id": shots}).write_parquet(path)
    con = connect(settings)
    rows = con.sql("select game_id, count(*) from fouls group by 1 order by 1").fetchall()
    assert rows == [(1, 2), (2, 2)]


def test_cli_sql_prints_rows(built_fixture: Settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(built_fixture.build_dir))
    result = CliRunner().invoke(app, ["sql", "select 1 as one"])
    assert result.exit_code == 0
    assert "one" in result.output


def test_cli_sql_csv_and_error(built_fixture: Settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(built_fixture.build_dir))
    ok = CliRunner().invoke(app, ["sql", "select 1 as one, 2 as two", "--csv"])
    assert ok.exit_code == 0
    assert ok.output.splitlines() == ["one,two", "1,2"]
    bad = CliRunner().invoke(app, ["sql", "select * from nope"])
    assert bad.exit_code == 1


def test_cli_sql_join_with_duplicate_column_names(built_fixture: Settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(built_fixture.build_dir))
    result = CliRunner().invoke(
        app,
        [
            "sql",
            "select * from shots s join tracking t on t.frame_idx = s.start_frame "
            "and t.player_id = s.shooter_id",
            "--csv",
        ],
    )
    assert result.exit_code == 0
    assert "game_id_1" in result.output.splitlines()[0]


def test_cli_sql_statement_without_rows(built_fixture: Settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(built_fixture.build_dir))
    result = CliRunner().invoke(app, ["sql", "create table t as select 1 as a"])
    assert result.exit_code == 0


def test_cli_sql_corrupt_parquet_exits_1(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "build" / "events" / "1" / "shots.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"garbage")
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(tmp_path / "build"))
    result = CliRunner().invoke(app, ["sql", "select count(*) from shots"])
    assert result.exit_code == 1
    assert "error:" in result.output
