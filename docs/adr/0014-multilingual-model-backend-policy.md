# ADR-0014 — Multilingual model and backend policy

- **Status:** Superseded by [ADR-0016](0016-cpu-first-npu-ready-execution.md) and [ADR-0019](0019-single-inference-engine.md)
- **Date:** 2026-11-26

## Decision (historical)

Select multilingual models by quality, CPU practicality, accelerator latency,
memory, and license; CPU as fallback; CUDA, AMD (DirectML/ROCm), and Intel NPU
as validated accelerated paths.

## Why superseded

CPU is the **primary** target, not a fallback; GPUs are optional and never on
the critical path; NPUs are the accelerator class Seeky designs for. Model
selection rules now live in [`../benchmarks/methodology.md`](../benchmarks/methodology.md);
the runtime contract lives in ADR-0019. The rule "one embedding model per index;
a model change requires a versioned reindex" is preserved in ADR-0019.
