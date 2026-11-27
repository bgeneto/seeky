"""Quati recipe (unicamp-dl/quati, CC-BY-4.0, Brazilian Portuguese 1M passages).

Quati publishes one set of judged topics for its 1M collection
(``topics/quati_test_topics.tsv`` and ``qrels/quati_1M_qrels.txt``). Following
the maintainer's WP-1.5 policy, the recipe partitions the judged topics
deterministically 50/50 by SHA-256 into ``dev`` and ``test`` without tuning.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ..cache import CachedFile
from ..canonical import normalize_text
from ..errors import IO, SCHEMA, fail
from ..jsio import iter_tsv
from ..transform import BuildRequest, DocumentSpec, QuerySpec, QrelSpec, SplitSpec
from . import find_source, register
from .mmarco import carve_out_split


def _read_collection(path: Path, location: str) -> tuple[list[DocumentSpec], set[str]]:
    documents: list[DocumentSpec] = []
    omitted: set[str] = set()
    seen: set[str] = set()
    for line_number, fields in enumerate(iter_tsv(path), start=1):
        where = f"{location}:{line_number}"
        if len(fields) < 2 or not fields[0].strip():
            raise fail(SCHEMA, "expected two TSV columns (doc_id, text)", location=where)
        doc_id = fields[0].strip()
        text = normalize_text("\t".join(fields[1:]))
        if doc_id in seen:
            raise fail(SCHEMA, f"duplicate passage ID {doc_id!r}", location=where)
        seen.add(doc_id)
        if not text.strip():
            omitted.add(doc_id)
            continue
        documents.append(DocumentSpec(doc_id, "", text))
    return documents, omitted


def _read_topics(path: Path, location: str) -> dict[str, str]:
    topics: dict[str, str] = {}
    header_seen = False
    for line_number, fields in enumerate(iter_tsv(path), start=1):
        where = f"{location}:{line_number}"
        if not header_seen:
            header_seen = True
            if fields == ["query_id", "query"]:
                continue
        if len(fields) != 2 or not fields[0].strip() or fields[1] == "":
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
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise fail(IO, str(exc), location=location) from exc
    for line_number, raw in enumerate(raw_lines, start=1):
        line = raw.strip()
        if not line:
            continue
        where = f"{location}:{line_number}"
        fields = line.split()
        if len(fields) == 4:
            query_id, _marker, document_id, grade_text = fields
        elif len(fields) == 3:
            query_id, document_id, grade_text = fields
        else:
            raise fail(SCHEMA, "expected three or four whitespace-separated columns", location=where)
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


@register("quati-pt")
def prepare_quati_pt(
    manifest: dict[str, Any], sources: list[CachedFile], seed: str
) -> BuildRequest:
    collection = find_source(sources, "/quati_1M.tsv")
    topics_file = find_source(sources, "/quati_test_topics.tsv")
    qrels_file = find_source(sources, "/quati_1M_qrels.txt")

    documents, omitted = _read_collection(collection.path, collection.url)
    doc_ids = {document.id for document in documents}
    topics = _read_topics(topics_file.path, topics_file.url)
    qrels, dropped_qrels = _read_qrels(qrels_file.path, qrels_file.url, doc_ids, omitted)

    missing = [query_id for query_id in qrels if query_id not in topics]
    if missing:
        raise fail(
            SCHEMA,
            f"qrels reference {len(missing)} topics missing from the topics file",
            location=missing[0],
        )

    dev_ids, test_ids = carve_out_split(sorted(qrels), seed=seed, purpose="quati-pt-split")

    def build(ids: list[str]) -> SplitSpec:
        return SplitSpec(
            queries=[
                QuerySpec(
                    id=query_id,
                    text=topics[query_id],
                    language="pt",
                    target_languages=("pt",),
                    language_slice="pt",
                    category="conceptual",
                )
                for query_id in ids
            ],
            qrels=[qrel for query_id in ids for qrel in qrels[query_id]],
        )

    notes: dict[str, Any] = {
        "source_format": "quati-1M",
        "source_language": "pt",
        "transform_seed": seed,
        "split_source": "deterministic 50/50 carve-out of judged topics (single public qrels set)",
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
