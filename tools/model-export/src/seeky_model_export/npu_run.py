"""Reach an Intel NPU through ORT's OpenVINO EP and verify parity."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np

from .artifacts import sha256_file, write_json
from .deadline import Deadline, GateTimeout, bounded_gate
from .frozen import embedding_view, load_frozen
from .metrics import mean_cosine
from .models import (
    ENCODER_SPECS,
    complete_graph_inputs,
    create_ort_session,
    export_embedder_static_fp32,
    load_tokenizer,
    model_directory,
    tokenize,
)
from .quantize import ArrayCalibrationReader, quantize_static_model
from .system import RunningProfile, apply_profile, capture_environment


class NpuRunError(RuntimeError):
    """The NPU session or parity probe failed."""


def prepare_npu_embedder(
    workspace: Path,
    *,
    profile: RunningProfile | None = None,
    deadline: Deadline | None = None,
) -> tuple[Path, Path]:
    selected_profile = profile or RunningProfile.t1_emulated()
    apply_profile(selected_profile)
    spec = ENCODER_SPECS["e5-small"]
    source_dir = model_directory(workspace, spec)
    fp32 = workspace / "variants" / "e5-small" / "npu-static-fp32" / "model.onnx"
    if not fp32.exists():
        if deadline is not None:
            deadline.check("npu:prepare:fp32")
        export_embedder_static_fp32(
            source_dir,
            fp32,
            spec,
            batch_size=1,
            sequence_length=32,
        )
    quantized = workspace / "variants" / "e5-small" / "npu-static-qdq" / "model.onnx"
    if not quantized.exists():
        if deadline is not None:
            deadline.check("npu:prepare:int8-static-qdq")
        tokenizer = load_tokenizer(source_dir)
        frozen = load_frozen(workspace)
        view = embedding_view(frozen, "e5-small")
        encoded = tokenize(
            tokenizer,
            [row["text"] for row in view["passages"][:128]],
            max_length=32,
            pad_to_max=True,
        )
        rows = [
            {name: value[index : index + 1] for name, value in encoded.items()}
            for index in range(128)
        ]
        quantize_static_model(fp32, quantized, ArrayCalibrationReader(fp32, rows))
    return fp32, quantized


def _cpu_vectors(
    workspace: Path,
    path: Path,
    profile: RunningProfile,
    query_texts: list[str],
    *,
    deadline: Deadline | None = None,
    stage: str = "npu:cpu",
) -> np.ndarray:
    spec = ENCODER_SPECS["e5-small"]
    tokenizer = load_tokenizer(model_directory(workspace, spec))
    session = create_ort_session(path, profile)
    rows = []
    encoded = tokenize(tokenizer, query_texts, max_length=32, pad_to_max=True)
    for index in range(len(query_texts)):
        if deadline is not None:
            deadline.check(f"{stage}:item-{index}")
        batch = {name: value[index : index + 1] for name, value in encoded.items()}
        inputs = complete_graph_inputs(session, batch)
        rows.append(session.run(None, inputs)[0][0, 0])
    return np.asarray(rows, dtype=np.float32)


def run_npu_gate(
    workspace: Path,
    *,
    profile: RunningProfile | None = None,
    deadline: Deadline | None = None,
) -> dict[str, Any]:
    gate_deadline = deadline or Deadline()
    selected_profile = profile or RunningProfile.t1_emulated()
    results: dict[str, Any] = {"schema": 1, "attempts": {}}
    with bounded_gate(
        "npu",
        workspace=workspace,
        deadline=gate_deadline,
        results=results,
        completed_key="attempts",
    ):
        profile_record = apply_profile(selected_profile)
        fp32, quantized = prepare_npu_embedder(
            workspace,
            profile=selected_profile,
            deadline=gate_deadline,
        )
        spec = ENCODER_SPECS["e5-small"]
        tokenizer = load_tokenizer(model_directory(workspace, spec))
        frozen = load_frozen(workspace)
        view = embedding_view(frozen, "e5-small")
        query_texts = [row["text"] for row in view["queries"][:8]]
        encoded = tokenize(tokenizer, query_texts, max_length=32, pad_to_max=True)

        provider_options = {
            "device_type": "NPU",
            "cache_dir": str(workspace / "cache" / "openvino-npu"),
            "enable_npu_fast_compile": "False",
            "num_of_threads": str(selected_profile.ort_threads),
        }
        results.update(
            {
                "label": "T1-emulated host, Intel NPU",
                "profile": profile_record,
                "environment": capture_environment(),
                "graph": "e5-small static batch1 sequence32",
                "fp32_sha256": sha256_file(fp32),
                "static_qdq_sha256": sha256_file(quantized),
                "provider_options": provider_options,
            }
        )
        for variant, path in (("fp32", fp32), ("int8-static-qdq", quantized)):
            gate_deadline.check(f"npu:variant-{variant}")
            started = time.perf_counter()
            try:
                session = create_ort_session(
                    path,
                    selected_profile,
                    providers=[("OpenVINOExecutionProvider", provider_options)],
                    disable_cpu_fallback=True,
                )
            except GateTimeout:
                raise
            except Exception as error:
                results["attempts"][variant] = {
                    "reached": False,
                    "error": type(error).__name__,
                }
                continue
            cold_load = time.perf_counter() - started
            outputs = []
            for index in range(len(query_texts)):
                gate_deadline.check(f"npu:{variant}:item-{index}")
                batch = {name: value[index : index + 1] for name, value in encoded.items()}
                inputs = complete_graph_inputs(session, batch)
                try:
                    output = session.run(None, inputs)[0]
                except GateTimeout:
                    raise
                except Exception as error:
                    results["attempts"][variant] = {
                        "reached": False,
                        "error": type(error).__name__,
                        "cold_load_seconds": cold_load,
                    }
                    break
                outputs.append(output[0, 0])
            else:
                npu_vectors = np.asarray(outputs, dtype=np.float32)
                cpu_vectors = _cpu_vectors(
                    workspace,
                    path,
                    selected_profile,
                    query_texts,
                    deadline=gate_deadline,
                    stage=f"npu:{variant}:cpu-parity",
                )
                cosine = mean_cosine(cpu_vectors, npu_vectors)
                results["attempts"][variant] = {
                    "reached": True,
                    "providers": session.get_providers(),
                    "cold_load_seconds": cold_load,
                    "mean_cosine_vs_cpu": cosine,
                    "parity_passed": cosine >= 0.99,
                }
        results["k3_passed"] = any(
            item.get("reached") and item.get("parity_passed")
            for item in results["attempts"].values()
        )
        write_json(workspace / "results" / "npu.json", results)
    return results
