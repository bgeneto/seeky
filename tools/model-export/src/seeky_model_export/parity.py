"""Parity reports for embedding and reranker deployment variants."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from .metrics import kendall_tau_b, mean_cosine, ndcg_at_k, neighbor_recall_at_k


class ParityError(RuntimeError):
    """A parity input or comparison is malformed."""


def _matrix(value: object, name: str) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim != 2 or len(matrix) == 0 or not np.isfinite(matrix).all():
        raise ParityError(f"{name} must be a non-empty finite matrix")
    norms = np.linalg.norm(matrix, axis=1)
    if np.any(norms == 0):
        raise ParityError(f"{name} contains a zero vector")
    return matrix / norms[:, None]


def _neighbors(queries: np.ndarray, passages: np.ndarray, ids: Sequence[str], k: int) -> list[list[str]]:
    scores = queries @ passages.T
    order = np.argsort(-scores, axis=1, kind="stable")[:, :k]
    return [[ids[index] for index in row] for row in order]


def bootstrap_mean_ci(
    values: object,
    *,
    seed: int = 6006,
    resamples: int = 10_000,
) -> tuple[float, float]:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or len(array) == 0 or not np.isfinite(array).all():
        raise ParityError("bootstrap input must be a non-empty finite vector")
    generator = np.random.default_rng(seed)
    indices = generator.integers(0, len(array), size=(resamples, len(array)))
    means = np.mean(array[indices], axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return float(low), float(high)


def embedding_parity(
    reference_queries: object,
    reference_passages: object,
    candidate_queries: object,
    candidate_passages: object,
    query_ids: Sequence[str],
    passage_ids: Sequence[str],
    *,
    qrels: Mapping[str, Mapping[str, int]] | None = None,
) -> dict[str, Any]:
    ref_q = _matrix(reference_queries, "reference queries")
    ref_p = _matrix(reference_passages, "reference passages")
    cand_q = _matrix(candidate_queries, "candidate queries")
    cand_p = _matrix(candidate_passages, "candidate passages")
    if ref_q.shape != cand_q.shape or ref_p.shape != cand_p.shape:
        raise ParityError("candidate and reference embeddings have incompatible shapes")
    if ref_p.shape[0] != len(passage_ids) or ref_q.shape[0] != len(query_ids):
        raise ParityError("embedding row counts do not match their IDs")
    if len(set(passage_ids)) != len(passage_ids) or len(set(query_ids)) != len(query_ids):
        raise ParityError("embedding IDs must be unique")

    similarity = mean_cosine(
        np.concatenate([ref_q, ref_p], axis=0),
        np.concatenate([cand_q, cand_p], axis=0),
    )
    k = min(100, ref_p.shape[0])
    ref_neighbors = _neighbors(ref_q, ref_p, passage_ids, k)
    cand_neighbors = _neighbors(cand_q, cand_p, passage_ids, k)
    recall = neighbor_recall_at_k(ref_neighbors, cand_neighbors, k)

    reference_ndcg = candidate_ndcg = None
    if qrels is not None:
        reference_ndcg = float(
            np.mean(
                [
                    ndcg_at_k(ranking, qrels.get(query_id, {}), 10)
                    for query_id, ranking in zip(query_ids, ref_neighbors, strict=True)
                ]
            )
        )
        candidate_ndcg = float(
            np.mean(
                [
                    ndcg_at_k(ranking, qrels.get(query_id, {}), 10)
                    for query_id, ranking in zip(query_ids, cand_neighbors, strict=True)
                ]
            )
        )
    return {
        "query_count": len(query_ids),
        "passage_count": len(passage_ids),
        "neighbor_k": k,
        "mean_cosine": similarity,
        "neighbor_recall_at_100": recall,
        "reference_nDCG@10": reference_ndcg,
        "candidate_nDCG@10": candidate_ndcg,
        "nDCG@10_delta": (
            None if reference_ndcg is None or candidate_ndcg is None else candidate_ndcg - reference_ndcg
        ),
    }


def reranker_parity(
    reference_scores: Sequence[Mapping[str, Mapping[str, float]]],
    candidate_scores: Sequence[Mapping[str, Mapping[str, float]]],
    qrels: Mapping[str, Mapping[str, int]],
    *,
    k: int,
) -> dict[str, Any]:
    if len(reference_scores) != len(candidate_scores) or not reference_scores:
        raise ParityError("reranker inputs must contain paired lists")
    taus: list[float] = []
    ndcgs: list[float] = []
    reference_ndcgs: list[float] = []
    max_abs_deltas: list[float] = []
    sum_abs_deltas = 0.0
    pair_count = 0
    for reference, candidate in zip(reference_scores, candidate_scores, strict=True):
        if len(reference) != 1 or len(candidate) != 1:
            raise ParityError("each reranker input must contain exactly one query")
        query_id = next(iter(reference))
        if query_id not in candidate:
            raise ParityError("candidate reranker lists do not match reference queries")
        ref = reference[query_id]
        cand = candidate[query_id]
        if set(ref) != set(cand) or not ref:
            raise ParityError("reranker passage IDs differ between variants")
        ids = sorted(ref)
        ref_values = np.array([ref[item] for item in ids], dtype=np.float64)
        cand_values = np.array([cand[item] for item in ids], dtype=np.float64)
        taus.append(kendall_tau_b(ref_values, cand_values))
        deltas = np.abs(ref_values - cand_values)
        max_abs_deltas.append(float(np.max(deltas)))
        sum_abs_deltas += float(np.sum(deltas))
        pair_count += len(deltas)
        ranking = sorted(cand, key=lambda item: (-cand[item], item))
        ndcgs.append(ndcg_at_k(ranking, qrels.get(query_id, {}), 10))
        ref_ranking = sorted(ref, key=lambda item: (-ref[item], item))
        reference_ndcgs.append(ndcg_at_k(ref_ranking, qrels.get(query_id, {}), 10))
    return {
        "list_count": len(taus),
        "mean_kendall_tau_b": float(np.mean(taus)),
        "worst_kendall_tau_b": float(np.min(taus)),
        "reference_nDCG@10": float(np.mean(reference_ndcgs)),
        "nDCG@10": float(np.mean(ndcgs)),
        "nDCG@10_delta": float(np.mean(ndcgs) - np.mean(reference_ndcgs)),
        "maximum_absolute_logit_delta": float(np.max(max_abs_deltas)),
        "mean_absolute_logit_delta": sum_abs_deltas / pair_count,
    }
