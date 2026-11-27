"""Reach an Intel NPU through ORT's OpenVINO EP and verify parity."""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from .artifacts import _PATH_TOKEN, failure_reason, sha256_file, write_json
from .deadline import Deadline, bounded_gate
from .frozen import embedding_view, load_frozen
from .metrics import mean_cosine
from .models import (
    ENCODER_SPECS,
    ModelError,
    complete_graph_inputs,
    create_ort_session,
    export_embedder_static_fp32,
    load_tokenizer,
    model_directory,
    pool_hidden,
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


def expose_openvino_runtime() -> None:
    """Put the pip ``openvino`` DLLs on the Windows loader path.

    onnxruntime-openvino loads ``openvino.dll`` when it creates the EP; without
    this the EP fails to load and the session asks for the CPU EP instead.
    """
    if sys.platform != "win32":
        return
    try:
        from onnxruntime.tools.add_openvino_win_libs import add_openvino_libs_to_path

        add_openvino_libs_to_path()
    except (ImportError, SystemExit) as error:
        raise NpuRunError("OpenVINO runtime libraries are not installed") from error


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


def _attempt_command(request: dict[str, Any]) -> list[str]:
    return [sys.executable, "-m", "seeky_model_export.npu_run"]


def _last_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return None
    return None


def _native_error(stderr: str) -> str:
    """The NPU compiler's last error line, without local paths."""
    for line in reversed(stderr.splitlines()):
        if "[ERROR]" in line:
            return _PATH_TOKEN.sub("<path>", line.strip())[:300]
    return ""


def run_attempt_isolated(
    path: Path,
    profile: RunningProfile,
    provider_options: dict[str, str],
    *,
    workspace: Path,
    variant: str,
    deadline: Deadline,
) -> tuple[dict[str, Any], np.ndarray | None]:
    """Run one NPU attempt in a child process.

    The NPU compiler can crash its process outright; isolating each attempt
    turns that into a recorded failure (§5: failures are results). The child
    inherits this process's CPU affinity and Job Object.
    """
    vectors_path = workspace / "raw" / "npu" / f"{variant}-vectors.npy"
    vectors_path.parent.mkdir(parents=True, exist_ok=True)
    vectors_path.unlink(missing_ok=True)
    request = {
        "model_path": str(path),
        "inputs_path": str(npu_inputs_path(workspace)),
        "vectors_path": str(vectors_path),
        "provider_options": provider_options,
        "profile": dataclasses.asdict(profile),
    }
    deadline.check(f"npu:variant-{variant}")
    try:
        completed = subprocess.run(
            _attempt_command(request),
            input=json.dumps(request),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1.0, deadline.remaining()),
        )
    except subprocess.TimeoutExpired:
        deadline.check(f"npu:{variant}:attempt")
        return {"reached": False, "error": "NPU attempt timed out"}, None
    record = _last_json(completed.stdout)
    if completed.returncode != 0 or record is None:
        return {
            "reached": False,
            "exit_code": completed.returncode,
            "error": "NPU attempt process ended without a result",
            "native_error": _native_error(completed.stderr),
        }, None
    vectors = np.load(vectors_path) if record.get("reached") else None
    return record, vectors


def _attempt_in_this_process(request: dict[str, Any]) -> dict[str, Any]:
    """Child body: compile on the NPU, run the frozen probe, save hidden states."""
    expose_openvino_runtime()
    profile = RunningProfile(**request["profile"])
    with np.load(request["inputs_path"]) as stored:
        encoded = {name: np.asarray(stored[name], dtype=np.int64) for name in stored.files}
    started = time.perf_counter()
    try:
        session = create_ort_session(
            Path(request["model_path"]),
            profile,
            providers=[("OpenVINOExecutionProvider", request["provider_options"])],
            disable_cpu_fallback=True,
        )
    except Exception as error:
        return {"reached": False, "error": failure_reason(error)}
    cold_load = time.perf_counter() - started
    outputs = []
    for index in range(len(encoded["input_ids"])):
        batch = {name: value[index : index + 1] for name, value in encoded.items()}
        try:
            output = session.run(None, complete_graph_inputs(session, batch))[0]
        except Exception as error:
            return {
                "reached": False,
                "error": failure_reason(error),
                "cold_load_seconds": cold_load,
            }
        outputs.append(output[0])
    np.save(request["vectors_path"], np.asarray(outputs, dtype=np.float32))
    return {
        "reached": True,
        "providers": session.get_providers(),
        "cold_load_seconds": cold_load,
    }


def embedding_parity(
    cpu_hidden: np.ndarray,
    npu_hidden: np.ndarray,
    attention_mask: np.ndarray,
    pooling: str,
) -> dict[str, Any]:
    """Apply the embedder tolerance (PREREGISTRATION §5) to pooled vectors.

    Token-0 cosine is kept as a diagnostic only; padded positions never reach
    a masked-mean embedding, so they must not decide parity.
    """
    record: dict[str, Any] = {
        "token0_cosine_vs_cpu": mean_cosine(cpu_hidden[:, 0, :], npu_hidden[:, 0, :]),
    }
    try:
        cpu = pool_hidden(cpu_hidden, attention_mask, pooling, normalize=True)
        npu = pool_hidden(npu_hidden, attention_mask, pooling, normalize=True)
    except ModelError as error:
        record.update({"parity_passed": False, "parity_error": failure_reason(error)})
        return record
    cosine = mean_cosine(cpu, npu)
    record.update({"mean_cosine_vs_cpu": cosine, "parity_passed": cosine >= 0.99})
    return record


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
        rows.append(session.run(None, inputs)[0][0])
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
        expose_openvino_runtime()

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
            attempt, npu_vectors = run_attempt_isolated(
                path,
                selected_profile,
                provider_options,
                workspace=workspace,
                variant=variant,
                deadline=gate_deadline,
            )
            if npu_vectors is not None:
                cpu_vectors = _cpu_vectors(
                    path,
                    selected_profile,
                    encoded,
                    deadline=gate_deadline,
                    stage=f"npu:{variant}:cpu-parity",
                )
                attempt.update(
                    embedding_parity(
                        cpu_vectors,
                        npu_vectors,
                        encoded["attention_mask"],
                        ENCODER_SPECS["e5-small"].pooling,
                    )
                )
            results["attempts"][variant] = attempt
        results["k3_passed"] = any(
            item.get("reached") and item.get("parity_passed")
            for item in results["attempts"].values()
        )
        write_json(workspace / "results" / "npu.json", results)
    return results


def _child_main() -> int:
    request = json.loads(sys.stdin.read())
    print(json.dumps(_attempt_in_this_process(request)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(_child_main())
