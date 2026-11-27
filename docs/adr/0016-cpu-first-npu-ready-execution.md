# ADR-0016 — CPU-first, NPU-ready, GPU-optional execution

- **Status:** Accepted
- **Date:** 2026-11-27
- **Supersedes:** backend parts of ADR-0004 and ADR-0014

## Context

Non-negotiable principles: a dedicated GPU must never be required; optional
acceleration targets low-power NPUs. The PoC treated CUDA as the preferred
backend and CPU as a fallback, and the earlier plan promised CUDA, AMD GPU, and
Intel GPU paths. GPU runtimes (CUDA/cuDNN) add hundreds of megabytes to
gigabytes of downloads, contradict the slim distribution, and serve a minority
of users.

## Decision

1. **CPU is the primary target.** Every budget in
   [`../benchmarks/methodology.md`](../benchmarks/methodology.md) is defined
   and verified on CPU-only reference hardware. Every feature must work on CPU.
2. **NPUs are the designed-for accelerator.** Through ONNX Runtime
   execution providers ([ADR-0019](0019-single-inference-engine.md)): OpenVINO
   (Intel NPU), QNN (Qualcomm Hexagon), VitisAI (AMD XDNA), CoreML (Apple
   Neural Engine). Reaching the Intel NPU with parity is part of the ORT
   validation gate (kill criterion K3). NPU use is optional, automatic when validated,
   and must produce vectors compatible with the CPU path for the same model.
3. **GPUs are opportunistic.** No GPU runtime is downloaded by default and no
   feature requires one. A GPU **opt-in asset pack** (for example a GPU OCR
   tier, or faster initial indexing) may be offered when a bake-off shows
   material value, its full deployment cost is accounted for, and it adds no
   complexity to the default CPU path. The PoC CUDA embedding path is frozen
   and receives no further investment.
4. **Auto selection** picks the fastest validated provider per workload
   (query-latency vs indexing-throughput) and falls back to CPU on any load or
   parity failure.

## Consequences

- Model selection weighs CPU latency/throughput heavily; large decoder-based
  embedders/rerankers (≥ 0.5B parameters) are reference ceilings in
  benchmarks, not shipped defaults.
- Static-shape bucketing and compiled-model caching are required for NPUs.
- The hardware test matrix is CPU tiers first, NPU second, GPU last.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| GPU-first with CPU fallback | Violates CPU-first; heavy downloads; minority hardware |
| CPU only, no NPU | Leaves low-power acceleration on the table on modern laptops |
| DirectML as the universal accelerator | Maintenance-mode API; GPU-centric; Windows only |
