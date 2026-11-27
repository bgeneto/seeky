# WP-0.6: pure K1/K3/K4 verdict logic against preregistered thresholds.
from seeky_model_export.verdicts import (
    embedder_verdict,
    k3_verdict,
    k4_verdict,
    ocr_verdict,
    reranker_verdict,
)


def _embedder(p95, rate):
    return {
        "variants": {
            "fp32": {
                "parity_passed": True,
                "timing": {
                    "query": {"p95_ms": p95},
                    "passage": {"passages_per_second": rate},
                },
            }
        }
    }


def test_embedder_role_passes_only_inside_both_targets():
    assert embedder_verdict({"e5": _embedder(19.9, 56.0)})["k1_fires"] is False
    assert embedder_verdict({"e5": _embedder(20.1, 60.0)})["k1_fires"] is True
    assert embedder_verdict({"e5": _embedder(10.0, 55.9)})["k1_fires"] is True


def test_parity_failure_cannot_rescue_a_fast_variant():
    result = _embedder(10.0, 100.0)
    result["variants"]["fp32"]["parity_passed"] = False
    verdict = embedder_verdict({"e5": result})
    assert verdict["k1_fires"] is True
    assert verdict["qualified_variants"] == []


def test_reranker_and_ocr_use_their_preregistered_targets():
    reranker = {
        "variants": {
            "best": {"parity_passed": True, "timing": {"depth_50": {"p95_ms": 250.0}}}
        }
    }
    assert reranker_verdict({"gte": reranker})["k1_fires"] is False
    ocr = {
        "variants": {
            "best": {
                "parity_passed": True,
                "model_bytes": 150_000_000,
                "timing": {
                    "page": {"p95_ms": 2000.0},
                    "added_peak_rss_bytes_upper_bound": 1024**3,
                },
            }
        }
    }
    assert ocr_verdict({"ppocr": ocr})["k1_fires"] is False
    ocr["variants"]["best"]["model_bytes"] += 1
    assert ocr_verdict({"ppocr": ocr})["k1_fires"] is True


def test_k4_attributes_runtime_only_when_models_fit_alone():
    assert (
        k4_verdict(runtime_bytes=20_000_000, embedder_bytes=100_000_000, reranker_bytes=100_000_000)[
            "k4_fires"
        ]
        is False
    )
    assert (
        k4_verdict(runtime_bytes=60_000_000, embedder_bytes=100_000_000, reranker_bytes=100_000_000)[
            "k4_fires"
        ]
        is True
    )
    assert (
        k4_verdict(runtime_bytes=20_000_000, embedder_bytes=200_000_000, reranker_bytes=100_000_000)[
            "k4_fires"
        ]
        is False
    )


def test_k3_requires_reach_and_parity():
    assert k3_verdict({"k3_passed": True})["k3_fires"] is False
    assert k3_verdict({"k3_passed": False})["k3_fires"] is True
