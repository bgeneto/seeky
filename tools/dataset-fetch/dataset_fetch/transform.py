"""Deterministic BEIR transforms and prepared-dataset validation (R24)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .canonical import encode_text, normalize_text, sha256_bytes, sha256_file
from .errors import DANGLING_REFERENCE, DUPLICATE_ID, SCHEMA, TRANSFORM, fail
from .jsio import (
    iter_jsonl,
    iter_tsv,
    jsonl_bytes,
    read_json,
    write_bytes,
)
from .manifest import (
    BEIR_CATEGORIES,
    BEIR_CONFIGURATION,
    LANGUAGE_SLICES,
    SPLITS,
    query_set_sha256,
    validate_relative_path,
)

TRANSFORM_SEED = "dataset-transform-v1"


@dataclass(frozen=True)
class DocumentSpec:
    id: str
    title: str
    body: str


@dataclass(frozen=True)
class QuerySpec:
    id: str
    text: str
    language: str
    target_languages: tuple[str, ...]
    language_slice: str
    category: str
    configuration: str = BEIR_CONFIGURATION


@dataclass(frozen=True)
class QrelSpec:
    query_id: str
    document_id: str
    grade: int


@dataclass
class SplitSpec:
    queries: list[QuerySpec]
    qrels: list[QrelSpec]


@dataclass
class BuildRequest:
    dataset_id: str
    documents: list[DocumentSpec]
    splits: dict[str, SplitSpec]
    files_root: str | None
    title_mode: str = "title-blank-line-body"
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass
class BuildResult:
    local_hashes: dict[str, str]
    counts: dict[str, Any]
    language_slices: dict[str, int]
    categories: dict[str, int]
    corpus_sha256: str
    query_set_sha256: dict[str, str]
    document_count: int
    notes: dict[str, Any]


def _document_text(title: str, body: str) -> tuple[str, str]:
    title = normalize_text(title).strip()
    body = normalize_text(body)
    if title and body:
        text = f"{title}\n\n{body}"
    elif title:
        text = title
    else:
        text = body
    return title, text


def _validate_request(request: BuildRequest) -> None:
    documents = request.documents
    if not documents:
        raise fail(TRANSFORM, "dataset has no documents", location=request.dataset_id)
    document_ids: set[str] = set()
    for document in documents:
        if not document.id.strip():
            raise fail(TRANSFORM, "empty document ID", location=request.dataset_id)
        if document.id in document_ids:
            raise fail(
                DUPLICATE_ID,
                f"duplicate document ID {document.id!r}",
                location=request.dataset_id,
            )
        document_ids.add(document.id)
        _, text = _document_text(document.title, document.body)
        if text == "":
            raise fail(
                TRANSFORM,
                f"document {document.id!r} has empty text",
                location=request.dataset_id,
            )
    if set(request.splits) != set(SPLITS):
        raise fail(TRANSFORM, "build requires exactly the dev and test splits")
    seen_queries: set[str] = set()
    for name in SPLITS:
        split = request.splits[name]
        if not split.queries:
            raise fail(TRANSFORM, f"split {name} has no queries", location=request.dataset_id)
        if not split.qrels:
            raise fail(TRANSFORM, f"split {name} has no qrels", location=request.dataset_id)
        query_ids = set()
        for query in split.queries:
            if not query.id.strip() or not query.text:
                raise fail(
                    TRANSFORM,
                    f"split {name} has a query with an empty ID or text",
                    location=request.dataset_id,
                )
            if query.id in query_ids:
                raise fail(
                    DUPLICATE_ID,
                    f"duplicate query ID {query.id!r} in split {name}",
                    location=request.dataset_id,
                )
            if query.id in seen_queries:
                raise fail(
                    TRANSFORM,
                    f"query ID {query.id!r} appears in both splits; dev/test must be disjoint",
                    location=request.dataset_id,
                )
            query_ids.add(query.id)
            seen_queries.add(query.id)
            _validate_query_metadata(query, name)
        pairs: set[tuple[str, str]] = set()
        for qrel in split.qrels:
            if qrel.query_id not in query_ids:
                raise fail(
                    DANGLING_REFERENCE,
                    f"qrel references unknown query {qrel.query_id!r} in split {name}",
                    location=request.dataset_id,
                )
            if qrel.document_id not in document_ids:
                raise fail(
                    DANGLING_REFERENCE,
                    f"qrel references unknown document {qrel.document_id!r} in split {name}",
                    location=request.dataset_id,
                )
            if not isinstance(qrel.grade, int) or isinstance(qrel.grade, bool):
                raise fail(TRANSFORM, "qrel grade must be an integer", location=request.dataset_id)
            if not 0 <= qrel.grade <= 3:
                raise fail(
                    TRANSFORM,
                    f"qrel grade {qrel.grade} is outside 0..=3",
                    location=request.dataset_id,
                )
            pair = (qrel.query_id, qrel.document_id)
            if pair in pairs:
                raise fail(
                    DUPLICATE_ID,
                    f"duplicate qrel {pair!r} in split {name}",
                    location=request.dataset_id,
                )
            pairs.add(pair)


def _validate_query_metadata(query: QuerySpec, split: str) -> None:
    location = f"{split}:{query.id}"
    if query.category not in BEIR_CATEGORIES:
        raise fail(
            TRANSFORM,
            f"category {query.category!r} is not a BEIR query category",
            location=location,
        )
    if query.configuration != BEIR_CONFIGURATION:
        raise fail(
            TRANSFORM,
            "BEIR datasets only support the default configuration",
            location=location,
        )
    if query.language_slice not in LANGUAGE_SLICES:
        raise fail(
            TRANSFORM,
            f"unknown language slice {query.language_slice!r}",
            location=location,
        )
    if not query.language:
        raise fail(TRANSFORM, "query language must be recorded, never guessed", location=location)
    targets = tuple(query.target_languages)
    if not targets or not all(targets):
        raise fail(TRANSFORM, "target_languages must be recorded", location=location)
    if query.language_slice == "cross_lingual":
        if query.language in targets or len(targets) < 1:
            raise fail(
                TRANSFORM,
                "a cross-lingual query must record source and target languages separately",
                location=location,
            )
    elif targets != (query.language,):
        raise fail(
            TRANSFORM,
            "a monolingual query must target exactly its own language",
            location=location,
        )


def write_dataset(request: BuildRequest, root: Path, *, relative_prefix: str) -> BuildResult:
    """Write a BEIR dataset below ``root`` and return hashes and counts."""

    _validate_request(request)
    documents = sorted(request.documents, key=lambda item: item.id)
    corpus_rows: list[dict[str, Any]] = []
    file_hashes: dict[str, str] = {}
    prefix = relative_prefix.rstrip("/") + "/"
    for document in documents:
        title, text = _document_text(document.title, document.body)
        metadata: dict[str, Any] = {}
        if request.files_root:
            file_name = sha256_bytes(document.id.encode("utf-8")) + ".txt"
            manifest_path = f"{request.files_root}/{file_name}"
            validate_relative_path(manifest_path, "files_root")
            if not manifest_path.startswith(prefix):
                raise fail(
                    TRANSFORM,
                    f"files_root must live below {relative_prefix}/",
                    location=manifest_path,
                )
            data = encode_text(text)
            write_bytes(root / manifest_path[len(prefix) :], data)
            file_hashes[manifest_path] = sha256_bytes(data)
            metadata["relative_path"] = manifest_path
        corpus_rows.append(
            {
                "_id": document.id,
                "title": title,
                "text": text,
                "metadata": metadata,
            }
        )
    corpus = jsonl_bytes(corpus_rows)
    write_bytes(root / "corpus.jsonl", corpus)
    file_hashes[f"{relative_prefix}/corpus.jsonl"] = sha256_bytes(corpus)

    query_set_hashes: dict[str, str] = {}
    all_slices: Counter[str] = Counter()
    all_categories: Counter[str] = Counter()
    counts: dict[str, Any] = {"documents": len(documents), "splits": {}}
    for name in SPLITS:
        split = request.splits[name]
        queries = sorted(split.queries, key=lambda item: item.id)
        qrels = sorted(split.qrels, key=lambda item: (item.query_id, item.document_id))
        rows = [
            {
                "_id": query.id,
                "text": query.text,
                "metadata": {
                    "language": query.language,
                    "target_languages": list(query.target_languages),
                    "language_slice": query.language_slice,
                    "category": query.category,
                    "configuration": query.configuration,
                },
            }
            for query in queries
        ]
        query_bytes = jsonl_bytes(rows)
        write_bytes(root / f"queries.{name}.jsonl", query_bytes)
        file_hashes[f"{relative_prefix}/queries.{name}.jsonl"] = sha256_bytes(query_bytes)

        qrel_lines = ["query-id\tcorpus-id\tscore\n"]
        qrel_lines.extend(
            f"{qrel.query_id}\t{qrel.document_id}\t{qrel.grade}\n" for qrel in qrels
        )
        qrel_bytes = "".join(qrel_lines).encode("utf-8")
        write_bytes(root / f"qrels.{name}.tsv", qrel_bytes)
        file_hashes[f"{relative_prefix}/qrels.{name}.tsv"] = sha256_bytes(qrel_bytes)

        query_set_hashes[name] = query_set_sha256(
            [
                {
                    "id": query.id,
                    "text": query.text,
                    "language": query.language,
                    "target_languages": list(query.target_languages),
                    "language_slice": query.language_slice,
                    "category": query.category,
                    "configuration": query.configuration,
                    "split": name,
                }
                for query in queries
            ]
        )
        split_slices = Counter(query.language_slice for query in queries)
        split_categories = Counter(query.category for query in queries)
        all_slices.update(split_slices)
        all_categories.update(split_categories)
        counts["splits"][name] = {
            "queries": len(queries),
            "qrels": len(qrels),
            "positive_qrels": sum(1 for qrel in qrels if qrel.grade > 0),
            "language_slices": dict(sorted(split_slices.items())),
            "categories": dict(sorted(split_categories.items())),
        }

    return BuildResult(
        local_hashes=dict(sorted(file_hashes.items())),
        counts=counts,
        language_slices=dict(sorted(all_slices.items())),
        categories=dict(sorted(all_categories.items())),
        corpus_sha256=sha256_bytes(corpus),
        query_set_sha256=query_set_hashes,
        document_count=len(documents),
        notes=request.notes,
    )


@dataclass
class ParsedDataset:
    documents: dict[str, dict[str, Any]]
    splits: dict[str, SplitSpec]
    counts: dict[str, Any]
    language_slices: dict[str, int]
    categories: dict[str, int]
    corpus_sha256: str
    query_set_sha256: dict[str, str]
    local_files: dict[str, str]


def parse_prepared(
    dataset_dir: Path,
    manifest: dict[str, Any],
    *,
    require_files: bool = True,
) -> ParsedDataset:
    """Parse and validate prepared files. Never performs network access."""

    local_hashes: dict[str, str] = manifest["local_file_sha256"]
    documents: dict[str, dict[str, Any]] = {}
    corpus_rel = manifest["corpus"]
    corpus_path = dataset_dir / corpus_rel
    corpus_sha = sha256_file(corpus_path)
    for line_number, record in iter_jsonl(corpus_path):
        location = f"{corpus_rel}:{line_number}"
        if not isinstance(record, dict):
            raise fail(SCHEMA, "corpus row must be a JSON object", location=location)
        doc_id = record.get("_id")
        title = record.get("title")
        text = record.get("text")
        metadata = record.get("metadata", {})
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise fail(SCHEMA, "document _id must be a nonempty string", location=location)
        if not isinstance(title, str) or not isinstance(text, str) or text == "":
            raise fail(SCHEMA, "document title/text are invalid", location=location)
        if not isinstance(metadata, dict):
            raise fail(SCHEMA, "document metadata must be an object", location=location)
        if doc_id in documents:
            raise fail(DUPLICATE_ID, "duplicate document ID", location=location)
        if require_files and manifest.get("files_root") is not None:
            relative = metadata.get("relative_path")
            if not isinstance(relative, str) or relative == "":
                raise fail(
                    SCHEMA,
                    "files_root requires metadata.relative_path",
                    location=location,
                )
            try:
                validate_relative_path(relative, "metadata.relative_path")
            except Exception as exc:  # noqa: BLE001 - re-raised as schema error
                raise fail(SCHEMA, f"invalid relative_path: {exc}", location=location) from exc
            if relative not in local_hashes:
                raise fail(
                    SCHEMA,
                    "engine file is not listed in local_file_sha256",
                    location=location,
                )
            bytes_ = (dataset_dir / relative).read_bytes()
            try:
                file_text = bytes_.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise fail(SCHEMA, "engine file is not UTF-8", location=location) from exc
            if file_text != text:
                raise fail(
                    SCHEMA,
                    "corpus text differs from the engine file",
                    location=location,
                )
        documents[doc_id] = record
    if not documents:
        raise fail(SCHEMA, "corpus is empty", location=corpus_rel)

    defaults = manifest["query_defaults"]
    splits: dict[str, SplitSpec] = {}
    all_slices: Counter[str] = Counter()
    all_categories: Counter[str] = Counter()
    query_hashes: dict[str, str] = {}
    counts: dict[str, Any] = {"documents": len(documents), "splits": {}}
    for name in SPLITS:
        split_files = manifest["splits"][name]
        queries_rel = split_files["queries"]
        qrels_rel = split_files["qrels"]
        queries: list[QuerySpec] = []
        query_ids: set[str] = set()
        for line_number, record in iter_jsonl(dataset_dir / queries_rel):
            location = f"{queries_rel}:{line_number}"
            if not isinstance(record, dict):
                raise fail(SCHEMA, "query row must be a JSON object", location=location)
            query_id = record.get("_id")
            text = record.get("text")
            metadata = record.get("metadata", {})
            if not isinstance(query_id, str) or not query_id.strip():
                raise fail(SCHEMA, "query _id must be a nonempty string", location=location)
            if not isinstance(text, str) or text == "":
                raise fail(SCHEMA, "query text must be a nonempty string", location=location)
            if not isinstance(metadata, dict):
                raise fail(SCHEMA, "query metadata must be an object", location=location)
            if query_id in query_ids:
                raise fail(DUPLICATE_ID, "duplicate query ID", location=location)
            query_ids.add(query_id)
            category = metadata.get("category", defaults["category"])
            language_slice = metadata.get("language_slice", defaults["language_slice"])
            configuration = metadata.get("configuration", defaults["configuration"])
            language = metadata.get("language", defaults.get("language") or "und")
            targets = metadata.get(
                "target_languages", defaults.get("target_languages", [])
            )
            if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
                raise fail(
                    SCHEMA, "target_languages must be a list of strings", location=location
                )
            query = QuerySpec(
                id=query_id,
                text=text,
                language=language,
                target_languages=tuple(targets),
                language_slice=language_slice,
                category=category,
                configuration=configuration,
            )
            _validate_query_metadata(query, name)
            queries.append(query)
        if not queries:
            raise fail(SCHEMA, "split has no queries", location=queries_rel)

        qrels: list[QrelSpec] = []
        seen: set[tuple[str, str]] = set()
        header_seen = False
        for line_number, fields in enumerate(iter_tsv(dataset_dir / qrels_rel), start=1):
            location = f"{qrels_rel}:{line_number}"
            if not header_seen:
                header_seen = True
                if fields == ["query-id", "corpus-id", "score"]:
                    continue
                raise fail(SCHEMA, "expected BEIR qrels header", location=location)
            if len(fields) != 3 or not fields[0] or not fields[1]:
                raise fail(SCHEMA, "expected three nonempty TSV columns", location=location)
            try:
                grade = int(fields[2])
            except ValueError as exc:
                raise fail(SCHEMA, "grade must be an integer", location=location) from exc
            if not 0 <= grade <= 3:
                raise fail(SCHEMA, "grade must be in 0..=3", location=location)
            query_id, document_id = fields[0], fields[1]
            if query_id not in query_ids:
                raise fail(
                    DANGLING_REFERENCE, "qrel references an unknown query", location=location
                )
            if document_id not in documents:
                raise fail(
                    DANGLING_REFERENCE, "qrel references an unknown document", location=location
                )
            if (query_id, document_id) in seen:
                raise fail(DUPLICATE_ID, "duplicate qrel", location=location)
            seen.add((query_id, document_id))
            qrels.append(QrelSpec(query_id, document_id, grade))
        if not qrels:
            raise fail(SCHEMA, "split has no qrels", location=qrels_rel)

        splits[name] = SplitSpec(queries, qrels)
        query_hashes[name] = query_set_sha256(
            [
                {
                    "id": query.id,
                    "text": query.text,
                    "language": query.language,
                    "target_languages": list(query.target_languages),
                    "language_slice": query.language_slice,
                    "category": query.category,
                    "configuration": query.configuration,
                    "split": name,
                }
                for query in sorted(queries, key=lambda item: item.id)
            ]
        )
        split_slices = Counter(query.language_slice for query in queries)
        split_categories = Counter(query.category for query in queries)
        all_slices.update(split_slices)
        all_categories.update(split_categories)
        counts["splits"][name] = {
            "queries": len(queries),
            "qrels": len(qrels),
            "positive_qrels": sum(1 for qrel in qrels if qrel.grade > 0),
            "language_slices": dict(sorted(split_slices.items())),
            "categories": dict(sorted(split_categories.items())),
        }

    dev_ids = {query.id for query in splits["dev"].queries}
    test_ids = {query.id for query in splits["test"].queries}
    overlap = dev_ids & test_ids
    if overlap:
        raise fail(
            TRANSFORM,
            f"dev and test share query IDs: {sorted(overlap)[:3]}",
            location=manifest["dataset_id"],
        )

    return ParsedDataset(
        documents=documents,
        splits=splits,
        counts=counts,
        language_slices=dict(sorted(all_slices.items())),
        categories=dict(sorted(all_categories.items())),
        corpus_sha256=corpus_sha,
        query_set_sha256=query_hashes,
        local_files=local_hashes,
    )


def read_json_object(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise fail(SCHEMA, "expected a JSON object", location=str(path))
    return value
