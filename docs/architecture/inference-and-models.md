# Inference and Models

| Field | Value |
|---|---|
| Status | Accepted target contract |
| Date | 2026-11-27 (v2; replaces `model-strategy.md`) |
| Governs | Inference runtime, execution providers, model manifest, model lifecycle, quantization |
| Related | [ADR-0016](../adr/0016-cpu-first-npu-ready-execution.md), [ADR-0019](../adr/0019-single-inference-engine.md), [candidates](../benchmarks/candidates.md), [methodology](../benchmarks/methodology.md) |

Candidate models and their license status live in
[`../benchmarks/candidates.md`](../benchmarks/candidates.md). This document
defines **how** models run, not **which** ones win.

## 1. Neural components

| Component | Trait (`seeky-core`) | Required for | Default state |
|---|---|---|---|
| Embedding model | `Embedder` | Semantic retrieval | On after provisioning |
| Reranker | `Reranker` | Refined stage | On if it passes its gate on CPU; otherwise NPU-only or off |
| Snippet scorer (pruner slot) | `SnippetScorer` | Snippet quality | Heuristic baseline; model only if a bake-off wins |
| OCR (detection + recognition pipeline, or a transcription model under [ADR-0021](../adr/0021-no-generative-models-in-product.md)) | `OcrEngine` | Scanned PDFs/images | Optional asset pack (CPU); GPU pack only if justified |
| Learned sparse encoder | `SparseEncoder` | Gated retriever | Off unless it wins its bake-off |
| Language identifier | `LanguageId` | Analyzers, slices | Native Rust library (no neural runtime needed) |

## 2. Runtime

- **ONNX Runtime** is the single inference engine for all neural components,
  through the `ort` crate with dynamic loading; the ORT library is a
  provisioned asset ([ADR-0019](../adr/0019-single-inference-engine.md)). One
  inference API, one model format, independent sessions per model and
  workload, optional execution providers, CPU fallback. A priority-zero gate
  with predeclared kill criteria validates the decision (plan WP-0.6).
- **One format, not one file:** NPU providers may need their own ONNX variants
  (static shapes, static QDQ quantization, compiled EP context caches), listed
  in the manifest.
- OCR transcription models run as split ONNX graphs (vision encoder, decoder
  with KV cache) with a greedy decode loop in `seeky-infer`.
- **Separate sessions per workload**: a latency session (batch 1, all physical
  cores, high priority) for queries; a throughput session (dynamic batches,
  capped threads, background priority) for indexing.
- Graph optimizations enabled; optimized model caches written to the asset cache.
- Tokenization with Hugging Face `tokenizers` (Rust), driven by the manifest
  (padding side and id, truncation, special tokens, prompts).
- Static embedders (lookup-table models), if selected, run natively in Rust
  behind the same `Embedder` trait.

## 3. Execution providers (CPU-first, NPU-ready)

| Hardware | Provider | Status | Notes |
|---|---|---|---|
| x86-64 CPU (AVX2, AVX-512/VNNI, AMX) | CPU (MLAS) | **Primary** | int8 dynamic quantization preferred when parity holds |
| ARM64 CPU (NEON, dotprod/i8mm) | CPU (MLAS) | **Primary** | Windows on ARM, Apple Silicon, Linux ARM |
| Intel NPU | OpenVINO EP | NPU target | Static shapes; compiled blob cache; PoC native OpenVINO path kept only if it wins the bake-off |
| Qualcomm Hexagon NPU | QNN EP | NPU target | Snapdragon X; quantized (QDQ) models |
| AMD XDNA NPU | VitisAI EP | NPU target | Ryzen AI; quantized models |
| Apple Neural Engine | CoreML EP | NPU target | macOS |
| Windows ML-managed EPs | Windows ML | Candidate | May supply OpenVINO/QNN/VitisAI EPs system-wide on Windows 11; evaluated in the NPU bake-off |
| GPUs (CUDA, DirectML, ROCm, Metal, Vulkan) | — | Not shipped by default | Opt-in pack only when a bake-off justifies it (for example GPU OCR), never a dependency of the default path ([ADR-0016](../adr/0016-cpu-first-npu-ready-execution.md)) |

Selection policy:

1. Detect hardware and installed drivers; load only validated providers.
2. Run the model's **parity vectors** on first load of each provider; a provider
   whose outputs deviate beyond tolerance is disabled for that model.
3. Pick the fastest validated provider **per workload** (query latency vs
   indexing throughput can differ — an NPU may win throughput per watt while
   the CPU wins batch-1 latency).
4. Any failure falls back to CPU with an actionable diagnostic; search never
   breaks because an accelerator fails.

NPU specifics: sequence-length buckets (for example 64/128/256/512) instead of
dynamic shapes; chunker must not silently truncate most passages to fit a
bucket; compiled-model caching so the first-load compile (tens of seconds in the
PoC) happens once per model revision.

## 4. Model manifest

Every model asset ships a manifest entry; the engine reads behavior from it and
hardcodes nothing (the PoC's `DIM = 384`, Gety paths, and tensor names are
removed).

```toml
id          = "embed/<family>/<variant>"
revision    = "<upstream commit or version>"
task        = "embedding"            # embedding | rerank | sparse | ocr-det | ocr-rec | ocr-transcribe | snippet
license     = "Apache-2.0"
languages   = ["multilingual"]

[tokenizer]
files        = ["tokenizer.json"]
padding_side = "right"
pad_id       = 1
max_tokens   = 512

[io]
inputs         = ["input_ids", "attention_mask"]
output         = "sentence_embedding"
pooling        = "in-graph"          # cls | mean | last-token | in-graph
normalize      = true
dimension      = 768
truncatable_to = [512, 256, 128]     # Matryoshka dimensions, if supported

[prompts]
query   = "query: "
passage = "passage: "

[[variants]]                          # one per precision/provider family
precision = "int8"
providers = ["cpu"]
file      = "model_int8.onnx"
sha256    = "…"

[parity]
vectors   = "parity.jsonl"            # inputs → reference outputs
tolerance = 0.01                      # cosine distance or logit delta
```

## 5. Model lifecycle

1. **Candidate** — listed in `candidates.md` with license status.
2. **Screened** — Stage A of the model bake-off protocol: quality in the
   reference runtime on the screening set
   ([methodology §8](../benchmarks/methodology.md)).
3. **Exported** — `tools/model-export` produces ONNX variants (fp32
   reference, fp16, int8 dynamic/QDQ, int4, provider-specific), parity
   vectors, and the manifest entry.
4. **Benchmarked** — Stage B/C: deployment variants measured with
   `seeky-bench`; report committed.
5. **Selected** — ADR records the decision and the decision rule outcome.
6. **Published** — assets and notices uploaded to R2 under immutable keys;
   manifest updated.
7. **Active** — engine builds a new index generation (blue/green) when the
   embedding recipe changes; rerankers/snippet scorers swap without reindexing.
8. **Retired** — old generation garbage-collected after promotion.

## 6. Quantization policy

- Reference: fp32 (or the upstream reference precision); every quantized
  variant is compared to it on the same inputs.
- Matrix per finalist: fp16, int8 (dynamic, static QDQ, or weight-only), int4
  weight-only (`MatMulNBits`, mainly for decoders). Calibration data comes from
  the `dev` split only.
- Selection: the smallest variant whose loss versus the reference stays inside
  the tolerance in [methodology §8.4](../benchmarks/methodology.md); quantization
  usually shrinks the download and speeds CPU inference, but the gain is
  measured per CPU tier, never assumed.
- NPU: provider-supported precision (int8/QDQ, fp16 where supported).
- Vector storage quantization (int8, binary) is a separate decision owned by
  the vector-store bake-off, measured end-to-end with rescoring.
- Quantization variant is part of the asset ID; the embedding precision used at
  index time is part of the generation recipe.

## 7. Index compatibility

- One embedding model, revision, dimension, and input recipe per index
  generation; never mix vectors.
- The provisioner knows which generation recipe the database expects; if its
  model is missing, the semantic lane pauses with a repair action while lexical
  search continues ([ADR-0018](../adr/0018-lexical-first-availability.md)).
- Changing the reranker, snippet scorer, or OCR engine never requires
  re-embedding (OCR changes re-extract affected files only).

## 8. Storage and download arithmetic

| Configuration | Bytes per passage (vector only) | 1M passages |
|---|---:|---:|
| 1024-d f32 | 4,096 | 4.1 GB |
| 768-d f32 | 3,072 | 3.1 GB |
| 384-d f32 | 1,536 | 1.5 GB |
| 768-d int8 | 768 | 0.77 GB |
| 256-d int8 (Matryoshka) | 256 | 0.26 GB |
| 768-d binary | 96 | 0.10 GB |
| 256-d binary | 32 | 0.03 GB |

Excludes ANN overhead, text, lexical index, and metadata. A binary first pass
with int8/f32 rescoring is a leading candidate for CPU-first scale; the
vector-store bake-off decides.
