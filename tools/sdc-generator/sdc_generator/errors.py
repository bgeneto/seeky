"""Typed, location-bearing errors for the SDC generator (SPEC-0004-R13).

Every structural failure raises :class:`SdcError` with a stable code, a
repository-relative or cache-relative file, an optional line and field, and a
message. The CLI prints one machine-readable JSON object on stderr and never a
traceback unless ``SDC_DEBUG`` is set.
"""

from __future__ import annotations

import json
from typing import Any

# Stable error codes named by SPEC-0004 section 5.1.
SOURCE_PIN_MISSING = "SOURCE_PIN_MISSING"
SOURCE_HASH_MISMATCH = "SOURCE_HASH_MISMATCH"
LICENSE_INELIGIBLE = "LICENSE_INELIGIBLE"
LICENSE_NOTICE_MISSING = "LICENSE_NOTICE_MISSING"
CACHE_MISS = "CACHE_MISS"
SCHEMA_INVALID = "SCHEMA_INVALID"
RENDER_FAILED = "RENDER_FAILED"
OUTPUT_HASH_MISMATCH = "OUTPUT_HASH_MISMATCH"
QREL_TARGET_STALE = "QREL_TARGET_STALE"
PROVENANCE_INCOMPLETE = "PROVENANCE_INCOMPLETE"
POOL_INCOMPLETE = "POOL_INCOMPLETE"
TEST_NOT_ELIGIBLE = "TEST_NOT_ELIGIBLE"

# Additional codes used by this implementation.
PROFILE_INVALID = "PROFILE_INVALID"
PROFILE_COUNT_MISMATCH = "PROFILE_COUNT_MISMATCH"
OUTPUT_EXISTS = "OUTPUT_EXISTS"
IO_ERROR = "IO_ERROR"
NETWORK_DISABLED = "NETWORK_DISABLED"
UNSUPPORTED = "UNSUPPORTED"
INTERNAL_ERROR = "INTERNAL_ERROR"


class SdcError(Exception):
    """A structural generator error carrying a machine-readable location."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        file: str | None = None,
        line: int | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.file = file
        self.line = line
        self.field = field

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "file": self.file,
            "line": self.line,
            "field": self.field,
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
    file: str | None = None,
    line: int | None = None,
    field: str | None = None,
) -> "SdcError":
    return SdcError(code, message, file=file, line=line, field=field)
