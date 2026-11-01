from pathlib import Path

import pytest

from ventaja.config import Settings


@pytest.fixture
def fixture_settings(tmp_path: Path) -> Settings:
    """Settings pointing at the committed game 114243 fixture, building into tmp_path."""
    return Settings(
        data_dir=Path(__file__).parent / "fixtures" / "114243",
        build_dir=tmp_path / "build",
    )


FIXTURE_SHOT_COUNT = 20
