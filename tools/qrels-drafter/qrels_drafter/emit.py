"""Write the quarantined draft judgment set (SPEC-0004 4.5-4.7)."""

from __future__ import annotations

from pathlib import Path

from . import config
from .corpus import Corpus
from .digest import digest, unit_float
from .judge import DocJudgment
from .jsonio import jsonl_bytes, pretty_bytes, write_bytes
from .templates import Draft

DRAFT_FILES = (
    "queries.draft.jsonl",
    "qrels.draft.documents.jsonl",
    "qrels.draft.passages.jsonl",
    "pools.draft.jsonl",
)


def stratum(draft: Draft) -> tuple[str, str, str]:
    return (draft.category, draft.language_slice, draft.configuration)


def assign_ids(drafts: list[Draft]) -> list[tuple[str, Draft]]:
    """Stable numeric IDs over a content-derived order, independent of the host."""

    ordered = sorted(
        drafts,
        key=lambda draft: (
            draft.category,
            draft.language_slice,
            draft.configuration,
            draft.anchor_id,
            draft.text.casefold(),
        ),
    )
    return [(f"q-sdc-v1-{index:06d}", draft) for index, draft in enumerate(ordered, start=1)]


def assign_splits(identified: list[tuple[str, Draft]], split_seed: str) -> dict[str, str]:
    """SPEC-0004 5.4: adjacent pairs inside each even stratum, seeded direction."""

    strata: dict[tuple[str, str, str], list[str]] = {}
    for query_id, draft in identified:
        strata.setdefault(stratum(draft), []).append(query_id)
    splits: dict[str, str] = {}
    for key in sorted(strata):
        ids = strata[key]
        if len(ids) % 2:
            raise ValueError(f"stratum {key} has an odd number of queries ({len(ids)})")
        ordered = sorted(ids, key=lambda qid: (digest(split_seed, "query-split-order", qid), qid))
        for index in range(0, len(ordered), 2):
            first, second = ordered[index], ordered[index + 1]
            direction = min(first, second)
            if unit_float(split_seed, "query-split-direction", direction) < 0.5:
                splits[first], splits[second] = "dev", "test"
            else:
                splits[first], splits[second] = "test", "dev"
    return splits


def _provenance(draft: Draft, corpus_hash: str) -> dict:
    if draft.origin == "llm":
        if not draft.grade_prompt_sha256:
            raise ValueError("an LLM draft needs a grade prompt hash")
        return {
            "drafted_by": config.DEFAULT_MODEL.drafted_by,
            "llm_prompt_sha256": draft.grade_prompt_sha256,
            "verified_by": [],
            "state": "draft",
            "adjudicated_by": None,
        }
    return {
        "drafted_by": config.drafted_by_tool(),
        "tool_config_sha256": config.tool_config_sha256(corpus_hash),
        "verified_by": [],
        "state": "draft",
        "adjudicated_by": None,
    }


def _query_provenance(draft: Draft, corpus_hash: str) -> dict:
    if draft.origin == "llm":
        if not draft.prompt_sha256:
            raise ValueError("an LLM query needs a prompt hash")
        return {
            "drafted_by": config.DEFAULT_MODEL.drafted_by,
            "llm_prompt_sha256": draft.prompt_sha256,
            "verified_by": [],
            "state": "draft",
            "adjudicated_by": None,
        }
    provenance = _provenance(draft, corpus_hash)
    return provenance


def build_rows(
    corpus: Corpus,
    identified: list[tuple[str, Draft]],
    judgments: list[list[DocJudgment]],
    splits: dict[str, str],
) -> tuple[list[dict], list[dict], list[dict]]:
    queries: list[dict] = []
    documents: list[dict] = []
    passages: list[dict] = []
    for (query_id, draft), judged in zip(identified, judgments):
        queries.append(
            {
                "_id": query_id,
                "text": draft.text,
                "language": draft.language,
                "target_languages": list(draft.target_languages),
                "language_slice": draft.language_slice,
                "category": draft.category,
                "configuration": draft.configuration,
                "split": splits[query_id],
                "filters": draft.filters,
                "provenance": _query_provenance(draft, corpus.corpus_hash),
            }
        )
        provenance = _provenance(draft, corpus.corpus_hash)
        for judgment in judged:
            document = corpus.documents[judgment.document_id]
            documents.append(
                {
                    "judgment_set_id": config.JUDGMENT_SET_ID,
                    "query_id": query_id,
                    "document_id": judgment.document_id,
                    "document_text_sha256": document.text_sha256,
                    "grade": judgment.grade,
                    "evidence_passage_ids": sorted(judgment.evidence_passage_ids),
                    "subtopic_labels": sorted(judgment.subtopic_labels),
                    "provenance": dict(provenance),
                }
            )
            for passage in judgment.passages:
                stored = next(
                    (item for item in corpus.passages(judgment.document_id) if item.id == passage.passage_id),
                    None,
                )
                if stored is None:
                    raise ValueError(f"unknown passage {passage.passage_id}")
                passages.append(
                    {
                        "judgment_set_id": config.JUDGMENT_SET_ID,
                        "query_id": query_id,
                        "document_id": judgment.document_id,
                        "passage_id": passage.passage_id,
                        "passage_text_sha256": stored.text_sha256,
                        "grade": passage.grade,
                        "evidence_spans": [dict(span) for span in passage.spans],
                        "provenance": dict(provenance),
                    }
                )
    queries.sort(key=lambda row: row["_id"])
    documents.sort(key=lambda row: (row["query_id"], row["document_id"]))
    passages.sort(key=lambda row: (row["query_id"], row["document_id"], row["passage_id"]))
    return queries, documents, passages


def manifest(corpus_hash: str, splits: dict[str, str]) -> dict:
    return {
        "schema_version": config.SCHEMA_VERSION,
        "judgment_set_id": config.JUDGMENT_SET_ID,
        "state": "draft",
        "split_seed": config.SPLIT_SEED,
        "compatible_corpus_hashes": [corpus_hash],
        "query_counts": {
            "dev": sum(1 for value in splits.values() if value == "dev"),
            "test": sum(1 for value in splits.values() if value == "test"),
        },
        "query_file_sha256": {},
        "file_sha256": {},
        "test_pool_system_ids": [],
        "supersedes": None,
        "test_exposure": "unexposed",
    }


def write_set(
    output: Path,
    corpus_hash: str,
    splits: dict[str, str],
    queries: list[dict],
    documents: list[dict],
    passages: list[dict],
) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    write_bytes(output / DRAFT_FILES[0], jsonl_bytes(queries))
    write_bytes(output / DRAFT_FILES[1], jsonl_bytes(documents))
    write_bytes(output / DRAFT_FILES[2], jsonl_bytes(passages))
    write_bytes(output / DRAFT_FILES[3], jsonl_bytes([]))
    value = manifest(corpus_hash, splits)
    write_bytes(output / "judgment-set.json", pretty_bytes(value))
    return value
