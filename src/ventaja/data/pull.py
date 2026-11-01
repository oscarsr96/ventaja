"""Download raw SkillCorner files over HTTPS."""

import os
from collections.abc import Callable, Iterable
from pathlib import Path

import httpx

from ventaja.config import Settings
from ventaja.data.catalog import RemoteFile, files_for

_CHUNK_SIZE = 1 << 20
# Servers gzip text responses, which makes Content-Length the compressed size.
_IDENTITY = {"Accept-Encoding": "identity"}


def _is_up_to_date(client: httpx.Client, f: RemoteFile, dest: Path) -> bool:
    """True when dest exists and its size equals the remote Content-Length."""
    if not dest.exists():
        return False
    response = client.head(f.url, headers=_IDENTITY)
    response.raise_for_status()
    length = response.headers.get("content-length")
    return length is not None and dest.stat().st_size == int(length)


def _download(client: httpx.Client, f: RemoteFile, dest: Path) -> int:
    """Stream f to dest through a temporary file; return bytes written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    written = 0
    with client.stream("GET", f.url, headers=_IDENTITY) as response:
        response.raise_for_status()
        with tmp.open("wb") as out:
            for chunk in response.iter_bytes(_CHUNK_SIZE):
                out.write(chunk)
                written += len(chunk)
    os.replace(tmp, dest)
    return written


def pull(
    files: Iterable[RemoteFile],
    settings: Settings,
    *,
    client: httpx.Client | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> list[Path]:
    """Download files into settings.data_dir, skipping those already complete.

    ``progress(relpath, bytes_written, bytes_written)`` is called after each
    file that is actually downloaded (not for skipped ones).
    """
    owned = client is None
    http = httpx.Client(follow_redirects=True, timeout=60.0) if client is None else client
    paths: list[Path] = []
    try:
        for f in files:
            dest = settings.raw_path(f.relpath)
            if not _is_up_to_date(http, f, dest):
                size = _download(http, f, dest)
                if progress is not None:
                    progress(f.relpath, size, size)
            paths.append(dest)
    finally:
        if owned:
            http.close()
    return paths


def status(
    settings: Settings, game_ids: Iterable[int] | None = None
) -> list[tuple[RemoteFile, bool]]:
    """Which catalog files are present locally (no network)."""
    return [(f, settings.raw_path(f.relpath).exists()) for f in files_for(game_ids)]
