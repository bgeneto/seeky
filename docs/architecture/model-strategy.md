# Model Strategy


Related: [Retrieval engine](retrieval-engine.md), [Distribution](distribution-and-provisioning.md)

## 1. Requirements

Seeky needs one embedding model and, once retrieval quality is enabled, one
multilingual reranker.

Mandatory requirements:

- **Multilingual** retrieval across user content languages, independent of UI
  language.
- Practical on CPU, not only on a high-end GPU.
- Accelerated on NVIDIA CUDA, AMD GPUs, and Intel NPUs where available.
- Permissive license compatible with an MIT open-source application and R2
  redistribution.
- ONNX and/or OpenVINO deployment path with quantization.
- Stable embedding dimension and tokenizer revision for index compatibility.
- Download and memory footprint appropriate for a slim desktop app.

No model is declared SOTA until it passes the retrieval evaluation gates on the
Seeky golden set.

## 2. Candidate embedding models

| Candidate | Dimensions | Multilingual | License | Role |
|---|---:|---|---|---|
| `gety-embed-v0` | 384 | Evaluate | MIT | Current compatibility baseline |
| `multilingual-e5-small` | 384 | Yes | MIT | CPU-first baseline candidate |
| `multilingual-e5-base` | 768 | Yes | MIT | Quality/CPU tradeoff |
| `BGE-M3` | 1024 | Yes | MIT | Strong multilingual dense/sparse baseline |
| `Qwen3-Embedding-0.6B` | 1024 | Yes | Apache-2.0 | Quality candidate; heavier CPU |
| `snowflake-arctic-embed-l-v2.0` | 1024 | Yes | Apache-2.0 | Alternative quality candidate |

Models with non-commercial, unclear, or incompatible redistribution terms are not
eligible, regardless of benchmark quality.

The final choice may differ by hardware profile only if the vector space remains
identical. Do not mix different embedding models in one index.

## 3. Candidate rerankers

| Candidate | Multilingual | License | Role |
|---|---|---|---|
| `Qwen3-Reranker-0.6B` | Yes | Apache-2.0 | Primary quality candidate |
| `bge-reranker-v2-m3` | Yes | Apache-2.0 (verify) | Alternative/benchmark candidate |

Reranking is optional at runtime and disabled if the model is unavailable or the
latency gate is missed. RRF results remain the fallback.

## 4. Backend strategy

| Hardware | Primary runtime | Artifact |
|---|---|---|
| CPU | ONNX Runtime | int8/uint8 ONNX |
| NVIDIA GPU | ONNX Runtime CUDA EP | FP16 ONNX |
| AMD GPU (Windows) | ONNX Runtime DirectML EP | ONNX; provider-specific validation |
| AMD GPU (Linux, optional) | ONNX Runtime ROCm EP | ONNX; research path |
| Intel NPU | OpenVINO | OpenVINO IR |
| Intel GPU | OpenVINO or DirectML | Benchmark decision |
| AMD NPU | Vendor runtime | Research only; not promised |

Rules:

- CPU is always a supported fallback.
- Auto mode selects the fastest validated accelerator, then falls back to CPU.
- Backend availability must reflect runtime and hardware, not only model files.
- A backend switch must not require reindexing for the same embedding model.
- Execution-provider failures produce actionable diagnostics and fallback.
- DirectML and ROCm support are accepted only after real-device validation.

## 5. Quantization policy

- CPU: int8/uint8 preferred when nDCG loss is under the gate.
- CUDA: FP16 preferred; int8 only if quality and speed justify it.
- OpenVINO NPU: use the vendor-supported precision and validate the 256/512-token
  shape constraints.
- DirectML: start with FP16/FP32 per provider support; benchmark.
- Store the quantization variant in the model ID and manifest.
- Re-run multilingual retrieval evaluation for every quantized artifact.

## 6. Selection process

1. Build the multilingual golden set.
2. Measure lexical-only and current-model baselines.
3. Evaluate each embedding candidate with the same chunking and retrieval depth.
4. Shortlist models that meet quality thresholds.
5. Benchmark CPU, CUDA, DirectML/AMD, and NPU latency and memory.
6. Measure indexing throughput and query latency separately; a model can be good
   at batch indexing and poor at single-query latency.
7. Evaluate storage cost at 100k chunks.
8. Select the smallest model that meets the quality gate, or the best quality
   model that meets the latency/memory budget.
9. Re-index and re-run the golden set with the selected model.
10. Record the decision in `docs/audits/evaluations/` and an ADR.

## 7. Quality gates

Initial gates for a production embedding model:

- Document Recall@10 at least equal to the current baseline on every language
  slice.
- nDCG@10 improves by at least 3 points over the baseline, or latency/memory
  improves materially at equal quality.
- No language slice drops by more than 2 points.
- CPU warm search p95 within the plan budget at 100k chunks.
- GPU/NPU warm search p95 within budget.
- Model license reviewed and distribution permitted.
- ONNX/OpenVINO export parity verified against the reference model.

Reranker gate:

- +5 nDCG@10 over the selected embedding pipeline.
- Passage Recall@10 does not regress.
- p95 latency remains within budget.
- Failure to load does not break search.

## 8. Index compatibility

Changing the embedding model or dimension requires:

- a new index format/version;
- a full reindex (or a dual-index migration);
- a UI explanation if storage is significant;
- no silent mixing of old and new vectors.

The first-run provisioner must know which embedding model the current database
expects. If the required model is unavailable, search must fail with an
actionable error rather than returning misleading results.

## 9. Tokenization and chunking

- Tokenizer revision is part of the model asset.
- Chunk sizes are tuned per model context window and retrieval evaluation.
- The NPU bucket size (for example 256 tokens) must not silently truncate most
  chunks; either resize chunks or reject the NPU profile for that model.
- Multilingual tokenizers must be tested on CJK, Cyrillic, Arabic, accented
  Latin, and mixed-language text.

## 10. Storage and download budget

- 384-d f32 vectors: ~1.5 KB/chunk.
- 768-d f32 vectors: ~3 KB/chunk.
- 1024-d f32 vectors: ~4 KB/chunk.
- Quantized storage is an option only after measuring recall.
- Model download size is a product metric and must be shown during provisioning.
- The installer remains slim; models are cached under the app data directory.

## 11. Open decisions

- Final embedding model and dimension.
- Whether reranking is CPU-only initially or enabled on all validated backends.
- DirectML versus ROCm as the AMD Windows/Linux path.
- FP16 versus int8 for each backend.
- Whether a lightweight sparse/lexical model is needed in addition to FTS5.
- How to represent model upgrades without a full reindex.

These decisions are resolved only by the evaluation harness and recorded in
`docs/audits/evaluations/`.
