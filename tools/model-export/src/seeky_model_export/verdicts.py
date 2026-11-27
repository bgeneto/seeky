"""Frozen K1/K3/K4 verdict arithmetic."""

from __future__ import annotations

from typing import Any

D2_BYTES = 250_000_000
O1_P95_MS = 2_000.0
O2_ADDED_BYTES = 1024**3
O3_MODEL_BYTES = 150_000_000
RERANKER_P95_MS = 250.0
EMBEDDER_P95_MS = 20.0
EMBEDDER_PASSAGES_PER_SECOND = 56.0


def _qualified_embedder_variants(results_by_model: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    variants = []
    for model, result in results_by_model.items():
        for name, variant in result.get("variants", {}).items():
            if not variant.get("parity_passed") or not variant.get("timing"):
                continue
            query = variant["timing"].get("query", {})
            passage = variant["timing"].get("passage", {})
            if query.get("p95_ms") is None or passage.get("passages_per_second") is None:
                continue
            variants.append(
                {
                    "model": model,
                    "variant": name,
                    "query_p95_ms": query["p95_ms"],
                    "passages_per_second": passage["passages_per_second"],
                    "meets_targets": (
                        query["p95_ms"] <= EMBEDDER_P95_MS
                        and passage["passages_per_second"] >= EMBEDDER_PASSAGES_PER_SECOND
                    ),
                }
            )
    return variants


def embedder_verdict(results_by_model: dict[str, dict[str, Any]]) -> dict[str, Any]:
    variants = _qualified_embedder_variants(results_by_model)
    winners = [item for item in variants if item["meets_targets"]]
    return {
        "role": "embedder",
        "target": {
            "query_p95_ms": EMBEDDER_P95_MS,
            "passages_per_second": EMBEDDER_PASSAGES_PER_SECOND,
        },
        "qualified_variants": variants,
        "winners": winners,
        "k1_fires": not winners,
    }


def reranker_verdict(results_by_model: dict[str, dict[str, Any]]) -> dict[str, Any]:
    variants = []
    for model, result in results_by_model.items():
        for name, variant in result.get("variants", {}).items():
            if not variant.get("parity_passed") or not variant.get("timing"):
                continue
            timing = variant["timing"].get("depth_50", {})
            if timing.get("p95_ms") is None:
                continue
            variants.append(
                {
                    "model": model,
                    "variant": name,
                    "depth_50_p95_ms": timing["p95_ms"],
                    "meets_target": timing["p95_ms"] <= RERANKER_P95_MS,
                }
            )
    winners = [item for item in variants if item["meets_target"]]
    return {
        "role": "reranker",
        "target": {"depth_50_p95_ms": RERANKER_P95_MS},
        "qualified_variants": variants,
        "winners": winners,
        "k1_fires": not winners,
    }


def ocr_verdict(results_by_model: dict[str, dict[str, Any]]) -> dict[str, Any]:
    variants = []
    for model, result in results_by_model.items():
        for name, variant in result.get("variants", {}).items():
            if not variant.get("parity_passed") or not variant.get("timing"):
                continue
            page = variant["timing"].get("page", {})
            added = variant["timing"].get("added_peak_rss_bytes_upper_bound")
            model_bytes = variant.get("model_bytes")
            if page.get("p95_ms") is None or added is None or model_bytes is None:
                continue
            variants.append(
                {
                    "model": model,
                    "variant": name,
                    "page_p95_ms": page["p95_ms"],
                    "added_peak_rss_bytes": added,
                    "model_bytes": model_bytes,
                    "meets_targets": (
                        page["p95_ms"] <= O1_P95_MS
                        and added <= O2_ADDED_BYTES
                        and model_bytes <= O3_MODEL_BYTES
                    ),
                }
            )
    winners = [item for item in variants if item["meets_targets"]]
    return {
        "role": "pp-ocr",
        "target": {
            "page_p95_ms": O1_P95_MS,
            "added_peak_rss_bytes": O2_ADDED_BYTES,
            "model_bytes": O3_MODEL_BYTES,
        },
        "qualified_variants": variants,
        "winners": winners,
        "k1_fires": not winners,
    }


def vlm_verdict(result: dict[str, Any]) -> dict[str, Any]:
    """Apply the 2x early-stop rule to the best parity-passing VLM variant."""
    candidates = []
    for name, variant in result.get("variants", {}).items():
        if not variant.get("parity_passed"):
            continue
        timing = variant.get("timing")
        if not timing:
            continue
        page = timing.get("page", {})
        if page.get("p95_ms") is not None:
            candidates.append((name, float(page["p95_ms"])))
    if not candidates:
        return {"role": "transcription-vlm", "evaluable": False, "k1_fires": False}
    name, p95 = min(candidates, key=lambda item: item[1])
    return {
        "role": "transcription-vlm",
        "evaluable": True,
        "best_variant": name,
        "page_p95_ms": p95,
        "k1_fires": O1_P95_MS < p95 <= 2 * O1_P95_MS,
        "outside_cpu_on_any_engine": p95 > 2 * O1_P95_MS,
    }


def k3_verdict(result: dict[str, Any]) -> dict[str, Any]:
    passed = bool(result.get("k3_passed"))
    return {"role": "intel-npu", "k3_fires": not passed, "reached_with_parity": passed}


def k4_verdict(
    *,
    runtime_bytes: int,
    embedder_bytes: int,
    reranker_bytes: int,
) -> dict[str, Any]:
    models = embedder_bytes + reranker_bytes
    total = models + runtime_bytes
    fires = total > D2_BYTES and models <= D2_BYTES
    return {
        "runtime_bytes": runtime_bytes,
        "embedder_bytes": embedder_bytes,
        "reranker_bytes": reranker_bytes,
        "models_bytes": models,
        "total_bytes": total,
        "d2_bytes": D2_BYTES,
        "models_alone_exceed_d2": models > D2_BYTES,
        "k4_fires": fires,
    }
