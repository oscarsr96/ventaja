from collections.abc import Iterator
from pathlib import Path

import pytest

from ventaja.config import Settings
from ventaja.data.build import build_events

FIXTURE_DATA_DIR = Path(__file__).parent / "fixtures" / "114243"
FIXTURE_GAME_ID = 114243


@pytest.fixture
def fixture_settings(tmp_path: Path) -> Settings:
    """Settings pointing at the committed game 114243 fixture, building into tmp_path."""
    return Settings(data_dir=FIXTURE_DATA_DIR, build_dir=tmp_path / "build")


@pytest.fixture(scope="session")
def built_fixture(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Settings]:
    """Settings whose build dir already holds the built event tables of the fixture game."""
    settings = Settings(data_dir=FIXTURE_DATA_DIR, build_dir=tmp_path_factory.mktemp("build"))
    build_events(FIXTURE_GAME_ID, settings)
    yield settings


FIXTURE_SHOT_COUNT = 20
