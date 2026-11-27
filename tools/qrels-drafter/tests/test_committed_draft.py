"""The committed draft under bench/qrels/sdc/drafts/sdc-v1 (WP-1.4, H6 open)."""

from __future__ import annotations

import unittest

import support
from qrels_drafter import config
from qrels_drafter.audit import audit_directory
from qrels_drafter.jsonio import load_json, read_jsonl


@unittest.skipUnless(
    (support.COMMITTED / "judgment-set.json").is_file(), "the committed draft is absent"
)
class CommittedDraft(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = audit_directory(support.COMMITTED)
        cls.queries = read_jsonl(support.COMMITTED / "queries.draft.jsonl")
        cls.documents = read_jsonl(support.COMMITTED / "qrels.draft.documents.jsonl")
        cls.passages = read_jsonl(support.COMMITTED / "qrels.draft.passages.jsonl")
        cls.manifest = load_json(support.COMMITTED / "judgment-set.json")

    def test_full_query_set_meets_category_and_split_minima(self):
        self.assertGreaterEqual(self.summary["queries"], 600)
        for split, count in self.summary["splits"].items():
            self.assertGreaterEqual(count, 300, split)
        for category in config.CATEGORIES:
            for split in ("dev", "test"):
                count = sum(
                    1
                    for query in self.queries
                    if query["category"] == category and query["split"] == split
                )
                self.assertGreaterEqual(count, 30, f"{category}/{split}")

    def test_language_and_cross_lingual_slices_meet_minima(self):
        for slice_name, minimum in (
            ("pt", 100),
            ("en", 100),
            ("cross_lingual", 60),
            ("non_latin_non_regression", 10),
        ):
            total = sum(1 for query in self.queries if query["language_slice"] == slice_name)
            self.assertGreaterEqual(total, minimum, slice_name)
        for language in ("es", "fr", "de"):
            total = sum(1 for query in self.queries if query["language"].split("-")[0] == language)
            self.assertGreaterEqual(total, 20, language)

    def test_every_stratum_is_even_and_balanced(self):
        strata: dict[tuple, dict[str, int]] = {}
        for query in self.queries:
            key = (query["category"], query["language_slice"], query["configuration"])
            strata.setdefault(key, {"dev": 0, "test": 0})[query["split"]] += 1
        self.assertTrue(strata)
        for key, counts in strata.items():
            self.assertEqual(counts["dev"], counts["test"], key)

    def test_tool_and_llm_provenance_follow_the_category_split(self):
        for query in self.queries:
            tool = query["provenance"]["drafted_by"].startswith("tool:")
            self.assertEqual(tool, query["category"] in config.TEMPLATE_CATEGORIES, query["_id"])
            if tool:
                self.assertNotEqual(query["language_slice"], "cross_lingual")

    def test_every_item_is_still_open_for_h6(self):
        self.assertEqual(self.manifest["state"], "draft")
        for row in self.queries + self.documents + self.passages:
            self.assertEqual(row["provenance"]["state"], "draft")
            self.assertEqual(row["provenance"]["verified_by"], [])
            self.assertIsNone(row["provenance"]["adjudicated_by"])

    def test_readme_pins_the_model_and_tool(self):
        notice = (support.TOOL_ROOT / "NOTICE.md").read_text(encoding="utf-8")
        self.assertIn(config.DEFAULT_MODEL.revision, notice)
        self.assertIn(config.DEFAULT_MODEL.weight_sha256, notice)
        self.assertIn(config.DEFAULT_MODEL.license, notice)

    def test_manifest_matches_spec_0004_4_7(self):
        self.assertEqual(self.manifest["judgment_set_id"], "sdc-v1")
        self.assertEqual(self.manifest["split_seed"], "sdc-v1-split-v1")
        self.assertEqual(self.manifest["test_exposure"], "unexposed")
        self.assertEqual(self.manifest["file_sha256"], {})
        self.assertEqual(self.manifest["query_file_sha256"], {})
        self.assertEqual(
            self.manifest["compatible_corpus_hashes"],
            ["1d65b8ff04091850b8deefa34f5658bee0b87ec4ff29667f002f6cec88ac2ef0"],
        )


if __name__ == "__main__":
    unittest.main()
