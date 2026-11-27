"""Run reranker variants on the frozen e5 first-stage lists."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from .artifacts import failure_reason, write_json
from .benchmark import summarize_latencies, token_length_summary
from .deadline import Deadline, bounded_gate
from .encoder_run import _batched, _prepare_variants, _variant_size
from .frozen import embedding_view, load_frozen
from .models import (
    ENCODER_SPECS,
    PROXY_RERANKER,
    RERANKERS,
    ModelError,
    ModelSpec,
    create_ort_session,
    download_encoder_assets,
    load_reference_model,
    load_tokenizer,
    model_directory,
    run_encoder_session,
    run_reference_model,
    tokenize,
)
from .parity import reranker_parity
from .system import RunningProfile, apply_profile, capture_environment, high_performance_power_scheme, wait_for_quiet_window

QUERY_COUNT = 30
DEPTH = 50
LATENCY_REPETITIONS = 30


class RerankerRunError(RuntimeError):
    """A reranker gate request outside the preregistered portfolio."""


def result_filename(model: str) -> str:
    """The proxy keeps ``reranker.json``; amendment rows get their own file."""
    return "reranker.json" if model == PROXY_RERANKER else f"reranker-{model}.json"


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1)
    if np.any(norms == 0):
        raise ValueError("first-stage embedding contains a zero vector")
    return matrix / norms[:, None]


def _candidate_lists(workspace: Path, frozen: dict[str, Any]) -> list[dict[str, Any]]:
    view = embedding_view(frozen, "e5-small")
    reference_dir = workspace / "reference" / "e5-small"
    queries = np.load(reference_dir / "queries.npy")
    passages = np.load(reference_dir / "passages.npy")
    miracl_query_count = view["source_counts"]["miracl"]["queries"]
    miracl_passage_count = view["source_counts"]["miracl"]["passages"]
    queries = _normalize_rows(queries[:miracl_query_count])
    passages = _normalize_rows(passages[:miracl_passage_count])
    scores = queries @ passages.T
    passages_rows = view["passages"][:miracl_passage_count]
    lists = []
    for index in range(min(QUERY_COUNT, miracl_query_count)):
        order = np.argsort(-scores[index], kind="stable")[:DEPTH]
        lists.append(
            {
                "query_id": view["queries"][index]["id"],
                "query": view["queries"][index]["text"],
                "passages": [passages_rows[item] for item in order],
            }
        )
    return lists


def _score_lists(
    session: Any,
    spec: ModelSpec,
    tokenizer: Any,
    lists: list[dict[str, Any]],
    *,
    deadline: Deadline | None = None,
    stage: str = "score-lists",
) -> list[dict[str, dict[str, float]]]:
    outputs = []
    for index, item in enumerate(lists):
        if deadline is not None:
            deadline.check(f"{stage}:list-{index}")
        passages = item["passages"]
        encoded = tokenize(
            tokenizer,
            [item["query"]] * len(passages),
            pair_texts=[passage["text"] for passage in passages],
            max_length=384,
        )
        values = run_encoder_session(session, encoded, spec)
        outputs.append(
            {
                item["query_id"]: {
                    passage["id"]: float(score)
                    for passage, score in zip(passages, values, strict=True)
                }
            }
        )
    return outputs


def _reference_lists(
    model: Any,
    spec: ModelSpec,
    tokenizer: Any,
    lists: list[dict[str, Any]],
    *,
    deadline: Deadline | None = None,
    stage: str = "reference-lists",
) -> list[dict[str, dict[str, float]]]:
    outputs = []
    for index, item in enumerate(lists):
        if deadline is not None:
            deadline.check(f"{stage}:list-{index}")
        passages = item["passages"]
        encoded = tokenize(
            tokenizer,
            [item["query"]] * len(passages),
            pair_texts=[passage["text"] for passage in passages],
            max_length=384,
        )
        rows = []
        for batch_index, batch in enumerate(_batched(encoded, 8)):
            if deadline is not None:
                deadline.check(f"{stage}:list-{index}:batch-{batch_index}")
            rows.append(run_reference_model(model, batch, spec))
        values = np.concatenate(rows)
        outputs.append(
            {
                item["query_id"]: {
                    passage["id"]: float(score)
                    for passage, score in zip(passages, values, strict=True)
                }
            }
        )
    return outputs


def _time_depth_lists(
    session: Any,
    spec: ModelSpec,
    tokenizer: Any,
    lists: list[dict[str, Any]],
    *,
    deadline: Deadline | None = None,
    stage: str = "time-depth-lists",
) -> dict[str, Any]:
    encoded_lists = [
        tokenize(
            tokenizer,
            [item["query"]] * DEPTH,
            pair_texts=[passage["text"] for passage in item["passages"]],
            max_length=384,
        )
        for item in lists
    ]
    token_lengths = [
        int(value)
        for encoded in encoded_lists
        for value in np.sum(encoded["attention_mask"], axis=1)
    ]
    for index, encoded in enumerate(encoded_lists[:3]):
        if deadline is not None:
            deadline.check(f"{stage}:warmup-{index}")
        run_encoder_session(session, encoded, spec)
    samples: list[float] = []
    repetitions = max(1, math.ceil(LATENCY_REPETITIONS / len(encoded_lists)))
    for repetition in range(repetitions):
        for index, encoded in enumerate(encoded_lists):
            if deadline is not None:
                deadline.check(f"{stage}:repetition-{repetition}:list-{index}")
            started = time.perf_counter_ns()
            run_encoder_session(session, encoded, spec)
            samples.append((time.perf_counter_ns() - started) / 1_000_000_000)
    summary = summarize_latencies(samples, resamples=2_000)
    summary["depth"] = DEPTH
    summary["inference_only"] = True
    summary["pair_token_lengths"] = token_length_summary(token_lengths)
    return {"summary": summary, "raw_seconds": samples}


def run_reranker_gate(
    workspace: Path,
    *,
    profile: RunningProfile | None = None,
    wait_seconds: float = 900.0,
    deadline: Deadline | None = None,
    model: str = PROXY_RERANKER,
) -> dict[str, Any]:
    if model not in RERANKERS:
        raise RerankerRunError("reranker is not in the preregistered portfolio")
    gate_deadline = deadline or Deadline()
    spec = ENCODER_SPECS[model]
    result_path = workspace / "results" / result_filename(model)
    selected_profile = profile or RunningProfile.t1_emulated()
    results: dict[str, Any] = {"schema": 1, "variants": {}}
    with bounded_gate(
        result_path.stem,
        workspace=workspace,
        deadline=gate_deadline,
        results=results,
    ):
        profile_record = apply_profile(selected_profile)
        results.update(
            {
                "label": "T1-emulated, provisional",
                "model": model,
                "repository": spec.repository,
                "revision": spec.revision,
                "profile": profile_record,
                "environment": capture_environment(),
                "depth": DEPTH,
                "latency_repetitions": LATENCY_REPETITIONS,
                "max_pair_tokens": 384,
            }
        )
        frozen = load_frozen(workspace)
        view = embedding_view(frozen, "granite-modernbert")
        # A model never downloaded before has no local tokenizer yet.
        tokenizer = load_tokenizer(download_encoder_assets(workspace, spec))
        variant_failures: dict[str, str] = {}
        variants = _prepare_variants(
            workspace,
            spec,
            tokenizer,
            deadline=gate_deadline,
            failures=None if model == PROXY_RERANKER else variant_failures,
        )
        if variant_failures:
            results["variant_failures"] = variant_failures
        gate_deadline.check("reranker:first-stage-lists")
        lists = _candidate_lists(workspace, frozen)
        results["queries"] = len(lists)

        reference_model = load_reference_model(model_directory(workspace, spec), spec)
        import torch

        torch.set_num_threads(selected_profile.ort_threads)
        gate_deadline.check("reranker:reference")
        reference = _reference_lists(
            reference_model,
            spec,
            tokenizer,
            lists,
            deadline=gate_deadline,
            stage="reranker:reference",
        )
        for name, path in variants.items():
            gate_deadline.check(f"reranker:variant-{name}")
            try:
                started = time.perf_counter()
                session = create_ort_session(path, selected_profile)
                cold_load_seconds = time.perf_counter() - started
                candidate = _score_lists(
                    session,
                    spec,
                    tokenizer,
                    lists,
                    deadline=gate_deadline,
                    stage=f"reranker:{name}:score",
                )
            except ModelError as error:
                if model == PROXY_RERANKER:
                    raise
                # Amendment 3: an unrunnable variant is a reported result.
                variant_failures[name] = failure_reason(error)
                results["variant_failures"] = variant_failures
                write_json(result_path, results)
                continue
            parity = reranker_parity(reference, candidate, view["qrels"], k=10)
            passes_parity = (
                parity["mean_kendall_tau_b"] >= 0.95
                and parity["worst_kendall_tau_b"] >= 0.90
                and abs(parity["nDCG@10_delta"]) <= 0.005
            )
            size, files = _variant_size(
                path.parent,
                deadline=gate_deadline,
                stage=f"reranker:{name}:size",
            )
            variant_result: dict[str, Any] = {
                "path_label": f"{model}/{name}",
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
                        timing = _time_depth_lists(
                            session,
                            spec,
                            tokenizer,
                            lists,
                            deadline=gate_deadline,
                            stage=f"reranker:{name}:time",
                        )
                    variant_result["timing"] = {"power": power, "depth_50": timing["summary"]}
                    raw_dir = workspace / "raw" / "reranker"
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    write_json(raw_dir / f"{name}-timings.json", {"durations_seconds": timing["raw_seconds"]})
                else:
                    variant_result["timing_skipped"] = "quiet window did not open"
            results["variants"][name] = variant_result
            write_json(result_path, results)
    return results
