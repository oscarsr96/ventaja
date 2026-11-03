from pathlib import Path
from typing import get_args

import polars as pl
import polars.selectors as cs
import pytest

from ventaja.config import Settings
from ventaja.data.load import load_aggregates
from ventaja.errors import DataNotFoundError
from ventaja.value.params import K_SHRINK
from ventaja.value.priors import Priors
from ventaja.value.zones import Zone


def _players(settings: Settings) -> pl.DataFrame:
    return (
        load_aggregates("shots", settings)
        .filter(pl.col("team_id").is_not_null())
        .select("player_id", cs.numeric().exclude("player_id", "team_id"))
        .group_by("player_id")
        .sum()
    )


def test_prior_shrinks_toward_league(built_fixture: Settings) -> None:
    p = Priors.from_settings(built_fixture)
    league = p.league_rate("above_break_3")
    assert 0.25 < league < 0.45
    assert p.player_rate(999999, "above_break_3") == league
    best = (
        _players(built_fixture)
        .sort("zone_above_break_3_attempts", descending=True)
        .row(0, named=True)
    )
    raw = best["zone_above_break_3_mades"] / best["zone_above_break_3_attempts"]
    shrunk = p.player_rate(best["player_id"], "above_break_3")
    assert abs(shrunk - league) < abs(raw - league) + 1e-9
    expected = (best["zone_above_break_3_mades"] + K_SHRINK * league) / (
        best["zone_above_break_3_attempts"] + K_SHRINK
    )
    assert shrunk == expected


def test_prior_zero_attempts_zone(built_fixture: Settings) -> None:
    p = Priors.from_settings(built_fixture)
    zero = _players(built_fixture).filter(pl.col("zone_corner_3_attempts") == 0)
    assert zero.height > 0
    pid = zero["player_id"][0]
    assert p.player_rate(pid, "corner_3") == p.league_rate("corner_3")


def test_league_rate_zero_attempts_falls_back_to_overall(built_fixture: Settings) -> None:
    p = Priors.from_settings(built_fixture)
    assert 0.0 < p.league_rate("far") < 1.0
    empty = Priors(
        pl.DataFrame(
            {
                "player_id": [1],
                "attempts": [10],
                "mades": [4],
                "zone_far_attempts": [0],
                "zone_far_mades": [0],
            }
        )
    )
    assert empty.league_rate("far") == 0.4


def test_contest_rates(built_fixture: Settings) -> None:
    p = Priors.from_settings(built_fixture)
    assert 0.0 < p.league_contest_rate("open") < 1.0
    assert p.player_contest_rate(999999, "blocked") == p.league_contest_rate("blocked")
    best = _players(built_fixture).sort("cl_open_attempts", descending=True).row(0, named=True)
    league = p.league_contest_rate("open")
    expected = (best["cl_open_mades"] + K_SHRINK * league) / (best["cl_open_attempts"] + K_SHRINK)
    assert p.player_contest_rate(best["player_id"], "open") == expected


def test_save_load_round_trip(built_fixture: Settings, tmp_path: Path) -> None:
    priors = Priors.from_settings(built_fixture)
    priors.save(tmp_path / "sub" / "priors.parquet")
    loaded = Priors.load(tmp_path / "sub" / "priors.parquet")
    players = list(priors._players["player_id"][:5])
    for zone in get_args(Zone):
        assert loaded.league_rate(zone) == priors.league_rate(zone)
        for player in players:
            assert loaded.player_rate(player, zone) == priors.player_rate(player, zone)
    for level in ("open", "light", "average", "plus", "blocked"):
        assert loaded.league_contest_rate(level) == priors.league_contest_rate(level)
        for player in players:
            assert loaded.player_contest_rate(player, level) == priors.player_contest_rate(
                player, level
            )


def test_default_missing_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ventaja.value.priors.DEFAULT_PRIORS_PATH", tmp_path / "nope.parquet")
    with pytest.raises(DataNotFoundError, match="ventaja model train"):
        Priors.default()


def test_packaged_priors_load() -> None:
    assert Priors.default().league_rate(get_args(Zone)[0]) > 0
