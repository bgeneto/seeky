"""MLDR recipe (Shitao/MLDR: JSonL.gz corpus plus native dev/test splits)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ..cache import CachedFile
from ..errors import SCHEMA, fail
from ..jsio import iter_jsonl, iter_tsv
from ..transform import BuildRequest, DocumentSpec, QuerySpec, QrelSpec, SplitSpec
from . import find_source, register


def _read_corpus(path: Path, location: str) -> list[DocumentSpec]:
    documents: list[DocumentSpec] = []
    for line_number, record in iter_jsonl(path, gzipped=True):
        where = f"{location}:{line_number}"
        if not isinstance(record, dict):
            raise fail(SCHEMA, "corpus row must be an object", location=where)
        doc_id = record.get("docid")
        text = record.get("text")
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise fail(SCHEMA, "corpus docid must be a nonempty string", location=where)
        if not isinstance(text, str):
            raise fail(SCHEMA, "corpus text must be a string", location=where)
        documents.append(DocumentSpec(doc_id, "", text))
    return documents


def _read_queries(path: Path, location: str) -> dict[str, str]:
    queries: dict[str, str] = {}
    for line_number, record in iter_jsonl(path, gzipped=True):
        where = f"{location}:{line_number}"
        if not isinstance(record, dict):
            raise fail(SCHEMA, "query row must be an object", location=where)
        query_id = record.get("query_id")
        text = record.get("query")
        if not isinstance(query_id, str) or not query_id.strip():
            raise fail(SCHEMA, "query_id must be a nonempty string", location=where)
        if not isinstance(text, str) or text == "":
            raise fail(SCHEMA, "query text must be a nonempty string", location=where)
        if query_id in queries:
            raise fail(SCHEMA, "duplicate query ID", location=where)
        queries[query_id] = text
    return queries


def _read_qrels(
    path: Path, location: str, documents: dict[str, DocumentSpec]
) -> dict[str, list[QrelSpec]]:
    by_query: dict[str, list[QrelSpec]] = defaultdict(list)
    header_seen = False
    for line_number, fields in enumerate(iter_tsv(path), start=1):
        where = f"{location}:{line_number}"
        if not header_seen:
            header_seen = True
            if not fields or fields[0] != "query-id":
                header_seen = False
            else:
                continue
        if len(fields) == 4:
            query_id, marker, document_id, grade_text = fields
            if marker != "Q0":
                raise fail(SCHEMA, "expected Q0 in the qrels marker column", location=where)
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
        if document_id not in documents:
            raise fail(
                SCHEMA,
                f"qrel references unknown document {document_id!r}",
                location=where,
            )
        by_query[query_id].append(QrelSpec(query_id, document_id, grade))
    return by_query


def _split(
    *,
    queries: dict[str, str],
    qrels: dict[str, list[QrelSpec]],
    language: str,
    language_slice: str,
) -> SplitSpec:
    query_ids = sorted(qrels)
    missing = [query_id for query_id in query_ids if query_id not in queries]
    if missing:
        raise fail(
            SCHEMA,
            f"qrels reference {len(missing)} queries missing from the split file",
            location=missing[0],
        )
    return SplitSpec(
        queries=[
            QuerySpec(
                id=query_id,
                text=queries[query_id],
                language=language,
                target_languages=(language,),
                language_slice=language_slice,
                category="conceptual",
            )
            for query_id in query_ids
        ],
        qrels=[qrel for query_id in query_ids for qrel in qrels[query_id]],
    )


@register("mldr-pt")
def prepare_pt(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    return _prepare(manifest, sources, seed, "pt")


@register("mldr-en")
def prepare_en(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    return _prepare(manifest, sources, seed, "en")


def _prepare(
    manifest: dict[str, Any],
    sources: list[CachedFile],
    seed: str,
    language: str,
) -> BuildRequest:
    corpus = find_source(sources, "/corpus.jsonl.gz")
    dev = find_source(sources, "/dev.jsonl.gz")
    test = find_source(sources, "/test.jsonl.gz")
    dev_qrels = find_source(sources, f"-{language}-dev.tsv")
    test_qrels = find_source(sources, f"-{language}-test.tsv")
    documents = _read_corpus(corpus.path, corpus.url)
    by_id = {document.id: document for document in documents}
    splits = {
        "dev": _split(
            queries=_read_queries(dev.path, dev.url),
            qrels=_read_qrels(dev_qrels.path, dev_qrels.url, by_id),
            language=language,
            language_slice=language,
        ),
        "test": _split(
            queries=_read_queries(test.path, test.url),
            qrels=_read_qrels(test_qrels.path, test_qrels.url, by_id),
            language=language,
            language_slice=language,
        ),
    }
    return BuildRequest(
        dataset_id=manifest["dataset_id"],
        documents=documents,
        splits=splits,
        files_root=manifest.get("files_root"),
        notes={
            "source_format": "mldr",
            "transform_seed": seed,
            "source_language": language,
            "split_source": "native dev and test",
            "title_mode": "body-only; MLDR articles start with their title",
        },
    )
