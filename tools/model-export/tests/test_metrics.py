# WP-0.6: hardware-free parity and metric checks.
import math

import numpy as np
import pytest

from seeky_model_export.metrics import (
    character_error_rate,
    kendall_tau_b,
    mean_cosine,
    ndcg_at_k,
    neighbor_recall_at_k,
    nearest_rank_percentile,
    normalize_ocr_text,
    strip_diacritics,
    word_error_rate,
)


def test_ocr_normalization_uses_nfc_and_collapses_whitespace():
    assert normalize_ocr_text("  Ame\u0301lia\t silva\n") == "Amélia silva"


def test_diacritic_insensitive_normalization_keeps_letters():
    assert strip_diacritics("Amélia ação") == "Amelia acao"
    assert normalize_ocr_text("Amélia ação") == "Amélia ação"


def test_cer_and_wer_measure_normalized_edit_distance():
    reference = "Amélia  silva\n"
    hypothesis = "Amelia silva"
    assert character_error_rate(reference, hypothesis) == pytest.approx(1 / 12)
    assert word_error_rate(reference, hypothesis) == pytest.approx(1 / 2)


def test_empty_ocr_reference_only_accepts_empty_hypothesis():
    assert character_error_rate("", "") == 0.0
    assert word_error_rate("", "") == 0.0
    assert character_error_rate("", "inserted") == 1.0
    assert word_error_rate("", "inserted words") == 1.0


def test_mean_cosine_requires_finite_compatible_vectors():
    assert mean_cosine([[1.0, 0.0]], [[1.0, 0.0]]) == pytest.approx(1.0)
    assert mean_cosine([[1.0, 0.0]], [[0.0, 1.0]]) == pytest.approx(0.0)
    with pytest.raises(ValueError):
        mean_cosine([[1.0]], [[1.0, 2.0]])
    with pytest.raises(ValueError):
        mean_cosine([[0.0, 0.0]], [[1.0, 0.0]])
    with pytest.raises(ValueError):
        mean_cosine([[math.nan]], [[1.0]])


def test_neighbor_recall_compares_reference_top_k_ids():
    reference = [["a", "b", "c"], ["x", "y", "z"]]
    candidate = [["a", "c", "d"], ["y", "x", "z"]]
    assert neighbor_recall_at_k(reference, candidate, 2) == pytest.approx(3 / 4)
    assert neighbor_recall_at_k(reference, candidate, 3) == pytest.approx(5 / 6)


def test_neighbor_recall_rejects_duplicate_or_short_lists():
    with pytest.raises(ValueError):
        neighbor_recall_at_k([["a", "a"]], [["a", "b"]], 2)
    with pytest.raises(ValueError):
        neighbor_recall_at_k([["a"]], [["a"]], 2)


def test_ndcg_uses_binary_relevance_and_rank_discount():
    qrels = {"a": 1, "b": 1}
    assert ndcg_at_k(["a", "b"], qrels, 2) == pytest.approx(1.0)
    expected = (1 / math.log2(3)) / (1 + 1 / math.log2(3))
    assert ndcg_at_k(["x", "a"], qrels, 2) == pytest.approx(expected)
    assert ndcg_at_k([], qrels, 2) == 0.0


def test_kendall_tau_b_handles_order_and_ties():
    assert kendall_tau_b([3.0, 2.0, 1.0], [30.0, 20.0, 10.0]) == pytest.approx(1.0)
    assert kendall_tau_b([3.0, 2.0, 1.0], [10.0, 20.0, 30.0]) == pytest.approx(-1.0)
    assert kendall_tau_b([1.0, 1.0, 0.0], [2.0, 1.0, 0.0]) == pytest.approx(2 / math.sqrt(6))


def test_nearest_rank_percentile_does_not_interpolate():
    assert nearest_rank_percentile([4.0, 1.0, 3.0, 2.0], 50) == 2.0
    assert nearest_rank_percentile([4.0, 1.0, 3.0, 2.0], 95) == 4.0
    with pytest.raises(ValueError):
        nearest_rank_percentile([], 95)
