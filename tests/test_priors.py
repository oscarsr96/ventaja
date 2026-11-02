import polars as pl
import polars.selectors as cs

from ventaja.config import Settings
from ventaja.data.load import load_aggregates
from ventaja.value.params import K_SHRINK
from ventaja.value.priors import Priors


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
