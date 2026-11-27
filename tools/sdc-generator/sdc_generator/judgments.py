"""Judgment-set validation, split freezing, and publication.

SPEC-0004 sections 4.1, 4.5-4.7, and 5.4-5.6. These commands are
development-only tooling: they never open a network connection, never import
an engine crate, and never write outside the requested paths.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .derive import digest, parse_iso_utc
from .errors import (
    IO_ERROR,
    OUTPUT_EXISTS,
    OUTPUT_HASH_MISMATCH,
    POOL_INCOMPLETE,
    PROVENANCE_INCOMPLETE,
    QREL_TARGET_STALE,
    SCHEMA_INVALID,
    TEST_NOT_ELIGIBLE,
    SdcError,
)
from .jsonio import (
    jsonl_bytes,
    load_json_file,
    pretty_json_bytes,
    read_jsonl_file,
    sha256_bytes,
    sha256_file,
    write_bytes,
    write_json_file,
)

CATEGORIES = (
    "known_item",
    "conceptual",
    "exact_identifier",
    "cross_language",
    "needle_in_haystack",
    "exploratory",
    "mixed_semantic_metadata",
    "code_search",
    "filename_partial",
)
LANGUAGE_SLICES = ("pt", "en", "cross_lingual", "other", "non_latin_non_regression")
CONFIGURATIONS = ("default", "code_enabled")
SPLITS = ("dev", "test")
SET_STATES = ("draft", "split_frozen", "frozen")
RECORD_STATES = ("draft", "verified", "adjudicated", "rejected")
EXPOSURES = ("unexposed", "exposed", "not-applicable")
ORIGINS = ("run", "known_target", "manual")

SET_MANIFEST_KEYS = {
    "schema_version",
    "judgment_set_id",
    "state",
    "split_seed",
    "compatible_corpus_hashes",
    "query_counts",
    "query_file_sha256",
    "file_sha256",
    "test_pool_system_ids",
    "supersedes",
    "test_exposure",
}
QUERY_KEYS = {
    "_id",
    "text",
    "language",
    "target_languages",
    "language_slice",
    "category",
    "configuration",
    "split",
    "filters",
    "provenance",
}
DOCUMENT_QREL_KEYS = {
    "judgment_set_id",
    "query_id",
    "document_id",
    "document_text_sha256",
    "grade",
    "evidence_passage_ids",
    "subtopic_labels",
    "provenance",
}
PASSAGE_QREL_KEYS = {
    "judgment_set_id",
    "query_id",
    "document_id",
    "passage_id",
    "passage_text_sha256",
    "grade",
    "evidence_spans",
    "provenance",
}
POOL_KEYS = {
    "query_id",
    "document_id",
    "passage_id",
    "origin",
    "run_id",
    "system_id",
    "rank",
    "corpus_hash",
}
PROVENANCE_KEYS = {"drafted_by", "verified_by", "state", "adjudicated_by"}
LLM_PROVENANCE_KEY = "llm_prompt_sha256"
TOOL_PROVENANCE_KEY = "tool_config_sha256"
FILTER_KEYS = {
    "extensions",
    "modified_after",
    "modified_before",
    "folder_prefix",
    "min_bytes",
    "max_bytes",
}

DRAFT_FILES = (
    "queries.draft.jsonl",
    "qrels.draft.documents.jsonl",
    "qrels.draft.passages.jsonl",
    "pools.draft.jsonl",
)
DRAFT_ROOT_SUFFIX = ("bench", "qrels", "sdc", "drafts")
_BCP47 = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_HUMAN = re.compile(r"^human:\S+$")
_LLM = re.compile(r"^llm:[^@\s]+@\S+$")
_TOOL = re.compile(r"^tool:[^@\s]+@\S+$")
# SPEC-0004 section 4.6: the categories where a template copies faithfully.
TOOL_DRAFT_CATEGORIES = frozenset(
    {
        "known_item",
        "exact_identifier",
        "needle_in_haystack",
        "mixed_semantic_metadata",
        "filename_partial",
        "code_search",
    }
)
_LABEL = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


@dataclass(frozen=True)
class _Row:
    data: dict[str, Any]
    file: str
    line: int


@dataclass(frozen=True)
class _Corpus:
    corpus_hash: str
    documents: dict[str, str]
    passages: dict[str, tuple[str, str, str]]


def _bad(message: str, *, file: str, line: int | None = None, field: str | None = None) -> None:
    raise SdcError(SCHEMA_INVALID, message, file=file, line=line, field=field)


def _stale(message: str, *, file: str, line: int | None = None, field: str | None = None) -> None:
    raise SdcError(QREL_TARGET_STALE, message, file=file, line=line, field=field)


def _prov(message: str, *, file: str, line: int | None = None, field: str | None = None) -> None:
    raise SdcError(PROVENANCE_INCOMPLETE, message, file=file, line=line, field=field)


def _ineligible(message: str, *, file: str, line: int | None = None, field: str | None = None) -> None:
    raise SdcError(TEST_NOT_ELIGIBLE, message, file=file, line=line, field=field)


def _pool(message: str, *, file: str, line: int | None = None, field: str | None = None) -> None:
    raise SdcError(POOL_INCOMPLETE, message, file=file, line=line, field=field)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _require_str(value: Any, field: str, *, file: str, line: int | None = None) -> str:
    if not isinstance(value, str) or not value:
        _bad(f"{field} must be a nonempty string", file=file, line=line, field=field)
    return value


def _check_keys(
    value: dict[str, Any], required: set[str], *, file: str, line: int | None = None
) -> None:
    if set(value) != required:
        _bad(
            f"field mismatch: missing={sorted(required - set(value))} "
            f"unknown={sorted(set(value) - required)}",
            file=file,
            line=line,
        )


def _check_ordering(
    rows: list[_Row], key: Callable[[dict[str, Any]], tuple[Any, ...]], message: str
) -> None:
    groups: dict[str, list[_Row]] = {}
    for row in rows:
        groups.setdefault(row.file, []).append(row)
    for file, items in groups.items():
        previous: tuple[Any, ...] | None = None
        for row in items:
            try:
                current = key(row.data)
                if previous is not None and current <= previous:
                    _bad(message, file=file, line=row.line)
            except (KeyError, TypeError, AttributeError):
                _bad(
                    "row lacks a comparable field needed for ordering",
                    file=file,
                    line=row.line,
                )
            previous = current


def _is_smoke(manifest: dict[str, Any]) -> bool:
    set_id = manifest["judgment_set_id"]
    return set_id == "sdc-smoke-v1" or set_id.startswith("sdc-smoke-")


def _is_under_drafts(root: Path) -> bool:
    parent_parts = root.resolve().parent.parts
    return tuple(parent_parts[-len(DRAFT_ROOT_SUFFIX) :]) == DRAFT_ROOT_SUFFIX


def _read_rows(path: Path, name: str, *, required: bool) -> list[_Row]:
    if not path.is_file():
        if required:
            _bad("required file is missing", file=name)
        return []
    rows = read_jsonl_file(path, display=name)
    return [_Row(data=row, file=name, line=index) for index, row in enumerate(rows, start=1)]


def _load_manifest(root: Path) -> dict[str, Any]:
    value = load_json_file(root / "judgment-set.json", display="judgment-set.json")
    if not isinstance(value, dict):
        _bad("judgment-set.json must be an object", file="judgment-set.json")
    return value


def _check_manifest(manifest: dict[str, Any], root: Path) -> None:
    file = "judgment-set.json"
    _check_keys(manifest, SET_MANIFEST_KEYS, file=file)
    if manifest["schema_version"] != 1:
        _bad("unsupported schema_version", file=file, field="schema_version")
    set_id = _require_str(manifest["judgment_set_id"], "judgment_set_id", file=file)
    if not set_id.isascii():
        _bad("judgment_set_id must be ASCII", file=file, field="judgment_set_id")
    if manifest["state"] not in SET_STATES:
        _bad("unknown state", file=file, field="state")
    seed = _require_str(manifest["split_seed"], "split_seed", file=file)
    try:
        seed.encode("ascii")
    except UnicodeEncodeError:
        _bad("split_seed must be ASCII", file=file, field="split_seed")
    if "\x00" in seed:
        _bad("split_seed must not contain NUL", file=file, field="split_seed")
    hashes = manifest["compatible_corpus_hashes"]
    if not isinstance(hashes, list) or not hashes:
        _bad(
            "compatible_corpus_hashes must be a nonempty array",
            file=file,
            field="compatible_corpus_hashes",
        )
    if not all(_is_hex(item) for item in hashes) or len(set(hashes)) != len(hashes):
        _bad(
            "compatible_corpus_hashes must be distinct lowercase SHA-256 values",
            file=file,
            field="compatible_corpus_hashes",
        )
    counts = manifest["query_counts"]
    if not isinstance(counts, dict) or set(counts) != set(SPLITS):
        _bad("query_counts must name dev and test", file=file, field="query_counts")
    for split in SPLITS:
        if not _is_int(counts[split]) or counts[split] < 0:
            _bad("query_counts values must be non-negative integers", file=file, field="query_counts")
    for name in ("query_file_sha256", "file_sha256"):
        mapping = manifest[name]
        if not isinstance(mapping, dict):
            _bad(f"{name} must be an object", file=file, field=name)
        if not all(isinstance(key, str) and key and _is_hex(value) for key, value in mapping.items()):
            _bad(f"{name} must map filenames to lowercase SHA-256 values", file=file, field=name)
    systems = manifest["test_pool_system_ids"]
    if not isinstance(systems, list) or not all(
        isinstance(item, str) and item for item in systems
    ):
        _bad("test_pool_system_ids must be a string array", file=file, field="test_pool_system_ids")
    if len(set(systems)) != len(systems):
        _bad("test_pool_system_ids must be distinct", file=file, field="test_pool_system_ids")
    supersedes = manifest["supersedes"]
    if supersedes is not None:
        if not isinstance(supersedes, str) or not supersedes or supersedes == set_id:
            _bad("supersedes must be null or a different judgment_set_id", file=file, field="supersedes")
    if manifest["test_exposure"] not in EXPOSURES:
        _bad("unknown test_exposure", file=file, field="test_exposure")
    state = manifest["state"]
    drafts = _is_under_drafts(root)
    if (state in ("draft", "split_frozen")) != drafts:
        _bad(
            "draft and split-frozen sets must live under a drafts directory",
            file=file,
            field="state",
        )
    if state == "draft":
        if manifest["query_file_sha256"] or manifest["file_sha256"]:
            _bad("a draft manifest must not freeze hashes", file=file, field="state")
    elif state == "split_frozen":
        if manifest["file_sha256"]:
            _bad("a split-frozen manifest must not freeze file hashes", file=file, field="state")
    else:
        if not manifest["file_sha256"]:
            _bad("a frozen manifest must record file hashes", file=file, field="state")


def _load_draft(root: Path, *, require_qrels: bool) -> dict[str, list[_Row]]:
    allowed = {"judgment-set.json", "reviewers.json", *DRAFT_FILES}
    for entry in root.iterdir():
        if entry.name not in allowed:
            _bad(f"unexpected entry in the draft: {entry.name}", file="judgment-set.json")
    return {
        "queries": _read_rows(root / DRAFT_FILES[0], DRAFT_FILES[0], required=True),
        "documents": _read_rows(
            root / DRAFT_FILES[1], DRAFT_FILES[1], required=require_qrels
        ),
        "passages": _read_rows(
            root / DRAFT_FILES[2], DRAFT_FILES[2], required=require_qrels
        ),
        "pools": _read_rows(root / DRAFT_FILES[3], DRAFT_FILES[3], required=False),
    }


def _published_names(smoke: bool) -> list[str]:
    names = [
        "queries.dev.jsonl",
        "qrels.dev.documents.jsonl",
        "qrels.dev.passages.jsonl",
        "pools.dev.jsonl",
    ]
    if not smoke:
        names.extend(
            [
                "queries.test.jsonl",
                "qrels.test.documents.jsonl",
                "qrels.test.passages.jsonl",
                "pools.test.jsonl",
            ]
        )
    return names


def _load_frozen(root: Path, manifest: dict[str, Any]) -> dict[str, list[_Row]]:
    names = _published_names(_is_smoke(manifest))
    allowed = {"judgment-set.json", "reviewers.json", *names}
    actual = {entry.name for entry in root.iterdir()}
    missing = sorted(set(names) - actual)
    extra = sorted(actual - allowed)
    if missing or extra:
        _bad(
            f"frozen layout mismatch: missing={missing} extra={extra}",
            file="judgment-set.json",
        )
    result: dict[str, list[_Row]] = {"queries": [], "documents": [], "passages": [], "pools": []}
    for name in names:
        if name.startswith("queries."):
            result["queries"].extend(_read_rows(root / name, name, required=True))
        elif name.endswith(".documents.jsonl"):
            result["documents"].extend(_read_rows(root / name, name, required=True))
        elif name.endswith(".passages.jsonl"):
            result["passages"].extend(_read_rows(root / name, name, required=True))
        else:
            result["pools"].extend(_read_rows(root / name, name, required=True))
    return result


def _load_corpus(root: Path) -> _Corpus:
    manifest = load_json_file(root / "manifest.json", display="manifest.json")
    if not isinstance(manifest, dict):
        _bad("corpus manifest must be an object", file="manifest.json")
    corpus_hash = manifest.get("corpus_hash")
    if not _is_hex(corpus_hash):
        _bad("corpus_hash must be 64 lowercase hex characters", file="manifest.json", field="corpus_hash")
    sidecars = manifest.get("sidecars")
    if not isinstance(sidecars, dict):
        _bad("corpus manifest sidecars must be an object", file="manifest.json", field="sidecars")
    for name in ("corpus.jsonl", "passages.jsonl"):
        digest_value, _ = sha256_file(root / name)
        if digest_value != sidecars.get(name):
            raise SdcError(
                OUTPUT_HASH_MISMATCH,
                f"{name} does not match the corpus manifest",
                file=name,
            )
    documents: dict[str, str] = {}
    for number, row in enumerate(read_jsonl_file(root / "corpus.jsonl", display="corpus.jsonl"), start=1):
        if not isinstance(row, dict) or not isinstance(row.get("_id"), str):
            _bad("corpus row needs a string _id", file="corpus.jsonl", line=number)
        text = row.get("text")
        metadata = row.get("metadata")
        if not isinstance(text, str) or not isinstance(metadata, dict):
            _bad("corpus row needs text and metadata", file="corpus.jsonl", line=number)
        expected = metadata.get("text_sha256")
        if not _is_hex(expected) or sha256_bytes(text.encode("utf-8")) != expected:
            _bad("corpus text hash is invalid", file="corpus.jsonl", line=number, field="text_sha256")
        if row["_id"] in documents:
            _bad("duplicate corpus document ID", file="corpus.jsonl", line=number)
        documents[row["_id"]] = expected
    passages: dict[str, tuple[str, str, str]] = {}
    for number, row in enumerate(read_jsonl_file(root / "passages.jsonl", display="passages.jsonl"), start=1):
        if not isinstance(row, dict) or not isinstance(row.get("_id"), str):
            _bad("passage row needs a string _id", file="passages.jsonl", line=number)
        document_id = row.get("document_id")
        if document_id not in documents:
            _bad("passage references an unknown document", file="passages.jsonl", line=number)
        text = row.get("text")
        if not isinstance(text, str):
            _bad("passage text must be a string", file="passages.jsonl", line=number)
        expected = row.get("text_sha256")
        if not _is_hex(expected) or sha256_bytes(text.encode("utf-8")) != expected:
            _bad("passage text hash is invalid", file="passages.jsonl", line=number, field="text_sha256")
        if row["_id"] in passages:
            _bad("duplicate passage ID", file="passages.jsonl", line=number)
        passages[row["_id"]] = (document_id, expected, text)
    return _Corpus(corpus_hash=corpus_hash, documents=documents, passages=passages)


def _check_compatible(manifest: dict[str, Any], corpus: _Corpus) -> None:
    if corpus.corpus_hash not in manifest["compatible_corpus_hashes"]:
        _bad(
            "corpus_hash is not listed in compatible_corpus_hashes",
            file="judgment-set.json",
            field="compatible_corpus_hashes",
        )


def _is_reviewer(value: Any) -> bool:
    """A human pseudonym or a pinned model identity (ADR-0026)."""
    return isinstance(value, str) and bool(_HUMAN.match(value) or _LLM.match(value))


def _validate_provenance(
    value: Any, *, file: str, line: int | None = None, field: str = "provenance"
) -> dict[str, Any]:
    if not isinstance(value, dict):
        _prov("provenance must be an object", file=file, line=line, field=field)
    unknown = set(value) - PROVENANCE_KEYS - {LLM_PROVENANCE_KEY, TOOL_PROVENANCE_KEY}
    if unknown:
        _bad(f"unknown provenance field(s): {sorted(unknown)}", file=file, line=line, field=field)
    missing = PROVENANCE_KEYS - set(value)
    if missing:
        _prov(f"provenance is missing {sorted(missing)}", file=file, line=line, field=field)
    drafted_by = value["drafted_by"]
    llm_draft = isinstance(drafted_by, str) and drafted_by.startswith("llm:")
    tool_draft = isinstance(drafted_by, str) and drafted_by.startswith("tool:")
    if not (
        isinstance(drafted_by, str)
        and (_HUMAN.match(drafted_by) or _LLM.match(drafted_by) or _TOOL.match(drafted_by))
    ):
        _prov(
            "drafted_by must be human:<id>, llm:<model>@<revision>, or tool:<id>@<version>",
            file=file,
            line=line,
            field="drafted_by",
        )
    if llm_draft:
        if LLM_PROVENANCE_KEY not in value or not _is_hex(value[LLM_PROVENANCE_KEY]):
            _prov("an LLM draft needs a lowercase SHA-256 llm_prompt_sha256", file=file, line=line, field=LLM_PROVENANCE_KEY)
    elif LLM_PROVENANCE_KEY in value:
        _bad("llm_prompt_sha256 is valid only for an LLM draft", file=file, line=line, field=LLM_PROVENANCE_KEY)
    if tool_draft:
        if TOOL_PROVENANCE_KEY not in value or not _is_hex(value[TOOL_PROVENANCE_KEY]):
            _prov("a tool draft needs a lowercase SHA-256 tool_config_sha256", file=file, line=line, field=TOOL_PROVENANCE_KEY)
    elif TOOL_PROVENANCE_KEY in value:
        _bad("tool_config_sha256 is valid only for a tool draft", file=file, line=line, field=TOOL_PROVENANCE_KEY)
    verified_by = value["verified_by"]
    if not isinstance(verified_by, list) or not all(_is_reviewer(item) for item in verified_by):
        _prov(
            "verified_by must be an array of human:<id> or llm:<model>@<revision> values",
            file=file,
            line=line,
            field="verified_by",
        )
    # ADR-0026: a model reviewer never verifies its own draft.
    if isinstance(drafted_by, str) and llm_draft and drafted_by in verified_by:
        _prov("a model may not verify its own draft", file=file, line=line, field="verified_by")
    if len(set(verified_by)) != len(verified_by):
        _prov("verified_by must be distinct", file=file, line=line, field="verified_by")
    state = value["state"]
    if state not in RECORD_STATES:
        _prov("unknown provenance state", file=file, line=line, field="state")
    if state in ("verified", "adjudicated") and not verified_by:
        _prov("a verified or adjudicated record needs verified_by", file=file, line=line, field="verified_by")
    adjudicated_by = value["adjudicated_by"]
    if state == "adjudicated":
        if not _is_reviewer(adjudicated_by):
            _prov("adjudicated_by must name a reviewer", file=file, line=line, field="adjudicated_by")
        if adjudicated_by not in verified_by:
            _prov("adjudicated_by must appear in verified_by", file=file, line=line, field="adjudicated_by")
        if len(set(verified_by)) < 2:
            _prov("adjudication needs two distinct reviewers", file=file, line=line, field="verified_by")
    elif adjudicated_by is not None:
        _prov("adjudicated_by must be null unless state is adjudicated", file=file, line=line, field="adjudicated_by")
    return value


def _require_eligible(provenance: dict[str, Any], *, file: str, line: int | None = None) -> None:
    if provenance["state"] not in ("verified", "adjudicated"):
        _ineligible(
            "record is not verified or adjudicated",
            file=file,
            line=line,
            field="provenance.state",
        )


def _validate_filters(value: Any, *, category: str, file: str, line: int) -> None:
    if category != "mixed_semantic_metadata":
        if value is not None:
            _bad("filters must be null outside mixed_semantic_metadata", file=file, line=line, field="filters")
        return
    if not isinstance(value, dict) or not value:
        _bad(
            "mixed_semantic_metadata needs a nonempty filters object",
            file=file,
            line=line,
            field="filters",
        )
    unknown = set(value) - FILTER_KEYS
    if unknown:
        _bad(f"unknown filter(s): {sorted(unknown)}", file=file, line=line, field="filters")
    if "extensions" in value:
        extensions = value["extensions"]
        if not isinstance(extensions, list) or not extensions or not all(
            isinstance(item, str) and item for item in extensions
        ):
            _bad("extensions must be a nonempty string array", file=file, line=line, field="filters.extensions")
    for key in ("modified_after", "modified_before"):
        if key in value:
            if not isinstance(value[key], str):
                _bad(f"{key} must be a UTC timestamp", file=file, line=line, field=f"filters.{key}")
            parse_iso_utc(value[key], file=file, field=f"filters.{key}")
    if "folder_prefix" in value:
        prefix = value["folder_prefix"]
        if not isinstance(prefix, str) or not prefix:
            _bad("folder_prefix must be a nonempty string", file=file, line=line, field="filters.folder_prefix")
        if prefix.startswith("/") or "\\" in prefix or ":" in prefix:
            _bad("folder_prefix must be corpus-relative", file=file, line=line, field="filters.folder_prefix")
        parts = prefix.split("/")
        if any(part in (".", "..") for part in parts if part):
            _bad("folder_prefix must not contain dot segments", file=file, line=line, field="filters.folder_prefix")
    for key in ("min_bytes", "max_bytes"):
        if key in value and (not _is_int(value[key]) or value[key] < 0):
            _bad(f"{key} must be a non-negative integer", file=file, line=line, field=f"filters.{key}")
    if "min_bytes" in value and "max_bytes" in value and value["min_bytes"] > value["max_bytes"]:
        _bad("min_bytes must not exceed max_bytes", file=file, line=line, field="filters")


def _validate_query_row(row: _Row, manifest: dict[str, Any]) -> None:
    data = row.data
    _check_keys(data, QUERY_KEYS, file=row.file, line=row.line)
    _require_str(data["_id"], "_id", file=row.file, line=row.line)
    if not data["_id"].isascii():
        _bad("query _id must be ASCII", file=row.file, line=row.line, field="_id")
    _require_str(data["text"], "text", file=row.file, line=row.line)
    language = _require_str(data["language"], "language", file=row.file, line=row.line)
    if not _BCP47.match(language):
        _bad("language must be BCP-47", file=row.file, line=row.line, field="language")
    targets = data["target_languages"]
    if not isinstance(targets, list) or not targets or not all(
        isinstance(item, str) and _BCP47.match(item) for item in targets
    ):
        _bad("target_languages must be a nonempty BCP-47 array", file=row.file, line=row.line, field="target_languages")
    if data["language_slice"] not in LANGUAGE_SLICES:
        _bad("unknown language_slice", file=row.file, line=row.line, field="language_slice")
    if data["category"] not in CATEGORIES:
        _bad("unknown category", file=row.file, line=row.line, field="category")
    if data["configuration"] not in CONFIGURATIONS:
        _bad("unknown configuration", file=row.file, line=row.line, field="configuration")
    if data["category"] == "code_search" and data["configuration"] != "code_enabled":
        _bad("code_search queries require configuration = code_enabled", file=row.file, line=row.line, field="configuration")
    if data["split"] not in SPLITS:
        _bad("unknown split", file=row.file, line=row.line, field="split")
    file_split = _file_split(row.file)
    if file_split is not None and data["split"] != file_split:
        _bad("query split disagrees with the file split", file=row.file, line=row.line, field="split")
    _validate_filters(data["filters"], category=data["category"], file=row.file, line=row.line)
    _validate_provenance(data["provenance"], file=row.file, line=row.line)
    _check_tool_scope(data["provenance"], data, file=row.file, line=row.line)


def _check_tool_scope(
    provenance: dict[str, Any], query: dict[str, Any], *, file: str, line: int | None
) -> None:
    """Keep tool drafts out of semantic paraphrase and pt<->en (SPEC-0004 4.6)."""
    if not str(provenance["drafted_by"]).startswith("tool:"):
        return
    if query["category"] not in TOOL_DRAFT_CATEGORIES or query["language_slice"] == "cross_lingual":
        _bad(
            f"a tool may not draft a {query['category']}/{query['language_slice']} record; "
            "use human: or llm: provenance",
            file=file,
            line=line,
            field="drafted_by",
        )


def _validate_queries(rows: list[_Row], manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _check_ordering(rows, lambda data: (data["_id"],), "queries must be sorted by _id without duplicates")
    queries: dict[str, dict[str, Any]] = {}
    for row in rows:
        _validate_query_row(row, manifest)
        queries[row.data["_id"]] = row.data
    return queries


def _file_split(name: str) -> str | None:
    for split in SPLITS:
        if f".{split}." in name or name.endswith(f".{split}.jsonl"):
            return split
    return None


def _query_for(data: dict[str, Any], queries: dict[str, dict[str, Any]], *, file: str, line: int) -> dict[str, Any]:
    query_id = data.get("query_id")
    if not isinstance(query_id, str) or query_id not in queries:
        _bad("judgment references an unknown query_id", file=file, line=line, field="query_id")
    split = _file_split(file)
    if split is not None and queries[query_id]["split"] != split:
        _bad("query split disagrees with the file split", file=file, line=line, field="query_id")
    return queries[query_id]


def _validate_passage_qrels(
    rows: list[_Row],
    manifest: dict[str, Any],
    queries: dict[str, dict[str, Any]],
    corpus: _Corpus | None,
) -> tuple[dict[tuple[str, str, str], int], set[tuple[str, str, str]]]:
    _check_ordering(
        rows,
        lambda data: (data["query_id"], data["document_id"], data["passage_id"]),
        "passage qrels must be sorted by query, document, and passage without duplicates",
    )
    grades: dict[tuple[str, str, str], int] = {}
    for row in rows:
        data = row.data
        _check_keys(data, PASSAGE_QREL_KEYS, file=row.file, line=row.line)
        if data["judgment_set_id"] != manifest["judgment_set_id"]:
            _bad("judgment_set_id disagrees with the manifest", file=row.file, line=row.line, field="judgment_set_id")
        query = _query_for(data, queries, file=row.file, line=row.line)
        document_id = _require_str(data["document_id"], "document_id", file=row.file, line=row.line)
        passage_id = _require_str(data["passage_id"], "passage_id", file=row.file, line=row.line)
        if not passage_id.startswith(document_id + ":p:"):
            _bad("passage_id does not belong to document_id", file=row.file, line=row.line, field="passage_id")
        if not _is_hex(data["passage_text_sha256"]):
            _bad("passage_text_sha256 must be lowercase SHA-256", file=row.file, line=row.line, field="passage_text_sha256")
        grade = data["grade"]
        if not _is_int(grade) or not 0 <= grade <= 3:
            _bad("grade must be an integer in 0..=3", file=row.file, line=row.line, field="grade")
        spans = data["evidence_spans"]
        if not isinstance(spans, list):
            _bad("evidence_spans must be an array", file=row.file, line=row.line, field="evidence_spans")
        previous_end = -1
        encoded: bytes | None = None
        if corpus is not None:
            passage = corpus.passages.get(passage_id)
            if passage is None or passage[0] != document_id:
                _bad("passage does not exist in the corpus", file=row.file, line=row.line, field="passage_id")
            if passage[1] != data["passage_text_sha256"]:
                _stale("passage_text_sha256 does not match the corpus", file=row.file, line=row.line, field="passage_text_sha256")
            encoded = passage[2].encode("utf-8")
        for span in spans:
            if not isinstance(span, dict) or set(span) != {"start_utf8", "end_utf8"}:
                _bad("evidence span needs start_utf8 and end_utf8", file=row.file, line=row.line, field="evidence_spans")
            start, end = span["start_utf8"], span["end_utf8"]
            if not _is_int(start) or not _is_int(end) or start < 0 or start >= end:
                _bad("evidence spans need ordered nonzero UTF-8 offsets", file=row.file, line=row.line, field="evidence_spans")
            if start < previous_end:
                _bad("evidence spans must be ordered and nonoverlapping", file=row.file, line=row.line, field="evidence_spans")
            if encoded is not None:
                if end > len(encoded):
                    _bad("evidence span is outside the passage", file=row.file, line=row.line, field="evidence_spans")
                try:
                    encoded[start:end].decode("utf-8")
                except UnicodeDecodeError:
                    _bad("evidence span splits a UTF-8 character", file=row.file, line=row.line, field="evidence_spans")
            previous_end = end
        _validate_provenance(data["provenance"], file=row.file, line=row.line)
        _check_tool_scope(data["provenance"], query, file=row.file, line=row.line)
        grades[(data["query_id"], document_id, passage_id)] = grade
    return grades, set(grades)


def _validate_document_qrels(
    rows: list[_Row],
    manifest: dict[str, Any],
    queries: dict[str, dict[str, Any]],
    corpus: _Corpus | None,
    passage_grades: dict[tuple[str, str, str], int],
    passage_ids: set[tuple[str, str, str]],
) -> set[tuple[str, str]]:
    _check_ordering(
        rows,
        lambda data: (data["query_id"], data["document_id"]),
        "document qrels must be sorted by query and document without duplicates",
    )
    judged: set[tuple[str, str]] = set()
    for row in rows:
        data = row.data
        _check_keys(data, DOCUMENT_QREL_KEYS, file=row.file, line=row.line)
        if data["judgment_set_id"] != manifest["judgment_set_id"]:
            _bad("judgment_set_id disagrees with the manifest", file=row.file, line=row.line, field="judgment_set_id")
        query = _query_for(data, queries, file=row.file, line=row.line)
        document_id = _require_str(data["document_id"], "document_id", file=row.file, line=row.line)
        if not _is_hex(data["document_text_sha256"]):
            _bad("document_text_sha256 must be lowercase SHA-256", file=row.file, line=row.line, field="document_text_sha256")
        grade = data["grade"]
        if not _is_int(grade) or not 0 <= grade <= 3:
            _bad("grade must be an integer in 0..=3", file=row.file, line=row.line, field="grade")
        evidence = data["evidence_passage_ids"]
        if not isinstance(evidence, list) or not all(isinstance(item, str) and item for item in evidence):
            _bad("evidence_passage_ids must be a string array", file=row.file, line=row.line, field="evidence_passage_ids")
        if len(set(evidence)) != len(evidence):
            _bad("evidence_passage_ids must be distinct", file=row.file, line=row.line, field="evidence_passage_ids")
        if grade == 0 and evidence:
            _bad("grade 0 must not carry evidence passages", file=row.file, line=row.line, field="evidence_passage_ids")
        if grade in (2, 3) and not evidence:
            _bad("grades 2 and 3 need at least one evidence passage", file=row.file, line=row.line, field="evidence_passage_ids")
        if corpus is not None:
            expected = corpus.documents.get(document_id)
            if expected is None:
                _bad("document does not exist in the corpus", file=row.file, line=row.line, field="document_id")
            if expected != data["document_text_sha256"]:
                _stale("document_text_sha256 does not match the corpus", file=row.file, line=row.line, field="document_text_sha256")
        for passage_id in evidence:
            key = (data["query_id"], document_id, passage_id)
            if key not in passage_ids:
                _bad("evidence passage does not belong to the document", file=row.file, line=row.line, field="evidence_passage_ids")
            if passage_grades.get(key, 0) <= 0:
                _bad("evidence passage needs a positive passage judgment", file=row.file, line=row.line, field="evidence_passage_ids")
        labels = data["subtopic_labels"]
        if not isinstance(labels, list):
            _bad("subtopic_labels must be an array", file=row.file, line=row.line, field="subtopic_labels")
        if query["category"] != "exploratory" and labels:
            _bad("subtopic_labels are valid only for exploratory queries", file=row.file, line=row.line, field="subtopic_labels")
        if query["category"] == "exploratory" and grade >= 2 and not labels:
            _bad("exploratory grades 2 and 3 need subtopic_labels", file=row.file, line=row.line, field="subtopic_labels")
        if any(not isinstance(label, str) or not _LABEL.match(label) for label in labels):
            _bad("subtopic labels must be ASCII snake_case", file=row.file, line=row.line, field="subtopic_labels")
        _validate_provenance(data["provenance"], file=row.file, line=row.line)
        _check_tool_scope(data["provenance"], query, file=row.file, line=row.line)
        judged.add((data["query_id"], document_id))
    return judged


def _validate_pools(
    rows: list[_Row],
    manifest: dict[str, Any],
    queries: dict[str, dict[str, Any]],
    corpus: _Corpus | None,
) -> None:
    _check_ordering(
        rows,
        lambda data: (
            data["query_id"],
            data["document_id"],
            data["passage_id"] or "",
            data["origin"],
            data["run_id"] or "",
        ),
        "pools must be sorted by query, document, passage, origin, and run without duplicates",
    )
    state = manifest["state"]
    for row in rows:
        data = row.data
        _check_keys(data, POOL_KEYS, file=row.file, line=row.line)
        query = _query_for(data, queries, file=row.file, line=row.line)
        document_id = _require_str(data["document_id"], "document_id", file=row.file, line=row.line)
        passage_id = data["passage_id"]
        if passage_id is not None:
            _require_str(passage_id, "passage_id", file=row.file, line=row.line)
            if not passage_id.startswith(document_id + ":p:"):
                _bad("passage_id does not belong to document_id", file=row.file, line=row.line, field="passage_id")
        origin = data["origin"]
        if origin not in ORIGINS:
            _bad("unknown pool origin", file=row.file, line=row.line, field="origin")
        if origin == "run":
            _require_str(data["run_id"], "run_id", file=row.file, line=row.line)
            _require_str(data["system_id"], "system_id", file=row.file, line=row.line)
            rank = data["rank"]
            if not _is_int(rank) or not 1 <= rank <= 20:
                _bad("a run pool row needs rank 1..=20", file=row.file, line=row.line, field="rank")
            if query["split"] == "test" and state != "draft":
                if data["system_id"] not in manifest["test_pool_system_ids"]:
                    _ineligible(
                        "test pool rows must come from the predeclared panel",
                        file=row.file,
                        line=row.line,
                        field="system_id",
                    )
        else:
            if any(data[key] is not None for key in ("run_id", "system_id", "rank")):
                _bad("non-run pool rows need null run_id, system_id, and rank", file=row.file, line=row.line)
        if not _is_hex(data["corpus_hash"]):
            _bad("pool corpus_hash must be lowercase SHA-256", file=row.file, line=row.line, field="corpus_hash")
        if data["corpus_hash"] not in manifest["compatible_corpus_hashes"]:
            _bad("pool corpus_hash is not compatible with the set", file=row.file, line=row.line, field="corpus_hash")
        if corpus is not None:
            if document_id not in corpus.documents:
                _bad("pool references an unknown document", file=row.file, line=row.line, field="document_id")
            if passage_id is not None:
                passage = corpus.passages.get(passage_id)
                if passage is None or passage[0] != document_id:
                    _bad("pool references an unknown passage", file=row.file, line=row.line, field="passage_id")


def _check_pool_coverage(
    pools: list[_Row],
    document_judged: set[tuple[str, str]],
    passage_judged: set[tuple[str, str, str]],
) -> None:
    for row in pools:
        data = row.data
        if data["passage_id"] is None:
            key = (data["query_id"], data["document_id"])
            if key not in document_judged:
                _pool("pooled document has no explicit judgment", file=row.file, line=row.line)
        else:
            key = (data["query_id"], data["document_id"], data["passage_id"])
            if key not in passage_judged:
                _pool("pooled passage has no explicit judgment", file=row.file, line=row.line)


def _eligible_queries(queries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [query for query in queries.values() if query["provenance"]["state"] != "rejected"]


def _validate_assignment(
    queries: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    *,
    file: str = "queries.draft.jsonl",
) -> None:
    included = _eligible_queries(queries)
    if _is_smoke(manifest):
        for query in included:
            if query["split"] != "dev":
                _ineligible(
                    "sdc-smoke-v1 must not contain a test split",
                    file=file,
                    field="split",
                )
        return
    strata: dict[tuple[str, str, str], list[str]] = {}
    for query in included:
        key = (query["category"], query["language_slice"], query["configuration"])
        strata.setdefault(key, []).append(query["_id"])
    seed = manifest["split_seed"]
    expected: dict[str, str] = {}
    for key, ids in strata.items():
        if len(ids) % 2:
            _bad(
                f"stratum {key} has an odd number of queries ({len(ids)})",
                file=file,
                field="split",
            )
        ordered = sorted(ids, key=lambda qid: (digest(seed, "query-split-order", qid), qid))
        for index in range(0, len(ordered), 2):
            first, second = ordered[index], ordered[index + 1]
            direction = min(first, second)
            u = int.from_bytes(digest(seed, "query-split-direction", direction)[:8], "big") / (1 << 64)
            if u < 0.5:
                expected[first], expected[second] = "dev", "test"
            else:
                expected[first], expected[second] = "test", "dev"
    for query in included:
        if query["split"] != expected[query["_id"]]:
            _bad(
                f"query {query['_id']} split does not match the frozen assignment",
                file=file,
                field="split",
            )


def _validate_minima(
    queries: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    *,
    file: str = "queries.draft.jsonl",
) -> None:
    included = _eligible_queries(queries)
    if _is_smoke(manifest):
        by_category = {category: 0 for category in CATEGORIES}
        for query in included:
            if query["split"] == "test":
                _ineligible("sdc-smoke-v1 must not contain a test split", file=file, field="split")
            by_category[query["category"]] += 1
        for category, count in by_category.items():
            if count < 5:
                _bad(
                    f"minimum not met for category {category}: {count} < 5",
                    file=file,
                    field="category",
                )
        return
    total = len(included)
    if total < 600:
        _bad(f"minimum not met for queries: {total} < 600", file=file, field="split")
    for split in SPLITS:
        split_count = sum(1 for query in included if query["split"] == split)
        if split_count < 300:
            _bad(
                f"minimum not met for split {split}: {split_count} < 300",
                file=file,
                field="split",
            )
        for category in CATEGORIES:
            count = sum(
                1 for query in included if query["split"] == split and query["category"] == category
            )
            if count < 30:
                _bad(
                    f"minimum not met for {category} in {split}: {count} < 30",
                    file=file,
                    field="category",
                )
        pt = sum(
            1 for query in included if query["split"] == split and query["language_slice"] == "pt"
        )
        en = sum(
            1 for query in included if query["split"] == split and query["language_slice"] == "en"
        )
        cross = sum(
            1 for query in included if query["split"] == split and query["language_slice"] == "cross_lingual"
        )
        if pt < 40:
            _bad(f"minimum not met for Portuguese in {split}: {pt} < 40", file=file, field="language_slice")
        if en < 40:
            _bad(f"minimum not met for English in {split}: {en} < 40", file=file, field="language_slice")
        if cross < 30:
            _bad(f"minimum not met for cross-lingual in {split}: {cross} < 30", file=file, field="language_slice")
    pt_total = sum(1 for query in included if query["language_slice"] == "pt")
    en_total = sum(1 for query in included if query["language_slice"] == "en")
    if pt_total < 100:
        _bad(f"minimum not met for Portuguese: {pt_total} < 100", file=file, field="language_slice")
    if en_total < 100:
        _bad(f"minimum not met for English: {en_total} < 100", file=file, field="language_slice")
    non_latin = sum(
        1 for query in included if query["language_slice"] == "non_latin_non_regression"
    )
    if non_latin < 10:
        _bad(
            f"minimum not met for non-Latin non-regression: {non_latin} < 10",
            file=file,
            field="language_slice",
        )
    for language in ("es", "fr", "de"):
        count = sum(
            1 for query in included if query["language"].split("-")[0].lower() == language
        )
        if count < 20:
            _bad(
                f"minimum not met for {language}: {count} < 20",
                file=file,
                field="language",
            )


def _split_query_rows(
    queries: dict[str, dict[str, Any]], manifest: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    included = _eligible_queries(queries)
    splits = ["dev"] if _is_smoke(manifest) else list(SPLITS)
    return {
        split: sorted(
            (query for query in included if query["split"] == split),
            key=lambda query: query["_id"],
        )
        for split in splits
    }


def _document_qrel_key(data: dict[str, Any]) -> tuple[Any, ...]:
    return (data["query_id"], data["document_id"])


def _passage_qrel_key(data: dict[str, Any]) -> tuple[Any, ...]:
    return (data["query_id"], data["document_id"], data["passage_id"])


def _pool_key(data: dict[str, Any]) -> tuple[Any, ...]:
    return (
        data["query_id"],
        data["document_id"],
        data["passage_id"] or "",
        data["origin"],
        data["run_id"] or "",
    )


def _validate_query_hashes(
    queries: dict[str, dict[str, Any]], manifest: dict[str, Any]
) -> dict[str, str]:
    computed = {
        split: sha256_bytes(jsonl_bytes(rows))
        for split, rows in _split_query_rows(queries, manifest).items()
    }
    if computed != manifest["query_file_sha256"]:
        _bad(
            "query_file_sha256 does not match the frozen query membership",
            file="judgment-set.json",
            field="query_file_sha256",
        )
    return computed


def _validate_file_hashes(root: Path, manifest: dict[str, Any]) -> None:
    expected = set(_published_names(_is_smoke(manifest)))
    if set(manifest["file_sha256"]) != expected:
        _bad(
            "file_sha256 must name exactly the published JSONL files",
            file="judgment-set.json",
            field="file_sha256",
        )
    for name in sorted(expected):
        digest_value, _ = sha256_file(root / name)
        if digest_value != manifest["file_sha256"][name]:
            raise SdcError(
                OUTPUT_HASH_MISMATCH,
                f"{name} does not match the frozen manifest",
                file=name,
            )


def _check_reviewers(root: Path, rows: Iterable[dict[str, Any]]) -> None:
    path = root / "reviewers.json"
    if not path.is_file():
        return
    value = load_json_file(path, display="reviewers.json")
    if not isinstance(value, dict):
        _bad("reviewers.json must be an object", file="reviewers.json")
    ids: set[str] | None = None
    reviewers = value.get("reviewers")
    if isinstance(reviewers, list):
        ids = set()
        for item in reviewers:
            if not isinstance(item, dict) or not isinstance(item.get("reviewer_id"), str):
                _bad("reviewers must contain reviewer_id values", file="reviewers.json")
            ids.add(item["reviewer_id"])
    elif value and all(isinstance(item, (str, list)) for item in value.values()):
        ids = set(value)
    if ids is None:
        return
    for row in rows:
        provenance = row["provenance"]
        humans = [provenance["drafted_by"], *provenance["verified_by"]]
        if provenance["adjudicated_by"] is not None:
            humans.append(provenance["adjudicated_by"])
        for human in humans:
            if not human.startswith("human:"):
                continue
            if human[len("human:") :] not in ids:
                _prov(
                    f"reviewer {human} is not listed in reviewers.json",
                    file="reviewers.json",
                    field=human,
                )


def _summary(
    manifest: dict[str, Any],
    queries: dict[str, dict[str, Any]],
    documents: list[_Row],
    passages: list[_Row],
    pools: list[_Row],
) -> dict[str, Any]:
    included = _eligible_queries(queries)
    return {
        "judgment_set_id": manifest["judgment_set_id"],
        "state": manifest["state"],
        "queries": len(included),
        "documents": len(documents),
        "passages": len(passages),
        "pools": len(pools),
        "splits": {
            split: sum(1 for query in included if query["split"] == split)
            for split in SPLITS
        },
    }


def validate_judgment_set(
    set_dir: Path, corpus_root: Path, *, allow_draft: bool = False
) -> dict[str, Any]:
    """Validate a draft, split-frozen, or frozen judgment set offline."""

    root = Path(set_dir)
    manifest = _load_manifest(root)
    _check_manifest(manifest, root)
    state = manifest["state"]
    if state in ("draft", "split_frozen"):
        if not allow_draft:
            _ineligible(
                "a quarantined draft must be validated with --allow-draft",
                file="judgment-set.json",
                field="state",
            )
    elif allow_draft:
        _bad(
            "--allow-draft is valid only for a draft or split-frozen set",
            file="judgment-set.json",
            field="state",
        )
    corpus = _load_corpus(Path(corpus_root))
    _check_compatible(manifest, corpus)
    if state == "frozen":
        names = _load_frozen(root, manifest)
    else:
        names = _load_draft(root, require_qrels=False)

    queries = _validate_queries(names["queries"], manifest)
    if state == "split_frozen":
        for row in names["queries"]:
            if row.data["provenance"]["state"] != "rejected":
                _require_eligible(row.data["provenance"], file=row.file, line=row.line)
    passage_grades, passage_ids = _validate_passage_qrels(
        names["passages"], manifest, queries, corpus
    )
    document_judged = _validate_document_qrels(
        names["documents"], manifest, queries, corpus, passage_grades, passage_ids
    )
    _validate_pools(names["pools"], manifest, queries, corpus)
    _check_reviewers(
        root,
        [
            row.data
            for row in names["queries"] + names["documents"] + names["passages"]
        ],
    )

    if state in ("split_frozen", "frozen"):
        aggregate_file = "judgment-set.json" if state == "frozen" else "queries.draft.jsonl"
        _validate_assignment(queries, manifest, file=aggregate_file)
        _validate_minima(queries, manifest, file=aggregate_file)
        _validate_query_hashes(queries, manifest)
        _validate_pool_panel(manifest, queries)
        actual_counts = {
            split: sum(1 for query in _eligible_queries(queries) if query["split"] == split)
            for split in SPLITS
        }
        if manifest["query_counts"] != actual_counts:
            _bad("query_counts do not match the query records", file="judgment-set.json", field="query_counts")
    if state == "frozen":
        _validate_file_hashes(root, manifest)
        _check_pool_coverage(names["pools"], document_judged, passage_ids)
        for row in names["queries"] + names["documents"] + names["passages"]:
            if row.data["provenance"]["state"] == "rejected":
                _ineligible("a frozen set must omit rejected records", file=row.file, line=row.line)
            _require_eligible(row.data["provenance"], file=row.file, line=row.line)
        _validate_exposure(manifest)
    return _summary(manifest, queries, names["documents"], names["passages"], names["pools"])


def _validate_pool_panel(
    manifest: dict[str, Any], queries: dict[str, dict[str, Any]]
) -> None:
    smoke = _is_smoke(manifest)
    systems = manifest["test_pool_system_ids"]
    if smoke:
        if systems:
            _bad("sdc-smoke-v1 must not declare test_pool_system_ids", file="judgment-set.json", field="test_pool_system_ids")
        return
    has_test = any(query["split"] == "test" for query in _eligible_queries(queries))
    if manifest["state"] == "frozen" and has_test and not systems:
        _ineligible(
            "a published set with test queries needs a predeclared test_pool_system_ids panel",
            file="judgment-set.json",
            field="test_pool_system_ids",
        )


def _validate_exposure(manifest: dict[str, Any]) -> None:
    if _is_smoke(manifest):
        if manifest["test_exposure"] != "not-applicable":
            _bad("sdc-smoke-v1 test_exposure must be not-applicable", file="judgment-set.json", field="test_exposure")
    elif manifest["test_exposure"] not in ("unexposed", "exposed"):
        _bad("a full set test_exposure must be unexposed or exposed", file="judgment-set.json", field="test_exposure")


def freeze_split(draft_dir: Path) -> dict[str, Any]:
    """Freeze query membership and intended splits (SPEC-0004 section 5.4)."""

    root = Path(draft_dir)
    manifest = _load_manifest(root)
    _check_manifest(manifest, root)
    if manifest["state"] != "draft":
        _bad("freeze-split requires state = draft", file="judgment-set.json", field="state")
    names = _load_draft(root, require_qrels=False)
    queries = _validate_queries(names["queries"], manifest)
    for row in names["queries"]:
        if row.data["provenance"]["state"] != "rejected":
            _require_eligible(row.data["provenance"], file=row.file, line=row.line)
    _validate_assignment(queries, manifest)
    _validate_minima(queries, manifest)
    if names["pools"]:
        _ineligible(
            "split freeze must precede run pooling",
            file=names["pools"][0].file,
            line=names["pools"][0].line,
        )
    _check_reviewers(root, [row.data for row in names["queries"]])
    split_rows = _split_query_rows(queries, manifest)
    frozen = dict(manifest)
    frozen["state"] = "split_frozen"
    frozen["query_counts"] = {
        split: sum(1 for query in _eligible_queries(queries) if query["split"] == split)
        for split in SPLITS
    }
    frozen["query_file_sha256"] = {
        split: sha256_bytes(jsonl_bytes(rows)) for split, rows in split_rows.items()
    }
    frozen["file_sha256"] = {}
    write_json_file(root / "judgment-set.json", frozen)
    return _summary(frozen, queries, [], [], [])


def publish(draft_dir: Path, output_dir: Path) -> str:
    """Publish a split-frozen draft as an immutable frozen judgment set."""

    root = Path(draft_dir)
    output = Path(output_dir)
    if output.exists():
        raise SdcError(OUTPUT_EXISTS, f"output already exists: {output.name}", file=output.name)
    manifest = _load_manifest(root)
    _check_manifest(manifest, root)
    if manifest["state"] != "split_frozen":
        _ineligible(
            "publish requires a split-frozen draft",
            file="judgment-set.json",
            field="state",
        )
    names = _load_draft(root, require_qrels=True)
    queries = _validate_queries(names["queries"], manifest)
    for row in names["queries"]:
        state = row.data["provenance"]["state"]
        if state != "rejected":
            _require_eligible(row.data["provenance"], file=row.file, line=row.line)
    passage_grades, passage_ids = _validate_passage_qrels(
        names["passages"], manifest, queries, None
    )
    _validate_document_qrels(
        names["documents"], manifest, queries, None, passage_grades, passage_ids
    )
    _validate_pools(names["pools"], manifest, queries, None)
    _check_reviewers(
        root,
        [row.data for row in names["queries"] + names["documents"] + names["passages"]],
    )
    for row in names["documents"] + names["passages"]:
        state = row.data["provenance"]["state"]
        if state != "rejected":
            _require_eligible(row.data["provenance"], file=row.file, line=row.line)
    _validate_assignment(queries, manifest)
    _validate_minima(queries, manifest)
    _validate_query_hashes(queries, manifest)
    _validate_pool_panel({**manifest, "state": "frozen"}, queries)

    split_rows = _split_query_rows(queries, manifest)
    included_ids = {query["_id"] for rows in split_rows.values() for query in rows}
    for row in names["documents"] + names["passages"]:
        if row.data["provenance"]["state"] == "rejected":
            continue
        if row.data["query_id"] not in included_ids:
            _bad(
                "record references a query that will not be published",
                file=row.file,
                line=row.line,
                field="query_id",
            )
    for row in names["pools"]:
        if row.data["query_id"] not in included_ids:
            _bad(
                "pool row references a query that will not be published",
                file=row.file,
                line=row.line,
                field="query_id",
            )

    documents = [
        row.data for row in names["documents"] if row.data["provenance"]["state"] != "rejected"
    ]
    passages = [
        row.data for row in names["passages"] if row.data["provenance"]["state"] != "rejected"
    ]
    pools = [row.data for row in names["pools"]]
    included_passage_grades = {
        (row["query_id"], row["document_id"], row["passage_id"]): row["grade"]
        for row in passages
    }
    for row in documents:
        for passage_id in row["evidence_passage_ids"]:
            key = (row["query_id"], row["document_id"], passage_id)
            if included_passage_grades.get(key, 0) <= 0:
                _bad(
                    "an evidence passage was rejected or has no positive judgment",
                    file="qrels.draft.documents.jsonl",
                    field="evidence_passage_ids",
                )
    _check_pool_coverage(
        names["pools"],
        {(row["query_id"], row["document_id"]) for row in documents},
        set(included_passage_grades),
    )

    files: dict[str, bytes] = {}
    for split, query_rows in split_rows.items():
        split_documents = sorted(
            (row for row in documents if queries[row["query_id"]]["split"] == split),
            key=_document_qrel_key,
        )
        split_passages = sorted(
            (row for row in passages if queries[row["query_id"]]["split"] == split),
            key=_passage_qrel_key,
        )
        split_pools = sorted(
            (row for row in pools if queries[row["query_id"]]["split"] == split),
            key=_pool_key,
        )
        files[f"queries.{split}.jsonl"] = jsonl_bytes(query_rows)
        files[f"qrels.{split}.documents.jsonl"] = jsonl_bytes(split_documents)
        files[f"qrels.{split}.passages.jsonl"] = jsonl_bytes(split_passages)
        files[f"pools.{split}.jsonl"] = jsonl_bytes(split_pools)

    frozen = dict(manifest)
    frozen["state"] = "frozen"
    frozen["query_counts"] = {
        split: sum(1 for query in _eligible_queries(queries) if query["split"] == split)
        for split in SPLITS
    }
    frozen["file_sha256"] = {name: sha256_bytes(data) for name, data in files.items()}
    frozen["test_exposure"] = "not-applicable" if _is_smoke(manifest) else "unexposed"

    parent = output.parent
    temporary = parent / f".{output.name}.tmp"
    try:
        parent.mkdir(parents=True, exist_ok=True)
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir()
        for name, data in files.items():
            write_bytes(temporary / name, data)
        write_json_file(temporary / "judgment-set.json", frozen)
        reviewers = root / "reviewers.json"
        if reviewers.is_file():
            shutil.copyfile(reviewers, temporary / "reviewers.json")
        os.rename(temporary, output)
    except SdcError:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        raise SdcError(
            IO_ERROR,
            "cannot write the published judgment set",
            file=output.name,
        ) from exc
    return sha256_bytes(pretty_json_bytes(frozen))
