"""Functional floor check under the preregistered T0-emulated limits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .artifacts import write_json
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


def _pick_variant(workspace: Path, model: str) -> Path:
    preferences = ("int8-dynamic", "int8-static-qdq", "fp32")
    for name in preferences:
        suffix = "" if name == "fp32" else f"{name}/model.onnx"
        candidate = workspace / "variants" / model / suffix
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"no prepared T0 variant for {model}")


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
        session = create_ort_session(_pick_variant(workspace, "e5-small"), profile)
        encoded = tokenize(tokenizer, [view["queries"][0]["text"]], max_length=64)
        vector = run_encoder_session(session, encoded, spec)
        checks["embedder"] = {
            "passed": vector.shape == (1, 384) and bool(np.isfinite(vector).all()),
            "shape": list(vector.shape),
        }

        gate_deadline.check("t0:reranker")
        rerank_spec = ENCODER_SPECS["gte-reranker"]
        rerank_tokenizer = load_tokenizer(model_directory(workspace, rerank_spec))
        rerank = create_ort_session(_pick_variant(workspace, "gte-reranker"), profile)
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
