"""Tests for the rule-based profile phrase."""

import random
from typing import Any

import pytest

from ventaja.profile.phrase import (
    ALT_NAMES_EN,
    ALT_NAMES_ES,
    BUCKET_NAMES_EN,
    BUCKET_NAMES_ES,
    ZONE_NAMES_EN,
    ZONE_NAMES_ES,
    profile_phrase,
)
from ventaja.value.params import ALT_TYPES, CLOCK_BUCKETS

ZONES = ("restricted_area", "paint_non_ra", "mid_range", "corner_3", "above_break_3")
BANNED = (
    "malo",
    "mala",
    "error",
    "culpa",
    "egoísta",
    "egoista",
    "bad",
    "mistake",
    "fault",
    "selfish",
)

LEAGUE: dict[str, Any] = {"mean_cost": 0.2, "good_read_share": 0.4, "late_held_share": 0.15}


def row_with(season: bool = False, **overrides: Any) -> dict[str, Any]:
    """A full neutral row (every key present); ``overrides`` set the case under test."""
    row: dict[str, Any] = {
        "player_id": 1,
        "n_shots": 30,
        "n_readable": 30,
        "mean_cost": 0.2,
        "good_read_share": 0.4,
        "late_held_share": 0.15,
        "ignored_alt": None,
        "n_with_summary": 30,
        "n_late_held": 4,
    }
    for label, _, _ in CLOCK_BUCKETS:
        row[f"cost_{label}"] = 0.2
        row[f"n_{label}"] = 10
    for alt in ALT_TYPES:
        row[f"n_alt_{alt}"] = 0
        row[f"cost_alt_{alt}"] = None
    if season:
        row |= {
            "season_attempts": 400,
            "season_cns_share": 0.3,
            "season_contested_share": 0.2,
        }
        for z in ZONES:
            row[f"shift_{z}"] = 0.0
    row |= overrides
    return row


def test_small_sample_phrase() -> None:
    text = profile_phrase(
        row_with(n_readable=3, mean_cost=0.5, ignored_alt="post", n_alt_post=5), LEAGUE
    )
    assert text.startswith("Con 3 tiros valorados la muestra es pequeña")
    assert "deja pasar" not in text
    assert text.endswith(".")


def test_small_sample_singular_and_clock_rule() -> None:
    assert profile_phrase(row_with(n_readable=1), LEAGUE).startswith("Con 1 tiro valorado la")
    row = row_with(n_readable=6, **{"n_24-14": 2, "n_14-6": 2, "n_6-0": 0, "cost_6-0": 0.9})
    row["cost_24-14"] = 0.1
    row["cost_14-6"] = 0.4
    text = profile_phrase(row, LEAGUE)
    assert "mucho reloj" not in text
    assert "reloj medio" in text
    assert "elige bien" not in text and "decide en la media" not in text


def test_good_reader() -> None:
    text = profile_phrase(row_with(good_read_share=0.5), LEAGUE)
    assert text == "Elige bien el tiro."


def test_average_reader() -> None:
    assert profile_phrase(row_with(), LEAGUE) == "Decide en la media de la liga."


def test_leaves_passes_and_names_alternative() -> None:
    row = row_with(mean_cost=0.27, ignored_alt="open_corner", n_alt_open_corner=4)
    text = profile_phrase(row, LEAGUE)
    assert "Suele tener un pase mejor disponible" in text
    assert "la opción que más deja pasar es la esquina abierta" in text
    assert text[0].isupper()


def test_alternative_needs_minimum() -> None:
    text = profile_phrase(row_with(ignored_alt="post", n_alt_post=2), LEAGUE)
    assert "opción" not in text


def test_late_tendency() -> None:
    text = profile_phrase(row_with(late_held_share=0.3), LEAGUE)
    assert "tiende a tirar cuando la ventaja ya se ha esfumado" in text
    assert "tiende" not in profile_phrase(row_with(late_held_share=0.2), LEAGUE)


def test_clock_rule_picks_worst_bucket() -> None:
    row = row_with(**{"cost_24-14": 0.1, "cost_14-6": 0.2, "cost_6-0": 0.4})
    assert "su coste sube con el reloj agotándose" in profile_phrase(row, LEAGUE)
    # A bucket with a single readable shot is ignored.
    row["n_6-0"] = 1
    assert "su coste sube con reloj medio" in profile_phrase(row, LEAGUE)
    # Unknown or too-close costs: no rule.
    row["cost_14-6"] = None
    assert "coste" not in profile_phrase(row, LEAGUE)
    row = row_with(**{"cost_6-0": 0.23})
    assert "coste" not in profile_phrase(row, LEAGUE)


def test_season_sentence_zone_shift() -> None:
    row = row_with(season=True, shift_corner_3=0.2, shift_mid_range=0.16)
    text = profile_phrase(row, LEAGUE)
    assert text.count(".") == 2
    assert "En estos partidos tira más desde esquina que en su temporada." in text
    row = row_with(season=True, season_cns_share=0.65, season_contested_share=0.55)
    text = profile_phrase(row, LEAGUE)
    assert "Es sobre todo un tirador tras recepción" in text
    assert "la mayoría de sus tiros de temporada son con mano encima" in text


def test_no_season_block_no_second_sentence() -> None:
    row = row_with(shift_corner_3=0.5, season_cns_share=0.9)
    assert profile_phrase(row, LEAGUE).count(".") == 1
    row = row_with(season=True, season_attempts=None, shift_corner_3=0.5)
    assert profile_phrase(row, LEAGUE).count(".") == 1


def test_unknown_values_do_not_fire() -> None:
    row = row_with(good_read_share=None, mean_cost=None, late_held_share=None)
    text = profile_phrase(row, LEAGUE)
    assert "media" not in text and "tiende" not in text


def test_english_variant() -> None:
    row = row_with(
        season=True,
        good_read_share=0.5,
        late_held_share=0.3,
        ignored_alt="rim_cut",
        n_alt_rim_cut=5,
        shift_above_break_3=0.3,
        season_cns_share=0.7,
    )
    text = profile_phrase(row, LEAGUE, lang="en")
    assert text.startswith("Picks the shot well; the option he most often leaves is the rim cut")
    assert "tends to shoot once the advantage has faded" in text
    assert "In these games he shoots more from above-the-break three than over his season" in text
    assert "he is mostly a catch-and-shoot player" in text
    small = profile_phrase(row_with(n_readable=1), LEAGUE, lang="en")
    assert small.startswith("With 1 valued shot the sample is small")
    assert profile_phrase(row_with(n_readable=4), LEAGUE, lang="en").startswith(
        "With 4 valued shots"
    )


def test_name_dicts_cover_keys() -> None:
    assert set(ALT_NAMES_ES) == set(ALT_NAMES_EN) == set(ALT_TYPES)
    assert set(ZONE_NAMES_ES) == set(ZONE_NAMES_EN) == set(ZONES)
    labels = {label for label, _, _ in CLOCK_BUCKETS}
    assert set(BUCKET_NAMES_ES) == set(BUCKET_NAMES_EN) == labels


def _random_row(rng: random.Random, season: bool) -> dict[str, Any]:
    row = row_with(
        season=season,
        n_readable=rng.randint(0, 40),
        mean_cost=rng.uniform(0.0, 0.6),
        good_read_share=rng.uniform(0.0, 1.0),
        late_held_share=rng.uniform(0.0, 0.6),
        ignored_alt=rng.choice((*ALT_TYPES, None)),
    )
    for alt in ALT_TYPES:
        row[f"n_alt_{alt}"] = rng.randint(0, 8)
    for label, _, _ in CLOCK_BUCKETS:
        row[f"cost_{label}"] = rng.choice((None, rng.uniform(0.0, 0.8)))
        row[f"n_{label}"] = rng.randint(0, 6)
    if season:
        row["season_cns_share"] = rng.uniform(0.0, 1.0)
        row["season_contested_share"] = rng.uniform(0.0, 1.0)
        for z in ZONES:
            row[f"shift_{z}"] = rng.uniform(-0.4, 0.4)
    return row


def test_banned_words_never_appear() -> None:
    rng = random.Random(7)
    for i in range(50):
        row = _random_row(rng, season=i % 2 == 0)
        for lang in ("es", "en"):
            text = profile_phrase(row, LEAGUE, lang=lang).lower()  # type: ignore[arg-type]
            assert text.endswith(".")
            assert not [w for w in BANNED if w in text], text
    for names in (ALT_NAMES_ES, ALT_NAMES_EN, ZONE_NAMES_ES, ZONE_NAMES_EN):
        assert not [w for v in names.values() for w in BANNED if w in v.lower()]


@pytest.mark.parametrize("lang", ["es", "en"])
def test_never_empty(lang: str) -> None:
    empty = {"n_readable": 12}
    assert profile_phrase(empty, LEAGUE, lang=lang)  # type: ignore[arg-type]
