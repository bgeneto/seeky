# WP-0.6: frozen-view and latency/throughput aggregation checks.
import pytest

from seeky_model_export.benchmark import (
    BenchmarkError,
    summarize_latencies,
    summarize_throughput,
    token_length_summary,
)
from seeky_model_export.frozen import FrozenDataError, embedding_view, load_frozen


def _frozen():
    return {
        "schema": 1,
        "seed": "fixed",
        "miracl": {
            "queries": [{"id": "q1", "text": "query"}],
            "qrels": {"q1": {"d1": 1}},
            "passages": [{"id": "d1", "text": "passage"}],
        },
        "mmarco": {
            "queries": [{"id": "q2", "text": "consulta"}],
            "passages": [{"id": "d2", "text": "passagem"}],
        },
    }


def test_embedding_view_qualifies_ids_and_prepares_identifiers():
    view = embedding_view(_frozen(), "e5-small")
    assert [row["id"] for row in view["passages"]] == ["miracl:d1", "mmarco:d2"]
    assert view["passages"][0]["text"].startswith("passage: ")
    assert view["queries"][0]["text"].startswith("query: ")


def test_frozen_view_rejects_incomplete_or_empty_samples():
    broken = _frozen()
    broken["miracl"]["passages"] = []
    with pytest.raises(FrozenDataError):
        embedding_view(broken, "e5-small")
    with pytest.raises(FrozenDataError):
        embedding_view({"schema": 1}, "e5-small")


def test_latency_summary_uses_nearest_rank_percentiles():
    summary = summarize_latencies([0.001 * number for number in range(1, 101)])
    assert summary["count"] == 100
    assert summary["p50_ms"] == pytest.approx(50.0)
    assert summary["p95_ms"] == pytest.approx(95.0)
    assert summary["p95_ci95_ms"][0] <= summary["p95_ms"] <= summary["p95_ci95_ms"][1]


def test_throughput_summary_converts_batch_times_and_computes_ci():
    summary = summarize_throughput([0.1] * 32, batch_size=8)
    assert summary["passages"] == 256
    assert summary["passages_per_second"] == pytest.approx(80.0)
    low, high = summary["throughput_ci95"]
    assert low <= 80.0 <= high


def test_token_length_summary_records_real_sequence_lengths():
    summary = token_length_summary([8, 12, 20, 40])
    assert summary == {
        "count": 4,
        "mean": 20.0,
        "p50": 12.0,
        "p95": 40.0,
        "max": 40.0,
    }


def test_timing_summaries_reject_empty_or_non_positive_inputs():
    with pytest.raises(BenchmarkError):
        summarize_latencies([])
    with pytest.raises(BenchmarkError):
        summarize_latencies([0.0, -1.0])
    with pytest.raises(BenchmarkError):
        summarize_throughput([], batch_size=8)
    with pytest.raises(BenchmarkError):
        summarize_throughput([0.1], batch_size=0)
