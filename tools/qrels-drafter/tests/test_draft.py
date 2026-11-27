"""End-to-end draft behaviour on the committed smoke corpus (SPEC-0004 R15-R25)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support
from qrels_drafter import config
from qrels_drafter.audit import audit_directory
from qrels_drafter.jsonio import load_json, read_jsonl
from qrels_drafter.model import command_runner
from qrels_drafter.pipeline import run_draft

TEMPLATE = set(config.TEMPLATE_CATEGORIES)
SEMANTIC = set(config.LLM_CATEGORIES)


def _read(directory: Path) -> dict:
    return {
        "queries": read_jsonl(directory / "queries.draft.jsonl"),
        "documents": read_jsonl(directory / "qrels.draft.documents.jsonl"),
        "passages": read_jsonl(directory / "qrels.draft.passages.jsonl"),
        "pools": read_jsonl(directory / "pools.draft.jsonl"),
        "manifest": load_json(directory / "judgment-set.json"),
    }


class DraftedFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = support.draft_fixture()
        cls.data = _read(cls.directory)

    def test_same_corpus_and_config_produce_byte_identical_draft(self):
        second = Path(tempfile.mkdtemp(prefix="qrels-drafter-again-")) / "draft"
        run_draft(
            support.CORPUS,
            second,
            command_runner([sys.executable, str(support.STUB)]),
            plan=support.TEST_PLAN,
            check_minima=False,
        )
        for name in (
            "queries.draft.jsonl",
            "qrels.draft.documents.jsonl",
            "qrels.draft.passages.jsonl",
            "pools.draft.jsonl",
            "judgment-set.json",
        ):
            self.assertEqual((self.directory / name).read_bytes(), (second / name).read_bytes(), name)

    def test_tool_provenance_covers_only_template_faithful_categories(self):
        by_id = {query["_id"]: query for query in self.data["queries"]}
        seen_tool = set()
        seen_llm = set()
        for query in self.data["queries"]:
            provenance = query["provenance"]
            if provenance["drafted_by"].startswith("tool:"):
                self.assertIn(query["category"], TEMPLATE)
                self.assertNotEqual(query["language_slice"], "cross_lingual")
                seen_tool.add(query["category"])
            else:
                self.assertIn(query["category"], SEMANTIC)
                seen_llm.add(query["category"])
        self.assertEqual(seen_tool, TEMPLATE)
        self.assertEqual(seen_llm, SEMANTIC)
        for row in self.data["documents"] + self.data["passages"]:
            query = by_id[row["query_id"]]
            self.assertEqual(
                row["provenance"]["drafted_by"].startswith("tool:"),
                query["provenance"]["drafted_by"].startswith("tool:"),
                row["query_id"],
            )

    def test_records_carry_the_pinned_provenance_hashes(self):
        corpus_hash = self.data["manifest"]["compatible_corpus_hashes"][0]
        expected_tool = config.tool_config_sha256(corpus_hash)
        tool_hashes = {
            row["provenance"]["tool_config_sha256"]
            for row in self.data["queries"]
            if row["provenance"]["drafted_by"].startswith("tool:")
        }
        self.assertEqual(tool_hashes, {expected_tool})
        for row in self.data["queries"]:
            provenance = row["provenance"]
            if provenance["drafted_by"].startswith("llm:"):
                self.assertEqual(provenance["drafted_by"], config.DEFAULT_MODEL.drafted_by)
                self.assertRegex(provenance["llm_prompt_sha256"], r"^[0-9a-f]{64}$")
                self.assertNotIn("tool_config_sha256", provenance)

    def test_every_record_stays_unverified_draft(self):
        for row in self.data["queries"] + self.data["documents"] + self.data["passages"]:
            self.assertEqual(row["provenance"]["state"], "draft")
            self.assertEqual(row["provenance"]["verified_by"], [])
            self.assertIsNone(row["provenance"]["adjudicated_by"])

    def test_manifest_is_a_quarantined_unexposed_draft(self):
        manifest = self.data["manifest"]
        self.assertEqual(manifest["judgment_set_id"], "sdc-v1")
        self.assertEqual(manifest["state"], "draft")
        self.assertEqual(manifest["split_seed"], "sdc-v1-split-v1")
        self.assertEqual(manifest["test_exposure"], "unexposed")
        self.assertEqual(manifest["query_file_sha256"], {})
        self.assertEqual(manifest["file_sha256"], {})
        self.assertEqual(manifest["test_pool_system_ids"], [])
        self.assertEqual(len(manifest["compatible_corpus_hashes"]), 1)
        self.assertEqual(self.data["pools"], [])

    def test_configuration_split_is_disjoint(self):
        for query in self.data["queries"]:
            if query["category"] == "code_search":
                self.assertEqual(query["configuration"], "code_enabled")
            else:
                self.assertEqual(query["configuration"], "default")

    def test_mixed_metadata_queries_carry_structured_filters(self):
        mixed = [query for query in self.data["queries"] if query["category"] == "mixed_semantic_metadata"]
        self.assertTrue(mixed)
        for query in mixed:
            self.assertIsInstance(query["filters"], dict)
            self.assertTrue(query["filters"])
        for query in self.data["queries"]:
            if query["category"] != "mixed_semantic_metadata":
                self.assertIsNone(query["filters"])

    def test_evidence_passages_carry_positive_passage_grades(self):
        grades = {
            (row["query_id"], row["document_id"], row["passage_id"]): row["grade"]
            for row in self.data["passages"]
        }
        for row in self.data["documents"]:
            if row["grade"] == 0:
                self.assertEqual(row["evidence_passage_ids"], [])
            if row["grade"] >= 2:
                self.assertTrue(row["evidence_passage_ids"])
            for passage_id in row["evidence_passage_ids"]:
                key = (row["query_id"], row["document_id"], passage_id)
                self.assertGreater(grades.get(key, 0), 0, key)

    def test_explicit_zero_is_distinct_from_unjudged(self):
        zeros = [row for row in self.data["documents"] if row["grade"] == 0]
        self.assertTrue(zeros)
        for row in zeros:
            self.assertEqual(row["evidence_passage_ids"], [])
        judged = {(row["query_id"], row["document_id"]) for row in self.data["documents"]}
        corpus_ids = {
            json.loads(line)["_id"]
            for line in (support.CORPUS / "corpus.jsonl").read_text(encoding="utf-8").splitlines()
        }
        self.assertTrue(corpus_ids)
        # Most (query, document) pairs stay unjudged: absence is not grade 0.
        query = self.data["queries"][0]
        unjudged = {document for document in corpus_ids if (query["_id"], document) not in judged}
        self.assertGreater(len(unjudged), 100)

    def test_snippet_spans_are_ordered_and_nonempty(self):
        for row in self.data["passages"]:
            previous = -1
            for span in row["evidence_spans"]:
                self.assertEqual(set(span), {"start_utf8", "end_utf8"})
                self.assertGreaterEqual(span["start_utf8"], previous)
                self.assertLess(span["start_utf8"], span["end_utf8"])
                previous = span["end_utf8"]

    def test_no_personal_paths_or_secrets_in_the_draft(self):
        for name in ("queries.draft.jsonl", "qrels.draft.documents.jsonl", "qrels.draft.passages.jsonl"):
            blob = (self.directory / name).read_text(encoding="utf-8")
            for marker in ("C:\\", "C:/", "\\\\Users\\\\", "/Users/", "/home/", "password", "PRIVATE KEY"):
                self.assertNotIn(marker, blob, name)

    def test_audit_passes_and_reports_coverage(self):
        expected = sum(
            count for category in support.TEST_PLAN.values() for count in category.values()
        )
        llm = sum(
            count
            for category, slices in support.TEST_PLAN.items()
            if category in SEMANTIC
            for count in slices.values()
        )
        summary = audit_directory(self.directory, check_minima=False)
        self.assertEqual(summary["queries"], expected)
        self.assertEqual(summary["llm_drafted"], llm)
        self.assertEqual(summary["tool_drafted"], expected - llm)

    def test_generator_accepts_the_draft(self):
        # The generator requires the quarantined location bench/qrels/sdc/drafts/<id>.
        quarantine = (
            Path(tempfile.mkdtemp(prefix="qrels-drafter-repo-"))
            / "bench"
            / "qrels"
            / "sdc"
            / "drafts"
            / "sdc-v1"
        )
        quarantine.mkdir(parents=True)
        for name in (
            "judgment-set.json",
            "queries.draft.jsonl",
            "qrels.draft.documents.jsonl",
            "qrels.draft.passages.jsonl",
            "pools.draft.jsonl",
        ):
            (quarantine / name).write_bytes((self.directory / name).read_bytes())
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(support.GENERATOR)
        finished = subprocess.run(
            [
                sys.executable,
                "-m",
                "sdc_generator",
                "judgments",
                "validate",
                "--allow-draft",
                "--set",
                str(quarantine),
                "--corpus",
                str(support.CORPUS),
            ],
            cwd=str(support.REPO_ROOT),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(finished.returncode, 0, finished.stderr)
        self.assertIn('"state":"draft"', finished.stdout)

    def test_utf8_jsonl_has_no_crlf(self):
        for name in ("queries.draft.jsonl", "qrels.draft.documents.jsonl"):
            data = (self.directory / name).read_bytes()
            self.assertNotIn(b"\r", data)
            self.assertTrue(data.endswith(b"\n"))


if __name__ == "__main__":
    unittest.main()
