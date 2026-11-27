"""Execute the preregistered encoder/reranker deployment matrix."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from .artifacts import sha256_file, write_json
from .benchmark import summarize_latencies, summarize_throughput, token_length_summary
from .deadline import Deadline, bounded_gate
from .frozen import embedding_view, load_frozen
from .models import (
    ENCODER_SPECS,
    ModelSpec,
    complete_graph_inputs,
    create_ort_session,
    download_encoder_assets,
    export_reranker_fp32,
    load_reference_model,
    load_tokenizer,
    manifest_for_directory,
    model_directory,
    run_encoder_session,
    run_reference_model,
    tokenize,
)
from .parity import embedding_parity
from .quantize import ArrayCalibrationReader, quantize_dynamic_model, quantize_static_model
from .system import (
    ProfileError,
    RunningProfile,
    apply_profile,
    capture_environment,
    high_performance_power_scheme,
    wait_for_quiet_window,
)

QUERY_REPETITIONS = 30
PASSAGE_BATCH_SIZE = 8
PASSAGE_PASSES = 3


def _batched(encoded: dict[str, np.ndarray], batch_size: int):
    count = len(next(iter(encoded.values())))
    for start in range(0, count, batch_size):
        yield {name: value[start : start + batch_size] for name, value in encoded.items()}


def _variant_directory(workspace: Path, spec: ModelSpec, variant: str) -> Path:
    return workspace / "variants" / spec.slug / variant


def _variant_size(
    directory: Path,
    *,
    deadline: Deadline | None = None,
    stage: str = "size",
) -> tuple[int, list[dict[str, Any]]]:
    files = []
    total = 0
    for index, path in enumerate(sorted(directory.rglob("*"))):
        if path.is_file():
            if deadline is not None:
                deadline.check(f"{stage}:file-{index}")
            total += path.stat().st_size
            files.append(
                {
                    "filename": path.relative_to(directory).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return total, files


def _prepare_variants(
    workspace: Path,
    spec: ModelSpec,
    tokenizer: Any,
    *,
    deadline: Deadline | None = None,
) -> dict[str, Path]:
    if deadline is not None:
        deadline.check(f"{spec.slug}:prepare:assets")
    source_dir = download_encoder_assets(workspace, spec)
    if spec.slug == "gte-reranker":
        fp32 = _variant_directory(workspace, spec, "fp32") / "model.onnx"
        if not fp32.exists():
            if deadline is not None:
                deadline.check(f"{spec.slug}:prepare:fp32")
            export_reranker_fp32(source_dir, fp32, spec)
    else:
        fp32 = source_dir / "onnx" / "model.onnx"
    variants = {"fp32": fp32}
    dynamic = _variant_directory(workspace, spec, "int8-dynamic") / "model.onnx"
    if not dynamic.exists():
        if deadline is not None:
            deadline.check(f"{spec.slug}:prepare:int8-dynamic")
        quantize_dynamic_model(fp32, dynamic)
    variants["int8-dynamic"] = dynamic
    static = _variant_directory(workspace, spec, "int8-static-qdq") / "model.onnx"
    if not static.exists():
        if deadline is not None:
            deadline.check(f"{spec.slug}:prepare:int8-static-qdq")
        if spec.slug == "gte-reranker":
            frozen = load_frozen(workspace)
            view = embedding_view(frozen, "granite-modernbert")
            pairs = []
            for index in range(128):
                query = view["queries"][index % len(view["queries"])]["text"]
                passage = view["passages"][index % len(view["passages"])]["text"]
                pairs.append((query, passage))
            calibration_text = [item[0] for item in pairs]
            calibration_pair = [item[1] for item in pairs]
            encoded = tokenize(
                tokenizer,
                calibration_text,
                pair_texts=calibration_pair,
                max_length=384,
                pad_to_max=True,
            )
        else:
            frozen = load_frozen(workspace)
            view = embedding_view(frozen, spec.slug)
            encoded = tokenize(
                tokenizer,
                [row["text"] for row in view["passages"][:128]],
                max_length=384,
                pad_to_max=True,
            )
        import onnxruntime as ort

        calibration_session = ort.InferenceSession(
            str(fp32),
            providers=["CPUExecutionProvider"],
        )
        encoded = complete_graph_inputs(calibration_session, encoded)
        rows = [
            {name: value[index : index + 1] for name, value in encoded.items()}
            for index in range(128)
        ]
        quantize_static_model(
            fp32,
            static,
            ArrayCalibrationReader(fp32, rows),
        )
    variants["int8-static-qdq"] = static
    return variants


def _encode_corpus(
    session: Any,
    tokenizer: Any,
    spec: ModelSpec,
    texts: list[str],
    *,
    max_length: int,
    batch_size: int = 8,
    deadline: Deadline | None = None,
    stage: str = "encode",
) -> np.ndarray:
    encoded = tokenize(tokenizer, texts, max_length=max_length)
    rows = []
    for index, batch in enumerate(_batched(encoded, batch_size)):
        if deadline is not None:
            deadline.check(f"{stage}:batch-{index}")
        rows.append(run_encoder_session(session, batch, spec))
    return np.concatenate(rows, axis=0)


def _reference_encode(
    model: Any,
    tokenizer: Any,
    spec: ModelSpec,
    texts: list[str],
    *,
    max_length: int,
    batch_size: int = 8,
    deadline: Deadline | None = None,
    stage: str = "reference",
) -> np.ndarray:
    encoded = tokenize(tokenizer, texts, max_length=max_length)
    rows = []
    for index, batch in enumerate(_batched(encoded, batch_size)):
        if deadline is not None:
            deadline.check(f"{stage}:batch-{index}")
        rows.append(run_reference_model(model, batch, spec))
    return np.concatenate(rows, axis=0)


def _time_queries(
    session: Any,
    spec: ModelSpec,
    tokenizer: Any,
    queries: list[str],
    *,
    max_length: int,
    deadline: Deadline | None = None,
    stage: str = "time-queries",
) -> dict[str, Any]:
    encoded_queries = [
        tokenize(tokenizer, [query], max_length=max_length) for query in queries
    ]
    token_lengths = [int(np.sum(item["attention_mask"])) for item in encoded_queries]
    for index, batch in enumerate(encoded_queries[:3]):
        if deadline is not None:
            deadline.check(f"{stage}:warmup-{index}")
        run_encoder_session(session, batch, spec)
    samples: list[float] = []
    for repetition in range(QUERY_REPETITIONS):
        for index, batch in enumerate(encoded_queries):
            if deadline is not None:
                deadline.check(f"{stage}:repetition-{repetition}:item-{index}")
            started = time.perf_counter_ns()
            run_encoder_session(session, batch, spec)
            samples.append((time.perf_counter_ns() - started) / 1_000_000_000)
    summary = summarize_latencies(samples, resamples=2_000)
    summary["inference_only"] = True
    summary["token_lengths"] = token_length_summary(token_lengths)
    return {"summary": summary, "raw_seconds": samples}


def _time_passages(
    session: Any,
    spec: ModelSpec,
    tokenizer: Any,
    passages: list[str],
    *,
    max_length: int,
    deadline: Deadline | None = None,
    stage: str = "time-passages",
) -> dict[str, Any]:
    batches = [
        tokenize(
            tokenizer,
            passages[start : start + PASSAGE_BATCH_SIZE],
            max_length=max_length,
        )
        for start in range(0, len(passages), PASSAGE_BATCH_SIZE)
    ]
    token_lengths = [
        int(value)
        for batch in batches
        for value in np.sum(batch["attention_mask"], axis=1)
    ]
    for index, batch in enumerate(batches[:3]):
        if deadline is not None:
            deadline.check(f"{stage}:warmup-{index}")
        run_encoder_session(session, batch, spec)
    durations: list[float] = []
    for repetition in range(PASSAGE_PASSES):
        for index, batch in enumerate(batches):
            if deadline is not None:
                deadline.check(f"{stage}:pass-{repetition}:batch-{index}")
            started = time.perf_counter_ns()
            run_encoder_session(session, batch, spec)
            durations.append((time.perf_counter_ns() - started) / 1_000_000_000)
    summary = summarize_throughput(
        durations,
        batch_size=PASSAGE_BATCH_SIZE,
        resamples=2_000,
    )
    summary["passes"] = PASSAGE_PASSES
    summary["inference_only"] = True
    summary["token_lengths"] = token_length_summary(token_lengths)
    return {"summary": summary, "raw_seconds": durations}


def run_encoder_gate(
    workspace: Path,
    slug: str,
    *,
    profile: RunningProfile | None = None,
    wait_seconds: float = 900.0,
    deadline: Deadline | None = None,
) -> dict[str, Any]:
    if slug not in {"e5-small", "granite-modernbert"}:
        raise ValueError("embedding gate supports only preregistered embedders")
    gate_deadline = deadline or Deadline()
    spec = ENCODER_SPECS[slug]
    selected_profile = profile or RunningProfile.t1_emulated()
    results: dict[str, Any] = {"schema": 1, "variants": {}}
    with bounded_gate(
        f"encoders-{slug}",
        workspace=workspace,
        deadline=gate_deadline,
        results=results,
    ):
        frozen = load_frozen(workspace)
        view = embedding_view(frozen, slug)
        gate_deadline.check(f"encoders:{slug}:load-frozen")
        results.update(
            {
                "label": "T1-emulated, provisional",
                "model": slug,
                "repository": spec.repository,
                "revision": spec.revision,
                "profile": selected_profile.to_public_dict(),
                "environment": capture_environment(),
                "samples": view["source_counts"],
                "query_repetitions": QUERY_REPETITIONS,
                "passage_batch_size": PASSAGE_BATCH_SIZE,
                "passage_passes": PASSAGE_PASSES,
                "max_query_tokens": 64,
                "max_passage_tokens": 384,
            }
        )
        tokenizer = load_tokenizer(model_directory(workspace, spec))
        variants = _prepare_variants(
            workspace,
            spec,
            tokenizer,
            deadline=gate_deadline,
        )

        reference_dir = workspace / "reference" / slug
        reference_dir.mkdir(parents=True, exist_ok=True)
        query_reference = reference_dir / "queries.npy"
        passage_reference = reference_dir / "passages.npy"
        gate_deadline.check(f"encoders:{slug}:reference")
        if query_reference.exists() and passage_reference.exists():
            reference_queries = np.load(query_reference)
            reference_passages = np.load(passage_reference)
        else:
            reference_model = load_reference_model(model_directory(workspace, spec), spec)
            import psutil
            import torch

            torch.set_num_threads(psutil.cpu_count(logical=True) or 1)
            reference_queries = _reference_encode(
                reference_model,
                tokenizer,
                spec,
                [row["text"] for row in view["queries"]],
                max_length=64,
                deadline=gate_deadline,
                stage=f"encoders:{slug}:reference-queries",
            )
            reference_passages = _reference_encode(
                reference_model,
                tokenizer,
                spec,
                [row["text"] for row in view["passages"]],
                max_length=384,
                deadline=gate_deadline,
                stage=f"encoders:{slug}:reference-passages",
            )
            np.save(query_reference, reference_queries)
            np.save(passage_reference, reference_passages)
        profile_record = apply_profile(selected_profile)
        results["profile"] = profile_record
        import torch

        torch.set_num_threads(selected_profile.ort_threads)

        query_ids = [row["id"] for row in view["queries"]]
        passage_ids = [row["id"] for row in view["passages"]]

        for name, path in variants.items():
            gate_deadline.check(f"encoders:{slug}:variant-{name}")
            started = time.perf_counter()
            session = create_ort_session(path, selected_profile)
            cold_load_seconds = time.perf_counter() - started
            candidate_queries = _encode_corpus(
                session,
                tokenizer,
                spec,
                [row["text"] for row in view["queries"]],
                max_length=64,
                deadline=gate_deadline,
                stage=f"encoders:{slug}:{name}:queries",
            )
            candidate_passages = _encode_corpus(
                session,
                tokenizer,
                spec,
                [row["text"] for row in view["passages"]],
                max_length=384,
                deadline=gate_deadline,
                stage=f"encoders:{slug}:{name}:passages",
            )
            parity = embedding_parity(
                reference_queries,
                reference_passages,
                candidate_queries,
                candidate_passages,
                query_ids,
                passage_ids,
                qrels=view["qrels"],
            )
            passes_parity = (
                parity["mean_cosine"] >= 0.99
                and parity["neighbor_recall_at_100"] >= 0.98
                and (
                    parity["nDCG@10_delta"] is None
                    or abs(parity["nDCG@10_delta"]) <= 0.005
                )
            )
            size, files = _variant_size(
                path.parent,
                deadline=gate_deadline,
                stage=f"encoders:{slug}:{name}:size",
            )
            variant_result: dict[str, Any] = {
                "path_label": f"{slug}/{name}",
                "providers": session.get_providers(),
                "model_bytes": size,
                "files": files,
                "cold_load_seconds": cold_load_seconds,
                "parity": parity,
                "parity_passed": passes_parity,
                "timing": None,
            }
            if passes_parity:
                quiet = wait_for_quiet_window(
                    timeout_seconds=wait_seconds,
                    deadline=gate_deadline,
                )
                variant_result["quiet_window"] = quiet
                if quiet["quiet"]:
                    with high_performance_power_scheme(deadline=gate_deadline) as power:
                        query_timing = _time_queries(
                            session,
                            spec,
                            tokenizer,
                            [row["text"] for row in view["queries"]],
                            max_length=64,
                            deadline=gate_deadline,
                            stage=f"encoders:{slug}:{name}:time-queries",
                        )
                        passage_timing = _time_passages(
                            session,
                            spec,
                            tokenizer,
                            [row["text"] for row in view["passages"]],
                            max_length=384,
                            deadline=gate_deadline,
                            stage=f"encoders:{slug}:{name}:time-passages",
                        )
                    variant_result["timing"] = {
                        "power": power,
                        "query": query_timing["summary"],
                        "passage": passage_timing["summary"],
                    }
                    raw_dir = workspace / "raw" / "encoders"
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    write_json(
                        raw_dir / f"{slug}-{name}-timings.json",
                        {
                            "query_seconds": query_timing["raw_seconds"],
                            "passage_batch_seconds": passage_timing["raw_seconds"],
                        },
                    )
                else:
                    variant_result["timing_skipped"] = "quiet window did not open"
            results["variants"][name] = variant_result
            write_json(workspace / "results" / f"encoders-{slug}.json", results)
    return results
