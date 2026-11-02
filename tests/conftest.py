from collections.abc import Iterator
from pathlib import Path

import pytest

from ventaja.config import Settings
from ventaja.data.build import build_aggregates, build_events, build_meta, build_tracking
from ventaja.decision.align import Aligner
from ventaja.value.features import shot_rows
from ventaja.value.model import ValueModel, fit
from ventaja.value.priors import Priors

FIXTURE_DATA_DIR = Path(__file__).parent / "fixtures" / "114243"
FIXTURE_GAME_ID = 114243


@pytest.fixture
def fixture_settings(tmp_path: Path) -> Settings:
    """Settings pointing at the committed game 114243 fixture, building into tmp_path."""
    return Settings(data_dir=FIXTURE_DATA_DIR, build_dir=tmp_path / "build")


@pytest.fixture(scope="session")
def built_fixture(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Settings]:
    """Settings whose build dir already holds every built table of the fixture."""
    settings = Settings(data_dir=FIXTURE_DATA_DIR, build_dir=tmp_path_factory.mktemp("build"))
    build_events(FIXTURE_GAME_ID, settings)
    build_tracking(FIXTURE_GAME_ID, settings)
    build_meta(FIXTURE_GAME_ID, settings)
    build_aggregates(settings)
    yield settings


@pytest.fixture(scope="session")
def fixture_priors(built_fixture: Settings) -> Priors:
    """Season priors of the fixture's aggregates."""
    return Priors.from_settings(built_fixture)


@pytest.fixture(scope="session")
def trained_fixture_model(built_fixture: Settings, fixture_priors: Priors) -> ValueModel:
    """A toy value model fitted on the fixture's shots (tests only)."""
    return fit(shot_rows(Aligner(FIXTURE_GAME_ID, built_fixture), fixture_priors))


FIXTURE_SHOT_COUNT = 20
