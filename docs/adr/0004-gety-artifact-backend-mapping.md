# ADR-0004 — CPU/CUDA/NPU mapping on Gety model artifacts

- **Status:** Superseded by [ADR-0016](0016-cpu-first-npu-ready-execution.md) and [ADR-0019](0019-single-inference-engine.md)
- **Date:** 2026-11-26

## Decision (historical)

Use Gety's installed `gety-embed-v0` artifacts directly: uint8 ONNX on CPU via
ONNX Runtime, FP16 ONNX on the ORT CUDA EP, OpenVINO IR on Intel AI Boost NPU.
Auto mode resolved CUDA → NPU → CPU.

## Why superseded

- CPU-first, NPU-ready, GPU-optional (ADR-0016): auto mode no longer prefers a
  GPU, and no GPU path is on the critical path.
- The engine is model-agnostic and loads models from a verified manifest, not a
  third-party installation (ADR-0019, ADR-0011).
- `gety-embed-v0` remains a benchmark baseline only.
