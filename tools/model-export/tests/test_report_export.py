# WP-0.6: partial evidence never reaches a K1-K4 verdict.
import os
import time

from seeky_model_export.artifacts import write_json
from seeky_model_export.report_export import export_results


def _reranker_result(p95_ms: float) -> dict:
    return {
        "schema": 1,
        "variants": {
            "fp32": {
                "parity_passed": True,
                "model_bytes": 1024,
                "timing": {"depth_50": {"p95_ms": p95_ms}},
            }
        },
    }


def test_completed_gate_still_produces_its_verdict(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    write_json(results / "reranker.json", _reranker_result(100.0))

    summary = export_results(tmp_path, tmp_path / "out")

    assert summary["incomplete_sources"] == []
    assert "k1_reranker" in summary["verdicts"]
    assert summary["verdicts"]["k1_reranker"]["k1_fires"] is False


def test_newer_timeout_artifact_blocks_a_partial_verdict(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    write_json(results / "reranker.json", _reranker_result(900.0))
    marker = results / "reranker-timeout.json"
    write_json(
        marker,
        {
            "schema": 1,
            "status": "timed_out",
            "gate": "reranker",
            "stage": "reranker:int8-dynamic",
            "completed_variants": ["fp32"],
            "verdicts": None,
        },
    )
    newer = time.time() + 10.0
    os.utime(marker, (newer, newer))

    summary = export_results(tmp_path, tmp_path / "out")

    assert summary["incomplete_sources"] == ["reranker"]
    assert "k1_reranker" not in summary["verdicts"]
    assert not (tmp_path / "out" / "raw-results" / "reranker.json").exists()


def test_k4_counts_only_the_e5_class_embedder():
    # PREREGISTRATION §6 K4: ModernBERT is never added to the default path,
    # even when its parity-passing variant is smaller than e5's.
    from seeky_model_export import report_export

    embedders = {
        "e5-small": {"variants": {"fp32": {"parity_passed": True, "model_bytes": 470}}},
        "granite-modernbert": {"variants": {"fp32": {"parity_passed": True, "model_bytes": 390}}},
    }

    assert report_export.k4_embedder_bytes(embedders) == 470
