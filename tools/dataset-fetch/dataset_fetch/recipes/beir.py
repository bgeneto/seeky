"""BEIR-family recipe (Hugging Face mteb/BeIR JSONL mirrors)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ..cache import CachedFile
from ..canonical import normalize_text
from ..errors import SCHEMA, fail
from ..jsio import iter_jsonl, iter_tsv
from ..transform import BuildRequest, DocumentSpec, QuerySpec, QrelSpec, SplitSpec
from . import find_source, optional_source, register
from .mmarco import carve_out_split


def _read_corpus(path: Path, location: str) -> list[DocumentSpec]:
    documents: list[DocumentSpec] = []
    for line_number, record in iter_jsonl(path):
        where = f"{location}:{line_number}"
        if not isinstance(record, dict):
            raise fail(SCHEMA, "corpus row must be an object", location=where)
        doc_id = record.get("_id")
        title = record.get("title", "")
        text = record.get("text")
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise fail(SCHEMA, "corpus _id must be a nonempty string", location=where)
        if not isinstance(title, str) or not isinstance(text, str):
            raise fail(SCHEMA, "corpus title/text must be strings", location=where)
        documents.append(DocumentSpec(doc_id, title, text))
    return documents


def _read_queries(path: Path, location: str) -> dict[str, str]:
    queries: dict[str, str] = {}
    for line_number, record in iter_jsonl(path):
        where = f"{location}:{line_number}"
        if not isinstance(record, dict):
            raise fail(SCHEMA, "query row must be an object", location=where)
        query_id = record.get("_id")
        text = record.get("text")
        if not isinstance(query_id, str) or not query_id.strip():
            raise fail(SCHEMA, "query _id must be a nonempty string", location=where)
        if not isinstance(text, str) or text == "":
            raise fail(SCHEMA, "query text must be a nonempty string", location=where)
        if query_id in queries:
            raise fail(SCHEMA, "duplicate query ID", location=where)
        queries[query_id] = text
    return queries


def _read_qrels(
    path: Path,
    location: str,
    documents: dict[str, DocumentSpec],
    omitted: set[str] | None = None,
) -> tuple[dict[str, list[QrelSpec]], int, int, int]:
    omitted = omitted or set()
    by_query: dict[str, list[QrelSpec]] = defaultdict(list)
    dropped_qrels = 0
    clamped_negative = 0
    header_seen = False
    for line_number, fields in enumerate(iter_tsv(path), start=1):
        where = f"{location}:{line_number}"
        if not header_seen:
            header_seen = True
            if fields == ["query-id", "corpus-id", "score"]:
                continue
            raise fail(SCHEMA, "expected BEIR qrels header", location=where)
        if len(fields) != 3 or not fields[0] or not fields[1]:
            raise fail(SCHEMA, "expected three nonempty TSV columns", location=where)
        try:
            grade = int(fields[2])
        except ValueError as exc:
            raise fail(SCHEMA, "grade must be an integer", location=where) from exc
        if grade == -1:
            # TREC qrels (e.g. TREC-COVID) use -1 for explicit non-relevant;
            # trec_eval treats -1 as 0. Record every mapping visibly.
            grade = 0
            clamped_negative += 1
        elif not 0 <= grade <= 3:
            raise fail(SCHEMA, "grade must be in 0..=3", location=where)
        query_id, document_id = fields[0], fields[1]
        if document_id in omitted:
            dropped_qrels += 1
            continue
        if document_id not in documents:
            raise fail(
                SCHEMA,
                f"qrel references unknown document {document_id!r}",
                location=where,
            )
        by_query[query_id].append(QrelSpec(query_id, document_id, grade))
    dropped_queries = sorted(query_id for query_id, rows in by_query.items() if not rows)
    for query_id in dropped_queries:
        del by_query[query_id]
    return by_query, dropped_qrels, len(dropped_queries), clamped_negative


def _split_request(
    *,
    queries: dict[str, str],
    qrels: dict[str, list[QrelSpec]],
    language: str,
    language_slice: str,
    category: str,
) -> SplitSpec:
    query_ids = sorted(qrels)
    missing = [query_id for query_id in query_ids if query_id not in queries]
    if missing:
        raise fail(
            SCHEMA,
            f"qrels reference {len(missing)} queries missing from queries.jsonl",
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
                category=category,
            )
            for query_id in query_ids
        ],
        qrels=[qrel for query_id in query_ids for qrel in qrels[query_id]],
    )


def prepare(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    defaults = manifest["query_defaults"]
    language = defaults.get("language") or "en"
    language_slice = defaults["language_slice"]
    category = defaults["category"]
    corpus = find_source(sources, "/corpus.jsonl")
    queries = find_source(sources, "/queries.jsonl")
    dev_qrels = optional_source(sources, "/qrels/dev.tsv")
    if dev_qrels is None:
        # SciFact ships train claims instead of a dev qrels file; they are the
        # source-native tuning split and are never derived from test.
        dev_qrels = optional_source(sources, "/qrels/train.tsv")
    test_qrels = find_source(sources, "/qrels/test.tsv")
    all_documents = _read_corpus(corpus.path, corpus.url)
    omitted = {
        document.id
        for document in all_documents
        if not normalize_text(document.title).strip()
        and not normalize_text(document.body).strip()
    }
    documents = [document for document in all_documents if document.id not in omitted]
    by_id = {document.id: document for document in documents}
    query_text = _read_queries(queries.path, queries.url)
    if dev_qrels is not None:
        dev, dev_dropped_qrels, dev_dropped_queries, dev_clamped = _read_qrels(
            dev_qrels.path, dev_qrels.url, by_id, omitted
        )
        test, test_dropped_qrels, test_dropped_queries, test_clamped = _read_qrels(
            test_qrels.path, test_qrels.url, by_id, omitted
        )
        clamped_negative = dev_clamped + test_clamped
        split_notes: dict[str, Any] = {
            "dev_split_source": dev_qrels.url,
            "test_split_source": test_qrels.url,
        }
    else:
        # Datasets like TREC-COVID publish only a single test qrels file.
        # Partition deterministically 50/50 by SHA-256 without tuning.
        combined, dropped_qrels, dropped_queries, clamped_negative = _read_qrels(
            test_qrels.path, test_qrels.url, by_id, omitted
        )
        dev_ids, test_ids = carve_out_split(
            sorted(combined), seed=seed, purpose=f"{manifest['dataset_id']}-split"
        )
        dev = {query_id: combined[query_id] for query_id in dev_ids}
        test = {query_id: combined[query_id] for query_id in test_ids}
        dev_dropped_qrels, test_dropped_qrels = dropped_qrels, 0
        dev_dropped_queries, test_dropped_queries = dropped_queries, 0
        split_notes = {
            "dev_split_source": test_qrels.url,
            "test_split_source": test_qrels.url,
            "split_source": "deterministic 50/50 carve-out of source test qrels (no public dev/train qrels)",
        }
    splits = {
        "dev": _split_request(
            queries=query_text,
            qrels=dev,
            language=language,
            language_slice=language_slice,
            category=category,
        ),
        "test": _split_request(
            queries=query_text,
            qrels=test,
            language=language,
            language_slice=language_slice,
            category=category,
        ),
    }
    notes: dict[str, Any] = {
        "source_format": "mteb-beir",
        "transform_seed": seed,
        **split_notes,
        "query_filter": "queries with at least one qrel in the split",
    }
    if clamped_negative:
        notes["negative_qrel_grades_mapped_to_zero"] = clamped_negative
    if omitted:
        # A few BEIR rows have neither title nor text. They cannot be indexed
        # or match the loader's nonempty-text contract, so they are omitted and
        # their (few) qrels are dropped, visibly and deterministically.
        notes["empty_documents_omitted"] = len(omitted)
        notes["qrels_dropped_for_empty_documents"] = {
            "dev": dev_dropped_qrels,
            "test": test_dropped_qrels,
        }
        notes["queries_dropped_for_empty_documents"] = {
            "dev": dev_dropped_queries,
            "test": test_dropped_queries,
        }
    return BuildRequest(
        dataset_id=manifest["dataset_id"],
        documents=documents,
        splits=splits,
        files_root=manifest.get("files_root"),
        notes=notes,
    )


@register("beir-scifact")
def prepare_scifact(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    return prepare(manifest, sources, seed)


@register("beir-nfcorpus")
def prepare_nfcorpus(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    return prepare(manifest, sources, seed)


@register("beir-fiqa")
def prepare_fiqa(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    return prepare(manifest, sources, seed)


@register("beir-trec-covid")
def prepare_trec_covid(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    return prepare(manifest, sources, seed)
