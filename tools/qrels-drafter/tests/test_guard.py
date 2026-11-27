"""The anti-copy guard keeps semantic drafts from favouring lexical retrieval."""

import unittest

from qrels_drafter import config
from qrels_drafter.guard import guard_violation
from qrels_drafter.semantic import copies_a_judged_target

TARGET = (
    "The maintenance contract amendment renews the annual inspection service for the "
    "harbour district depot and lists every scheduled intervention."
)


class GuardTests(unittest.TestCase):
    def test_shared_eight_token_shingle_is_rejected(self):
        query = "renews the annual inspection service for the harbour district depot"
        self.assertIsNotNone(guard_violation(query, [TARGET], config.GUARD))

    def test_verbatim_span_is_rejected(self):
        query = "annual inspection service for the harbour"
        reason = guard_violation(query, [TARGET], config.GUARD)
        self.assertEqual(reason, "copies a 5-token verbatim span")

    def test_common_topic_words_are_not_a_copy(self):
        # Keyword queries legitimately share topic words; only spans are copying.
        self.assertIsNone(guard_violation("contract renewal inspection terms", [TARGET], config.GUARD))

    def test_paraphrase_with_new_wording_passes(self):
        query = "agreement extending yearly depot checks"
        self.assertIsNone(guard_violation(query, [TARGET], config.GUARD))

    def test_single_word_query_is_rejected(self):
        self.assertIsNotNone(guard_violation("harbour", [TARGET], config.GUARD))


class GradeThreeCopyGate(unittest.TestCase):
    """The draft must reject a query that copies any document it grades 3."""

    class _Doc:
        title = "Maintenance Contract Amendment Inspection Service"
        text = (
            "The maintenance contract amendment renews the annual inspection service "
            "for the harbour district depot and lists every scheduled intervention."
        )

    class _Corpus:
        documents = {"doc-a": None}

    def setUp(self):
        self.corpus = GradeThreeCopyGate._Corpus()
        self.corpus.documents = {"doc-a": GradeThreeCopyGate._Doc()}

    def test_query_copying_a_grade3_document_is_rejected(self):
        grades = {"doc-a": 3}
        self.assertTrue(
            copies_a_judged_target(
                "maintenance contract amendment renews the annual inspection service",
                grades,
                self.corpus,
            )
        )

    def test_paraphrase_of_a_grade3_document_passes(self):
        grades = {"doc-a": 3}
        self.assertFalse(
            copies_a_judged_target("depot agreement yearly checks", grades, self.corpus)
        )

    def test_a_grade0_document_is_not_a_copy_target(self):
        self.assertFalse(
            copies_a_judged_target(
                "maintenance contract amendment renews the annual inspection service",
                {"doc-a": 0},
                self.corpus,
            )
        )


if __name__ == "__main__":
    unittest.main()
