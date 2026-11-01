import gzip
import json

from ventaja.config import Settings


def test_fixture_tracking_is_a_small_excerpt(fixture_settings: Settings) -> None:
    path = fixture_settings.raw_path("matches/114243/114243_tracking_data.jsonl.gz")
    assert path.stat().st_size < 2_000_000
    with gzip.open(path, "rt") as fh:
        n = sum(1 for _ in fh)
    assert 1_500 < n < 3_000


def test_fixture_events_are_complete(fixture_settings: Settings) -> None:
    path = fixture_settings.raw_path("matches/114243/114243_dynamic_events.json")
    events = json.loads(path.read_text())
    assert len(events["shots"]) == 159
    assert len(events) == 20
