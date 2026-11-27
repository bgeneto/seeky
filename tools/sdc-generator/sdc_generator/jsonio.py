"""Strict JSON/JSONL readers, canonical encoders, and hash helpers.

SPEC-0004 section 4.3: UTF-8, LF newlines, sorted keys and two-space
indentation for manifests, one compact object per line for JSONL, and no
unknown schema versions, duplicate keys, invalid UTF-8, trailing data, or NaN.
"""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from .errors import IO_ERROR, SCHEMA_INVALID, SdcError


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number: {value}")


def _decode_utf8(data: bytes, *, file: str | None) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SdcError(
            SCHEMA_INVALID,
            f"invalid UTF-8 at byte {exc.start}",
            file=file,
            line=None,
        ) from exc


def loads_strict(text: str, *, file: str | None = None) -> Any:
    """Parse JSON, rejecting duplicate keys, NaN/Infinity, and trailing data."""

    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ValueError as exc:
        line = getattr(exc, "lineno", None)
        raise SdcError(
            SCHEMA_INVALID, f"invalid JSON: {exc}", file=file, line=line
        ) from exc


def load_json_bytes(data: bytes, *, file: str | None = None) -> Any:
    return loads_strict(_decode_utf8(data, file=file), file=file)


def load_json_file(path: Path, *, display: str | None = None) -> Any:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SdcError(IO_ERROR, f"cannot read: {exc}", file=display or str(path)) from exc
    return load_json_bytes(data, file=display or str(path))


def canonical_json_bytes(value: Any) -> bytes:
    """Canonical JSON for hashing: sorted keys, compact, no trailing newline."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def pretty_json_bytes(value: Any) -> bytes:
    """Manifest JSON: sorted keys, two-space indentation, trailing newline."""

    text = json.dumps(
        value,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    )
    return (text + "\n").encode("utf-8")


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise SdcError(IO_ERROR, f"cannot write {path.name}: {exc}") from exc


def write_json_file(path: Path, value: Any) -> None:
    write_bytes(path, pretty_json_bytes(value))


def write_jsonl_file(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    chunks: list[bytes] = []
    for row in rows:
        line = json.dumps(
            row,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        chunks.append(line.encode("utf-8") + b"\n")
    write_bytes(path, b"".join(chunks))


def read_jsonl_bytes(data: bytes, *, file: str) -> list[dict[str, Any]]:
    text = _decode_utf8(data, file=file)
    if text and not text.endswith("\n"):
        raise SdcError(
            SCHEMA_INVALID,
            "JSONL must end with exactly one LF newline",
            file=file,
        )
    if "\r" in text:
        raise SdcError(SCHEMA_INVALID, "JSONL must use LF newlines", file=file)
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(text.split("\n")[:-1], start=1):
        if not line:
            raise SdcError(SCHEMA_INVALID, "blank JSONL line", file=file, line=number)
        value = loads_strict(line, file=file)
        if not isinstance(value, dict):
            raise SdcError(
                SCHEMA_INVALID, "JSONL row must be an object", file=file, line=number
            )
        rows.append(value)
    return rows


def read_jsonl_file(path: Path, *, display: str | None = None) -> list[dict[str, Any]]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SdcError(IO_ERROR, f"cannot read: {exc}", file=display or path.name) from exc
    return read_jsonl_bytes(data, file=display or path.name)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise SdcError(IO_ERROR, f"cannot read {path.name}: {exc}") from exc
    return digest.hexdigest(), size


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def normalize_extracted(text: str) -> str:
    """Normalize extractor output for comparison: NFC, LF, collapse whitespace."""

    text = nfc(text.replace("\r\n", "\n").replace("\r", "\n"))
    return " ".join(text.split())


def posix_relative(path: Path, root: Path) -> str:
    """Return a POSIX relative path; reject attempts to escape the root."""

    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise SdcError(
            SCHEMA_INVALID, f"path outside the corpus root: {path.name}"
        ) from exc
    return relative.as_posix()


def assert_relative_posix(value: str, *, field: str, file: str | None = None) -> None:
    if not value or value.startswith("/") or "\\" in value or ":" in value:
        raise SdcError(
            SCHEMA_INVALID,
            f"{field} must be a POSIX relative path: {value!r}",
            file=file,
            field=field,
        )
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise SdcError(
            SCHEMA_INVALID,
            f"{field} contains an empty, dot, or parent segment: {value!r}",
            file=file,
            field=field,
        )


def iter_jsonl_rows(rows: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    yield from rows
