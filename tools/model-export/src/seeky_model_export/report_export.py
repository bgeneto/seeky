"""Sanitize external result JSON and compute frozen gate verdicts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import load_json, write_json
from .verdicts import (
    embedder_verdict,
    k3_verdict,
    k4_verdict,
    ocr_verdict,
    reranker_verdict,
    vlm_verdict,
)

RUNTIME_INSTALLED_BYTES = 14_877_304
K4_EMBEDDER = "e5-small"
RESULT_FILES = {
    "encoders-e5-small": "encoders-e5-small.json",
    "encoders-granite-modernbert": "encoders-granite-modernbert.json",
    "reranker": "reranker.json",
    "ocr": "ocr.json",
    "ocr-memory": "ocr-memory.json",
    "florence": "florence.json",
    "npu": "npu.json",
    "t0": "t0-functional.json",
    # Preregistration amendment 2: supplementary rows, never part of K1.
    "encoders-bekko-a8m": "encoders-bekko-a8m.json",
    "encoders-gety-embed-v0": "encoders-gety-embed-v0.json",
    # Preregistration amendment 3: a supplementary reranker, never part of K1.
    "reranker-hs-rerank-1": "reranker-hs-rerank-1.json",
}
SUPPLEMENTARY_EMBEDDER_KEYS = {
    "bekko-a8m": "encoders-bekko-a8m",
    "gety-embed-v0": "encoders-gety-embed-v0",
}
SUPPLEMENTARY_RERANKER_KEYS = {"hs-rerank-1": "reranker-hs-rerank-1"}



def k4_embedder_bytes(embedders: dict[str, Any]) -> int:
    """Smallest parity-passing e5-class variant (PREREGISTRATION §6 K4).

    ModernBERT and optional packs never join the default-path arithmetic.
    """
    result = embedders.get(K4_EMBEDDER) or {}
    return min(
        (
            variant["model_bytes"]
            for variant in result.get("variants", {}).values()
            if variant.get("parity_passed") and variant.get("model_bytes")
        ),
        default=0,
    )

def _read_optional(workspace: Path, filename: str) -> dict[str, Any] | None:
    path = workspace / "results" / filename
    if not path.exists():
        return None
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValueError("stage result is not a JSON object")
    return value


def _read_complete(workspace: Path, filename: str) -> tuple[dict[str, Any] | None, bool]:
    """Load a gate result unless a newer timeout artifact marks it partial.

    A timed-out gate leaves its completed variants in
    ``results/<gate>-timeout.json``; those partial numbers must never reach a
    K1-K4 verdict, so the stage is skipped until a complete run replaces it.
    """
    value = _read_optional(workspace, filename)
    if value is None:
        return None, False
    stem = filename.removesuffix(".json")
    marker = workspace / "results" / f"{stem}-timeout.json"
    result_path = workspace / "results" / filename
    if not marker.exists():
        return value, False
    try:
        if marker.stat().st_mtime_ns < result_path.stat().st_mtime_ns:
            return value, False
    except OSError:
        pass
    return None, True


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize(item)
            for key, item in value.items()
            if key not in {"detail", "hypotheses", "samples_seconds"}
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and ("\\" in value or value.startswith("/")):
        return "<external-path>"
    return value


def export_results(workspace: Path, destination: Path) -> dict[str, Any]:
    loaded: dict[str, dict[str, Any] | None] = {}
    incomplete: list[str] = []
    for key, filename in RESULT_FILES.items():
        value, timed_out = _read_complete(workspace, filename)
        loaded[key] = value
        if timed_out:
            incomplete.append(key)
    destination.mkdir(parents=True, exist_ok=True)
    raw_dir = destination / "raw-results"
    raw_dir.mkdir(exist_ok=True)
    for key, value in loaded.items():
        if value is not None:
            write_json(raw_dir / f"{key}.json", _sanitize(value))
    for source_name in ("text-acquisition-summary.json", "ocr/manifest.json"):
        source = workspace / "data" / source_name
        if source.exists():
            write_json(
                raw_dir / source.name,
                _sanitize(load_json(source)),
            )

    embedders = {
        key: value
        for key, value in (
            ("e5-small", loaded["encoders-e5-small"]),
            ("granite-modernbert", loaded["encoders-granite-modernbert"]),
        )
        if value is not None
    }
    verdicts: dict[str, Any] = {}
    if embedders:
        verdicts["k1_embedder"] = embedder_verdict(embedders)
    if loaded["reranker"] is not None:
        verdicts["k1_reranker"] = reranker_verdict({"gte-reranker": loaded["reranker"]})
    if loaded["ocr"] is not None:
        verdicts["k1_ocr"] = ocr_verdict({"pp-ocr": loaded["ocr"]})
    if loaded["florence"] is not None:
        verdicts["k1_florence"] = vlm_verdict(loaded["florence"])
    if loaded["npu"] is not None:
        verdicts["k3"] = k3_verdict(loaded["npu"])

    embedder_bytes = k4_embedder_bytes(embedders)
    reranker_bytes = 0
    if loaded["reranker"] is not None:
        reranker_bytes = min(
            (
                variant["model_bytes"]
                for variant in loaded["reranker"].get("variants", {}).values()
                if variant.get("parity_passed") and variant.get("model_bytes")
            ),
            default=0,
        )
    verdicts["k4"] = k4_verdict(
        runtime_bytes=RUNTIME_INSTALLED_BYTES,
        embedder_bytes=embedder_bytes,
        reranker_bytes=reranker_bytes,
    )
    supplementary = {
        model: loaded[key]
        for model, key in SUPPLEMENTARY_EMBEDDER_KEYS.items()
        if loaded[key] is not None
    }
    summary = {
        "schema": 1,
        "sources_present": [key for key, value in loaded.items() if value is not None],
        "incomplete_sources": incomplete,
        "runtime_installed_bytes": RUNTIME_INSTALLED_BYTES,
        "verdicts": verdicts,
    }
    if supplementary:
        # Same K1 arithmetic, reported beside the frozen verdict, never in it.
        row = embedder_verdict(supplementary)
        summary["supplementary_embedders"] = {
            "amendment": 2,
            "affects_k1": False,
            "target": row["target"],
            "qualified_variants": row["qualified_variants"],
        }
    supplementary_rerankers = {
        model: loaded[key]
        for model, key in SUPPLEMENTARY_RERANKER_KEYS.items()
        if loaded[key] is not None
    }
    if supplementary_rerankers:
        row = reranker_verdict(supplementary_rerankers)
        summary["supplementary_rerankers"] = {
            "amendment": 3,
            "affects_k1": False,
            "target": row["target"],
            "qualified_variants": row["qualified_variants"],
        }
    write_json(destination / "summary-data.json", _sanitize(summary))
    return summary
