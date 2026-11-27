"""Judgment commands and validation (SPEC-0004-R14, sections 4.5-4.7, 5.4).

Every test names its requirement IDs. Fixtures are synthetic and built in a
temporary directory; no user data and no network are involved.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from support import (
    SOURCES_DIR,
    TESTMINI_PROFILE,
    TOOL_ROOT,
    build_mini,
    corpus_rows,
    manifest,
    sidecar_rows,
    temporary_directory,
)

from sdc_generator.errors import SdcError
from sdc_generator.judgments import (
    freeze_split,
    publish,
    validate_judgment_set,
)

CATEGORIES = (
    "known_item",
    "conceptual",
    "exact_identifier",
    "cross_language",
    "needle_in_haystack",
    "exploratory",
    "mixed_semantic_metadata",
    "code_search",
    "filename_partial",
)

SLICE_LANGUAGES = {
    "pt": ("pt-BR", ["pt"]),
    "en": ("en-US", ["en"]),
    "cross_lingual": ("pt-BR", ["en"]),
    "other": ("es-ES", ["es"]),
    "non_latin_non_regression": ("ja-JP", ["ja"]),
}


def _digest(seed: str, purpose: str, stable_key: str) -> bytes:
    payload = b"SDC1\0" + seed.encode("ascii") + b"\0" + purpose.encode("ascii")
    payload += b"\0" + stable_key.encode("ascii")
    return hashlib.sha256(payload).digest()


def _unit(seed: str, purpose: str, stable_key: str) -> float:
    return int.from_bytes(_digest(seed, purpose, stable_key)[:8], "big") / (1 << 64)


def split_assignment(queries: list[dict[str, Any]], split_seed: str) -> dict[str, str]:
    """Independent reference implementation of SPEC-0004 section 5.4."""

    strata: dict[tuple[str, str, str], list[str]] = {}
    for query in queries:
        key = (
            query["category"],
            query["language_slice"],
            query["configuration"],
        )
        strata.setdefault(key, []).append(query["_id"])
    result: dict[str, str] = {}
    for ids in strata.values():
        ordered = sorted(ids, key=lambda qid: (_digest(split_seed, "query-split-order", qid), qid))
        for index in range(0, len(ordered), 2):
            first, second = ordered[index], ordered[index + 1]
            direction = min(first, second)
            if _unit(split_seed, "query-split-direction", direction) < 0.5:
                result[first], result[second] = "dev", "test"
            else:
                result[first], result[second] = "test", "dev"
    return result


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        for row in rows
    )
    path.write_text(data, encoding="utf-8", newline="\n")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _human_provenance() -> dict[str, Any]:
    return {
        "drafted_by": "human:reviewer-a",
        "verified_by": ["human:reviewer-a"],
        "state": "verified",
        "adjudicated_by": None,
    }


def _manifest(
    *,
    set_id: str,
    state: str,
    corpus_hash: str,
    split_seed: str | None = None,
    test_pool_system_ids: list[str] | None = None,
    test_exposure: str = "unexposed",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "judgment_set_id": set_id,
        "state": state,
        "split_seed": split_seed or f"{set_id}-split-v1",
        "compatible_corpus_hashes": [corpus_hash],
        "query_counts": {"dev": 0, "test": 0},
        "query_file_sha256": {},
        "file_sha256": {},
        "test_pool_system_ids": test_pool_system_ids or [],
        "supersedes": None,
        "test_exposure": test_exposure,
    }


def _query(
    *,
    qid: str,
    index: int,
    category: str,
    language_slice: str,
    split: str,
    configuration: str = "default",
    filters: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    language, targets = SLICE_LANGUAGES[language_slice]
    if language_slice == "cross_lingual" and index % 2:
        language, targets = "en-US", ["pt"]
    return {
        "_id": qid,
        "text": f"synthetic query {index} for {category}",
        "language": language,
        "target_languages": targets,
        "language_slice": language_slice,
        "category": category,
        "configuration": configuration,
        "split": split,
        "filters": filters,
        "provenance": provenance or _human_provenance(),
    }


def smoke_queries() -> list[dict[str, Any]]:
    """Forty-five dev queries, five per category (SPEC-0004-R26)."""

    slices = ("pt", "en", "cross_lingual", "other", "non_latin_non_regression")
    rows: list[dict[str, Any]] = []
    index = 1
    for category in CATEGORIES:
        for position in range(5):
            language_slice = slices[position]
            configuration = "code_enabled" if category == "code_search" else "default"
            filters = {"extensions": ["pdf"]} if category == "mixed_semantic_metadata" else None
            rows.append(
                _query(
                    qid=f"q-sdc-smoke-v1-{index:06d}",
                    index=index,
                    category=category,
                    language_slice=language_slice,
                    split="dev",
                    configuration=configuration,
                    filters=filters,
                )
            )
            index += 1
    return rows


def full_queries() -> list[dict[str, Any]]:
    """Six hundred queries meeting the SPEC-0004-R16/R17 minima."""

    sizes = [66, 66, 66, 66, 66, 66, 68, 68, 68]
    small = (
        ("pt", 12),
        ("en", 12),
        ("cross_lingual", 8),
        ("other", 32),
        ("non_latin_non_regression", 2),
    )
    large = (
        ("pt", 12),
        ("en", 12),
        ("cross_lingual", 4),
        ("other", 40),
        ("non_latin_non_regression", 0),
    )
    draft: list[dict[str, Any]] = []
    index = 1
    for category, size in zip(CATEGORIES, sizes, strict=True):
        allocation = small if size == 66 else large
        for language_slice, count in allocation:
            for _ in range(count):
                configuration = "code_enabled" if category == "code_search" else "default"
                filters = {"extensions": ["pdf"]} if category == "mixed_semantic_metadata" else None
                draft.append(
                    _query(
                        qid=f"q-sdc-v1-{index:06d}",
                        index=index,
                        category=category,
                        language_slice=language_slice,
                        split="dev",
                        configuration=configuration,
                        filters=filters,
                    )
                )
                index += 1
    assignment = split_assignment(draft, "sdc-v1-split-v1")
    for query in draft:
        query["split"] = assignment[query["_id"]]
    for query in draft:
        if query["language_slice"] == "other":
            query["language"] = ("es-ES", "fr-FR", "de-DE")[int(query["_id"][-2:]) % 3]
            query["target_languages"] = [query["language"][:2]]
    return draft


def _qrels(
    queries: list[dict[str, Any]],
    document: dict[str, Any],
    passage: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    documents: list[dict[str, Any]] = []
    passages: list[dict[str, Any]] = []
    for query in queries:
        subtopics = ["overview"] if query["category"] == "exploratory" else []
        documents.append(
            {
                "judgment_set_id": "",
                "query_id": query["_id"],
                "document_id": document["_id"],
                "document_text_sha256": document["metadata"]["text_sha256"],
                "grade": 3,
                "evidence_passage_ids": [passage["_id"]],
                "subtopic_labels": subtopics,
                "provenance": _human_provenance(),
            }
        )
        passages.append(
            {
                "judgment_set_id": "",
                "query_id": query["_id"],
                "document_id": document["_id"],
                "passage_id": passage["_id"],
                "passage_text_sha256": passage["text_sha256"],
                "grade": 3,
                "evidence_spans": [],
                "provenance": _human_provenance(),
            }
        )
    return documents, passages


def _pools(queries: list[dict[str, Any]], document_id: str, corpus_hash: str) -> list[dict[str, Any]]:
    return [
        {
            "query_id": query["_id"],
            "document_id": document_id,
            "passage_id": None,
            "origin": "known_target",
            "run_id": None,
            "system_id": None,
            "rank": None,
            "corpus_hash": corpus_hash,
        }
        for query in queries
    ]


def _draft_root(base: Path, set_id: str) -> Path:
    return base / "bench" / "qrels" / "sdc" / "drafts" / set_id


def _write_smoke_draft(
    root: Path,
    *,
    corpus_root: Path,
    queries: list[dict[str, Any]] | None = None,
    write_qrels: bool = True,
    include_pool: bool = False,
) -> dict[str, Any]:
    rows = corpus_rows(corpus_root)
    document = rows[sorted(rows)[0]]
    passage = next(
        item for item in sidecar_rows(corpus_root, "passages.jsonl")
        if item["document_id"] == document["_id"]
    )
    query_rows = queries if queries is not None else smoke_queries()
    set_id = "sdc-smoke-v1"
    corpus_hash = manifest(corpus_root)["corpus_hash"]
    data = _manifest(set_id=set_id, state="draft", corpus_hash=corpus_hash)
    _write_json(root / "judgment-set.json", data)
    _write_json(
        root / "reviewers.json",
        {
            "schema_version": 1,
            "reviewers": [
                {"reviewer_id": "reviewer-a", "roles": ["verifier"]},
                {"reviewer_id": "reviewer-b", "roles": ["verifier", "adjudicator"]},
            ],
        },
    )
    _write_jsonl(root / "queries.draft.jsonl", sorted(query_rows, key=lambda row: row["_id"]))
    if write_qrels:
        documents, passages = _qrels(query_rows, document, passage)
        for row in documents:
            row["judgment_set_id"] = set_id
        for row in passages:
            row["judgment_set_id"] = set_id
        _write_jsonl(
            root / "qrels.draft.documents.jsonl",
            sorted(documents, key=lambda row: (row["query_id"], row["document_id"])),
        )
        _write_jsonl(
            root / "qrels.draft.passages.jsonl",
            sorted(
                passages,
                key=lambda row: (row["query_id"], row["document_id"], row["passage_id"]),
            ),
        )
    if include_pool:
        _write_jsonl(
            root / "pools.draft.jsonl",
            sorted(
                _pools(query_rows, document["_id"], corpus_hash),
                key=lambda row: (
                    row["query_id"],
                    row["document_id"],
                    row["passage_id"] or "",
                    row["origin"],
                    row["run_id"] or "",
                ),
            ),
        )
    return {"document": document, "passage": passage, "corpus_hash": corpus_hash}


class JudgmentTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="sdc-judgments-"))
        cls.corpus = cls.tmp / "corpus"
        build_mini(cls.corpus)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_draft_validate_requires_allow_draft(self) -> None:
        # SPEC-0004-R14, R22: a quarantined draft is not benchmark-eligible.
        root = _draft_root(self.tmp, "draft-only")
        _write_smoke_draft(root, corpus_root=self.corpus)
        with self.assertRaises(SdcError) as caught:
            validate_judgment_set(root, self.corpus)
        self.assertEqual(caught.exception.code, "TEST_NOT_ELIGIBLE")
        summary = validate_judgment_set(root, self.corpus, allow_draft=True)
        self.assertEqual(summary["state"], "draft")
        self.assertEqual(summary["queries"], 45)

    def test_allow_draft_is_rejected_outside_the_draft_area(self) -> None:
        # SPEC-0004 sections 4.1 and 4.7: only bench/qrels/sdc/drafts qualifies.
        bad_roots = (
            self.tmp / "drafts" / "x",
            self.tmp / "bench" / "qrels" / "drafts" / "x",
            self.tmp / "bench" / "qrels" / "sdc" / "published",
        )
        for index, bad_root in enumerate(bad_roots):
            with self.subTest(index=index):
                _write_smoke_draft(bad_root, corpus_root=self.corpus)
                with self.assertRaises(SdcError) as caught:
                    validate_judgment_set(bad_root, self.corpus, allow_draft=True)
                self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

        canonical = _draft_root(self.tmp, "canonical")
        _write_smoke_draft(canonical, corpus_root=self.corpus)
        summary = validate_judgment_set(canonical, self.corpus, allow_draft=True)
        self.assertEqual(summary["state"], "draft")

    def test_freeze_split_records_query_hashes_and_smoke_minima(self) -> None:
        # SPEC-0004-R14, R26, section 5.4.
        root = _draft_root(self.tmp, "freeze-smoke")
        _write_smoke_draft(root, corpus_root=self.corpus)
        summary = freeze_split(root)
        self.assertEqual(summary["state"], "split_frozen")
        data = json.loads((root / "judgment-set.json").read_text(encoding="utf-8"))
        self.assertEqual(data["state"], "split_frozen")
        self.assertEqual(data["query_counts"], {"dev": 45, "test": 0})
        self.assertEqual(sorted(data["query_file_sha256"]), ["dev"])
        self.assertEqual(len(data["query_file_sha256"]["dev"]), 64)
        self.assertEqual(data["file_sha256"], {})
        # The recorded digest is over the exact bytes publication will write.
        expected = "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            for row in sorted(smoke_queries(), key=lambda row: row["_id"])
        ).encode("utf-8")
        self.assertEqual(data["query_file_sha256"]["dev"], hashlib.sha256(expected).hexdigest())
        with self.assertRaises(SdcError):
            freeze_split(root)

    def test_freeze_split_rejects_a_full_set_below_minima(self) -> None:
        # SPEC-0004-R16, R17.
        root = _draft_root(self.tmp, "below-minima")
        rows = full_queries()[:20]
        assignment = split_assignment(rows, "sdc-v1-split-v1")
        for row in rows:
            row["split"] = assignment[row["_id"]]
        _write_json(
            root / "judgment-set.json",
            _manifest(set_id="sdc-v1", state="draft", corpus_hash="0" * 64),
        )
        _write_jsonl(root / "queries.draft.jsonl", sorted(rows, key=lambda row: row["_id"]))
        with self.assertRaises(SdcError) as caught:
            freeze_split(root)
        self.assertIn("minimum", caught.exception.message)

    def test_freeze_split_accepts_full_minima_and_rejects_reassignment(self) -> None:
        # SPEC-0004-R16, R17, section 5.4.
        root = _draft_root(self.tmp, "full-set")
        rows = full_queries()
        _write_json(
            root / "judgment-set.json",
            _manifest(set_id="sdc-v1", state="draft", corpus_hash="0" * 64),
        )
        _write_jsonl(root / "queries.draft.jsonl", sorted(rows, key=lambda row: row["_id"]))
        summary = freeze_split(root)
        self.assertEqual(summary["state"], "split_frozen")
        self.assertEqual(summary["queries"], 600)
        data = json.loads((root / "judgment-set.json").read_text(encoding="utf-8"))
        self.assertEqual(data["query_counts"], {"dev": 300, "test": 300})
        self.assertEqual(sorted(data["query_file_sha256"]), ["dev", "test"])

        other = _draft_root(self.tmp, "reassigned")
        changed = [dict(row) for row in rows]
        changed[0]["split"] = "test" if changed[0]["split"] == "dev" else "dev"
        _write_json(
            other / "judgment-set.json",
            _manifest(set_id="sdc-v1", state="draft", corpus_hash="0" * 64),
        )
        _write_jsonl(other / "queries.draft.jsonl", sorted(changed, key=lambda row: row["_id"]))
        with self.assertRaises(SdcError) as caught:
            freeze_split(other)
        self.assertIn("split", caught.exception.message)

    def test_freeze_split_rejects_pool_rows(self) -> None:
        # SPEC-0004-R16/R23: split freeze precedes any run pool.
        root = _draft_root(self.tmp, "pooled-too-early")
        fixture = _write_smoke_draft(root, corpus_root=self.corpus)
        _write_jsonl(
            root / "pools.draft.jsonl",
            [
                {
                    "query_id": "q-sdc-smoke-v1-000001",
                    "document_id": fixture["document"]["_id"],
                    "passage_id": None,
                    "origin": "run",
                    "run_id": "run-1",
                    "system_id": "baseline",
                    "rank": 1,
                    "corpus_hash": fixture["corpus_hash"],
                }
            ],
        )
        with self.assertRaises(SdcError) as caught:
            freeze_split(root)
        self.assertEqual(caught.exception.code, "TEST_NOT_ELIGIBLE")

    def test_publish_requires_split_frozen(self) -> None:
        root = _draft_root(self.tmp, "publish-draft")
        _write_smoke_draft(root, corpus_root=self.corpus)
        with self.assertRaises(SdcError) as caught:
            publish(root, self.tmp / "out")
        self.assertEqual(caught.exception.code, "TEST_NOT_ELIGIBLE")

    def test_publish_requires_a_predeclared_test_pool_panel(self) -> None:
        # SPEC-0004-R24: test pooling precedes exposure and names its systems.
        root = _draft_root(self.tmp, "panel")
        rows = full_queries()
        _write_json(
            root / "judgment-set.json",
            _manifest(set_id="sdc-v1", state="draft", corpus_hash="0" * 64),
        )
        _write_jsonl(root / "queries.draft.jsonl", sorted(rows, key=lambda row: row["_id"]))
        _write_jsonl(root / "qrels.draft.documents.jsonl", [])
        _write_jsonl(root / "qrels.draft.passages.jsonl", [])
        freeze_split(root)
        with self.assertRaises(SdcError) as caught:
            publish(root, self.tmp / "out-panel")
        self.assertEqual(caught.exception.code, "TEST_NOT_ELIGIBLE")

    def test_publish_refuses_unverified_and_missing_provenance(self) -> None:
        # SPEC-0004-R20-R22.
        root = _draft_root(self.tmp, "publish-provenance")
        _write_smoke_draft(root, corpus_root=self.corpus)
        freeze_split(root)
        qrels_path = root / "qrels.draft.documents.jsonl"
        rows = [json.loads(line) for line in qrels_path.read_text(encoding="utf-8").splitlines()]
        rows[0]["provenance"]["state"] = "draft"
        rows[0]["provenance"]["verified_by"] = []
        _write_jsonl(qrels_path, rows)
        with self.assertRaises(SdcError) as caught:
            publish(root, self.tmp / "out-unverified")
        self.assertIn(caught.exception.code, {"TEST_NOT_ELIGIBLE", "PROVENANCE_INCOMPLETE"})

        root2 = _draft_root(self.tmp, "publish-missing-provenance")
        _write_smoke_draft(root2, corpus_root=self.corpus)
        freeze_split(root2)
        qrels_path2 = root2 / "qrels.draft.documents.jsonl"
        rows2 = [json.loads(line) for line in qrels_path2.read_text(encoding="utf-8").splitlines()]
        del rows2[0]["provenance"]["verified_by"]
        _write_jsonl(qrels_path2, rows2)
        with self.assertRaises(SdcError) as caught:
            publish(root2, self.tmp / "out-missing")
        self.assertEqual(caught.exception.code, "PROVENANCE_INCOMPLETE")

    def test_publish_refuses_an_existing_output_and_is_atomic(self) -> None:
        # SPEC-0004-R14, section 4.1.
        root = _draft_root(self.tmp, "publish-once")
        fixture = _write_smoke_draft(root, corpus_root=self.corpus)
        freeze_split(root)
        _write_jsonl(
            root / "pools.draft.jsonl",
            _pools(smoke_queries(), fixture["document"]["_id"], fixture["corpus_hash"]),
        )
        output = self.tmp / "published" / "sdc-smoke-v1"
        digest = publish(root, output)
        self.assertEqual(len(digest), 64)
        self.assertEqual(manifest_like(output)["state"], "frozen")
        with self.assertRaises(SdcError) as caught:
            publish(root, output)
        self.assertEqual(caught.exception.code, "OUTPUT_EXISTS")

    def test_publish_rejects_a_query_edit_after_freeze(self) -> None:
        # SPEC-0004-R23: frozen query membership and split assignment are immutable.
        root = _draft_root(self.tmp, "publish-frozen-query")
        _write_smoke_draft(root, corpus_root=self.corpus)
        freeze_split(root)
        path = root / "queries.draft.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["text"] = "reworded after freeze"
        _write_jsonl(path, rows)
        with self.assertRaises(SdcError) as caught:
            publish(root, self.tmp / "out-edited")
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_publish_omits_rejected_records(self) -> None:
        # SPEC-0004-R22: rejected records remain quarantined and are never published.
        root = _draft_root(self.tmp, "publish-rejected")
        _write_smoke_draft(root, corpus_root=self.corpus)
        freeze_split(root)
        path = root / "qrels.draft.documents.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rejected = dict(rows[0])
        rejected["provenance"] = {
            "drafted_by": "human:reviewer-a",
            "verified_by": [],
            "state": "rejected",
            "adjudicated_by": None,
        }
        rows[0] = rejected
        _write_jsonl(path, rows)
        output = self.tmp / "published" / "rejected"
        publish(root, output)
        published = [
            json.loads(line)
            for line in (output / "qrels.dev.documents.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertNotIn(rejected["query_id"], {row["query_id"] for row in published})
        self.assertEqual(len(published), len(smoke_queries()) - 1)

    def test_publish_refuses_incomplete_pool_coverage(self) -> None:
        # SPEC-0004-R24, section 5.6.
        root = _draft_root(self.tmp, "pool-incomplete")
        fixture = _write_smoke_draft(root, corpus_root=self.corpus, include_pool=False)
        freeze_split(root)
        _write_jsonl(
            root / "pools.draft.jsonl",
            [
                {
                    "query_id": "q-sdc-smoke-v1-000001",
                    "document_id": fixture["document"]["_id"],
                    "passage_id": fixture["passage"]["_id"],
                    "origin": "run",
                    "run_id": "run-1",
                    "system_id": "baseline",
                    "rank": 1,
                    "corpus_hash": fixture["corpus_hash"],
                }
            ],
        )
        path = root / "qrels.draft.passages.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows = [row for row in rows if row["query_id"] != "q-sdc-smoke-v1-000001"]
        _write_jsonl(path, rows)
        document_path = root / "qrels.draft.documents.jsonl"
        document_rows = [
            json.loads(line)
            for line in document_path.read_text(encoding="utf-8").splitlines()
        ]
        for row in document_rows:
            if row["query_id"] == "q-sdc-smoke-v1-000001":
                row["grade"] = 1
                row["evidence_passage_ids"] = []
        _write_jsonl(document_path, document_rows)
        with self.assertRaises(SdcError) as caught:
            publish(root, self.tmp / "out-pool")
        self.assertEqual(caught.exception.code, "POOL_INCOMPLETE")

    def test_validate_frozen_checks_corpus_target_hashes(self) -> None:
        # SPEC-0004-R19, R25.
        root = _draft_root(self.tmp, "frozen-validate")
        _write_smoke_draft(root, corpus_root=self.corpus)
        freeze_split(root)
        output = self.tmp / "published" / "frozen"
        publish(root, output)
        summary = validate_judgment_set(output, self.corpus)
        self.assertEqual(summary["state"], "frozen")
        self.assertEqual(summary["queries"], 45)
        path = output / "qrels.dev.passages.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["passage_text_sha256"] = "f" * 64
        _write_jsonl(path, rows)
        refresh_frozen_file_hashes(output)
        with self.assertRaises(SdcError) as caught:
            validate_judgment_set(output, self.corpus)
        self.assertEqual(caught.exception.code, "QREL_TARGET_STALE")

    def test_frozen_set_rejects_draft_and_rejected_records(self) -> None:
        # SPEC-0004-R22: no unverified item is benchmark-eligible.
        root = _draft_root(self.tmp, "frozen-draft")
        _write_smoke_draft(root, corpus_root=self.corpus)
        freeze_split(root)
        output = self.tmp / "published" / "frozen-draft"
        publish(root, output)
        path = output / "qrels.dev.documents.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["provenance"]["state"] = "draft"
        rows[0]["provenance"]["verified_by"] = []
        _write_jsonl(path, rows)
        refresh_frozen_file_hashes(output)
        with self.assertRaises(SdcError) as caught:
            validate_judgment_set(output, self.corpus)
        self.assertIn(caught.exception.code, {"TEST_NOT_ELIGIBLE", "PROVENANCE_INCOMPLETE"})

    def test_malformed_inputs_are_typed_and_location_bearing(self) -> None:
        # SPEC-0004-R13/R14: no panic, stable code, relative file and line.
        root = _draft_root(self.tmp, "malformed")
        _write_smoke_draft(root, corpus_root=self.corpus)
        (root / "queries.draft.jsonl").write_bytes(b"\xff\n")
        with self.assertRaises(SdcError) as caught:
            validate_judgment_set(root, self.corpus, allow_draft=True)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")
        self.assertEqual(caught.exception.file, "queries.draft.jsonl")
        self.assertNotIn(str(root), caught.exception.file or "")

    def test_malformed_grades_ids_and_spans(self) -> None:
        cases = {
            "bool-grade": lambda rows: rows[0].__setitem__("grade", True),
            "float-grade": lambda rows: rows[0].__setitem__("grade", 2.0),
            "bad-span": lambda rows: rows[0].__setitem__(
                "evidence_spans", [{"start_utf8": 10, "end_utf8": 5}]
            ),
            "duplicate-query": lambda rows: rows[1].__setitem__(
                "query_id", rows[0]["query_id"]
            ),
            "missing-order-key": lambda rows: rows[0].pop("query_id"),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                root = _draft_root(self.tmp, f"malformed-{name}")
                _write_smoke_draft(root, corpus_root=self.corpus)
                path = root / "qrels.draft.passages.jsonl"
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                mutate(rows)
                _write_jsonl(path, rows)
                with self.assertRaises(SdcError) as caught:
                    validate_judgment_set(root, self.corpus, allow_draft=True)
                self.assertIn(caught.exception.code, {"SCHEMA_INVALID", "QREL_TARGET_STALE"})
                self.assertIsNotNone(caught.exception.file)

    def test_duplicate_query_ids_are_rejected(self) -> None:
        root = _draft_root(self.tmp, "duplicate-ids")
        rows = smoke_queries()
        rows[1]["_id"] = rows[0]["_id"]
        _write_smoke_draft(root, corpus_root=self.corpus, queries=rows)
        with self.assertRaises(SdcError) as caught:
            validate_judgment_set(root, self.corpus, allow_draft=True)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")


def manifest_like(root: Path) -> dict[str, Any]:
    return json.loads((root / "judgment-set.json").read_text(encoding="utf-8"))


def refresh_frozen_file_hashes(root: Path) -> None:
    """Recompute file_sha256 after a test deliberately tampers with a frozen set."""

    data = manifest_like(root)
    data["file_sha256"] = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in data["file_sha256"]
    }
    _write_json(root / "judgment-set.json", data)


class CommandTests(unittest.TestCase):
    """End-to-end CLI tests for the three judgment commands (R14)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="sdc-judgment-cli-"))
        cls.corpus = cls.tmp / "corpus"
        build_mini(cls.corpus)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, *args: str, pythonpath: str | None = None) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["PYTHONPATH"] = pythonpath or str(TOOL_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "sdc_generator", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )

    def test_judgment_command_smoke(self) -> None:
        # SPEC-0004-R14 command smoke tests.
        root = _draft_root(self.tmp, "cli")
        _write_smoke_draft(root, corpus_root=self.corpus)
        validate = self._run(
            "judgments", "validate", "--set", str(root),
            "--corpus", str(self.corpus), "--allow-draft",
        )
        self.assertEqual(validate.returncode, 0, validate.stderr)
        freeze = self._run("judgments", "freeze-split", "--draft", str(root))
        self.assertEqual(freeze.returncode, 0, freeze.stderr)
        output = self.tmp / "published" / "cli"
        publish = self._run(
            "judgments", "publish", "--draft", str(root), "--output", str(output)
        )
        self.assertEqual(publish.returncode, 0, publish.stderr)
        self.assertEqual(len(publish.stdout.strip()), 64)
        frozen = self._run(
            "judgments", "validate", "--set", str(output), "--corpus", str(self.corpus)
        )
        self.assertEqual(frozen.returncode, 0, frozen.stderr)

    def test_build_verify_and_judgment_validation_never_access_network(self) -> None:
        # SPEC-0004-R14: only fetch may open a network connection.
        with temporary_directory("sdc-network-") as directory:
            blocker = directory / "blocker"
            blocker.mkdir()
            (blocker / "sitecustomize.py").write_text(
                "import socket\n"
                "def _deny(*args, **kwargs):\n"
                "    raise OSError('network disabled by SPEC-0004-R14 test')\n"
                "socket.socket = _deny\n"
                "socket.create_connection = _deny\n"
                "socket.getaddrinfo = _deny\n",
                encoding="utf-8",
            )
            path = os.pathsep.join([str(blocker), str(TOOL_ROOT)])
            probe = subprocess.run(
                [sys.executable, "-c", "import socket; socket.socket()"],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": path},
                timeout=60,
            )
            self.assertNotEqual(probe.returncode, 0, "network blocker failed to engage")
            output = directory / "corpus"
            for args in (
                (
                    "build", "--profile", str(TESTMINI_PROFILE), "--seed", "net-v1",
                    "--sources", str(SOURCES_DIR), "--cache", str(directory / "cache"),
                    "--output", str(output),
                ),
                ("verify", "--output", str(output)),
            ):
                result = self._run(*args, pythonpath=path)
                self.assertEqual(result.returncode, 0, result.stderr)
            root = directory / "bench" / "qrels" / "sdc" / "drafts" / "sdc-smoke-v1"
            _write_smoke_draft(root, corpus_root=output)
            result = self._run(
                "judgments", "validate", "--set", str(root),
                "--corpus", str(output), "--allow-draft", pythonpath=path,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


class DependencyInspectionTests(unittest.TestCase):
    def test_runtime_dependency_set_is_empty_and_stdlib_only(self) -> None:
        # SPEC-0004-R14 dependency/license inspection.
        lock = (TOOL_ROOT / "requirements.lock").read_text(encoding="utf-8")
        self.assertIn("Runtime dependency set: EMPTY", lock)
        import ast

        package = TOOL_ROOT / "sdc_generator"
        for path in package.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    top = name.split(".")[0]
                    self.assertTrue(
                        top in sys.stdlib_module_names or top == "sdc_generator",
                        f"unexpected dependency {name!r} in {path.name}",
                    )
                    if top in {"socket", "ssl", "urllib", "http", "ftplib", "smtplib"}:
                        self.assertEqual(path.name, "sources.py", f"network import in {path.name}")


if __name__ == "__main__":
    unittest.main()
