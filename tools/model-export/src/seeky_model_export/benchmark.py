"""Nearest-rank timing summaries and deterministic bootstrap intervals."""

from __future__ import annotations

from typing import Any

import numpy as np

from .metrics import nearest_rank_percentile

DEFAULT_SEED = 6006
DEFAULT_RESAMPLES = 10_000


class BenchmarkError(RuntimeError):
    """A timing sample is empty, invalid, or cannot be summarized."""


def _vector(values: object, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or len(array) == 0 or not np.isfinite(array).all():
        raise BenchmarkError(f"{name} must be a non-empty finite vector")
    if np.any(array <= 0):
        raise BenchmarkError(f"{name} must contain positive values only")
    return array


def _bootstrap_percentile_ci(
    values: np.ndarray,
    percentile: float,
    *,
    seed: int = DEFAULT_SEED,
    resamples: int = DEFAULT_RESAMPLES,
) -> tuple[float, float]:
    generator = np.random.default_rng(seed)
    estimates = np.empty(resamples, dtype=np.float64)
    for index in range(resamples):
        sampled = values[generator.integers(0, len(values), size=len(values))]
        estimates[index] = nearest_rank_percentile(sampled, percentile)
    low, high = np.percentile(estimates, [2.5, 97.5])
    return float(low), float(high)


def summarize_latencies(
    seconds: object,
    *,
    seed: int = DEFAULT_SEED,
    resamples: int = DEFAULT_RESAMPLES,
) -> dict[str, Any]:
    values = _vector(seconds, "latency")
    milliseconds = values * 1000.0
    p50 = nearest_rank_percentile(milliseconds, 50)
    p95 = nearest_rank_percentile(milliseconds, 95)
    p50_ci = _bootstrap_percentile_ci(milliseconds, 50, seed=seed, resamples=resamples)
    p95_ci = _bootstrap_percentile_ci(milliseconds, 95, seed=seed, resamples=resamples)
    return {
        "count": len(values),
        "mean_ms": float(np.mean(milliseconds)),
        "p50_ms": p50,
        "p95_ms": p95,
        "p50_ci95_ms": list(p50_ci),
        "p95_ci95_ms": list(p95_ci),
        "min_ms": float(np.min(milliseconds)),
        "max_ms": float(np.max(milliseconds)),
    }


def token_length_summary(lengths: object) -> dict[str, float | int]:
    values = _vector(lengths, "token length")
    return {
        "count": len(values),
        "mean": float(np.mean(values)),
        "p50": nearest_rank_percentile(values, 50),
        "p95": nearest_rank_percentile(values, 95),
        "max": float(np.max(values)),
    }


def summarize_throughput(
    batch_seconds: object,
    *,
    batch_size: int,
    seed: int = DEFAULT_SEED,
    resamples: int = DEFAULT_RESAMPLES,
) -> dict[str, Any]:
    if batch_size <= 0:
        raise BenchmarkError("throughput batch size must be positive")
    durations = _vector(batch_seconds, "batch duration")
    passages = len(durations) * batch_size
    total = float(np.sum(durations))
    rate = passages / total
    generator = np.random.default_rng(seed)
    estimates = np.empty(resamples, dtype=np.float64)
    for index in range(resamples):
        sampled = durations[generator.integers(0, len(durations), size=len(durations))]
        estimates[index] = passages / float(np.sum(sampled))
    low, high = np.percentile(estimates, [2.5, 97.5])
    return {
        "batch_size": batch_size,
        "batches": len(durations),
        "passages": passages,
        "total_seconds": total,
        "passages_per_second": rate,
        "throughput_ci95": [float(low), float(high)],
        "batch_mean_ms": float(np.mean(durations) * 1000.0),
        "batch_p95_ms": nearest_rank_percentile(durations * 1000.0, 95),
    }
