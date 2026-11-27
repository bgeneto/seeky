"""Corpus profiles (SPEC-0004 section 4.2)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .derive import parse_iso_utc
from .errors import PROFILE_INVALID, SCHEMA_INVALID, SdcError
from .jsonio import load_json_file

SCHEMA_VERSION = 1

# The renderer IDs fixed by SPEC-0004 section 4.2/4.3.
RENDERERS = (
    "pdf",
    "scanned-pdf",
    "scanned-image",
    "docx",
    "xlsx",
    "pptx",
    "odt",
    "rtf",
    "html",
    "epub",
    "eml",
    "md",
    "txt",
    "code",
)

INJECTION_KEYS = (
    "exact_byte_copies",
    "exact_text_copies",
    "scanned_variants",
    "near_duplicate_documents",
    "version_groups",
    "boilerplate_documents",
)

_PROFILE_KEYS = {
    "schema_version",
    "corpus_id",
    "source_set_ids",
    "default_seed",
    "extends",
    "target_documents",
    "target_passages",
    "max_committed_bytes",
    "renderers",
    "injection",
    "scan_recipes",
    "clock_start",
    "clock_end",
}

# Share of rendered files that are source code, used to derive the code root
# size from the profile target (ADR-0024 keeps code in a disjoint root).
CODE_SHARE = 0.10


@dataclass(frozen=True)
class Profile:
    schema_version: int
    corpus_id: str
    source_set_ids: tuple[str, ...]
    default_seed: str
    extends: str | None
    target_documents: int
    target_passages: int
    max_committed_bytes: int | None
    renderers: tuple[str, ...]
    injection: dict[str, int]
    scan_recipes: tuple[str, ...]
    clock_start: str
    clock_end: str
    path: Path
    file_sha256: str

    @property
    def code_documents(self) -> int:
        return max(1, math.ceil(self.target_documents * CODE_SHARE))

    @property
    def derived_documents(self) -> int:
        value = (
            self.injection["exact_byte_copies"]
            + self.injection["exact_text_copies"]
            + self.injection["scanned_variants"]
            + self.injection["near_duplicate_documents"]
            + 2 * self.injection["version_groups"]
            + self.code_documents
        )
        return value

    @property
    def base_documents(self) -> int:
        return self.target_documents - self.derived_documents

    @property
    def is_smoke(self) -> bool:
        return self.corpus_id == "sdc-smoke"

    def validate_generated_counts(
        self, *, rendered_files: int, passages: int, total_bytes: int
    ) -> None:
        if self.is_smoke:
            if rendered_files != self.target_documents:
                raise SdcError(
                    PROFILE_INVALID,
                    f"{self.corpus_id} must render exactly "
                    f"{self.target_documents} files, got {rendered_files}",
                    file=self.path.name,
                    field="target_documents",
                )
            if passages < self.target_passages:
                raise SdcError(
                    PROFILE_INVALID,
                    f"{self.corpus_id} must contain at least "
                    f"{self.target_passages} passages, got {passages}",
                    file=self.path.name,
                    field="target_passages",
                )
            if self.max_committed_bytes is not None and total_bytes > self.max_committed_bytes:
                raise SdcError(
                    PROFILE_INVALID,
                    f"{self.corpus_id} is {total_bytes} bytes, above the "
                    f"{self.max_committed_bytes}-byte cap",
                    file=self.path.name,
                    field="max_committed_bytes",
                )
            return
        # Scale profiles: section 4.4 ranges, +/-5 percent of the target for
        # rendered files. Full sdc-s/sdc-m use the absolute passage ranges from
        # the table; reduced test fixtures only need their planned lower bound.
        low = math.floor(self.target_documents * 0.95)
        high = math.ceil(self.target_documents * 1.05)
        if not low <= rendered_files <= high:
            raise SdcError(
                PROFILE_INVALID,
                f"{self.corpus_id} must render {low}-{high} files, "
                f"got {rendered_files}",
                file=self.path.name,
                field="target_documents",
            )
        if self.target_documents < 1_000:
            if passages < self.target_passages:
                raise SdcError(
                    PROFILE_INVALID,
                    f"{self.corpus_id} must contain at least "
                    f"{self.target_passages} passages, got {passages}",
                    file=self.path.name,
                    field="target_passages",
                )
            return
        passage_low, passage_high = (
            (90_000, 110_000)
            if self.target_documents < 50_000
            else (900_000, 1_100_000)
        )
        if not passage_low <= passages <= passage_high:
            raise SdcError(
                PROFILE_INVALID,
                f"{self.corpus_id} must contain {passage_low}-{passage_high} "
                f"passages, got {passages}",
                file=self.path.name,
                field="target_passages",
            )


def _require(condition: bool, message: str, *, file: str, field: str) -> None:
    if not condition:
        raise SdcError(SCHEMA_INVALID, message, file=file, field=field)


def _int(value: Any, *, file: str, field: str, minimum: int) -> int:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value >= minimum,
        f"{field} must be an integer >= {minimum}",
        file=file,
        field=field,
    )
    return int(value)


def load_profile(path: Path, *, display: str | None = None) -> Profile:
    from .jsonio import sha256_bytes

    display = display or path.name
    raw_bytes = path.read_bytes()
    value = load_json_file(path, display=display)
    _require(isinstance(value, dict), "profile must be a JSON object", file=display, field="")
    unknown = set(value) - _PROFILE_KEYS
    _require(not unknown, f"unknown profile fields: {sorted(unknown)}", file=display, field="")
    missing = _PROFILE_KEYS - set(value)
    _require(not missing, f"missing profile fields: {sorted(missing)}", file=display, field="")
    _require(
        value["schema_version"] == SCHEMA_VERSION,
        f"unsupported profile schema_version {value['schema_version']!r}",
        file=display,
        field="schema_version",
    )

    corpus_id = value["corpus_id"]
    _require(
        isinstance(corpus_id, str) and corpus_id and corpus_id.isascii(),
        "corpus_id must be a nonempty ASCII string",
        file=display,
        field="corpus_id",
    )
    _require(
        corpus_id == path.stem,
        f"corpus_id {corpus_id!r} must equal the profile file stem {path.stem!r}",
        file=display,
        field="corpus_id",
    )

    source_set_ids = value["source_set_ids"]
    _require(
        isinstance(source_set_ids, list)
        and source_set_ids
        and all(isinstance(item, str) and item for item in source_set_ids)
        and len(set(source_set_ids)) == len(source_set_ids),
        "source_set_ids must be a nonempty list of distinct strings",
        file=display,
        field="source_set_ids",
    )

    default_seed = value["default_seed"]
    _require(
        isinstance(default_seed, str) and default_seed and default_seed.isascii(),
        "default_seed must be a nonempty ASCII string",
        file=display,
        field="default_seed",
    )

    target_documents = _int(value["target_documents"], file=display, field="target_documents", minimum=1)

    extends = value["extends"]
    if corpus_id in ("sdc-smoke", "sdc-s") or target_documents < 50_000:
        _require(extends is None, f"{corpus_id} must not extend another profile", file=display, field="extends")
    else:
        _require(
            extends == "sdc-s",
            "a scale profile above sdc-s must extend sdc-s",
            file=display,
            field="extends",
        )

    target_passages = _int(value["target_passages"], file=display, field="target_passages", minimum=1)
    _require(
        target_passages >= target_documents,
        "target_passages must be at least target_documents",
        file=display,
        field="target_passages",
    )

    max_committed_bytes = value["max_committed_bytes"]
    if max_committed_bytes is not None:
        _int(max_committed_bytes, file=display, field="max_committed_bytes", minimum=1)

    renderers = value["renderers"]
    _require(
        isinstance(renderers, list)
        and len(set(renderers)) == len(renderers)
        and all(item in RENDERERS for item in renderers),
        "renderers contains an unknown or duplicate renderer ID",
        file=display,
        field="renderers",
    )
    missing_renderers = sorted(set(RENDERERS) - set(renderers))
    _require(
        not missing_renderers,
        f"every profile must render every required format; missing {missing_renderers}",
        file=display,
        field="renderers",
    )

    injection_raw = value["injection"]
    _require(isinstance(injection_raw, dict), "injection must be an object", file=display, field="injection")
    _require(
        set(injection_raw) == set(INJECTION_KEYS),
        f"injection keys must be exactly {list(INJECTION_KEYS)}",
        file=display,
        field="injection",
    )
    injection = {
        key: _int(injection_raw[key], file=display, field=f"injection.{key}", minimum=0)
        for key in INJECTION_KEYS
    }

    scan_recipes = value["scan_recipes"]
    _require(
        isinstance(scan_recipes, list)
        and scan_recipes
        and all(isinstance(item, str) and item for item in scan_recipes)
        and len(set(scan_recipes)) == len(scan_recipes),
        "scan_recipes must be a nonempty list of distinct recipe IDs",
        file=display,
        field="scan_recipes",
    )

    clock_start = value["clock_start"]
    clock_end = value["clock_end"]
    _require(isinstance(clock_start, str), "clock_start must be a string", file=display, field="clock_start")
    _require(isinstance(clock_end, str), "clock_end must be a string", file=display, field="clock_end")
    start = parse_iso_utc(clock_start, file=display, field="clock_start")
    end = parse_iso_utc(clock_end, file=display, field="clock_end")
    _require(start <= end, "clock_start must not be after clock_end", file=display, field="clock_start")

    profile = Profile(
        schema_version=SCHEMA_VERSION,
        corpus_id=corpus_id,
        source_set_ids=tuple(source_set_ids),
        default_seed=default_seed,
        extends=extends,
        target_documents=target_documents,
        target_passages=target_passages,
        max_committed_bytes=max_committed_bytes,
        renderers=tuple(renderers),
        injection=injection,
        scan_recipes=tuple(scan_recipes),
        clock_start=clock_start,
        clock_end=clock_end,
        path=path,
        file_sha256=sha256_bytes(raw_bytes),
    )

    derived = profile.derived_documents
    _require(
        derived < target_documents,
        f"injection counts and code share ({derived}) leave no base documents",
        file=display,
        field="target_documents",
    )
    _require(
        profile.base_documents >= 8,
        "profile leaves fewer than 8 base documents",
        file=display,
        field="target_documents",
    )
    # Derived roles sample base documents without replacement.
    required_base = (
        injection["exact_byte_copies"]
        + injection["exact_text_copies"]
        + injection["scanned_variants"]
        + injection["near_duplicate_documents"]
    )
    _require(
        profile.base_documents >= required_base,
        "base document count cannot supply the configured derived roles",
        file=display,
        field="injection",
    )
    return profile


def load_profiles(directory: Path) -> dict[str, Profile]:
    profiles: dict[str, Profile] = {}
    for path in sorted(directory.glob("*.json")):
        profile = load_profile(path)
        profiles[profile.corpus_id] = profile
    return profiles
