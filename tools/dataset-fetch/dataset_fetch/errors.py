"""Typed, location-bearing errors for dataset preparation (SPEC-0003 R23).

Every structural failure raises :class:`DatasetFetchError` with a stable code,
a dataset-relative or cache-relative location, and a message. The CLI prints
one JSON object on stderr and exits non-zero; it never prints a traceback
unless ``DATASET_FETCH_DEBUG`` is set.
"""

from __future__ import annotations

import json
from typing import Any

SCHEMA = "SCHEMA"
IO = "IO"
HASH_MISMATCH = "HASH_MISMATCH"
SIZE_MISMATCH = "SIZE_MISMATCH"
TERMS_MISMATCH = "TERMS_MISMATCH"
LICENSE_FORBIDDEN = "LICENSE_FORBIDDEN"
CACHE_MISS = "CACHE_MISS"
NETWORK = "NETWORK"
TRANSFORM = "TRANSFORM"
DANGLING_REFERENCE = "DANGLING_REFERENCE"
DUPLICATE_ID = "DUPLICATE_ID"
OUTPUT_EXISTS = "OUTPUT_EXISTS"
UNSUPPORTED = "UNSUPPORTED"
LOCK_MISMATCH = "LOCK_MISMATCH"


class DatasetFetchError(Exception):
    """A structural preparation error carrying a machine-readable location."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        location: str | None = None,
        line: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.location = location
        self.line = line

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "location": self.location,
            "line": self.line,
            "message": self.message,
        }

    def as_json(self) -> str:
        return json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )


def fail(
    code: str,
    message: str,
    *,
    location: str | None = None,
    line: int | None = None,
) -> DatasetFetchError:
    return DatasetFetchError(code, message, location=location, line=line)
