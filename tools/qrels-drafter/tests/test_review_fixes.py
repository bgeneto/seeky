"""WP-1.4 review fixes: duplicates, literals, ambiguity, needles, evidence.

Each test is a property of the drafted fixture, so a regression in any category
fails without hard-coding one query.
"""

from __future__ import annotations

import unittest

import support
from qrels_drafter.corpus import Corpus, tokenize
from qrels_drafter.jsonio import read_jsonl


class ReviewFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = support.draft_fixture()
        cls.corpus = Corpus.load(support.CORPUS)
        cls.queries = read_jsonl(cls.directory / "queries.draft.jsonl")
        cls.documents = read_jsonl(cls.directory / "qrels.draft.documents.jsonl")
        cls.passages = read_jsonl(cls.directory / "qrels.draft.passages.jsonl")
        cls.by_query: dict[str, list[dict]] = {}
        for row in cls.documents:
            cls.by_query.setdefault(row["query_id"], []).append(row)
        cls.pass_by_query: dict[str, list[dict]] = {}
        for row in cls.passages:
            cls.pass_by_query.setdefault(row["query_id"], []).append(row)

    def test_duplicate_siblings_carry_the_same_grade(self):
        for query in self.queries:
            judged = {row["document_id"]: row["grade"] for row in self.by_query[query["_id"]]}
            for document_id, grade in judged.items():
                if grade <= 0:
                    continue
                for cluster_id in self.corpus.documents[document_id].duplicate_cluster_ids:
                    for member in self.corpus.clusters[cluster_id].member_document_ids:
                        if member in judged:
                            self.assertEqual(judged[member], grade, f"{query['_id']} {member}")

    def test_grade_zero_never_contains_the_query_literal(self):
        for query in self.queries:
            text = query["text"].casefold()
            for row in self.by_query[query["_id"]]:
                if row["grade"] != 0:
                    continue
                document = self.corpus.documents[row["document_id"]]
                if query["category"] == "code_search":
                    between = text.split(" ", 2)
                    literal = between[2] if len(between) == 3 else ""
                elif query["category"] == "needle_in_haystack":
                    literal = text.removeprefix("find ").strip()
                elif query["category"] == "exact_identifier":
                    literal = query["text"].split()[-1]
                else:
                    literal = ""
                if literal and literal in document.text.casefold():
                    self.fail(f"{query['_id']}: grade-0 {document.id} contains {literal!r}")

    def test_filename_and_head_targets_are_unambiguous(self):
        for query in self.queries:
            if query["category"] == "filename_partial":
                fragment = query["text"].rsplit(".", 1)[0].casefold()
                target = next(row["document_id"] for row in self.by_query[query["_id"]] if row["grade"] == 3)
                allowed = {target, *(member for member, _ in self.corpus.related(target))}
                for document in self.corpus.documents.values():
                    if document.id in allowed:
                        continue
                    self.assertNotIn(fragment, document.basename.casefold(), query["_id"])

    def test_every_document_holding_the_needle_or_code_phrase_is_a_target(self):
        # The SDC long reports share one sentence pool, so a needle can recur in
        # another report; every holder is then a grade-3 target (SPEC-0004 5.4).
        checked = 0
        for query in self.queries:
            if query["category"] == "needle_in_haystack":
                literal = query["text"].removeprefix("find ").strip()
            elif query["category"] == "code_search":
                # The code phrase is the query's last four word tokens.
                literal = " ".join(tokenize(query["text"])[-4:])
            else:
                continue
            hits = set(self.corpus.documents_with_phrase(literal))
            targets = {row["document_id"] for row in self.by_query[query["_id"]] if row["grade"] == 3}
            self.assertTrue(hits, f"{query['_id']}: no document holds {literal!r}")
            self.assertTrue(hits <= targets, f"{query['_id']}: {sorted(hits - targets)}")
            checked += 1
        self.assertGreater(checked, 0)

    def test_llm_evidence_is_content_not_a_heading(self):
        for query in self.queries:
            if not query["provenance"]["drafted_by"].startswith("llm:"):
                continue
            for row in self.pass_by_query.get(query["_id"], []):
                if row["grade"] <= 0:
                    continue
                passage = next(
                    item
                    for item in self.corpus.passages(row["document_id"])
                    if item.id == row["passage_id"]
                )
                self.assertNotEqual(passage.kind, "heading", query["_id"])
                self.assertIsNone(passage.boilerplate_family_id, query["_id"])


if __name__ == "__main__":
    unittest.main()
