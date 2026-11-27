# WP-0.6: embedding/reranker parity report behavior on synthetic vectors.
import numpy as np
import pytest

from seeky_model_export.parity import (
    ParityError,
    bootstrap_mean_ci,
    embedding_parity,
    reranker_parity,
)


def test_bootstrap_is_deterministic_and_contains_the_mean():
    values = np.arange(1.0, 21.0)
    low, high = bootstrap_mean_ci(values, seed=6006, resamples=500)
    assert np.mean(values) == pytest.approx(10.5)
    assert low <= 10.5 <= high
    assert (low, high) == bootstrap_mean_ci(values, seed=6006, resamples=500)


def test_embedding_parity_reports_identity_and_neighbor_recall():
    passages = np.eye(4, dtype=np.float32)
    queries = np.eye(4, dtype=np.float32)
    report = embedding_parity(
        queries,
        passages,
        queries,
        passages,
        ["q0", "q1", "q2", "q3"],
        ["p0", "p1", "p2", "p3"],
    )
    assert report["mean_cosine"] == pytest.approx(1.0)
    assert report["neighbor_recall_at_100"] == 1.0
    assert report["query_count"] == 4
    assert report["passage_count"] == 4


def test_embedding_parity_detects_a_changed_ranking():
    generator = np.random.default_rng(42)
    passages = generator.normal(size=(101, 8)).astype(np.float32)
    queries = passage_queries = np.array([passages[0]])
    candidate = passages.copy()
    candidate[0] = -queries[0]
    report = embedding_parity(
        queries,
        passages,
        passage_queries,
        candidate,
        ["q"],
        [f"p{number}" for number in range(101)],
    )
    assert report["mean_cosine"] < 1.0
    assert report["neighbor_recall_at_100"] < 1.0


def test_embedding_parity_rejects_incompatible_shapes():
    with pytest.raises(ParityError):
        embedding_parity(
            np.ones((2, 3)),
            np.ones((2, 4)),
            np.ones((2, 3)),
            np.ones((2, 3)),
            ["q1", "q2"],
            ["p1", "p2"],
        )


def test_reranker_parity_checks_tau_and_ndcg():
    reference = [
        {"q1": {"p1": 3.0, "p2": 2.0, "p3": 1.0}},
        {"q2": {"p4": 3.0, "p5": 2.0, "p6": 1.0}},
    ]
    candidate = [
        {"q1": {"p1": 3.0, "p2": 2.0, "p3": 1.0}},
        {"q2": {"p4": 1.0, "p5": 2.0, "p6": 3.0}},
    ]
    qrels = {"q1": {"p1": 1}, "q2": {"p6": 1}}
    report = reranker_parity(reference, candidate, qrels, k=3)
    assert report["mean_kendall_tau_b"] == pytest.approx(0.0)
    assert report["nDCG@10"] == pytest.approx(1.0)
    assert report["worst_kendall_tau_b"] == pytest.approx(-1.0)


def test_reranker_parity_rejects_missing_query_lists():
    with pytest.raises(ParityError):
        reranker_parity(
            [{"q1": {"p1": 1.0}}],
            [{"q2": {"p1": 1.0}}],
            {"q1": {"p1": 1}},
            k=1,
        )
