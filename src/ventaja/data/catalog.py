"""Catalog of the remote SkillCorner files ventaja downloads."""

from collections.abc import Iterable
from dataclasses import dataclass

from ventaja.config import GAME_IDS

RAW_BASE = "https://raw.githubusercontent.com/SkillCorner/opendata-basketball/main/data/"
LFS_BASE = "https://media.githubusercontent.com/media/SkillCorner/opendata-basketball/main/data/"

_STATIC_FILES = (
    "matches.json",
    "player_id_aliases.csv",
    "aggregates/acb_shotsaggregates_20252026.csv",
    "aggregates/acb_drivesaggregates_20252026.csv",
    "aggregates/acb_picksaggregates_20252026.csv",
)


@dataclass(frozen=True)
class RemoteFile:
    """A file to download: path relative to data_dir, source URL, and whether it is Git LFS."""

    relpath: str
    url: str
    lfs: bool


def files_for(game_ids: Iterable[int] | None = None, *, tracking: bool = True) -> list[RemoteFile]:
    """Remote files needed for the given games (all ten when None)."""
    ids = GAME_IDS if game_ids is None else tuple(game_ids)
    files = [RemoteFile(p, RAW_BASE + p, False) for p in _STATIC_FILES]
    for gid in ids:
        base = f"matches/{gid}/{gid}"
        for suffix in ("game_data.json", "dynamic_events.json"):
            files.append(RemoteFile(f"{base}_{suffix}", f"{RAW_BASE}{base}_{suffix}", False))
        if tracking:
            rel = f"{base}_tracking_data.jsonl.gz"
            files.append(RemoteFile(rel, LFS_BASE + rel, True))
    return files
