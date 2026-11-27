"""SPEC-0004 R26: the dev-only ``sdc-smoke-v1`` draft (WP-1.4, H6 open)."""

from __future__ import annotations

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
from qrels_drafter.pipeline import run_draft


class SmokeDraft(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp(prefix="qrels-drafter-smoke-")) / "draft"
        cls.summary = run_draft(
            support.CORPUS,
            cls.directory,
            support.stub_runner(),
            spec=config.SMOKE_SET,
            check_minima=False,
        )
        cls.queries = read_jsonl(cls.directory / "queries.draft.jsonl")
        cls.documents = read_jsonl(cls.directory / "qrels.draft.documents.jsonl")
        cls.passages = read_jsonl(cls.directory / "qrels.draft.passages.jsonl")
        cls.manifest = load_json(cls.directory / "judgment-set.json")

    def test_smoke_set_is_dev_only_and_covers_every_category_five_times(self):
        # SPEC-0004 R26.
        self.assertEqual(self.manifest["judgment_set_id"], config.SMOKE_SET_ID)
        self.assertEqual(self.manifest["test_exposure"], "not-applicable")
        self.assertEqual(self.manifest["query_counts"]["test"], 0)
        self.assertEqual(len(self.queries), 9 * config.SMOKE_MIN_PER_CATEGORY)
        for category in config.CATEGORIES:
            count = sum(1 for query in self.queries if query["category"] == category)
            self.assertGreaterEqual(count, config.SMOKE_MIN_PER_CATEGORY, category)
        for query in self.queries:
            self.assertEqual(query["split"], "dev")
            self.assertTrue(query["_id"].startswith(f"q-{config.SMOKE_SET_ID}-"))

    def test_smoke_drafts_never_enter_a_test_split_or_a_pool(self):
        self.assertEqual(self.summary["splits"]["test"], 0)
        self.assertEqual(self.summary["pools"], 0)
        self.assertFalse((self.directory / "pools.draft.jsonl").read_text(encoding="utf-8"))

    def test_smoke_tool_records_hash_the_smoke_config(self):
        expected = config.tool_config_sha256(self.manifest["compatible_corpus_hashes"][0], config.SMOKE_SET)
        for query in self.queries:
            if query["provenance"]["drafted_by"].startswith("tool:"):
                self.assertEqual(query["provenance"]["tool_config_sha256"], expected)
            if query["provenance"]["drafted_by"].startswith("llm:"):
                self.assertNotIn("tool_config_sha256", query["provenance"])
        for row in self.documents:
            self.assertEqual(row["judgment_set_id"], config.SMOKE_SET_ID)

    def test_audit_accepts_the_smoke_draft(self):
        summary = audit_directory(self.directory, corpus_root=support.CORPUS)
        self.assertEqual(summary["queries"], 45)
        self.assertEqual(summary["splits"], {"dev": 45, "test": 0})
        self.assertEqual(summary["language_copy"]["copy_failures"], 0)
        self.assertEqual(summary["language_copy"]["language_failures"], 0)

    def test_generator_accepts_the_smoke_draft(self):
        quarantine = (
            Path(tempfile.mkdtemp(prefix="qrels-drafter-smoke-repo-"))
            / "bench"
            / "qrels"
            / "sdc"
            / "drafts"
            / config.SMOKE_SET_ID
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


if __name__ == "__main__":
    unittest.main()
