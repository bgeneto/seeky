"""The model bake-off decision rule (WP-1.4 model choice)."""

from __future__ import annotations

import json
import unittest

import support
from qrels_drafter.bakeoff import build_lexicons, decide, detect_language, render_table
from qrels_drafter.corpus import Corpus

REPORT = support.TOOL_ROOT / "bakeoff-2026-11-27.json"


def _model(model_id: str, *, strict=24, no_copy=23, language=14, latency=2.0) -> dict:
    return {
        "model_id": model_id,
        "revision": "0" * 40,
        "weight_sha256": "0" * 64,
        "quantization": "test",
        "decode": {},
        "queries": 24,
        "strict_json": strict,
        "no_copy": no_copy,
        "language_ok": language,
        "mean_tokens": 4.0,
        "median_latency_s": latency,
        "retries": 0,
        "grade_probe_valid": "3/3",
        "rows": [],
        "grade_rows": [],
    }


class DecisionRule(unittest.TestCase):
    def test_committed_bakeoff_chooses_qwen3(self):
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        chosen, reason = decide(report)
        self.assertEqual(chosen, "qwen3-0.6b")
        self.assertIn("language", reason)
        table = render_table(report)
        self.assertIn("qwen3-0.6b", table)
        self.assertIn("qwen2.5-1.5b-instruct", table)

    def test_gate_failure_keeps_the_incumbent(self):
        report = {
            "models": {
                "qwen3-0.6b": _model("qwen3-0.6b", no_copy=10, language=24),
                "qwen2.5-1.5b-instruct": _model("qwen2.5-1.5b-instruct", language=14),
            }
        }
        chosen, reason = decide(report)
        self.assertEqual(chosen, "qwen2.5-1.5b-instruct")
        self.assertIn("gate", reason)

    def test_tie_goes_to_the_smaller_faster_model(self):
        report = {
            "models": {
                "qwen3-0.6b": _model("qwen3-0.6b", language=18, latency=1.5),
                "qwen2.5-1.5b-instruct": _model("qwen2.5-1.5b-instruct", language=18, latency=2.5),
            }
        }
        chosen, reason = decide(report)
        self.assertEqual(chosen, "qwen3-0.6b")
        self.assertIn("tie", reason)


class LanguageCheck(unittest.TestCase):
    def test_lexicon_separates_portuguese_and_english(self):
        corpus = Corpus.load(support.CORPUS)
        lexicons = build_lexicons(corpus)
        self.assertEqual(detect_language("manutenção preventiva trimestral", lexicons), "pt")
        self.assertEqual(detect_language("maintenance schedule services annual", lexicons), "en")


if __name__ == "__main__":
    unittest.main()
