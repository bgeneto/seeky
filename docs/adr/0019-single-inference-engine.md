# ADR-0019 — ONNX Runtime as the single inference engine, with a validation gate

- **Status:** Accepted
- **Date:** 2026-11-27
- **Supersedes:** runtime parts of ADR-0004 and ADR-0014

## Context

The core must be model-agnostic: replacing an embedding model, reranker,
snippet scorer, or OCR model must not require rewriting the engine. The PoC
hardcodes `DIM = 384`, Gety paths, output tensor names, and uses two runtimes
(ONNX Runtime and the native OpenVINO API).

The inference engine is a first-order product decision: it sets the runtime
download and binary size, the available quantization formats, which NPUs can be
reached, and how much export and integration code must be maintained. Every
additional engine multiplies those costs.

Seeky ships no generative features, so every neural component is a relatively
small model that a general-purpose runtime can execute. ONNX Runtime offers one
inference API, one model format (`.onnx`), one shared library for all models,
independent sessions per model and workload, optional hardware acceleration
through execution providers (EPs), and CPU fallback. It runs the PoC today.

A file format is not an architecture: ONNX, GGUF, and OpenVINO IR can all carry
encoders and decoders. ONNX Runtime is chosen on its merits for Seeky's needs,
not because other formats imply generative models.

The choice of engine is decided mostly by **speed, memory, size, NPU reach,
and parity**, not by retrieval quality: quality is a property of the model, and
parity tests prove the engine preserves it. The engine can therefore be
validated early, before the evaluation corpus and judgments exist.

## Decision

1. **ONNX Runtime is the single inference engine** for all neural components
   (embedder, reranker, snippet scorer, sparse encoder, OCR), through the `ort`
   crate, dynamically loaded and provisioned as an asset. The engine is an
   implementation detail of `seeky-infer`; no engine type crosses its public
   traits (`Embedder`, `Reranker`, `SnippetScorer`, `OcrEngine`, defined in
   `seeky-core`).
2. **Acceleration through execution providers** (ADR-0016): CPU everywhere;
   OpenVINO (Intel NPU), QNN (Qualcomm), VitisAI (AMD), and CoreML (Apple) as
   optional, hardware-conditional providers with CPU fallback. One API and one
   format do not remove hardware-specific native libraries: EP libraries are
   provisioned only on matching hardware.
3. **One format, not one file.** A model may need provider-specific ONNX
   variants (for example static-shape or QDQ statically quantized files for
   NPUs, compiled EP context caches). The model manifest lists them.
4. **Validation gate with kill criteria.** This decision is falsifiable. The
   ORT validation gate (implementation plan WP-0.6, priority zero) measures
   one representative model per role on T1 CPU-only and checks the kill
   criteria predeclared in
   [`../benchmarks/methodology.md`](../benchmarks/methodology.md) §8.7
   (budget miss, export failure of a clearly better model, no NPU reach,
   download size). If none fires, this ADR stands. If one fires, a challenger
   engine is measured **for that role only** (plan WP-2.3), and any change is
   recorded in an ADR that supersedes this one for that role.
5. The native OpenVINO API path from the PoC is removed unless the NPU bake-off
   (WP-5.2) shows a material, reproducible advantage over the OpenVINO EP.
6. Every model is described by a **model manifest** (ID, revision, task,
   dimensions and allowed truncations, max sequence length, pooling,
   normalization, query/passage prompts, tokenizer and padding, ONNX variants
   per precision and provider, license, hashes, parity vectors). The engine
   reads behavior from the manifest; nothing model-specific is hardcoded.
7. **One embedding vector space per index generation.** A model, revision,
   dimension, or embedding-input-recipe change creates a new index generation
   built in the background (blue/green); vectors are never mixed. Precision
   variants and providers of the same model share a generation only when they
   pass the vector-parity threshold.
8. Every exported or quantized artifact passes a parity test against the
   reference implementation before publication.
9. **Runtime-cost rule.** A component that cannot run well on ONNX Runtime is
   benchmarked with its **full deployment cost** (runtime bytes, model bytes
   per quantization, code and CI to maintain) and may bring a second engine
   only if it beats the best ONNX Runtime candidate by the predeclared
   new-engine margin (methodology §8.6), and only via a superseding ADR. Opt-in
   packs follow the same rule, and their engine never becomes a dependency of
   the default path.

## Consequences

- Bake-offs compare candidates **as deployed** on ONNX Runtime (format +
  quantized variant + execution provider), never as published.
- Exportability to ONNX with parity is an eligibility criterion for every model
  candidate; models available only in another format are priced under the
  runtime-cost rule.
- Autoregressive OCR transcription models (ADR-0021) run on plain ONNX Runtime
  as split graphs (vision encoder, decoder with KV cache) with a greedy decode
  loop in `seeky-infer`; this is the riskiest role and is part of the
  validation gate.
- `tools/model-export` owns ONNX export, quantization (fp16, int8 dynamic and
  static QDQ, int4 `MatMulNBits`), provider variants, and parity vectors;
  Python is allowed there and only there.
- Static embedders (lookup-table models) are implemented natively behind the
  `Embedder` trait if they win a bake-off; they need no engine.

## Alternatives considered

| Option | Why not chosen now |
|---|---|
| Open three-way engine bake-off (ORT vs llama.cpp vs OpenVINO) before deciding | Weeks of export and integration work to test alternatives unlikely to win; replaced by the validation gate, which measures challengers only where a kill criterion fires |
| llama.cpp/ggml (GGUF) | Runs encoders and decoders with strong weight-only quantization, but adds a second engine and has narrower NPU reach; challenger for a role only if a kill criterion fires |
| Native OpenVINO (IR) | Strong on Intel NPUs, but the OpenVINO EP reaches them without a second API; kept only if WP-5.2 shows an advantage |
| candle / burn / tract (pure Rust) | CPU kernels and NPU coverage not competitive with ORT for Seeky's roles today |
| Two or more engines in the default product | Multiplies binary size, code paths, test matrix, and security surface |
