"""Shared synthetic fixtures for dataset-fetch tests (no network, no bulk data)."""

from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path
from typing import Any

from dataset_fetch.canonical import sha256_bytes
from dataset_fetch.jsio import pretty_json_bytes

DATASET_ID = "beir-scifact"

CORPUS = [
    {"_id": "d1", "title": "Alpha", "text": "First document about induction."},
    {"_id": "d2", "title": "", "text": "Second document about magnets."},
    {"_id": "d3", "title": "Gamma", "text": "Third document about induction and magnets."},
    {"_id": "d4", "title": "Delta", "text": "Fourth document about tables."},
]

QUERIES = [
    {"_id": "q1", "text": "induction"},
    {"_id": "q2", "text": "magnets"},
    {"_id": "q3", "text": "third"},
    {"_id": "q4", "text": "alpha"},
]

QRELS_DEV = "query-id\tcorpus-id\tscore\nq1\td1\t2\nq2\td2\t1\n"
QRELS_TEST = "query-id\tcorpus-id\tscore\nq3\td3\t1\nq4\td1\t1\n"

TERMS = "Synthetic dataset terms for tests.\nLicense: MIT\n"


def jsonl(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(
        (json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        for row in rows
    )


def source_url(dataset_id: str, name: str) -> str:
    base = f"https://example.invalid/{dataset_id}"
    if name == "qrels.dev.tsv":
        return f"{base}/qrels/dev.tsv"
    if name == "qrels.test.tsv":
        return f"{base}/qrels/test.tsv"
    return f"{base}/{name}"


def source_files(dataset_id: str = DATASET_ID) -> dict[str, bytes]:
    return {
        "corpus.jsonl": jsonl(CORPUS),
        "queries.jsonl": jsonl(QUERIES),
        "qrels.dev.tsv": QRELS_DEV.encode("utf-8"),
        "qrels.test.tsv": QRELS_TEST.encode("utf-8"),
    }


def manifest(
    dataset_id: str = DATASET_ID,
    *,
    files_root: str | None = "data/files",
    license_id: str = "MIT",
    defaults: dict[str, Any] | None = None,
    sources: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    sources = sources or source_files(dataset_id)
    urls = [source_url(dataset_id, name) for name in sources]
    query_defaults = {
        "language_slice": "en",
        "category": "conceptual",
        "configuration": "default",
        "language": "en",
        "target_languages": ["en"],
    }
    if defaults:
        query_defaults.update(defaults)
    return {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "layout": "beir",
        "visibility": "public",
        "license": {
            "id": license_id,
            "url": "https://spdx.org/licenses/MIT.html",
            "redistribution": "download-only",
            "terms_url": f"https://example.invalid/{dataset_id}/terms.txt",
        },
        "source": {
            "revision": "synthetic-v1",
            "urls": urls,
            "sha256": [sha256_bytes(sources[name]) for name in sources],
        },
        "corpus": "data/corpus.jsonl",
        "files_root": files_root,
        "splits": {
            "dev": {"queries": "data/queries.dev.jsonl", "qrels": "data/qrels.dev.tsv"},
            "test": {"queries": "data/queries.test.jsonl", "qrels": "data/qrels.test.tsv"},
        },
        "query_defaults": query_defaults,
        "transform": {
            "script": "tools/dataset-fetch",
            "version": 1,
            "seed": "dataset-transform-v1",
        },
        "terms_sha256": sha256_bytes(TERMS.encode("utf-8")),
        "local_file_sha256": {},
    }


def write_dataset_dir(
    root: Path,
    *,
    dataset_id: str = DATASET_ID,
    manifest_value: dict[str, Any] | None = None,
) -> Path:
    dataset_dir = root / "bench" / "datasets" / dataset_id
    dataset_dir.mkdir(parents=True)
    value = manifest_value or manifest(dataset_id)
    (dataset_dir / "manifest.json").write_bytes(pretty_json_bytes(value))
    return dataset_dir


class FakeFetch:
    """Deterministic in-memory downloader recorded by URL."""

    def __init__(self, mapping: dict[str, bytes]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def __call__(self, url: str, dest: Path) -> None:
        self.calls.append(url)
        if url not in self.mapping:
            raise AssertionError(f"unexpected URL: {url}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.mapping[url])


def fetch_mapping(
    dataset_id: str = DATASET_ID, *, terms: bytes = TERMS
) -> dict[str, bytes]:
    mapping: dict[str, bytes] = {}
    for name, data in source_files(dataset_id).items():
        mapping[source_url(dataset_id, name)] = data
    mapping[f"https://example.invalid/{dataset_id}/terms.txt"] = terms.encode("utf-8")
    return mapping


def write_gzip_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as handle:
        for row in rows:
            handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))


def clean(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
