# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline-model downloader for the llamafile tier.

Mozilla distributes ready-to-run **llamafiles** — single self-contained
executables that bundle an inference engine and a quantised model — on Hugging
Face. This module picks an appropriate one for the machine's RAM and downloads
it robustly:

* **Streaming** with a progress callback (so the UI shows a live bar).
* **Resumable** — a partial ``.part`` file is continued with an HTTP ``Range``
  request instead of restarting a multi-GB download.
* **Atomic** — bytes land in ``<name>.part`` and are ``os.replace``d into place
  only on success, so an interrupted download never looks complete.
* **Executable** — the finished file is ``chmod +x`` so llamafile can run it.

The HTTP layer is injectable (``opener``) so the logic is unit-tested without
touching the network. Nothing here ever runs the model — it only fetches it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

_CHUNK = 1024 * 1024  # 1 MiB
_HTTP_TIMEOUT = 30

# Progress callback: (downloaded_bytes, total_bytes_or_None) -> None.
ProgressFn = Callable[[int, Optional[int]], None]


@dataclass(frozen=True)
class ModelSpec:
    """A downloadable llamafile model."""

    name: str            # Short id, e.g. "phi3-mini".
    url: str             # Direct download URL (Hugging Face resolve link).
    filename: str        # Local filename to save as.
    approx_size: str     # Human-readable size for the UI, e.g. "2.4 GB".
    min_ram_gb: float    # Recommended minimum RAM to run it.


# Curated registry of official Mozilla llamafiles, smallest first. These are the
# canonical Hugging Face ``Mozilla/*-llamafile`` repos; update the quant suffix
# here if Mozilla re-publishes a file under a new name.
MODELS: dict[str, ModelSpec] = {
    "tinyllama-1.1b": ModelSpec(
        name="tinyllama-1.1b",
        url=("https://huggingface.co/Mozilla/TinyLlama-1.1B-Chat-v1.0-llamafile/"
             "resolve/main/TinyLlama-1.1B-Chat-v1.0.Q5_K_M.llamafile?download=true"),
        filename="TinyLlama-1.1B-Chat-v1.0.Q5_K_M.llamafile",
        approx_size="0.8 GB",
        min_ram_gb=2.0,
    ),
    "phi3-mini": ModelSpec(
        name="phi3-mini",
        url=("https://huggingface.co/Mozilla/Phi-3-mini-4k-instruct-llamafile/"
             "resolve/main/Phi-3-mini-4k-instruct.Q4_K_M.llamafile?download=true"),
        filename="Phi-3-mini-4k-instruct.Q4_K_M.llamafile",
        approx_size="2.4 GB",
        min_ram_gb=4.0,
    ),
    "mistral-7b": ModelSpec(
        name="mistral-7b",
        url=("https://huggingface.co/Mozilla/Mistral-7B-Instruct-v0.3-llamafile/"
             "resolve/main/Mistral-7B-Instruct-v0.3.Q4_K_M.llamafile?download=true"),
        filename="Mistral-7B-Instruct-v0.3.Q4_K_M.llamafile",
        approx_size="4.4 GB",
        min_ram_gb=8.0,
    ),
    "llama3.1-8b": ModelSpec(
        name="llama3.1-8b",
        url=("https://huggingface.co/Mozilla/Meta-Llama-3.1-8B-Instruct-llamafile/"
             "resolve/main/Meta-Llama-3.1-8B-Instruct.Q4_K_M.llamafile?download=true"),
        filename="Meta-Llama-3.1-8B-Instruct.Q4_K_M.llamafile",
        approx_size="4.9 GB",
        min_ram_gb=16.0,
    ),
}

# RAM (GB) upper bound -> model id. Picks the best model that comfortably fits.
_RAM_TIERS = (
    (4, "tinyllama-1.1b"),
    (8, "phi3-mini"),
    (16, "mistral-7b"),
    (float("inf"), "llama3.1-8b"),
)


def detect_ram_gb() -> float:
    """Return total system RAM in GB, with a conservative fallback."""
    try:
        import psutil  # type: ignore

        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        return 4.0


def select_model(total_ram_gb: Optional[float] = None) -> ModelSpec:
    """Pick the best :class:`ModelSpec` for the machine's RAM."""
    ram = total_ram_gb if total_ram_gb is not None else detect_ram_gb()
    for threshold, model_id in _RAM_TIERS:
        if ram < threshold:
            return MODELS[model_id]
    return MODELS[_RAM_TIERS[-1][1]]


def engine_dir() -> Path:
    """Directory where downloaded llamafiles live (``~/.novato/engine``)."""
    from .config import config_dir

    return config_dir() / "engine"


def model_path(spec: ModelSpec) -> Path:
    """Absolute path where ``spec`` will be / is stored."""
    return engine_dir() / spec.filename


def is_downloaded(spec: ModelSpec) -> bool:
    """True if the model is fully downloaded and executable."""
    p = model_path(spec)
    return p.is_file() and os.access(p, os.X_OK)


def _default_opener(url: str, headers: dict):
    """Default HTTP opener using requests in streaming mode."""
    if requests is None:  # pragma: no cover
        raise RuntimeError("The 'requests' library is required to download models.")
    return requests.get(url, headers=headers, stream=True, timeout=_HTTP_TIMEOUT)


def download_model(
    spec: ModelSpec,
    *,
    dest_dir: Optional[Path] = None,
    progress: Optional[ProgressFn] = None,
    opener: Callable[[str, dict], object] = _default_opener,
    resume: bool = True,
) -> Path:
    """Download ``spec`` into ``dest_dir`` (default ``~/.novato/engine``).

    Returns the path to the finished, executable llamafile. Raises
    :class:`DownloadError` on failure. Safe to re-run: an already-complete file
    is returned immediately, and a partial ``.part`` file is resumed.
    """
    dest_dir = dest_dir or engine_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / spec.filename
    part = dest_dir / (spec.filename + ".part")

    if final.is_file() and os.access(final, os.X_OK):
        return final  # Already done.

    already = part.stat().st_size if (resume and part.exists()) else 0
    headers = {"Accept-Encoding": "identity"}
    if already:
        headers["Range"] = f"bytes={already}-"

    try:
        resp = opener(spec.url, headers)
    except Exception as exc:  # network / DNS / TLS
        raise DownloadError(f"Could not start download: {exc}") from exc

    try:
        status = getattr(resp, "status_code", 200)
        if status not in (200, 206):
            raise DownloadError(f"Download failed with HTTP {status} for {spec.url}")

        # A full response replaces the old prefix when the server ignores Range.
        mode = "ab" if already and status == 206 else "wb"
        if status == 200:
            already = 0
        total, expected_body = _response_sizes(resp, already, status)
        received = 0
        with open(part, mode) as fh:
            if progress:
                progress(already, total)
            for chunk in _iter_chunks(resp):
                if not chunk:
                    continue
                if expected_body is not None and received + len(chunk) > expected_body:
                    raise DownloadError("Response exceeded its advertised byte length.")
                fh.write(chunk)
                received += len(chunk)
                if progress:
                    progress(already + received, total)

        downloaded = already + received
        if not downloaded or (total is not None and downloaded != total):
            raise DownloadError("Download is incomplete; partial data was kept for resuming.")
        if expected_body is not None and received != expected_body:
            raise DownloadError("Response ended before its advertised byte length.")

        # Only a complete response can become the executable model.
        os.chmod(part, 0o755)
        os.replace(part, final)
        return final
    except DownloadError:
        raise
    except Exception as exc:
        raise DownloadError(f"Could not complete download: {exc}") from exc
    finally:
        close = getattr(resp, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass  # Cleanup must not hide the original transfer failure.


def _response_sizes(resp, already: int, status: int) -> tuple[Optional[int], Optional[int]]:
    """Validate resume boundaries and return (complete size, response size)."""
    headers = {key.lower(): value for key, value in (getattr(resp, "headers", {}) or {}).items()}
    if headers.get("content-encoding", "identity").lower() not in ("", "identity"):
        raise DownloadError("Encoded model responses cannot be safely resumed.")
    length = headers.get("content-length")
    if length is not None:
        try:
            length = int(length)
        except (TypeError, ValueError) as exc:
            raise DownloadError("Invalid Content-Length header.") from exc
        if length < 0:
            raise DownloadError("Invalid Content-Length header.")
    if status == 206:
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", headers.get("content-range", ""))
        if not match:
            raise DownloadError("Missing or invalid Content-Range for a partial response.")
        start, end, total = map(int, match.groups())
        if start != already or not start <= end < total:
            raise DownloadError("Response range does not match the partial download.")
        expected = end - start + 1
        if length is not None and length != expected:
            raise DownloadError("Content-Length conflicts with Content-Range.")
        return total, expected
    return length, length


def _iter_chunks(resp):
    """Yield byte chunks from a response (requests-like or a raw iterator)."""
    if hasattr(resp, "iter_content"):
        return resp.iter_content(chunk_size=_CHUNK)
    if hasattr(resp, "__iter__"):
        return resp
    raise DownloadError("Opener returned a non-streamable response.")


def human_size(num_bytes: Optional[int]) -> str:
    """Format a byte count as a human-readable string."""
    if not num_bytes:
        return "?"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


class DownloadError(RuntimeError):
    """Raised when a model download cannot be completed."""
