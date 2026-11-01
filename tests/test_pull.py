from pathlib import Path

import httpx

from ventaja.config import Settings
from ventaja.data.catalog import RemoteFile
from ventaja.data.pull import pull, status


class _Server:
    """Mock HTTP server serving one payload and counting GET requests."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.gets = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(self.payload))})
        self.gets += 1
        return httpx.Response(200, content=self.payload)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "raw", build_dir=tmp_path / "build")


def _file() -> RemoteFile:
    return RemoteFile("matches.json", "https://x/matches.json", lfs=False)


def test_pull_writes_file_atomically(tmp_path: Path) -> None:
    server = _Server(b"[]")
    with server.client() as c:
        [path] = pull([_file()], _settings(tmp_path), client=c)
    assert path.read_bytes() == b"[]"
    assert not path.with_name(path.name + ".tmp").exists()


def test_pull_skips_when_size_matches(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    dest = settings.raw_path("matches.json")
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"[]")
    server = _Server(b"{}")
    with server.client() as c:
        [path] = pull([_file()], settings, client=c)
    assert server.gets == 0
    assert path.read_bytes() == b"[]"


def test_pull_redownloads_when_size_differs(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    dest = settings.raw_path("matches.json")
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"x")
    server = _Server(b"[]")
    with server.client() as c:
        pull([_file()], settings, client=c)
    assert server.gets == 1
    assert dest.read_bytes() == b"[]"


def test_pull_reports_progress(tmp_path: Path) -> None:
    events: list[tuple[str, int, int]] = []
    with _Server(b"[]").client() as c:
        pull([_file()], _settings(tmp_path), client=c, progress=lambda *a: events.append(a))
    assert events == [("matches.json", 2, 2)]


def test_status_reports_missing_without_network(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, build_dir=tmp_path / "b")
    rows = status(settings, [114243])
    assert all(present is False for _, present in rows)
