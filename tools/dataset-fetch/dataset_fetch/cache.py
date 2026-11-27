"""External download cache with SHA-256, size, and terms verification.

The cache lives outside the repository. Network access happens only in
``prepare`` when a declared source file or the pinned terms snapshot is
missing; ``verify`` never touches this module's download path.
"""

from __future__ import annotations

import os
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import sha256_file
from .errors import (
    CACHE_MISS,
    HASH_MISMATCH,
    IO,
    NETWORK,
    SIZE_MISMATCH,
    TERMS_MISMATCH,
    fail,
)

Fetch = Callable[[str, Path], None]


@dataclass(frozen=True)
class CachedFile:
    url: str
    path: Path
    size_bytes: int
    sha256: str


def default_cache_root() -> Path:
    override = os.environ.get("SEEKY_DATASET_CACHE")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "seeky-dev" / "datasets"
    return Path.home() / ".cache" / "seeky-datasets"


def _http_get(url: str, dest: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "seeky-dataset-fetch/0.1 (+https://github.com/bgeneto/seeky)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as handle:
                shutil.copyfileobj(response, handle, length=1024 * 1024)
    except (urllib.error.URLError, OSError) as exc:
        raise fail(NETWORK, f"download failed: {exc}", location=url) from exc


class DownloadCache:
    def __init__(
        self,
        root: Path,
        dataset_id: str,
        *,
        offline: bool = False,
        fetch: Fetch | None = None,
    ) -> None:
        self.root = root / dataset_id
        self.dataset_id = dataset_id
        self.offline = offline
        self.fetch: Fetch = fetch or _http_get

    @property
    def downloads(self) -> Path:
        return self.root / "downloads"

    @property
    def terms(self) -> Path:
        return self.root / "terms"

    def ensure(self, source: dict[str, Any]) -> list[CachedFile]:
        files: list[CachedFile] = []
        seen: set[str] = set()
        for url, expected in zip(source["urls"], source["sha256"], strict=True):
            name = url.rsplit("/", 1)[-1]
            if name in seen:
                raise fail(
                    "SCHEMA",
                    "source file names must be unique in one dataset",
                    location=url,
                )
            seen.add(name)
            dest = self.downloads / name
            if dest.exists():
                actual = sha256_file(dest)
                if actual != expected:
                    raise fail(
                        HASH_MISMATCH,
                        "cached file digest differs from the pinned source hash; "
                        "remove it or choose another cache",
                        location=str(dest),
                    )
            else:
                self._download(url, dest, expected, mismatch_code=HASH_MISMATCH)
            size = dest.stat().st_size
            files.append(CachedFile(url, dest, size, expected))
        return files

    def ensure_terms(self, terms_url: str, expected_sha256: str) -> CachedFile:
        dest = self.terms / f"{expected_sha256}.txt"
        if dest.exists():
            actual = sha256_file(dest)
            if actual != expected_sha256:
                raise fail(
                    TERMS_MISMATCH,
                    "cached terms snapshot digest differs from the pinned digest",
                    location=str(dest),
                )
        else:
            self._download(
                terms_url,
                dest,
                expected_sha256,
                mismatch_code=TERMS_MISMATCH,
                require_existing_parent=True,
            )
        return CachedFile(terms_url, dest, dest.stat().st_size, expected_sha256)

    def _download(
        self,
        url: str,
        dest: Path,
        expected_sha256: str,
        *,
        mismatch_code: str,
        require_existing_parent: bool = False,
    ) -> None:
        if self.offline:
            raise fail(
                CACHE_MISS,
                "file is absent from the cache and --offline forbids downloading",
                location=url,
            )
        if require_existing_parent:
            dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(dest.name + ".part")
        if temp.exists():
            temp.unlink()
        try:
            self.fetch(url, temp)
        except Exception:
            if temp.exists():
                temp.unlink()
            raise
        actual = sha256_file(temp)
        if actual != expected_sha256:
            temp.unlink()
            raise fail(
                mismatch_code,
                f"downloaded content digest {actual} does not match the pinned hash",
                location=url,
            )
        if dest.exists():
            temp.unlink()
            raise fail(
                HASH_MISMATCH,
                "destination appeared while downloading; refusing to overwrite it",
                location=str(dest),
            )
        try:
            os.replace(temp, dest)
        except OSError as exc:
            temp.unlink(missing_ok=True)
            raise fail(IO, str(exc), location=str(dest)) from exc
        if dest.stat().st_size == 0:
            raise fail(SIZE_MISMATCH, "downloaded file is empty", location=url)
