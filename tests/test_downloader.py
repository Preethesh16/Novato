"""Tests for the offline-model downloader (no real network)."""

from __future__ import annotations

import os

import pytest

from novato import downloader
from novato.downloader import DownloadError, ModelSpec, human_size, select_model


@pytest.fixture()
def spec():
    return ModelSpec(
        name="test-model",
        url="https://example.test/model.llamafile?download=true",
        filename="model.llamafile",
        approx_size="0.1 GB",
        min_ram_gb=2.0,
    )


class _FakeResp:
    """A minimal requests-like streaming response."""

    def __init__(self, body: bytes, *, status=200, headers=None):
        self._body = body
        self.status_code = status
        self.headers = headers or {"Content-Length": str(len(body))}

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]


# -- model selection --------------------------------------------------------

@pytest.mark.parametrize("ram,name", [
    (2, "tinyllama-1.1b"),
    (6, "phi3-mini"),
    (12, "mistral-7b"),
    (64, "llama3.1-8b"),
])
def test_select_model(ram, name):
    assert select_model(ram).name == name


def test_registry_urls_are_llamafiles():
    for spec in downloader.MODELS.values():
        assert spec.url.startswith("https://")
        assert ".llamafile" in spec.url


# -- successful download ----------------------------------------------------

def test_download_writes_executable_file(tmp_path, spec):
    body = b"MZ" + b"\x00" * 4096  # pretend binary
    seen = []

    def opener(url, headers):
        assert "model.llamafile" in url
        return _FakeResp(body)

    def progress(done, total):
        seen.append((done, total))

    path = downloader.download_model(
        spec, dest_dir=tmp_path, opener=opener, progress=progress
    )
    assert path.read_bytes() == body
    assert os.access(path, os.X_OK)  # chmod +x applied
    # No leftover .part file.
    assert not (tmp_path / "model.llamafile.part").exists()
    # Progress was reported and reached the total.
    assert seen[-1][0] == len(body)
    assert seen[-1][1] == len(body)


def test_already_downloaded_is_noop(tmp_path, spec):
    final = tmp_path / spec.filename
    final.write_bytes(b"data")
    final.chmod(0o755)

    def opener(url, headers):
        raise AssertionError("should not download when file already exists")

    path = downloader.download_model(spec, dest_dir=tmp_path, opener=opener)
    assert path == final


# -- resume -----------------------------------------------------------------

def test_resume_from_partial(tmp_path, spec):
    part = tmp_path / (spec.filename + ".part")
    part.write_bytes(b"AAAA")  # 4 bytes already downloaded

    captured = {}

    def opener(url, headers):
        captured["range"] = headers.get("Range")
        # Server honours range: returns the remaining bytes with 206.
        rest = b"BBBB"
        return _FakeResp(
            rest, status=206,
            headers={"Content-Range": "bytes 4-7/8", "Content-Length": "4"},
        )

    path = downloader.download_model(spec, dest_dir=tmp_path, opener=opener)
    assert captured["range"] == "bytes=4-"
    assert path.read_bytes() == b"AAAABBBB"


def test_server_ignores_range_restarts(tmp_path, spec):
    part = tmp_path / (spec.filename + ".part")
    part.write_bytes(b"OLD")

    def opener(url, headers):
        # Server ignores Range and sends full content with 200.
        return _FakeResp(b"FRESH", status=200)

    path = downloader.download_model(spec, dest_dir=tmp_path, opener=opener)
    assert path.read_bytes() == b"FRESH"  # not "OLDFRESH"


# -- error handling ---------------------------------------------------------

def test_http_error_raises(tmp_path, spec):
    def opener(url, headers):
        return _FakeResp(b"", status=404)

    with pytest.raises(DownloadError):
        downloader.download_model(spec, dest_dir=tmp_path, opener=opener)
    # Failed download leaves no executable final file.
    assert not (tmp_path / spec.filename).exists()


def test_opener_exception_raises(tmp_path, spec):
    def opener(url, headers):
        raise OSError("no network")

    with pytest.raises(DownloadError):
        downloader.download_model(spec, dest_dir=tmp_path, opener=opener)


# -- helpers ----------------------------------------------------------------

@pytest.mark.parametrize("n,expected", [
    (None, "?"),
    (0, "?"),
    (512, "512 B"),
    (1536, "1.5 KB"),
    (2 * 1024 ** 3, "2.0 GB"),
])
def test_human_size(n, expected):
    assert human_size(n) == expected
