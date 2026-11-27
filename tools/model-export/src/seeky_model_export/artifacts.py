"""Artifact safety, checksums, downloads, and strict manifest I/O."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import requests


class ArtifactError(RuntimeError):
    """A safe, typed artifact or manifest failure."""


def ensure_external_workspace(path: str | os.PathLike[str]) -> Path:
    """Create *path* only when it is outside every Git worktree."""
    resolved = Path(path).expanduser().resolve()
    for parent in (resolved, *resolved.parents):
        if (parent / ".git").exists():
            raise ArtifactError("workspace must be outside every Git worktree")
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ArtifactError("workspace cannot be created") from error
    return resolved


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise ArtifactError("file cannot be hashed") from error
    return digest.hexdigest()


def load_json(path: str | os.PathLike[str]) -> Any:
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ArtifactError("JSON manifest cannot be read") from error


def write_json(path: str | os.PathLike[str], value: Any) -> Path:
    destination = Path(path)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                value,
                stream,
                ensure_ascii=True,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
        temporary.replace(destination)
    except (OSError, TypeError, ValueError) as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ArtifactError("JSON manifest cannot be written") from error
    return destination


def download_file(
    url: str,
    destination: str | os.PathLike[str],
    *,
    expected_sha256: str | None = None,
) -> Path:
    """Download a public artifact atomically and optionally verify its digest."""
    target = Path(destination)
    temporary = target.with_name(target.name + ".part")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=(15, 120)) as response:
            response.raise_for_status()
            with temporary.open("wb") as stream:
                for block in response.iter_content(1024 * 1024):
                    if block:
                        stream.write(block)
        if expected_sha256 is not None and sha256_file(temporary) != expected_sha256.lower():
            raise ArtifactError("downloaded artifact has the wrong SHA-256")
        temporary.replace(target)
    except (OSError, requests.RequestException) as error:
        temporary.unlink(missing_ok=True)
        raise ArtifactError("public artifact download failed") from error
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target
