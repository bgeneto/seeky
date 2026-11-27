"""Verify a generated corpus tree (SPEC-0004-R4, R13, R25)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import FORMATS, PASSAGE_KINDS, sort_key_locator
from .derive import parse_iso_utc
from .errors import OUTPUT_HASH_MISMATCH, SCHEMA_INVALID, SdcError
from .jsonio import (
    canonical_json_sha256,
    load_json_file,
    read_jsonl_file,
    sha256_bytes,
    sha256_file,
)

SIDECARS = (
    "corpus.jsonl",
    "passages.jsonl",
    "extraction-truth.jsonl",
    "duplicate-clusters.jsonl",
    "versions.jsonl",
)
CLUSTER_KINDS = ("exact_byte", "exact_text", "near_duplicate", "version", "scanned_variant")
MANIFEST_KEYS = {
    "schema_version",
    "corpus_id",
    "profile_sha256",
    "source_set_sha256",
    "seed",
    "generator_version",
    "renderer_lock_sha256",
    "document_count",
    "passage_count",
    "default_roots",
    "code_enabled_roots",
    "injection_counts",
    "files",
    "sidecars",
    "corpus_hash",
}
CORPUS_KEYS = {"_id", "title", "text", "metadata"}
METADATA_KEYS = {
    "relative_path",
    "media_type",
    "format",
    "languages",
    "file_class",
    "source_set_id",
    "source_item_id",
    "source_sha256",
    "content_sha256",
    "text_sha256",
    "byte_count",
    "modified_at",
    "render_recipe_id",
    "duplicate_cluster_ids",
    "version_group_id",
    "version_number",
    "is_latest",
    "boilerplate_family_ids",
}
PASSAGE_KEYS = {
    "_id",
    "document_id",
    "text",
    "start_utf8",
    "end_utf8",
    "text_sha256",
    "kind",
    "locator",
    "boilerplate_family_id",
}


def _bad(message: str, *, file: str, line: int | None = None, field: str | None = None) -> None:
    raise SdcError(SCHEMA_INVALID, message, file=file, line=line, field=field)


def _check_keys(value: dict[str, Any], required: set[str], *, file: str, line: int | None = None) -> None:
    if set(value) != required:
        _bad(
            f"field mismatch: missing={sorted(required - set(value))} "
            f"unknown={sorted(set(value) - required)}",
            file=file,
            line=line,
        )


def _is_hex(value: Any, length: int = 64) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(char in "0123456789abcdef" for char in value)
    )


def _relative_file(root: Path, relative: str, *, field: str) -> Path:
    if not relative or relative.startswith("/") or "\\" in relative or ":" in relative:
        _bad(f"{field} must be a POSIX relative path", file="corpus.jsonl", field=field)
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        _bad(f"{field} has an invalid segment", file="corpus.jsonl", field=field)
    path = root / Path(relative)
    if not path.is_file():
        _bad(f"{field} does not exist", file="corpus.jsonl", field=field)
    return path


def verify_corpus(root: Path) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    manifest = load_json_file(manifest_path, display="manifest.json")
    if not isinstance(manifest, dict):
        _bad("manifest must be an object", file="manifest.json")
    _check_keys(manifest, MANIFEST_KEYS, file="manifest.json")
    if manifest["schema_version"] != 1:
        _bad("unsupported manifest schema_version", file="manifest.json", field="schema_version")
    if not isinstance(manifest["seed"], str) or not manifest["seed"]:
        _bad("seed must be nonempty", file="manifest.json", field="seed")
    for key in ("profile_sha256", "source_set_sha256", "renderer_lock_sha256"):
        if not _is_hex(manifest[key]):
            _bad(f"{key} must be 64 lowercase hex characters", file="manifest.json", field=key)
    if manifest["default_roots"] != ["files/documents"]:
        _bad("default_roots must be ['files/documents']", file="manifest.json", field="default_roots")
    if manifest["code_enabled_roots"] != ["files/documents", "files/code"]:
        _bad(
            "code_enabled_roots must be ['files/documents', 'files/code']",
            file="manifest.json",
            field="code_enabled_roots",
        )

    declared_files = manifest["files"]
    if not isinstance(declared_files, list):
        _bad("files must be an array", file="manifest.json", field="files")
    declared: dict[str, dict[str, Any]] = {}
    previous = ""
    for row in declared_files:
        if not isinstance(row, dict) or set(row) != {"path", "byte_count", "sha256"}:
            _bad("file rows need path, byte_count, and sha256", file="manifest.json", field="files")
        path = row["path"]
        if not isinstance(path, str) or path <= previous:
            _bad("files must be path-sorted and unique", file="manifest.json", field="files")
        previous = path
        declared[path] = row

    files_root = root / "files"
    actual: dict[str, Path] = {}
    if files_root.is_dir():
        for path in sorted(files_root.rglob("*")):
            if path.is_symlink():
                _bad("corpus must not contain symlinks", file=path.name)
            if path.is_file():
                actual[path.relative_to(root).as_posix()] = path
    missing = sorted(set(declared) - set(actual))
    added = sorted(set(actual) - set(declared))
    changed = sorted(
        path
        for path in set(declared) & set(actual)
        if sha256_file(actual[path]) != (declared[path]["sha256"], declared[path]["byte_count"])
    )
    if missing or added or changed:
        raise SdcError(
            OUTPUT_HASH_MISMATCH,
            f"file set mismatch: missing={missing[:3]} added={added[:3]} changed={changed[:3]}",
            file="manifest.json",
            field="files",
        )

    sidecars = manifest["sidecars"]
    if not isinstance(sidecars, dict) or set(sidecars) != set(SIDECARS):
        _bad("sidecars must name exactly the five sidecars", file="manifest.json", field="sidecars")
    for name in SIDECARS:
        digest, _ = sha256_file(root / name)
        if digest != sidecars[name]:
            raise SdcError(
                OUTPUT_HASH_MISMATCH,
                f"{name} digest does not match the manifest",
                file=name,
            )

    corpus_rows = read_jsonl_file(root / "corpus.jsonl", display="corpus.jsonl")
    passage_rows = read_jsonl_file(root / "passages.jsonl", display="passages.jsonl")
    truth_rows = read_jsonl_file(root / "extraction-truth.jsonl", display="extraction-truth.jsonl")
    cluster_rows = read_jsonl_file(root / "duplicate-clusters.jsonl", display="duplicate-clusters.jsonl")
    version_rows = read_jsonl_file(root / "versions.jsonl", display="versions.jsonl")

    documents: dict[str, dict[str, Any]] = {}
    previous_id = ""
    for line, row in enumerate(corpus_rows, start=1):
        _check_keys(row, CORPUS_KEYS, file="corpus.jsonl", line=line)
        doc_id = row["_id"]
        if not isinstance(doc_id, str) or not doc_id:
            _bad("document _id must be a nonempty string", file="corpus.jsonl", line=line)
        if doc_id <= previous_id:
            _bad("corpus.jsonl must be sorted by _id without duplicates", file="corpus.jsonl", line=line)
        previous_id = doc_id
        metadata = row["metadata"]
        if not isinstance(metadata, dict):
            _bad("metadata must be an object", file="corpus.jsonl", line=line)
        _check_keys(metadata, METADATA_KEYS, file="corpus.jsonl", line=line)
        relative = metadata["relative_path"]
        path = _relative_file(root, relative, field="relative_path")
        if metadata["format"] not in FORMATS:
            _bad("unknown format", file="corpus.jsonl", line=line, field="format")
        if metadata["file_class"] not in ("document", "source_code"):
            _bad("unknown file_class", file="corpus.jsonl", line=line, field="file_class")
        if metadata["file_class"] == "source_code":
            if not relative.startswith("files/code/"):
                _bad("source_code files must live under files/code", file="corpus.jsonl", line=line)
        elif relative.startswith("files/code/"):
            _bad("files/code must contain only source_code", file="corpus.jsonl", line=line)
        expected_digest, expected_size = sha256_file(path)
        if metadata["content_sha256"] != expected_digest or metadata["byte_count"] != expected_size:
            raise SdcError(
                OUTPUT_HASH_MISMATCH,
                f"content hash or byte count mismatch for {doc_id}",
                file="corpus.jsonl",
                line=line,
            )
        if metadata["text_sha256"] != sha256_bytes(row["text"].encode("utf-8")):
            raise SdcError(
                OUTPUT_HASH_MISMATCH,
                f"text hash mismatch for {doc_id}",
                file="corpus.jsonl",
                line=line,
            )
        if not isinstance(metadata["languages"], list) or not metadata["languages"]:
            _bad("languages must be a nonempty array", file="corpus.jsonl", line=line)
        if not _is_hex(metadata["source_sha256"]):
            _bad("source_sha256 must be 64 lowercase hex characters", file="corpus.jsonl", line=line)
        if not isinstance(metadata["duplicate_cluster_ids"], list) or not all(
            isinstance(item, str) for item in metadata["duplicate_cluster_ids"]
        ):
            _bad("duplicate_cluster_ids must be a string array", file="corpus.jsonl", line=line)
        if not isinstance(metadata["boilerplate_family_ids"], list):
            _bad("boilerplate_family_ids must be an array", file="corpus.jsonl", line=line)
        try:
            parse_iso_utc(str(metadata["modified_at"]))
        except SdcError as exc:
            _bad(
                f"modified_at is not a UTC timestamp: {metadata['modified_at']!r}",
                file="corpus.jsonl",
                line=line,
                field="modified_at",
            )
        version_values = (
            metadata["version_group_id"],
            metadata["version_number"],
            metadata["is_latest"],
        )
        if any(value is None for value in version_values) and not all(
            value is None for value in version_values
        ):
            _bad("version fields are either all null or all populated", file="corpus.jsonl", line=line)
        documents[doc_id] = row

    # Passages.
    passages_by_doc: dict[str, list[dict[str, Any]]] = {}
    passage_ids: set[str] = set()
    previous_passage = ""
    for line, row in enumerate(passage_rows, start=1):
        _check_keys(row, PASSAGE_KEYS, file="passages.jsonl", line=line)
        passage_id = row["_id"]
        if passage_id <= previous_passage:
            _bad("passages.jsonl must be sorted by _id without duplicates", file="passages.jsonl", line=line)
        previous_passage = passage_id
        passage_ids.add(passage_id)
        document = documents.get(row["document_id"])
        if document is None:
            _bad("dangling document_id", file="passages.jsonl", line=line)
        encoded = document["text"].encode("utf-8")
        start, end = row["start_utf8"], row["end_utf8"]
        if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(encoded)):
            _bad("passage offsets are out of bounds", file="passages.jsonl", line=line)
        if row["kind"] not in PASSAGE_KINDS:
            _bad("unknown passage kind", file="passages.jsonl", line=line)
        text = row["text"]
        if encoded[start:end].decode("utf-8") != text:
            _bad("passage text is not the exact document substring", file="passages.jsonl", line=line)
        if row["text_sha256"] != sha256_bytes(text.encode("utf-8")):
            raise SdcError(
                OUTPUT_HASH_MISMATCH,
                "passage text hash mismatch",
                file="passages.jsonl",
                line=line,
            )
        if row["locator"].get("block_id") is None:
            _bad("passage locator lacks block_id", file="passages.jsonl", line=line)
        passages_by_doc.setdefault(row["document_id"], []).append(row)
    for doc_id, rows in passages_by_doc.items():
        previous_end = -1
        previous_start = -1
        for row in rows:
            if row["start_utf8"] < previous_start:
                _bad(
                    f"passages for {doc_id} are not ordered by start offset",
                    file="passages.jsonl",
                )
            if row["start_utf8"] < previous_end and row["kind"] != "context":
                _bad(
                    f"overlapping passages in {doc_id}",
                    file="passages.jsonl",
                )
            previous_start = row["start_utf8"]
            previous_end = row["end_utf8"]
        families = {
            row["boilerplate_family_id"]
            for row in rows
            if row["boilerplate_family_id"] is not None
        }
        declared_families = set(documents[doc_id]["metadata"]["boilerplate_family_ids"])
        if families != declared_families:
            _bad(
                f"boilerplate families disagree for {doc_id}",
                file="passages.jsonl",
            )

    # Clusters.
    clusters: dict[str, dict[str, Any]] = {}
    previous_cluster = ""
    for line, row in enumerate(cluster_rows, start=1):
        if set(row) != {"cluster_id", "kind", "canonical_document_id", "member_document_ids"}:
            _bad("cluster row has the wrong fields", file="duplicate-clusters.jsonl", line=line)
        cluster_id = row["cluster_id"]
        if cluster_id <= previous_cluster:
            _bad("clusters must be sorted and unique", file="duplicate-clusters.jsonl", line=line)
        previous_cluster = cluster_id
        if row["kind"] not in CLUSTER_KINDS:
            _bad("unknown cluster kind", file="duplicate-clusters.jsonl", line=line)
        members = row["member_document_ids"]
        if (
            not isinstance(members, list)
            or len(members) < 2
            or len(set(members)) != len(members)
        ):
            _bad("cluster members must be distinct and at least two", file="duplicate-clusters.jsonl", line=line)
        if row["canonical_document_id"] not in members:
            _bad("cluster canonical document must be a member", file="duplicate-clusters.jsonl", line=line)
        for member in members:
            if member not in documents:
                _bad("cluster references an unknown document", file="duplicate-clusters.jsonl", line=line)
            if cluster_id not in documents[member]["metadata"]["duplicate_cluster_ids"]:
                _bad("member does not list the cluster", file="duplicate-clusters.jsonl", line=line)
        clusters[cluster_id] = row
    for doc_id, document in documents.items():
        for cluster_id in document["metadata"]["duplicate_cluster_ids"]:
            cluster = clusters.get(cluster_id)
            if cluster is None or doc_id not in cluster["member_document_ids"]:
                _bad("dangling duplicate_cluster_ids", file="corpus.jsonl")

    # Versions.
    previous_version = ""
    for line, row in enumerate(version_rows, start=1):
        if set(row) != {"version_group_id", "members"}:
            _bad("version row has the wrong fields", file="versions.jsonl", line=line)
        group_id = row["version_group_id"]
        if group_id <= previous_version:
            _bad("versions must be sorted and unique", file="versions.jsonl", line=line)
        previous_version = group_id
        members = row["members"]
        if not isinstance(members, list) or len(members) < 2:
            _bad("version groups need at least two members", file="versions.jsonl", line=line)
        numbers = [member.get("version_number") for member in members]
        if numbers != list(range(1, len(members) + 1)):
            _bad("version numbers must be consecutive from 1", file="versions.jsonl", line=line)
        latest = [member for member in members if member.get("is_latest") is True]
        if len(latest) != 1 or members[-1] is not latest[0]:
            _bad("exactly the last member must be latest", file="versions.jsonl", line=line)
        cluster = clusters.get(group_id)
        if cluster is None or cluster["kind"] != "version":
            _bad("version group lacks its version cluster", file="versions.jsonl", line=line)
        member_ids = [member["document_id"] for member in members]
        if sorted(member_ids) != sorted(cluster["member_document_ids"]):
            _bad("version cluster members disagree", file="versions.jsonl", line=line)
        if members[0]["changed_passages"]:
            _bad("the first version has no changed passages", file="versions.jsonl", line=line)
        for index, member in enumerate(members):
            document = documents.get(member["document_id"])
            if document is None:
                _bad("version references an unknown document", file="versions.jsonl", line=line)
            if document["metadata"]["version_group_id"] != group_id:
                _bad("document version metadata disagrees", file="corpus.jsonl")
            if document["metadata"]["version_number"] != member["version_number"]:
                _bad("document version number disagrees", file="corpus.jsonl")
            if index == 0:
                continue
            previous_members = {item["document_id"]: item for item in members[:index]}
            previous_id = members[index - 1]["document_id"]
            for change in member["changed_passages"]:
                if set(change) != {"change", "from_passage_id", "to_passage_id"}:
                    _bad("changed passage has the wrong fields", file="versions.jsonl", line=line)
                if change["change"] not in ("added", "removed", "modified"):
                    _bad("unknown change kind", file="versions.jsonl", line=line)
                if change["change"] == "added":
                    if change["from_passage_id"] is not None:
                        _bad("added change needs a null from_passage_id", file="versions.jsonl", line=line)
                    if change["to_passage_id"] not in passage_ids:
                        _bad("added change points to a missing passage", file="versions.jsonl", line=line)
                elif change["change"] == "removed":
                    if change["to_passage_id"] is not None:
                        _bad("removed change needs a null to_passage_id", file="versions.jsonl", line=line)
                    if change["from_passage_id"] not in passage_ids:
                        _bad("removed change points to a missing passage", file="versions.jsonl", line=line)
                else:
                    if (
                        change["from_passage_id"] not in passage_ids
                        or change["to_passage_id"] not in passage_ids
                    ):
                        _bad("modified change points to a missing passage", file="versions.jsonl", line=line)
                    if not change["from_passage_id"].startswith(previous_id + ":p:"):
                        _bad("modified change must reference the adjacent version", file="versions.jsonl", line=line)
                    if not change["to_passage_id"].startswith(member["document_id"] + ":p:"):
                        _bad("modified change must reference the member version", file="versions.jsonl", line=line)

    # Extraction truth.
    previous_truth: tuple[str, str] | None = None
    for line, row in enumerate(truth_rows, start=1):
        if set(row) != {"document_id", "locator", "text", "text_sha256", "truth_origin"}:
            _bad("extraction truth row has the wrong fields", file="extraction-truth.jsonl", line=line)
        if row["document_id"] not in documents:
            _bad("extraction truth references an unknown document", file="extraction-truth.jsonl", line=line)
        if not isinstance(row["locator"], dict) or not row["locator"]:
            _bad("extraction truth locator must be a nonempty object", file="extraction-truth.jsonl", line=line)
        key = (row["document_id"], sort_key_locator(row["locator"]))
        if previous_truth is not None and key <= previous_truth:
            _bad("extraction truth must be sorted by document and locator", file="extraction-truth.jsonl", line=line)
        previous_truth = key
        if row["truth_origin"] != "generator-known":
            _bad("unknown truth_origin", file="extraction-truth.jsonl", line=line)
        if row["text_sha256"] != sha256_bytes(row["text"].encode("utf-8")):
            raise SdcError(
                OUTPUT_HASH_MISMATCH,
                "extraction truth hash mismatch",
                file="extraction-truth.jsonl",
                line=line,
            )

    if manifest["document_count"] != len(documents):
        raise SdcError(
            OUTPUT_HASH_MISMATCH,
            "document_count does not match corpus.jsonl",
            file="manifest.json",
        )
    if manifest["passage_count"] != len(passage_rows):
        raise SdcError(
            OUTPUT_HASH_MISMATCH,
            "passage_count does not match passages.jsonl",
            file="manifest.json",
        )
    if len(declared) != len(documents):
        raise SdcError(
            OUTPUT_HASH_MISMATCH,
            "files and corpus.jsonl disagree on the rendered document count",
            file="manifest.json",
        )

    payload = {
        "files": manifest["files"],
        "sidecars": manifest["sidecars"],
        "default_roots": manifest["default_roots"],
        "code_enabled_roots": manifest["code_enabled_roots"],
    }
    if manifest["corpus_hash"] != canonical_json_sha256(payload):
        raise SdcError(
            OUTPUT_HASH_MISMATCH,
            "corpus_hash does not match the manifest payload",
            file="manifest.json",
        )

    allowed_top = {"manifest.json", "files", *SIDECARS}
    for entry in root.iterdir():
        if entry.name not in allowed_top:
            raise SdcError(
                OUTPUT_HASH_MISMATCH,
                f"unexpected entry in the corpus tree: {entry.name}",
                file="manifest.json",
            )

    return {
        "corpus_id": manifest["corpus_id"],
        "seed": manifest["seed"],
        "corpus_hash": manifest["corpus_hash"],
        "documents": len(documents),
        "passages": len(passage_rows),
        "files": len(declared),
        "bytes": sum(row["byte_count"] for row in declared.values()),
    }
