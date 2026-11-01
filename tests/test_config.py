from pathlib import Path

import pytest

from ventaja.config import Settings
from ventaja.data.catalog import files_for
from ventaja.errors import VentajaError


def test_defaults_point_to_user_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VENTAJA_DATA_DIR", raising=False)
    monkeypatch.delenv("VENTAJA_BUILD_DIR", raising=False)
    s = Settings.from_env()
    assert s.data_dir == Path.home() / ".cache" / "ventaja" / "raw"
    assert s.build_dir == Path.home() / ".cache" / "ventaja" / "build"


def test_env_overrides_and_build_dir_is_outside_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", str(tmp_path / "clone" / "data"))
    monkeypatch.setenv("VENTAJA_BUILD_DIR", str(tmp_path / "build"))
    s = Settings.from_env()
    assert s.data_dir == tmp_path / "clone" / "data"
    assert not s.build_dir.is_relative_to(s.data_dir)


def test_path_helpers_follow_layout(tmp_path: Path) -> None:
    s = Settings(data_dir=tmp_path / "raw", build_dir=tmp_path / "build")
    assert s.raw_path("matches.json") == tmp_path / "raw" / "matches.json"
    assert s.events_parquet(1, "shots") == tmp_path / "build" / "events" / "1" / "shots.parquet"
    assert s.tracking_parquet(1) == tmp_path / "build" / "tracking" / "1.parquet"


def test_catalog_for_one_game_has_eight_files_and_lfs_only_for_tracking() -> None:
    files = files_for([114243])
    assert len(files) == 5 + 3
    lfs = [f for f in files if f.lfs]
    assert [f.relpath for f in lfs] == ["matches/114243/114243_tracking_data.jsonl.gz"]
    assert lfs[0].url.startswith(
        "https://media.githubusercontent.com/media/SkillCorner/opendata-basketball/main/data/"
    )


def test_catalog_without_tracking_skips_lfs() -> None:
    assert not any(f.lfs for f in files_for([114243], tracking=False))


def test_catalog_all_games_defaults_to_ten() -> None:
    assert sum(f.lfs for f in files_for(None)) == 10


def test_catalog_rejects_unknown_game() -> None:
    with pytest.raises(VentajaError, match="unknown game 999"):
        files_for([999])


def test_env_paths_expand_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTAJA_DATA_DIR", "~/x")
    monkeypatch.setenv("VENTAJA_BUILD_DIR", "~/y")
    s = Settings.from_env()
    assert s.data_dir == Path.home() / "x"
    assert s.build_dir == Path.home() / "y"
