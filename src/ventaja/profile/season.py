"""Season profile from SkillCorner aggregates, crossed with the tracked games.

Pure Polars: a missing value or a zero denominator is ``None``, never ``0.0``.
Rates are raw season rates (not shrunk like ``Priors``).
"""

import polars as pl

from ventaja.value.zones import ZONES, Zone

__all__ = [
    "MAIN_ZONES",
    "SEASON_INT_KEYS",
    "SEASON_KEYS",
    "season_profile",
    "tracked_zone_mix",
    "zone_shift",
]

MAIN_ZONES: tuple[Zone, ...] = ZONES[:5]

_SHOT_KEYS = (
    "season_games",
    "season_attempts",
    "season_fg",
    "season_three_share",
    "season_cns_share",
    "season_contested_share",
    "season_open_fg",
    *(f"season_zone_share_{z}" for z in MAIN_ZONES),
    "season_avg_distance",
)
_DRIVE_KEYS = (
    "season_drives",
    "season_drive_kickout_share",
    "season_drive_pullup_share",
    "season_drive_rim_share",
)
# Every key of ``season_profile``, in order, and the ones that hold counts (ints).
SEASON_KEYS: tuple[str, ...] = _SHOT_KEYS + _DRIVE_KEYS
SEASON_INT_KEYS = frozenset({"season_games", "season_attempts", "season_drives"})
_SUMMED = (
    "games_played",
    "attempts",
    "mades",
    "three_attempts",
    "cns_attempts",
    "contested_attempts",
    "cl_open_attempts",
    "cl_open_mades",
    *(f"zone_{z}_attempts" for z in MAIN_ZONES),
)
_DRIVE_SUMMED = (
    "games_played",
    "total_drives",
    "end_type_kickout_count",
    "end_type_pullup_count",
    "end_type_shot_near_basket_count",
)


def _ratio(num: float, den: float) -> float | None:
    return num / den if den else None


def _player_sums(df: pl.DataFrame, player_id: int, columns: tuple[str, ...]) -> dict[str, float]:
    """Column sums over the player's rows with a non-null team (never the ``total`` row)."""
    rows = df.filter((pl.col("player_id") == player_id) & pl.col("team_id").is_not_null())
    if rows.is_empty():
        return {}
    sums = rows.select(pl.col(c).cast(pl.Float64).sum() for c in columns).row(0, named=True)
    if "avg_attempts_distance" in rows.columns:
        weighted = rows.select(
            (pl.col("avg_attempts_distance") * pl.col("attempts")).sum().alias("w"),
            pl.col("attempts")
            .filter(pl.col("avg_attempts_distance").is_not_null())
            .sum()
            .alias("n"),
        ).row(0, named=True)
        sums["dist_weighted"], sums["dist_attempts"] = weighted["w"], weighted["n"]
    return sums


def season_profile(
    player_id: int, shots_agg: pl.DataFrame, drives_agg: pl.DataFrame | None
) -> dict[str, float | int | None]:
    """Season rates of a player from the shots and drives aggregates.

    Rows with a null ``team_id`` (the ``total`` rows) are ignored; the per-team rows are summed.
    A player absent from ``shots_agg`` gives all-``None``; absent from ``drives_agg`` (or
    ``drives_agg is None``) gives a null drives block.
    """
    out: dict[str, float | int | None] = dict.fromkeys(SEASON_KEYS)
    s = _player_sums(shots_agg, player_id, _SUMMED)
    if not s:
        return out
    att = s["attempts"]
    out["season_games"] = int(s["games_played"])
    out["season_attempts"] = int(att)
    out["season_fg"] = _ratio(s["mades"], att)
    out["season_three_share"] = _ratio(s["three_attempts"], att)
    out["season_cns_share"] = _ratio(s["cns_attempts"], att)
    out["season_contested_share"] = _ratio(s["contested_attempts"], att)
    out["season_open_fg"] = _ratio(s["cl_open_mades"], s["cl_open_attempts"])
    for z in MAIN_ZONES:
        out[f"season_zone_share_{z}"] = _ratio(s[f"zone_{z}_attempts"], att)
    out["season_avg_distance"] = _ratio(s.get("dist_weighted", 0.0), s.get("dist_attempts", 0.0))
    if drives_agg is not None:
        d = _player_sums(drives_agg, player_id, _DRIVE_SUMMED)
        if d:
            total = d["total_drives"]
            out["season_drives"] = int(total)
            out["season_drive_kickout_share"] = _ratio(d["end_type_kickout_count"], total)
            out["season_drive_pullup_share"] = _ratio(d["end_type_pullup_count"], total)
            out["season_drive_rim_share"] = _ratio(d["end_type_shot_near_basket_count"], total)
    return out


def tracked_zone_mix(player_id: int, options: pl.DataFrame) -> dict[str, float | None]:
    """Zone mix of a player's shots in the tracked decisions.

    ``backcourt`` and ``far`` are grouped into ``other``. No shots gives ``None`` shares and
    ``tracked_attempts`` 0.
    """
    zones = options.filter((pl.col("option_type") == "shot") & (pl.col("player_id") == player_id))[
        "zone"
    ].to_list()
    n = len(zones)
    out: dict[str, float | None] = {}
    for z in MAIN_ZONES:
        out[f"tracked_zone_share_{z}"] = zones.count(z) / n if n else None
    out["tracked_zone_share_other"] = (
        sum(1 for z in zones if z not in MAIN_ZONES) / n if n else None
    )
    out["tracked_attempts"] = n
    return out


def zone_shift(
    season: dict[str, float | int | None], tracked: dict[str, float | None]
) -> dict[str, float | None]:
    """``shift_{zone}`` = tracked share minus season share, ``None`` if either is missing."""
    out: dict[str, float | None] = {}
    for z in MAIN_ZONES:
        t, s = tracked.get(f"tracked_zone_share_{z}"), season.get(f"season_zone_share_{z}")
        out[f"shift_{z}"] = None if t is None or s is None else t - s
    return out
