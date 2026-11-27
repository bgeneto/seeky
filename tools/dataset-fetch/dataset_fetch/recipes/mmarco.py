"""mMARCO recipe and constructed cross-lingual pairs (SPEC-0003 §4.2).

mMARCO is a translation of MS MARCO into 14 languages. Relevance triples
keep the original MS MARCO passage IDs, so a Portuguese query with its triples
can be paired against the English collection (and vice versa). A constructed
pair keeps the source query text and the manifest-declared triples, records
both languages, and uses the stable ID ``<source-query-id>-xl-<src>-<tgt>``.

The real pin is blocked (see bench/datasets/README.md): the Portuguese or
English collection is 3.2-3.4 GB per language. The construction itself is
implemented and covered by synthetic fixtures.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ..cache import CachedFile
from ..canonical import normalize_text, sha256_bytes
from ..errors import SCHEMA, fail
from ..jsio import iter_tsv
from ..transform import BuildRequest, DocumentSpec, QuerySpec, QrelSpec, SplitSpec
from . import find_source, register

LANGUAGE_NAMES = {"pt": "portuguese", "en": "english"}


def constructed_query_id(source_id: str, source_language: str, target_language: str) -> str:
    return f"{source_id}-xl-{source_language}-{target_language}"


def construct_cross_lingual(
    queries: dict[str, str],
    qrels: dict[str, list[QrelSpec]],
    *,
    source_language: str,
    target_language: str,
) -> tuple[list[QuerySpec], list[QrelSpec]]:
    """Build one cross-lingual split from source queries and triples."""

    if source_language == target_language:
        raise fail(SCHEMA, "a cross-lingual pair needs two distinct languages")
    built_queries: list[QuerySpec] = []
    built_qrels: list[QrelSpec] = []
    for source_id in sorted(qrels):
        if source_id not in queries:
            raise fail(
                SCHEMA,
                f"qrels reference unknown query {source_id!r}",
                location="mmarco.qrels",
            )
        query_id = constructed_query_id(source_id, source_language, target_language)
        built_queries.append(
            QuerySpec(
                id=query_id,
                text=queries[source_id],
                language=source_language,
                target_languages=(target_language,),
                language_slice="cross_lingual",
                category="conceptual",
            )
        )
        for qrel in qrels[source_id]:
            built_qrels.append(QrelSpec(query_id, qrel.document_id, qrel.grade))
    if not built_queries:
        raise fail(SCHEMA, "no cross-lingual queries were constructed")
    return built_queries, built_qrels


def carve_out_split(
    query_ids: list[str],
    *,
    seed: str,
    purpose: str,
    fraction: float = 0.5,
) -> tuple[list[str], list[str]]:
    """Deterministically split query IDs when a source has no test qrels.

    Keys are ordered by ``SHA-256(seed NUL purpose NUL query_id)`` so the
    assignment does not depend on input order or platform. Both halves keep
    their source qrels; nothing is tuned on them.
    """

    if not 0.0 < fraction < 1.0:
        raise fail(SCHEMA, "split fraction must be between 0 and 1")
    ordered = sorted(
        sorted(set(query_ids)),
        key=lambda query_id: sha256_bytes(
            f"{seed}\0{purpose}\0{query_id}".encode("utf-8")
        ),
    )
    cut = max(1, min(len(ordered) - 1, round(len(ordered) * fraction)))
    return sorted(ordered[:cut]), sorted(ordered[cut:])


def _load_collection(path: Path, location: str) -> list[DocumentSpec]:
    documents: list[DocumentSpec] = []
    seen: set[str] = set()
    for line_number, fields in enumerate(iter_tsv(path), start=1):
        where = f"{location}:{line_number}"
        if len(fields) != 2 or not fields[0] or fields[1] == "":
            raise fail(SCHEMA, "expected two nonempty TSV columns", location=where)
        if fields[0] in seen:
            raise fail(SCHEMA, "duplicate passage ID", location=where)
        seen.add(fields[0])
        documents.append(DocumentSpec(fields[0], "", normalize_text(fields[1])))
    return documents


def _load_queries(path: Path, location: str) -> dict[str, str]:
    queries: dict[str, str] = {}
    for line_number, fields in enumerate(iter_tsv(path), start=1):
        where = f"{location}:{line_number}"
        if len(fields) != 2 or not fields[0] or fields[1] == "":
            raise fail(SCHEMA, "expected two nonempty TSV columns", location=where)
        if fields[0] in queries:
            raise fail(SCHEMA, "duplicate query ID", location=where)
        queries[fields[0]] = normalize_text(fields[1])
    return queries


def _load_qrels(
    path: Path, location: str, documents: dict[str, DocumentSpec]
) -> dict[str, list[QrelSpec]]:
    by_query: dict[str, list[QrelSpec]] = defaultdict(list)
    for line_number, fields in enumerate(iter_tsv(path), start=1):
        where = f"{location}:{line_number}"
        if len(fields) == 4:
            query_id, _marker, document_id, grade_text = fields
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


def _prepare(
    manifest: dict[str, Any],
    sources: list[CachedFile],
    seed: str,
    *,
    source_language: str,
    target_language: str | None,
) -> BuildRequest:
    source_name = LANGUAGE_NAMES[source_language]
    target_name = LANGUAGE_NAMES[target_language or source_language]
    collection = find_source(sources, f"/{target_name}_collection.tsv")
    queries_file = find_source(sources, f"/{source_name}_queries.dev.tsv")
    qrels_file = find_source(sources, "/qrels.dev.tsv")
    documents = _load_collection(collection.path, collection.url)
    by_id = {document.id: document for document in documents}
    queries = _load_queries(queries_file.path, queries_file.url)
    qrels = _load_qrels(qrels_file.path, qrels_file.url, by_id)
    missing = [query_id for query_id in qrels if query_id not in queries]
    if missing:
        raise fail(
            SCHEMA,
            f"qrels reference {len(missing)} queries missing from the dev queries file",
            location=missing[0],
        )
    dev_ids, test_ids = carve_out_split(sorted(qrels), seed=seed, purpose="mmarco-split")

    def build(ids: list[str]) -> SplitSpec:
        if target_language is None:
            return SplitSpec(
                queries=[
                    QuerySpec(
                        id=query_id,
                        text=queries[query_id],
                        language=source_language,
                        target_languages=(source_language,),
                        language_slice=source_language,
                        category="conceptual",
                    )
                    for query_id in ids
                ],
                qrels=[qrel for query_id in ids for qrel in qrels[query_id]],
            )
        pair_queries, pair_qrels = construct_cross_lingual(
            {query_id: queries[query_id] for query_id in ids},
            {query_id: qrels[query_id] for query_id in ids},
            source_language=source_language,
            target_language=target_language,
        )
        return SplitSpec(queries=pair_queries, qrels=pair_qrels)

    return BuildRequest(
        dataset_id=manifest["dataset_id"],
        documents=documents,
        splits={"dev": build(dev_ids), "test": build(test_ids)},
        files_root=manifest.get("files_root"),
        notes={
            "source_format": "mmarco-tsv",
            "transform_seed": seed,
            "split_source": "deterministic carve-out of dev (no public test qrels)",
            "cross_lingual": target_language is not None,
        },
    )


@register("mmarco-pt")
def prepare_mmarco_pt(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    return _prepare(manifest, sources, seed, source_language="pt", target_language=None)


@register("mmarco-pt-en")
def prepare_mmarco_pt_en(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    return _prepare(manifest, sources, seed, source_language="pt", target_language="en")


@register("mmarco-en-pt")
def prepare_mmarco_en_pt(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    return _prepare(manifest, sources, seed, source_language="en", target_language="pt")
