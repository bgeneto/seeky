"""Reach an Intel NPU through ORT's OpenVINO EP and verify parity."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np

from .artifacts import failure_reason, sha256_file, write_json
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


NPU_QUERIES = 8
NPU_SEQUENCE = 32


def npu_inputs_path(workspace: Path) -> Path:
    """Tokenized probe queries, written by the CPU environment.

    The OpenVINO environment has neither PyTorch nor Transformers, so the
    prepare step (CPU venv) freezes the exact token IDs the NPU gate feeds.
    """
    return workspace / "variants" / "e5-small" / "npu-inputs.npz"


def load_npu_inputs(workspace: Path) -> dict[str, np.ndarray]:
    path = npu_inputs_path(workspace)
    if not path.is_file():
        raise NpuRunError("tokenized NPU probe is missing; run the prepare step in the CPU environment")
    with np.load(path) as stored:
        encoded = {name: np.asarray(stored[name], dtype=np.int64) for name in stored.files}
    if "input_ids" not in encoded or encoded["input_ids"].shape != (NPU_QUERIES, NPU_SEQUENCE):
        raise NpuRunError("tokenized NPU probe has an unexpected shape")
    return encoded


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
    probe = npu_inputs_path(workspace)
    if not probe.exists():
        tokenizer = load_tokenizer(source_dir)
        view = embedding_view(load_frozen(workspace), "e5-small")
        encoded = tokenize(
            tokenizer,
            [row["text"] for row in view["queries"][:NPU_QUERIES]],
            max_length=NPU_SEQUENCE,
            pad_to_max=True,
        )
        np.savez(probe, **encoded)
    return fp32, quantized


def _cpu_vectors(
    path: Path,
    profile: RunningProfile,
    encoded: dict[str, np.ndarray],
    *,
    deadline: Deadline | None = None,
    stage: str = "npu:cpu",
) -> np.ndarray:
    session = create_ort_session(path, profile)
    rows = []
    for index in range(len(encoded["input_ids"])):
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
        encoded = load_npu_inputs(workspace)

        provider_options = {
            "device_type": "NPU",
            "cache_dir": str(workspace / "cache" / "openvino-npu"),
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
                    "error": failure_reason(error),
                }
                continue
            cold_load = time.perf_counter() - started
            outputs = []
            for index in range(len(encoded["input_ids"])):
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
                        "error": failure_reason(error),
                        "cold_load_seconds": cold_load,
                    }
                    break
                outputs.append(output[0, 0])
            else:
                npu_vectors = np.asarray(outputs, dtype=np.float32)
                cpu_vectors = _cpu_vectors(
                    path,
                    selected_profile,
                    encoded,
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
