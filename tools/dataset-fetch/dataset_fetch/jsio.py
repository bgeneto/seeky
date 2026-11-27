"""Strict JSON/JSONL/TSV readers and deterministic writers."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .canonical import canonical_json
from .errors import IO, SCHEMA, fail


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number: {value}")


def _parse(text: str, *, location: str, line: int | None) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ValueError as exc:
        raise fail(SCHEMA, f"invalid JSON: {exc}", location=location, line=line) from exc


def read_json(path: Path) -> Any:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise fail(IO, str(exc), location=str(path)) from exc
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise fail(
            SCHEMA, f"invalid UTF-8 at byte {exc.start}", location=str(path)
        ) from exc
    return _parse(text, location=str(path), line=None)


def iter_jsonl(path: Path, *, gzipped: bool = False) -> Iterator[tuple[int, Any]]:
    opener = gzip.open if gzipped else open
    try:
        with opener(path, "rb") as handle:  # type: ignore[operator]
            for index, raw in enumerate(handle, start=1):
                try:
                    line = raw.decode("utf-8").rstrip("\r\n")
                except UnicodeDecodeError as exc:
                    raise fail(
                        SCHEMA,
                        f"invalid UTF-8 at byte {exc.start}",
                        location=str(path),
                        line=index,
                    ) from exc
                if not line.strip():
                    raise fail(SCHEMA, "blank JSONL line", location=str(path), line=index)
                yield index, _parse(line, location=str(path), line=index)
    except OSError as exc:
        raise fail(IO, str(exc), location=str(path)) from exc


def read_jsonl(path: Path, *, gzipped: bool = False) -> list[Any]:
    return [record for _, record in iter_jsonl(path, gzipped=gzipped)]


def iter_tsv(path: Path, *, gzipped: bool = False) -> Iterator[list[str]]:
    opener = gzip.open if gzipped else open
    try:
        with opener(path, "rt", encoding="utf-8", newline="") as handle:  # type: ignore[operator]
            for raw in handle:
                line = raw.rstrip("\r\n")
                if line == "":
                    continue
                yield line.split("\t")
    except (OSError, UnicodeDecodeError) as exc:
        raise fail(IO, str(exc), location=str(path)) from exc


def jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(
        (canonical_json(row) + "\n").encode("utf-8") for row in rows
    )


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(data)
    except OSError as exc:
        raise fail(IO, str(exc), location=str(path)) from exc


def write_text(path: Path, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


def pretty_json_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise fail(SCHEMA, f"value is not serializable JSON: {exc}") from exc
    return (text + "\n").encode("utf-8")
