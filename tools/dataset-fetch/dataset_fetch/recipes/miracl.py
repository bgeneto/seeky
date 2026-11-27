"""MIRACL recipe (miracl/miracl + miracl/miracl-corpus, Apache-2.0).

MIRACL publishes public qrels only for its ``dev`` split (``test-a`` and
``test-b`` topics have no public qrels). Following the maintainer's WP-1.5
policy, the recipe partitions the public ``dev`` qrels deterministically 50/50
by SHA-256 into ``dev`` and ``test`` without tuning.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..cache import CachedFile
from ..canonical import normalize_text
from ..errors import SCHEMA, fail
from ..jsio import iter_jsonl, iter_tsv
from ..transform import BuildRequest, DocumentSpec, QuerySpec, QrelSpec, SplitSpec
from . import find_source, register
from .mmarco import carve_out_split

_SHARD_RE = re.compile(r"/docs-(\d+)\.jsonl\.gz$")


def _corpus_shards(sources: list[CachedFile]) -> list[CachedFile]:
    matched: list[tuple[int, CachedFile]] = []
    for source in sources:
        match = _SHARD_RE.search(source.url)
        if match is not None:
            matched.append((int(match.group(1)), source))
    if not matched:
        raise fail(
            SCHEMA,
            "expected at least one MIRACL corpus shard (docs-<n>.jsonl.gz)",
            location="manifest.source.urls",
        )
    matched.sort(key=lambda item: item[0])
    return [source for _, source in matched]


def _read_corpus(shards: list[CachedFile]) -> tuple[list[DocumentSpec], set[str]]:
    documents: list[DocumentSpec] = []
    omitted: set[str] = set()
    seen: set[str] = set()
    for shard in shards:
        for line_number, record in iter_jsonl(shard.path, gzipped=True):
            where = f"{shard.url}:{line_number}"
            if not isinstance(record, dict):
                raise fail(SCHEMA, "corpus row must be an object", location=where)
            doc_id = record.get("docid")
            title = record.get("title", "")
            text = record.get("text")
            if not isinstance(doc_id, str) or not doc_id.strip():
                raise fail(SCHEMA, "corpus docid must be a nonempty string", location=where)
            if not isinstance(title, str) or not isinstance(text, str):
                raise fail(SCHEMA, "corpus title/text must be strings", location=where)
            if doc_id in seen:
                raise fail(SCHEMA, f"duplicate docid {doc_id!r}", location=where)
            seen.add(doc_id)
            if not normalize_text(title).strip() and not normalize_text(text).strip():
                omitted.add(doc_id)
                continue
            documents.append(DocumentSpec(doc_id, title, text))
    return documents, omitted


def _read_topics(path: Path, location: str) -> dict[str, str]:
    topics: dict[str, str] = {}
    for line_number, fields in enumerate(iter_tsv(path), start=1):
        where = f"{location}:{line_number}"
        if len(fields) != 2 or not fields[0] or fields[1] == "":
            raise fail(SCHEMA, "expected two nonempty TSV columns", location=where)
        query_id = fields[0].strip()
        if query_id in topics:
            raise fail(SCHEMA, "duplicate topic ID", location=where)
        topics[query_id] = normalize_text(fields[1])
    return topics


def _read_qrels(
    path: Path,
    location: str,
    doc_ids: set[str],
    omitted: set[str],
) -> tuple[dict[str, list[QrelSpec]], int]:
    by_query: dict[str, list[QrelSpec]] = defaultdict(list)
    dropped = 0
    for line_number, fields in enumerate(iter_tsv(path), start=1):
        where = f"{location}:{line_number}"
        if len(fields) == 4:
            query_id, marker, document_id, grade_text = fields
            if marker not in ("Q0", "0"):
                raise fail(SCHEMA, "expected Q0 or 0 in the qrels marker column", location=where)
        elif len(fields) == 3:
            query_id, document_id, grade_text = fields
        else:
            raise fail(SCHEMA, "expected three or four TSV columns", location=where)
        try:
            grade = int(grade_text)
        except ValueError as exc:
            raise fail(SCHEMA, "grade must be an integer", location=where) from exc
        if not 0 <= grade <= 3:
            raise fail(SCHEMA, "grade must be in 0..=3", location=where)
        if document_id in omitted:
            dropped += 1
            continue
        if document_id not in doc_ids:
            raise fail(
                SCHEMA,
                f"qrel references unknown document {document_id!r}",
                location=where,
            )
        by_query[query_id].append(QrelSpec(query_id, document_id, grade))
    return by_query, dropped


def _prepare(
    manifest: dict[str, Any],
    sources: list[CachedFile],
    seed: str,
    *,
    language: str,
) -> BuildRequest:
    shards = _corpus_shards(sources)
    topics_file = find_source(sources, f"/topics.miracl-v1.0-{language}-dev.tsv")
    qrels_file = find_source(sources, f"/qrels.miracl-v1.0-{language}-dev.tsv")
    documents, omitted = _read_corpus(shards)
    doc_ids = {document.id for document in documents}
    topics = _read_topics(topics_file.path, topics_file.url)
    qrels, dropped_qrels = _read_qrels(qrels_file.path, qrels_file.url, doc_ids, omitted)
    missing = [query_id for query_id in qrels if query_id not in topics]
    if missing:
        raise fail(
            SCHEMA,
            f"qrels reference {len(missing)} topics missing from the dev topics file",
            location=missing[0],
        )

    language_slice = manifest["query_defaults"]["language_slice"]
    dev_ids, test_ids = carve_out_split(
        sorted(qrels), seed=seed, purpose=f"miracl-{language}-split"
    )

    def build(ids: list[str]) -> SplitSpec:
        return SplitSpec(
            queries=[
                QuerySpec(
                    id=query_id,
                    text=topics[query_id],
                    language=language,
                    target_languages=(language,),
                    language_slice=language_slice,
                    category="conceptual",
                )
                for query_id in ids
            ],
            qrels=[qrel for query_id in ids for qrel in qrels[query_id]],
        )

    notes: dict[str, Any] = {
        "source_format": "miracl-v1.0",
        "source_language": language,
        "corpus_shards": len(shards),
        "transform_seed": seed,
        "split_source": "deterministic 50/50 carve-out of dev (MIRACL has no public test qrels)",
    }
    if omitted:
        notes["empty_documents_omitted"] = len(omitted)
        notes["qrels_dropped_for_empty_documents"] = dropped_qrels
    return BuildRequest(
        dataset_id=manifest["dataset_id"],
        documents=documents,
        splits={"dev": build(dev_ids), "test": build(test_ids)},
        files_root=manifest.get("files_root"),
        notes=notes,
    )


@register("miracl-es")
def prepare_es(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    return _prepare(manifest, sources, seed, language="es")


@register("miracl-fr")
def prepare_fr(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    return _prepare(manifest, sources, seed, language="fr")


@register("miracl-de")
def prepare_de(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    return _prepare(manifest, sources, seed, language="de")


@register("miracl-en")
def prepare_en(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    return _prepare(manifest, sources, seed, language="en")
