"""SPEC-0003 §4.2 BEIR manifest validation and fingerprinting (R23-R24).

The validator mirrors the Rust ``seeky-eval`` BEIR loader where the loader is
normative, and adds the WP-1.5 preparation invariants: a pinned terms digest,
a download-only license record, both split mappings, and complete local file
hashes.

The fingerprint must match the Rust loader byte-for-byte, so it is computed
over the *typed* manifest fields only (unknown keys are dropped, exactly like
serde's default struct deserialization) plus the sorted local file hashes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .canonical import canonical_json, sha256_bytes
from .errors import SCHEMA, fail

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
DATASET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

SPLITS = ("dev", "test")
CATEGORIES = (
    "known_item",
    "conceptual",
    "exact_identifier",
    "cross_lingual",
    "needle_in_haystack",
    "exploratory",
    "mixed_semantic_metadata",
    "code_search",
    "filename_partial",
)
BEIR_CATEGORIES = tuple(category for category in CATEGORIES if category != "code_search")
LANGUAGE_SLICES = ("pt", "en", "cross_lingual", "other", "non_latin_non_regression")
CONFIGURATIONS = ("default", "code_enabled")
BEIR_CONFIGURATION = "default"

LICENSE_KEYS = ("id", "url", "redistribution", "terms_url")
SOURCE_KEYS = ("revision", "urls", "sha256")
QUERY_DEFAULT_KEYS = ("language_slice", "category", "configuration")


def _require(condition: bool, location: str, message: str) -> None:
    if not condition:
        raise fail(SCHEMA, message, location=location)


def _string(value: Any, location: str) -> str:
    _require(isinstance(value, str) and value.strip() != "", location, "must be a nonempty string")
    return value  # type: ignore[return-value]


def _object(value: Any, location: str) -> dict[str, Any]:
    _require(isinstance(value, dict), location, "must be a JSON object")
    return value  # type: ignore[return-value]


def _hash(value: Any, location: str) -> str:
    text = _string(value, location)
    _require(bool(HASH_RE.match(text)), location, "must be 64 lowercase hex characters")
    return text


def validate_relative_path(value: Any, location: str) -> str:
    text = _string(value, location)
    _require(not text.startswith(("/", "\\")), location, "must be a relative path")
    normalized = text.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    _require(
        all(part != ".." for part in parts),
        location,
        "must not escape its root",
    )
    _require(bool(parts), location, "must name a file")
    return "/".join(parts)


def validate_manifest(
    manifest: Any,
    *,
    dataset_dir: Path | None = None,
    require_local_hashes: bool = True,
) -> dict[str, Any]:
    """Validate a loaded manifest and return it unchanged."""

    document = _object(manifest, "manifest")
    _require(document.get("schema_version") == 1, "manifest.schema_version", "must be 1")
    dataset_id = _string(document.get("dataset_id"), "manifest.dataset_id")
    _require(
        bool(DATASET_ID_RE.match(dataset_id)),
        "manifest.dataset_id",
        "must be lowercase ASCII with digits or dashes",
    )
    if dataset_dir is not None:
        _require(
            dataset_dir.name == dataset_id,
            "manifest.dataset_id",
            f"must match its directory name ({dataset_dir.name})",
        )
    _require(document.get("layout") == "beir", "manifest.layout", "must be 'beir'")
    _require(
        document.get("visibility") == "public",
        "manifest.visibility",
        "WP-1.5 manifests are public datasets only",
    )

    license_record = _object(document.get("license"), "manifest.license")
    for key in LICENSE_KEYS:
        _string(license_record.get(key), f"manifest.license.{key}")
    _require(
        license_record["redistribution"] == "download-only",
        "manifest.license.redistribution",
        "must be 'download-only': no evaluation data is redistributed",
    )

    source = _object(document.get("source"), "manifest.source")
    for key in SOURCE_KEYS:
        _require(key in source, f"manifest.source.{key}", "is required")
    _string(source["revision"], "manifest.source.revision")
    urls = source["urls"]
    hashes = source["sha256"]
    _require(isinstance(urls, list) and urls, "manifest.source.urls", "must be a nonempty list")
    _require(
        isinstance(hashes, list) and len(hashes) == len(urls),
        "manifest.source.sha256",
        "must be a list parallel to source.urls",
    )
    for index, url in enumerate(urls):
        _string(url, f"manifest.source.urls[{index}]")
        _require(
            url.startswith(("https://", "http://")),
            f"manifest.source.urls[{index}]",
            "must be an http(s) URL",
        )
    for index, digest in enumerate(hashes):
        _hash(digest, f"manifest.source.sha256[{index}]")
    _require(
        len({url.rsplit("/", 1)[-1] for url in urls}) == len(urls),
        "manifest.source.urls",
        "file names must be unique so the cache layout is unambiguous",
    )

    validate_relative_path(document.get("corpus"), "manifest.corpus")
    files_root = document.get("files_root")
    if files_root is not None:
        validate_relative_path(files_root, "manifest.files_root")

    splits = _object(document.get("splits"), "manifest.splits")
    _require(
        set(splits) == set(SPLITS),
        "manifest.splits",
        "must map exactly dev and test",
    )
    for name in SPLITS:
        split = _object(splits[name], f"manifest.splits.{name}")
        validate_relative_path(split.get("queries"), f"manifest.splits.{name}.queries")
        validate_relative_path(split.get("qrels"), f"manifest.splits.{name}.qrels")

    defaults = _object(document.get("query_defaults"), "manifest.query_defaults")
    for key in QUERY_DEFAULT_KEYS:
        _string(defaults.get(key), f"manifest.query_defaults.{key}")
    _require(
        defaults["category"] in BEIR_CATEGORIES,
        "manifest.query_defaults.category",
        "must be a non-code query category",
    )
    _require(
        defaults["language_slice"] in LANGUAGE_SLICES,
        "manifest.query_defaults.language_slice",
        "must be a known language slice",
    )
    _require(
        defaults["configuration"] == BEIR_CONFIGURATION,
        "manifest.query_defaults.configuration",
        "BEIR manifests must use the default configuration",
    )
    language = defaults.get("language")
    if language is not None:
        _string(language, "manifest.query_defaults.language")
    target_languages = defaults.get("target_languages", [])
    _require(
        isinstance(target_languages, list)
        and all(isinstance(item, str) and item for item in target_languages),
        "manifest.query_defaults.target_languages",
        "must be a list of nonempty strings",
    )

    transform = _object(document.get("transform"), "manifest.transform")
    _string(transform.get("script"), "manifest.transform.script")
    version = transform.get("version")
    _require(
        isinstance(version, int) and not isinstance(version, bool) and version >= 1,
        "manifest.transform.version",
        "must be an integer >= 1",
    )
    _string(transform.get("seed"), "manifest.transform.seed")

    terms = document.get("terms_sha256")
    _hash(terms, "manifest.terms_sha256")

    duplicate_clusters = document.get("duplicate_clusters")
    if duplicate_clusters is not None:
        validate_relative_path(duplicate_clusters, "manifest.duplicate_clusters")

    local_hashes = _object(document.get("local_file_sha256"), "manifest.local_file_sha256")
    if require_local_hashes:
        _require(
            bool(local_hashes),
            "manifest.local_file_sha256",
            "at least one local file hash is required",
        )
    for path, digest in local_hashes.items():
        validate_relative_path(path, f"manifest.local_file_sha256[{path}]")
        _hash(digest, f"manifest.local_file_sha256[{path}]")

    if require_local_hashes:
        required = [document["corpus"]]
        for name in SPLITS:
            required.append(splits[name]["queries"])
            required.append(splits[name]["qrels"])
        if duplicate_clusters is not None:
            required.append(duplicate_clusters)
        for path in required:
            _require(
                path in local_hashes,
                "manifest.local_file_sha256",
                f"required dataset file has no local hash: {path}",
            )

    return document


def typed_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """The manifest as the Rust ``BeirManifest`` struct serializes it."""

    license_record = manifest["license"]
    source = manifest["source"]
    defaults = manifest["query_defaults"]
    transform = manifest["transform"]
    splits = manifest["splits"]
    return {
        "schema_version": manifest["schema_version"],
        "dataset_id": manifest["dataset_id"],
        "layout": manifest["layout"],
        "visibility": manifest["visibility"],
        "license": {
            "id": license_record["id"],
            "url": license_record["url"],
            "redistribution": license_record["redistribution"],
            "terms_url": license_record["terms_url"],
        },
        "source": {
            "revision": source["revision"],
            "urls": list(source["urls"]),
            "sha256": list(source["sha256"]),
        },
        "corpus": manifest["corpus"],
        "files_root": manifest.get("files_root"),
        "splits": {
            name: {"queries": splits[name]["queries"], "qrels": splits[name]["qrels"]}
            for name in sorted(splits)
        },
        "query_defaults": {
            "language_slice": defaults["language_slice"],
            "category": defaults["category"],
            "configuration": defaults["configuration"],
            "language": defaults.get("language"),
            "target_languages": list(defaults.get("target_languages", [])),
        },
        "transform": {
            "script": transform["script"],
            "version": transform["version"],
            "seed": transform["seed"],
        },
        "duplicate_clusters": manifest.get("duplicate_clusters"),
    }


def dataset_fingerprint(
    manifest: dict[str, Any], local_hashes: dict[str, str]
) -> str:
    """SPEC-0003 §4.2 fingerprint, identical to the Rust loader's value."""

    payload = {
        "manifest": typed_manifest(manifest),
        "files": [
            {"path": path, "sha256": local_hashes[path]} for path in sorted(local_hashes)
        ],
    }
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def query_set_sha256(queries: list[dict[str, Any]]) -> str:
    """SPEC-0003 §4.2 query-set hash over the selected split's records."""

    records = [
        {
            "id": query["id"],
            "text": query["text"],
            "language": query["language"],
            "target_languages": list(query["target_languages"]),
            "language_slice": query["language_slice"],
            "category": query["category"],
            "configuration": query["configuration"],
            "split": query["split"],
            "filters": None,
        }
        for query in sorted(queries, key=lambda item: item["id"])
    ]
    return sha256_bytes(canonical_json(records).encode("utf-8"))
