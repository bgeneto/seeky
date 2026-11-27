"""Canonical JSON, text normalization, and hashing (SPEC-0003 §4.2)."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any

from .errors import IO, SCHEMA, fail


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise fail(IO, str(exc), location=str(path)) from exc
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    """UTF-8 JSON with sorted keys, compact separators, no trailing newline.

    Mirrors ``serde_json::to_string`` on a ``BTreeMap``-backed value: sorted
    keys, no whitespace, non-ASCII written as UTF-8, and no NaN/Infinity.
    """

    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise fail(SCHEMA, f"value is not canonical JSON: {exc}") from exc


def normalize_text(value: str) -> str:
    """Canonical NFC text with LF newlines (SPEC-0003 §4.2)."""

    text = value.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text)


def encode_text(value: str) -> bytes:
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise fail(SCHEMA, f"text is not encodable UTF-8: {exc}") from exc
