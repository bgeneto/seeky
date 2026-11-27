"""Acquire the frozen public text and OCR samples without committing content."""

from __future__ import annotations

import gzip
import hashlib
import heapq
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

import requests

from .artifacts import ArtifactError, download_file, sha256_file, write_json

MIRACL_ID = "miracl/miracl"
MIRACL_REVISION = "5be20db9509754dadad47689368639fcec739c00"
MIRACL_CORPUS_ID = "miracl/miracl-corpus"
MIRACL_CORPUS_REVISION = "d921ec7e349ce0d28daf30b2da9da5ee698bef0d"
MMARCO_ID = "unicamp-dl/mmarco"
MMARCO_REVISION = "6d039c4638c0ba3e46a9cb7b498b145e7edc6230"
SEED = "seeky-wp06-v1"
MINIMUM_FREE_BYTES = 50 * 1024**3


class DataError(RuntimeError):
    """A typed public-data acquisition or parsing failure."""


def parse_tsv_row(line: str, *, columns: int | None = None) -> list[str]:
    fields = line.rstrip("\r\n").split("\t")
    if columns is not None and len(fields) != columns:
        raise DataError("external TSV row has the wrong number of columns")
    if not fields or any(not field for field in fields):
        raise DataError("external TSV row contains an empty required field")
    return fields


def parse_qrels(text: str) -> dict[str, dict[str, int]]:
    qrels: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) == 4:
            query_id, _, doc_id, relevance = fields
        elif len(fields) == 3:
            query_id, doc_id, relevance = fields
        elif len(fields) == 2:
            query_id, doc_id = fields
            relevance = "1"
        else:
            raise DataError("external qrels row has an unsupported layout")
        try:
            value = int(relevance)
        except ValueError as error:
            raise DataError("external qrels relevance is not an integer") from error
        qrels.setdefault(query_id, {})[doc_id] = value
    if not qrels:
        raise DataError("external qrels file is empty")
    return qrels


def strip_gutenberg(text: str) -> str:
    start = re.search(
        r"^\*\*\* START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*\*\*\*$",
        text,
        flags=re.MULTILINE,
    )
    end = re.search(
        r"^\*\*\* END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*\*\*\*$",
        text,
        flags=re.MULTILINE,
    )
    if start is None or end is None or end.start() <= start.end():
        raise DataError("Project Gutenberg start/end markers were not found")
    body = text[start.end() : end.start()].strip()
    if not body:
        raise DataError("Project Gutenberg body is empty")
    return body


def _text_digest(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


class DeterministicReservoir:
    """Keep the smallest seeded hashes, independent of input order."""

    def __init__(
        self,
        capacity: int,
        seed: str,
        *,
        seen_text_digests: set[bytes] | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("reservoir capacity must be positive")
        self.capacity = capacity
        self.seed = seed.encode("utf-8")
        self._heap: list[tuple[int, int, dict[str, Any]]] = []
        self._counter = 0
        self._seen = seen_text_digests if seen_text_digests is not None else set()

    @property
    def seen_text_digests(self) -> set[bytes]:
        return self._seen

    def add(self, row: dict[str, Any]) -> bool:
        text = row["text"]
        digest = _text_digest(text)
        if digest in self._seen:
            return False
        self._seen.add(digest)
        identity = f"{row.get('id', '')}\0{text}".encode("utf-8")
        key = int.from_bytes(hashlib.sha256(self.seed + b"\0" + identity).digest(), "big")
        entry = (-key, self._counter, row)
        self._counter += 1
        if len(self._heap) < self.capacity:
            heapq.heappush(self._heap, entry)
        elif key < -self._heap[0][0]:
            heapq.heapreplace(self._heap, entry)
        return True

    def values(self) -> list[dict[str, Any]]:
        return [entry[2] for entry in sorted(self._heap, key=lambda entry: -entry[0])]


def _require_disk_budget(path: Path) -> None:
    if shutil.disk_usage(path).free < MINIMUM_FREE_BYTES:
        raise DataError("free disk is below the 50 GiB stop threshold")


def _hf_url(repository: str, revision: str, filename: str, *, dataset: bool = True) -> str:
    kind = "datasets" if dataset else "models"
    return f"https://huggingface.co/{kind}/{repository}/resolve/{revision}/{filename}"


def _cached_download(
    repository: str,
    revision: str,
    filename: str,
    raw_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    target = raw_dir / filename
    if not target.exists():
        try:
            download_file(_hf_url(repository, revision, filename), target)
        except ArtifactError as error:
            raise DataError("required public dataset file could not be downloaded") from error
    return target, {
        "repository": repository,
        "revision": revision,
        "filename": filename,
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise DataError("public text file cannot be decoded") from error


def _topics(text: str) -> dict[str, str]:
    topics: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t", maxsplit=1)
        if len(fields) != 2 or not fields[0] or not fields[1]:
            raise DataError("external topic row has an unsupported layout")
        topics[fields[0]] = fields[1]
    if not topics:
        raise DataError("external topics file is empty")
    return topics


def _miracl_shards() -> list[str]:
    url = f"https://huggingface.co/api/datasets/{MIRACL_CORPUS_ID}?blobs=false"
    try:
        response = requests.get(url, timeout=(15, 60))
        response.raise_for_status()
        siblings = response.json()["siblings"]
    except (requests.RequestException, KeyError, TypeError, ValueError) as error:
        raise DataError("MIRACL corpus file listing cannot be acquired") from error
    pattern = re.compile(r"miracl-corpus-v1\.0-en/docs-(\d+)\.jsonl\.gz$")
    shards = [item["rfilename"] for item in siblings if pattern.fullmatch(item.get("rfilename", ""))]
    if not shards:
        raise DataError("MIRACL English corpus has no downloadable shards")
    return sorted(shards, key=lambda name: int(pattern.fullmatch(name).group(1)))


def _iter_miracl_rows(path: Path) -> Iterable[dict[str, str]]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                doc_id = row["docid"]
                title = row.get("title", "")
                text = row["text"]
                combined = f"{title}\n{text}" if title else text
                if combined.strip():
                    yield {"id": str(doc_id), "text": combined}
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise DataError("MIRACL corpus shard is malformed") from error


def _iter_mmarco_rows(path: Path) -> Iterable[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            for line in stream:
                doc_id, text = parse_tsv_row(line, columns=2)
                if text.strip():
                    yield {"id": doc_id, "text": text}
    except (OSError, UnicodeError) as error:
        raise DataError("mMARCO Portuguese collection cannot be read") from error


def _frozen_digest(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def acquire_text_data(workspace: Path) -> dict[str, Any]:
    """Build the exact 1,024-passage/64-query set outside the repository."""
    data_dir = workspace / "data"
    frozen_path = data_dir / "frozen-text.json"
    summary_path = data_dir / "text-acquisition-summary.json"
    if frozen_path.exists():
        from .artifacts import load_json

        return load_json(frozen_path)
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    _require_disk_budget(workspace)
    source_files: list[dict[str, Any]] = []

    topics_name = "miracl-v1.0-en/topics/topics.miracl-v1.0-en-dev.tsv"
    qrels_name = "miracl-v1.0-en/qrels/qrels.miracl-v1.0-en-dev.tsv"
    topics_path, topics_record = _cached_download(MIRACL_ID, MIRACL_REVISION, topics_name, raw_dir)
    qrels_path, qrels_record = _cached_download(MIRACL_ID, MIRACL_REVISION, qrels_name, raw_dir)
    source_files.extend((topics_record, qrels_record))
    topics = _topics(_read_text(topics_path))
    all_qrels = parse_qrels(_read_text(qrels_path))
    query_ids = sorted(topics)[:32]
    if len(query_ids) != 32:
        raise DataError("MIRACL English dev has fewer than 32 queries")
    selected_qrels = {query_id: all_qrels.get(query_id, {}) for query_id in query_ids}
    wanted_doc_ids = {doc_id for qrels in selected_qrels.values() for doc_id in qrels}
    if not wanted_doc_ids:
        raise DataError("selected MIRACL queries have no judged passages")

    relevant: dict[str, dict[str, str]] = {}
    seen_texts: set[bytes] = set()
    others = DeterministicReservoir(512, SEED, seen_text_digests=seen_texts)
    for shard in _miracl_shards():
        _require_disk_budget(workspace)
        shard_path, shard_record = _cached_download(
            MIRACL_CORPUS_ID, MIRACL_CORPUS_REVISION, shard, raw_dir
        )
        source_files.append(shard_record)
        for row in _iter_miracl_rows(shard_path):
            digest = _text_digest(row["text"])
            if row["id"] in wanted_doc_ids:
                if row["id"] not in relevant:
                    relevant[row["id"]] = row
                    seen_texts.add(digest)
            elif digest not in seen_texts:
                others.add(row)

    missing = wanted_doc_ids.difference(relevant)
    if missing:
        raise DataError("MIRACL judged passages are missing from the published corpus")
    miracl_passages = [relevant[doc_id] for doc_id in sorted(relevant)]
    selected_digests = {_text_digest(row["text"]) for row in miracl_passages}
    for row in others.values():
        if len(miracl_passages) >= 512:
            break
        if _text_digest(row["text"]) not in selected_digests:
            miracl_passages.append(row)
            selected_digests.add(_text_digest(row["text"]))
    if len(miracl_passages) != 512 or len({_text_digest(row["text"]) for row in miracl_passages}) != 512:
        raise DataError("could not construct 512 unique MIRACL passages")

    queries_name = "data/google/queries/dev/portuguese_queries.dev.small.tsv"
    collection_name = "data/google/collections/portuguese_collection.tsv"
    queries_path, queries_record = _cached_download(MMARCO_ID, MMARCO_REVISION, queries_name, raw_dir)
    source_files.append(queries_record)
    mmarco_query_reservoir = DeterministicReservoir(32, SEED)
    for line in _read_text(queries_path).splitlines():
        if line.strip():
            query_id, text = parse_tsv_row(line, columns=2)
            mmarco_query_reservoir.add({"id": query_id, "text": text})
    mmarco_queries = mmarco_query_reservoir.values()
    if len(mmarco_queries) != 32:
        raise DataError("mMARCO Portuguese dev has fewer than 32 queries")

    _require_disk_budget(workspace)
    collection_path, collection_record = _cached_download(
        MMARCO_ID, MMARCO_REVISION, collection_name, raw_dir
    )
    source_files.append(collection_record)
    mmarco_reservoir = DeterministicReservoir(512, SEED, seen_text_digests=seen_texts)
    for row in _iter_mmarco_rows(collection_path):
        mmarco_reservoir.add(row)
    mmarco_passages = mmarco_reservoir.values()
    if len(mmarco_passages) != 512:
        raise DataError("could not construct 512 unique mMARCO passages")

    frozen = {
        "schema": 1,
        "seed": SEED,
        "miracl": {
            "repository": MIRACL_ID,
            "corpus_repository": MIRACL_CORPUS_ID,
            "language": "en",
            "split": "dev",
            "queries": [{"id": query_id, "text": topics[query_id]} for query_id in query_ids],
            "qrels": selected_qrels,
            "passages": miracl_passages,
        },
        "mmarco": {
            "repository": MMARCO_ID,
            "language": "pt",
            "split": "dev.small",
            "queries": mmarco_queries,
            "passages": mmarco_passages,
        },
    }
    combined = miracl_passages + mmarco_passages
    if len(combined) != 1024 or len({_text_digest(row["text"]) for row in combined}) != 1024:
        raise DataError("combined public text sample is not 1,024 unique passages")
    frozen["frozen_sha256"] = _frozen_digest(frozen)
    write_json(frozen_path, frozen)
    summary = {
        "schema": 1,
        "miracl_revisions": [MIRACL_REVISION, MIRACL_CORPUS_REVISION],
        "mmarco_revision": MMARCO_REVISION,
        "passages_per_source": 512,
        "queries_per_source": 32,
        "total_passages": 1024,
        "total_queries": 64,
        "frozen_sha256": frozen["frozen_sha256"],
        "source_files": source_files,
    }
    write_json(summary_path, summary)
    return frozen


GUTENBERG_SOURCES = {
    "en": {
        "title": "The Time Machine",
        "url": "https://gutenberg.pglaf.org/cache/epub/35/pg35.txt",
        "fallback_url": "https://www.gutenberg.org/cache/epub/35/pg35.txt",
    },
    "pt": {
        "title": "Dom Casmurro",
        "url": "https://gutenberg.pglaf.org/cache/epub/55752/pg55752.txt",
        "fallback_url": "https://www.gutenberg.org/cache/epub/55752/pg55752.txt",
    },
}


def acquire_gutenberg_texts(workspace: Path) -> dict[str, Any]:
    """Acquire and validate only the public-domain OCR source bodies."""
    data_dir = workspace / "data"
    output_path = data_dir / "gutenberg-sources.json"
    if output_path.exists():
        from .artifacts import load_json

        return load_json(output_path)
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    bodies: dict[str, Any] = {}
    for language, source in GUTENBERG_SOURCES.items():
        target = raw_dir / f"gutenberg-{language}.txt"
        errors: list[Exception] = []
        if not target.exists():
            for url in (source["url"], source["fallback_url"]):
                try:
                    download_file(url, target)
                    break
                except ArtifactError as error:
                    errors.append(error)
            else:
                raise DataError("Project Gutenberg source is temporarily unavailable") from errors[-1]
        body = strip_gutenberg(_read_text(target))
        bodies[language] = {
            "title": source["title"],
            "source_url": source["url"],
            "body": body,
            "source_sha256": sha256_file(target),
            "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        }
    write_json(output_path, bodies)
    return bodies
