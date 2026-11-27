"""The anti-copy guard keeps semantic drafts from favouring lexical retrieval."""

import unittest

from qrels_drafter import config
from qrels_drafter.guard import guard_violation

TARGET = (
    "The maintenance contract amendment renews the annual inspection service for the "
    "harbour district depot and lists every scheduled intervention."
)


class GuardTests(unittest.TestCase):
    def test_shared_eight_token_shingle_is_rejected(self):
        query = "renews the annual inspection service for the harbour district depot"
        self.assertIsNotNone(guard_violation(query, [TARGET], config.GUARD))

    def test_verbatim_span_is_rejected(self):
        query = "scheduled intervention list annual inspection service harbour"
        reason = guard_violation(query, [TARGET], config.GUARD)
        self.assertIsNotNone(reason)

    def test_paraphrase_with_new_wording_passes(self):
        query = "agreement extending yearly depot checks"
        self.assertIsNone(guard_violation(query, [TARGET], config.GUARD))

    def test_single_word_query_is_rejected(self):
        self.assertIsNotNone(guard_violation("harbour", [TARGET], config.GUARD))


if __name__ == "__main__":
    unittest.main()
