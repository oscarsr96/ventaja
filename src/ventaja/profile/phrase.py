"""Rule-based profile phrase of a player card (spec section 9).

One or two descriptive sentences built from the flat player row and the league row. A missing
key or a ``None`` value means "unknown": a rule that needs it does not fire. The wording never
accuses; it only describes what the tracked games show.
"""

from collections.abc import Mapping
from typing import Any, Literal

from ventaja.value.params import (
    ALT_TYPES,
    CLOCK_BUCKETS,
    PROFILE_ALT_MIN,
    PROFILE_COST_DELTA,
    PROFILE_LATE_SHARE,
    PROFILE_MIN_SHOTS,
    PROFILE_READ_DELTA,
    PROFILE_SEASON_DELTA,
    PROFILE_ZONE_SHIFT,
)

__all__ = [
    "ALT_NAMES_EN",
    "ALT_NAMES_ES",
    "BUCKET_NAMES_EN",
    "BUCKET_NAMES_ES",
    "ZONE_NAMES_EN",
    "ZONE_NAMES_ES",
    "profile_phrase",
]

Lang = Literal["es", "en"]

ALT_NAMES_ES = {
    "rim_cut": "el corte al aro",
    "open_corner": "la esquina abierta",
    "extra_pass": "el pase extra",
    "post": "el poste",
    "other": "otra",
}
ALT_NAMES_EN = {
    "rim_cut": "the rim cut",
    "open_corner": "the open corner",
    "extra_pass": "the extra pass",
    "post": "the post",
    "other": "another",
}
ZONE_NAMES_ES = {
    "restricted_area": "zona restringida",
    "paint_non_ra": "pintura",
    "mid_range": "media distancia",
    "corner_3": "esquina",
    "above_break_3": "triple frontal",
}
ZONE_NAMES_EN = {
    "restricted_area": "restricted area",
    "paint_non_ra": "paint",
    "mid_range": "mid-range",
    "corner_3": "corner",
    "above_break_3": "above-the-break three",
}
BUCKET_NAMES_ES = {"24-14": "mucho reloj", "14-6": "reloj medio", "6-0": "el reloj agotándose"}
BUCKET_NAMES_EN = {
    "24-14": "plenty of clock",
    "14-6": "mid clock",
    "6-0": "the clock running out",
}

_TEXT: dict[Lang, dict[str, str]] = {
    "es": {
        "small_one": "Con {n} tiro valorado la muestra es pequeña",
        "small_many": "Con {n} tiros valorados la muestra es pequeña",
        "read_one": "Con {r} tiro legible de {n} valorados la muestra es pequeña",
        "read_many": "Con {r} tiros legibles de {n} valorados la muestra es pequeña",
        "good": "elige bien el tiro",
        "leaves": "suele tener un pase mejor disponible",
        "average": "decide en la media de la liga",
        "alt": "la opción que más deja pasar es {alt}",
        "late": "tiende a tirar cuando la ventaja ya se ha esfumado",
        "clock": "su coste sube con {bucket}",
        "shift": "en estos partidos tira más desde {zone} que en su temporada",
        "cns": "es sobre todo un tirador tras recepción",
        "contested": "la mayoría de sus tiros de temporada son con mano encima",
        "none": "no hay datos suficientes para describir su perfil",
    },
    "en": {
        "small_one": "With {n} valued shot the sample is small",
        "small_many": "With {n} valued shots the sample is small",
        "read_one": "With {r} readable shot of {n} valued the sample is small",
        "read_many": "With {r} readable shots of {n} valued the sample is small",
        "good": "picks the shot well",
        "leaves": "usually has a better pass available",
        "average": "decides at the league average",
        "alt": "the option he most often leaves is {alt}",
        "late": "tends to shoot once the advantage has faded",
        "clock": "his cost rises with {bucket}",
        "shift": "in these games he shoots more from {zone} than over his season",
        "cns": "he is mostly a catch-and-shoot player",
        "contested": "most of his season shots are contested",
        "none": "there is not enough data to describe the profile",
    },
}

_CLOCK_MIN_SHOTS = 2  # readable shots a clock bucket needs to be compared


def _num(source: Mapping[str, Any], key: str) -> float | None:
    value = source.get(key)
    return None if value is None else float(value)


def _sentence(fragments: list[str]) -> str:
    text = "; ".join(fragments)
    return text[0].upper() + text[1:] + "."


def _reading(row: Mapping[str, Any], league: Mapping[str, Any], t: dict[str, str]) -> str | None:
    """Rule 2: global reading against the league."""
    good, good_lg = _num(row, "good_read_share"), _num(league, "good_read_share")
    cost, cost_lg = _num(row, "mean_cost"), _num(league, "mean_cost")
    comparable = False
    if good is not None and good_lg is not None:
        comparable = True
        if good >= good_lg + PROFILE_READ_DELTA:
            return t["good"]
    if cost is not None and cost_lg is not None:
        comparable = True
        if cost >= cost_lg + PROFILE_COST_DELTA:
            return t["leaves"]
    return t["average"] if comparable else None


def _alternative(row: Mapping[str, Any], names: dict[str, str], t: dict[str, str]) -> str | None:
    """Rule 3: the alternative the player most often leaves, if there are enough decisions."""
    alt = row.get("ignored_alt")
    if alt not in ALT_TYPES:
        return None
    n = _num(row, f"n_alt_{alt}")
    if n is None or n < PROFILE_ALT_MIN:
        return None
    return t["alt"].format(alt=names[alt])


def _late(row: Mapping[str, Any], t: dict[str, str]) -> str | None:
    """Rule 4: moments lost while holding the ball."""
    share = _num(row, "late_held_share")
    return t["late"] if share is not None and share >= PROFILE_LATE_SHARE else None


def _clock(row: Mapping[str, Any], names: dict[str, str], t: dict[str, str]) -> str | None:
    """Rule 5: the clock bucket where the cost is highest, if it clearly exceeds the lowest."""
    costs: list[tuple[str, float]] = []
    for label, _, _ in CLOCK_BUCKETS:
        n, cost = _num(row, f"n_{label}"), _num(row, f"cost_{label}")
        if n is not None and cost is not None and n >= _CLOCK_MIN_SHOTS:
            costs.append((label, cost))
    if len(costs) < 2:
        return None
    worst = max(costs, key=lambda item: item[1])
    if worst[1] - min(c for _, c in costs) < PROFILE_COST_DELTA:
        return None
    return t["clock"].format(bucket=names[worst[0]])


def _season(
    row: Mapping[str, Any], league: Mapping[str, Any], zones: dict[str, str], t: dict[str, str]
) -> list[str]:
    """Rule 6: fragments of the season sentence (empty without a season block).

    The catch-and-shoot and contested clauses compare with the league and need its value.
    """
    if row.get("season_attempts") is None:
        return []
    out: list[str] = []
    shifts = [(z, _num(row, f"shift_{z}")) for z in zones]
    known = [(z, s) for z, s in shifts if s is not None]
    if known:
        zone, shift = max(known, key=lambda item: item[1])
        if shift >= PROFILE_ZONE_SHIFT:
            out.append(t["shift"].format(zone=zones[zone]))
    for key, text in (("season_cns_share", "cns"), ("season_contested_share", "contested")):
        value, reference = _num(row, key), _num(league, key)
        if (
            value is not None
            and reference is not None
            and value >= reference + PROFILE_SEASON_DELTA
        ):
            out.append(t[text])
    return out


def profile_phrase(row: Mapping[str, Any], league: Mapping[str, Any], *, lang: Lang = "es") -> str:
    """One or two descriptive sentences about a player, from the card's flat row.

    The first sentence joins, with "; ", the fragments of the reading (rule 2), the ignored
    alternative (3), the lost moments (4) and the clock (5). With fewer than
    ``PROFILE_MIN_SHOTS`` readable shots it opens with the small-sample note, which counts the
    valued shots (``n_shots``), and adds only the clock rule. The second sentence (rule 6)
    exists only with a season block.
    """
    t = _TEXT[lang]
    alts = ALT_NAMES_ES if lang == "es" else ALT_NAMES_EN
    zones = ZONE_NAMES_ES if lang == "es" else ZONE_NAMES_EN
    buckets = BUCKET_NAMES_ES if lang == "es" else BUCKET_NAMES_EN

    n_readable = int(_num(row, "n_readable") or 0)
    clock = _clock(row, buckets, t)
    if n_readable < PROFILE_MIN_SHOTS:
        n_shots = int(_num(row, "n_shots") or n_readable)
        if n_readable < n_shots:  # the sentence counts what it gates on, and the valued shots
            key = "read_one" if n_readable == 1 else "read_many"
            opening = t[key].format(r=n_readable, n=n_shots)
        else:
            opening = (t["small_one"] if n_shots == 1 else t["small_many"]).format(n=n_shots)
        return _sentence([opening, *([clock] if clock else [])])

    first = [
        f
        for f in (
            _reading(row, league, t),
            _alternative(row, alts, t),
            _late(row, t),
            clock,
        )
        if f
    ]
    sentences = [_sentence(first)] if first else []
    season = _season(row, league, zones, t)
    if season:
        sentences.append(_sentence(season))
    return " ".join(sentences) if sentences else _sentence([t["none"]])
