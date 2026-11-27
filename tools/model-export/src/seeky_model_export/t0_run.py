"""Functional floor check under the preregistered T0-emulated limits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .artifacts import load_json, write_json
from .deadline import Deadline, bounded_gate
from .frozen import embedding_view, load_frozen
from .models import (
    ENCODER_SPECS,
    create_ort_session,
    load_tokenizer,
    model_directory,
    run_encoder_session,
    tokenize,
)
from .ocr_data import load_ocr_manifest
from .ocr_run import _new_engine, _page_text
from .system import RunningProfile, apply_profile, capture_environment


class T0VariantError(RuntimeError):
    """No parity-passing CPU variant is available for the T0 check."""


_RESULT_FILES = {
    "e5-small": "encoders-e5-small.json",
    "gte-reranker": "reranker.json",
}
# Smallest first: the T0 floor uses the cheapest variant that passed parity.
_PREFERENCES = ("int8-dynamic", "int8-static-qdq", "fp32")


def _variant_path(workspace: Path, model: str, name: str) -> Path:
    if name == "fp32" and model != "gte-reranker":
        # Embedders use the published fp32 graph; only the reranker is exported.
        return workspace / "models" / model / "onnx" / "model.onnx"
    return workspace / "variants" / model / name / "model.onnx"


def _pick_variant(workspace: Path, model: str) -> tuple[str, Path]:
    """Return the best parity-passing CPU variant (preregistration §4.2)."""
    result_path = workspace / "results" / _RESULT_FILES[model]
    if not result_path.is_file():
        raise T0VariantError(f"no completed gate result for {model}")
    variants = load_json(result_path).get("variants", {})
    for name in _PREFERENCES:
        if not variants.get(name, {}).get("parity_passed"):
            continue
        candidate = _variant_path(workspace, model, name)
        if candidate.is_file():
            return name, candidate
    raise T0VariantError(f"no parity-passing CPU variant for {model}")


def run_t0_functional(
    workspace: Path,
    *,
    deadline: Deadline | None = None,
) -> dict[str, Any]:
    gate_deadline = deadline or Deadline()
    profile = RunningProfile.t0_functional()
    result: dict[str, Any] = {"schema": 1, "checks": {}}
    with bounded_gate(
        "t0-functional",
        workspace=workspace,
        deadline=gate_deadline,
        results=result,
        completed_key="checks",
    ):
        profile_record = apply_profile(profile)
        frozen = load_frozen(workspace)
        checks: dict[str, Any] = result["checks"]

        gate_deadline.check("t0:embedder")
        spec = ENCODER_SPECS["e5-small"]
        tokenizer = load_tokenizer(model_directory(workspace, spec))
        view = embedding_view(frozen, "e5-small")
        embedder_variant, embedder_path = _pick_variant(workspace, "e5-small")
        session = create_ort_session(embedder_path, profile)
        encoded = tokenize(tokenizer, [view["queries"][0]["text"]], max_length=64)
        vector = run_encoder_session(session, encoded, spec)
        checks["embedder"] = {
            "passed": vector.shape == (1, 384) and bool(np.isfinite(vector).all()),
            "shape": list(vector.shape),
            "variant": embedder_variant,
        }

        gate_deadline.check("t0:reranker")
        rerank_spec = ENCODER_SPECS["gte-reranker"]
        rerank_tokenizer = load_tokenizer(model_directory(workspace, rerank_spec))
        rerank_variant, rerank_path = _pick_variant(workspace, "gte-reranker")
        rerank = create_ort_session(rerank_path, profile)
        pair = tokenize(
            rerank_tokenizer,
            [view["queries"][0]["text"]],
            pair_texts=[view["passages"][0]["text"]],
            max_length=384,
        )
        scores = run_encoder_session(rerank, pair, rerank_spec)
        checks["reranker"] = {
            "passed": scores.shape == (1,) and bool(np.isfinite(scores).all()),
            "shape": list(scores.shape),
            "variant": rerank_variant,
        }

        gate_deadline.check("t0:ocr")
        manifest, _ = load_ocr_manifest(workspace)
        page = next(item for item in manifest["pages"] if item["kind"] == "text")
        ocr = _new_engine(workspace / "models" / "ppocr", threads=profile.ort_threads)
        text = _page_text(ocr, workspace / "data" / "ocr" / page["image"])
        checks["ocr"] = {"passed": bool(text.strip()), "characters": len(text)}

        result.update(
            {
                "label": "T0 functional, not budget evidence",
                "profile": profile_record,
                "environment": capture_environment(),
                "passed": all(item["passed"] for item in checks.values()),
            }
        )
        write_json(workspace / "results" / "t0-functional.json", result)
    return result
