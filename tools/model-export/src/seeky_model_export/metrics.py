"""Deterministic, dependency-light metrics for the WP-0.6 gate."""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping, Sequence

import numpy as np


def normalize_ocr_text(text: str) -> str:
    """Apply the preregistered NFC and whitespace normalization."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def strip_diacritics(text: str) -> str:
    """Return normalized text with combining marks removed."""
    decomposed = unicodedata.normalize("NFKD", normalize_ocr_text(text))
    return " ".join(
        "".join(character for character in decomposed if not unicodedata.combining(character)).split()
    )


def _levenshtein(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for row, ref_item in enumerate(reference, start=1):
        current = [row]
        for column, hyp_item in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (ref_item != hyp_item),
                )
            )
        previous = current
    return previous[-1]


def _error_rate(reference: str, hypothesis: str, *, words: bool) -> float:
    ref_normalized = normalize_ocr_text(reference)
    hyp_normalized = normalize_ocr_text(hypothesis)
    if not ref_normalized:
        return float(bool(hyp_normalized))
    ref_items = ref_normalized.split() if words else ref_normalized
    hyp_items = hyp_normalized.split() if words else hyp_normalized
    return _levenshtein(ref_items, hyp_items) / len(ref_items)


def character_error_rate(reference: str, hypothesis: str) -> float:
    return _error_rate(reference, hypothesis, words=False)


def word_error_rate(reference: str, hypothesis: str) -> float:
    return _error_rate(reference, hypothesis, words=True)


def mean_cosine(reference: object, candidate: object) -> float:
    ref = np.asarray(reference, dtype=np.float64)
    cand = np.asarray(candidate, dtype=np.float64)
    if ref.ndim != 2 or ref.shape != cand.shape or ref.shape[0] == 0:
        raise ValueError("cosine inputs must be non-empty 2-D arrays of equal shape")
    if not np.isfinite(ref).all() or not np.isfinite(cand).all():
        raise ValueError("cosine inputs must be finite")
    ref_norm = np.linalg.norm(ref, axis=1)
    cand_norm = np.linalg.norm(cand, axis=1)
    if np.any(ref_norm == 0) or np.any(cand_norm == 0):
        raise ValueError("cosine inputs must not contain zero vectors")
    similarities = np.sum(ref * cand, axis=1) / (ref_norm * cand_norm)
    return float(np.mean(similarities))


def neighbor_recall_at_k(
    reference_ids: Sequence[Sequence[str]],
    candidate_ids: Sequence[Sequence[str]],
    k: int,
) -> float:
    if k <= 0 or len(reference_ids) == 0 or len(reference_ids) != len(candidate_ids):
        raise ValueError("neighbor inputs must be non-empty, paired, and k must be positive")
    hits = 0
    for reference, candidate in zip(reference_ids, candidate_ids, strict=True):
        if len(reference) < k or len(candidate) < k:
            raise ValueError("neighbor lists must contain at least k IDs")
        if len(set(reference)) != len(reference) or len(set(candidate)) != len(candidate):
            raise ValueError("neighbor lists must not contain duplicate IDs")
        hits += len(set(reference[:k]).intersection(candidate[:k]))
    return hits / (len(reference_ids) * k)


def ndcg_at_k(ranked_ids: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    gains = [max(0, int(qrels.get(doc_id, 0))) for doc_id in ranked_ids[:k]]
    ideal = sorted((max(0, int(value)) for value in qrels.values()), reverse=True)[:k]
    ideal_dcg = sum(value / math.log2(index + 2) for index, value in enumerate(ideal))
    if ideal_dcg == 0:
        return 0.0
    dcg = sum(value / math.log2(index + 2) for index, value in enumerate(gains))
    return dcg / ideal_dcg


def kendall_tau_b(reference_scores: object, candidate_scores: object) -> float:
    reference = np.asarray(reference_scores, dtype=np.float64)
    candidate = np.asarray(candidate_scores, dtype=np.float64)
    if reference.ndim != 1 or reference.shape != candidate.shape or len(reference) < 2:
        raise ValueError("Kendall inputs must be paired 1-D arrays with at least two items")
    if not np.isfinite(reference).all() or not np.isfinite(candidate).all():
        raise ValueError("Kendall inputs must be finite")
    pair_count = len(reference) * (len(reference) - 1) // 2
    concordant = discordant = reference_ties = candidate_ties = 0
    for left in range(len(reference) - 1):
        for right in range(left + 1, len(reference)):
            ref_delta = reference[left] - reference[right]
            cand_delta = candidate[left] - candidate[right]
            if ref_delta == 0:
                reference_ties += 1
            if cand_delta == 0:
                candidate_ties += 1
            if ref_delta == 0 or cand_delta == 0:
                continue
            if ref_delta * cand_delta > 0:
                concordant += 1
            else:
                discordant += 1
    denominator = math.sqrt(
        (pair_count - reference_ties) * (pair_count - candidate_ties)
    )
    if denominator == 0:
        return float(np.array_equal(reference, candidate))
    return (concordant - discordant) / denominator


def nearest_rank_percentile(values: object, percentile: float) -> float:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or len(array) == 0 or not np.isfinite(array).all():
        raise ValueError("percentile input must be a non-empty finite 1-D array")
    if not 0 < percentile <= 100:
        raise ValueError("percentile must be in (0, 100]")
    ordered = np.sort(array)
    rank = max(1, math.ceil(percentile / 100 * len(ordered)))
    return float(ordered[rank - 1])
