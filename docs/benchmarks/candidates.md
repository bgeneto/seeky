# Candidate Registry

| Field | Value |
|---|---|
| Status | Living document — refreshed at the start of every bake-off |
| Last refresh | 2026-11-27 |
| Related | [methodology](methodology.md), [ADR-0022](../adr/0022-permissive-license-gate.md), [inference-and-models](../architecture/inference-and-models.md) |

This registry seeds the bake-offs. It is **not** a ranking. Facts marked
*(verify)* must be confirmed from the primary source (model card, license file,
repository) when the bake-off starts; the first task of each bake-off is to
refresh this list with newly released candidates.

Legend — **Role:** `selected` (current decision, validated by a gate),
`baseline` (reference point), `challenger` (shippable if it wins), `probe`
(measured to learn a limit, not expected to ship), `conditional` (enters only if
a stated condition holds), `ceiling` (quality upper bound; too heavy for the
CPU budget, run offline only), `excluded`. **License:** `eligible`, `review`,
`ineligible`.

Candidates are compared as deployed on ONNX Runtime (ONNX variant +
quantization + provider, [ADR-0019](../adr/0019-single-inference-engine.md)),
following the funnel in [methodology §8](methodology.md). During Stage 0,
record every published format and whether an ONNX export path exists:
running on ONNX Runtime with parity is an eligibility criterion; a model that
cannot is priced under the ADR-0019 runtime-cost rule.

## 1. Embedding models

| Candidate | Size | Dims | License | Role | Notes |
|---|---|---|---|---|---|
| `gety-embed-v0` | 118M (e5-small finetune) | 384 | MIT | baseline | PoC model; CPU/NPU artifacts exist |
| `intfloat/multilingual-e5-small` | 118M (471 MB fp32) | 384 | MIT | baseline; **WP-0.6 proxy** | Prefix-sensitive (`query:`/`passage:`); official ONNX fp32/O4/int8 files verified at revision `614241f` on 2026-11-27 |
| `ibm-granite/granite-embedding-97m-multilingual-r2` | 97M (195 MB BF16) | 384 | Apache-2.0 | challenger; **WP-0.6 ModernBERT proxy** | ModernBERT, 32k context, released 2026-04; official ONNX fp32/int8 and OpenVINO exports verified at revision `835ad14` on 2026-11-27; pt explicitly supported |
| `hotchpotch/bekko-embedding-v1-a25m` | ~25M active | 384 (MRL 256/128/64) | MIT | challenger | 2026; ultra-compact; architecture and ONNX export *(verify)* |
| `hotchpotch/bekko-embedding-v1-a8m` | ~8M active | 384 (MRL) | MIT | challenger | T0-tier candidate; language coverage for pt *(verify)* |
| `Snowflake/snowflake-arctic-embed-m-v2.0` | 305M | 768 (MRL 256) | Apache-2.0 | challenger | Strong multilingual retrieval; heavier on CPU |
| `Alibaba-NLP/gte-multilingual-base` | 305M | 768 (elastic) | Apache-2.0 | challenger | Custom architecture; export path *(verify)* |
| `ibm-granite/granite-embedding-278m-multilingual` | 278M | 768 | Apache-2.0 | challenger | r1 family; check for r2 siblings *(verify)* |
| `intfloat/multilingual-e5-base` | 278M | 768 | MIT | challenger | Classic quality/CPU trade-off |
| `google/embeddinggemma-300m` | 308M | 768 (MRL 512/256/128) | Gemma Terms | challenger | **License review** (use policy pass-through) |
| `google/embeddinggemma-2` (text component) | 270M (130M backbone + 140M embedder) | 768 (MRL 512/256/128) | Apache-2.0 + Gemma Prohibited Use Policy | challenger | Released 2026-10-06. Text component of a multimodal model: competes on text merit, image capability only as the ADR-0023 tie-breaker (methodology §7). ONNX text graph 314 MB (q8) / 175 MB (q4) vs D2 *(vendor)*; model card warns against fp16 inference; **license review** (use policy pass-through). See §14 |
| `nomic-ai/nomic-embed-text-v2-moe` | 475M total / 305M active | 768 (MRL 256) | Apache-2.0 | challenger | MoE export/runtime cost *(verify)* |
| `minishlab/potion-multilingual-128M` | static | 256 | MIT | challenger | Static (lookup) embedder; native Rust; T0 tier or instant-semantic experiments |
| `BAAI/bge-m3` | 568M | 1024 (+ sparse, multi-vector) | MIT | ceiling | Offline quality reference |
| `Qwen/Qwen3-Embedding-0.6B` | 0.6B | 1024 (MRL) | Apache-2.0 | ceiling | Decoder; far beyond CPU indexing budget. Large decoders are ceilings, not shipped defaults ([ADR-0016](../adr/0016-cpu-first-npu-ready-execution.md)); a GPU opt-in tier would need its own ADR. As-deployed ONNX export below |
| `n24q02m/Qwen3-Embedding-0.6B-ONNX` | 0.6B | 1024 (MRL) | Apache-2.0 | ceiling (as-deployed variant of the row above) | Third-party ONNX export, opset 21, rev `dc873d6`: int8 dynamic (`quantize_dynamic` QInt8) 572 MB; q4f16 (`MatMulNBits` int4, block 128, symmetric, fp16 activations) 517 MB. Query instruction prefix required. Parity vs upstream fp32 not yet checked; q4f16 is GPU-oriented (fp16 activations) |
| `Snowflake/snowflake-arctic-embed-l-v2.0` | 568M | 1024 | Apache-2.0 | ceiling | Offline reference |
| `jinaai/jina-embeddings-v3` / `v4` / `v5-text-*` | — | — | CC-BY-NC (and variants) | excluded | Non-commercial license |
| `jinaai/jina-embeddings-v5-text-nano` (and `-retrieval`) | 239M (EuroBERT-210M) | 768 (MRL down to 32) | CC-BY-NC-4.0 → ineligible | excluded | Checked 2026-11-27. Technically attractive: 32k context, distilled from Qwen3-Embedding-4B, vendor-reported MMTEB 65.5, robust to binary quantization, official ONNX in the `-retrieval` repo (fp32, fp16, int8, q4, q4f16). Excluded regardless of quality under [ADR-0022](../adr/0022-permissive-license-gate.md); commercial terms are only available from Jina on request |
| `Qwen3-Embedding-4B` / `8B` | 4B / 8B | — | Apache-2.0 | excluded | GPU-class; violates CPU-first |

## 2. Rerankers (cross-encoders)

| Candidate | Size | License | Role | Notes |
|---|---|---|---|---|
| `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | 118M | Apache-2.0 weights; trained on mMARCO | baseline | Fast multilingual baseline; **training-data license review** |
| `Alibaba-NLP/gte-multilingual-reranker-base` | 306M (612 MB fp16) | Apache-2.0 | challenger; **WP-0.6 proxy** | Native `transformers>=5.18` sequence-classification export path verified at revision `9ba3cad` on 2026-11-27; no official ONNX file, so Optimum/`torch.onnx.export` required; pt explicitly supported |
| `agentic-in/elephant-rerank-v1-text-small` | small (ModernBERT) | Apache-2.0 | challenger | 2026; custom heads/loader — export risk *(verify)* |
| `BAAI/bge-reranker-v2-m3` | 568M | Apache-2.0 | challenger (NPU) / ceiling | Likely NPU-only on budget; community int8 ONNX exists |
| `mixedbread-ai/mxbai-rerank-base-v2` | 0.5B | Apache-2.0 | ceiling | Decoder-based |
| `Qwen/Qwen3-Reranker-0.6B` | 0.6B | Apache-2.0 | ceiling | Decoder-based; offline reference. As-deployed ONNX export below |
| `n24q02m/Qwen3-Reranker-0.6B-ONNX` | 0.6B | Apache-2.0 | ceiling (as-deployed variant of the row above) | Third-party ONNX export, opset 21, rev `342a8a5`: int8 dynamic 573 MB, q4f16 517 MB, and "yes/no" variants that output only the two scoring logits of the last token (int8 572 MB; a q4f16 yes/no file is listed in the card but absent from the repository at that revision). Pointwise prompt template; parity vs upstream not yet checked |
| Seeky-distilled small reranker | — | MIT (ours) | post-1.0 R&D | Only if no candidate meets Q6 on CPU |
| `jinaai/jina-reranker-v2-*` / `v3` | — | CC-BY-NC | excluded | Non-commercial |

Sources checked 2026-11-27 for the Qwen3 ONNX exports (§1, §2) and
jina-embeddings-v5-text-nano (§1): the Hugging Face model cards and file
listings of
[n24q02m/Qwen3-Embedding-0.6B-ONNX](https://huggingface.co/n24q02m/Qwen3-Embedding-0.6B-ONNX),
[n24q02m/Qwen3-Reranker-0.6B-ONNX](https://huggingface.co/n24q02m/Qwen3-Reranker-0.6B-ONNX),
[jinaai/jina-embeddings-v5-text-nano](https://huggingface.co/jinaai/jina-embeddings-v5-text-nano),
and its `-retrieval` repository. Third-party exports inherit the upstream
license but must pass the manifest parity check against the upstream fp32
model before any result counts.

## 3. Snippet scorers (search-engine "pruner" slot)

| Candidate | License | Role | Notes |
|---|---|---|---|
| Heuristic (lexical overlap, position, sentence quality) | MIT (ours) | baseline | Zero model cost |
| Bi-encoder sentence similarity (active embedder) | inherits | challenger | Visible results only |
| Cross-encoder sentence scoring (active reranker) | inherits | challenger | Visible results only; budget S3 |
| `naver/provence-*`, XProvence | CC-BY-NC | excluded | Non-commercial; LLM-context pruners |

## 4. Learned sparse retrieval (gated)

| Candidate | License | Role | Notes |
|---|---|---|---|
| OpenSearch multilingual neural-sparse document encoder (inference-free query side) | Apache-2.0 *(verify name/revision)* | challenger | Query cost ≈ tokenizer lookup; needs weighted-term index support |
| `BAAI/bge-m3` sparse head | MIT | ceiling | Reference |
| SPLADE v3 family | CC-BY-NC-SA | excluded | License; English-centric |

## 5. OCR

Two tiers are decided separately: the **CPU default tier** (must meet budgets
O1–O4) and an optional **GPU opt-in pack** (must clear the new-engine/OCR
margin over the CPU tier, [ADR-0016](../adr/0016-cpu-first-npu-ready-execution.md)).
Transcription VLMs are eligible only under the
[ADR-0021](../adr/0021-no-generative-models-in-product.md) transcription rule
(deterministic decoding, fixed prompt, hallucination gate). Vendor benchmark
claims are self-reported until reproduced in Stage A.

Priority follows fit with ONNX Runtime: (1) detection + recognition pipelines
and small encoder-decoders already in ONNX, plus OS-native OCR (no engine to
ship); (2) transcription VLMs, only if they export to ONNX and run with parity
as split graphs; (3) models with their own engine (Tesseract, `ocrs`/RTen) or
available only in GGUF, priced under the runtime-cost rule.

| Candidate | Type | Size | License | Tier / role | Formats and engine paths | Notes |
|---|---|---|---|---|---|---|
| PP-OCRv5 mobile det + rec / PP-OCRv6 rec via `oar-ocr` | det + rec | v5 det 4.7 MB + Latin rec 14 MB; v6 rec tiny/small/medium 4.4/20.4/73.3 MB | Apache-2.0 (verified) | CPU: baseline; **WP-0.6 proxy** | Official Paddle inference → `paddle2onnx` / ONNX; `oar-ocr` 0.11 runs PP-OCRv4–v6 on ONNX Runtime | Latin incl. pt; sizes and export path verified on 2026-11-27 |
| Windows.Media.Ocr | OS-native | 0 MB | OS component | CPU: challenger | OS API (no engine to ship) | Windows only; language packs |
| Apple Vision text recognition | OS-native | 0 MB | OS component | CPU: challenger | OS API (no engine to ship) | macOS only |
| Tesseract 5 | det + rec (LSTM) | small | Apache-2.0 | CPU: challenger | Own engine (C/C++ library); priced under the runtime-cost rule | Broad languages |
| `ocrs` | det + rec | small | MIT / Apache-2.0 | CPU: challenger | Own pure-Rust engine (RTen); priced under the runtime-cost rule | Latin scripts |
| LlamaIndex **OCRia-1 / OCRia-nano-1** | transcription VLM / det + rec + layout | OCRia-1: 5.175B checkpoint (vendor calls it 4B), 10.35 GB BF16; nano: 8.1M, 48.3 MB ONNX | Custom OCRia Model and Code License — **ineligible** | **excluded** (research evaluation only) | OCRia-1: BF16 + GGUF, no official ONNX found; nano: published split ONNX | Exact names and revisions verified on 2026-11-27; **no public OCRia-1.5 weight repository found**. Revenue/funding limits and the competing OCR/product restriction are incompatible with ADR-0022 |
| OpenBMB **MiniCPM-OCR 1.0** | transcription VLM | 1.300B; 2.60 GB BF16 | Apache-2.0 (verified model card + source LICENSE) | GPU pack: challenger; CPU: int4 probe | BF16; official GGUF/AWQ/GPTQ; no official ONNX found, so split export is unverified | Revision `883ca36`, checked 2026-11-27; card declares en/zh, so pt coverage remains an eligibility check |
| SoMark **OXR-1.0** | document parser VLM (Markdown/JSON + layout) | 1.534B checkpoint (vendor calls it 1.3B); 3.07 GB BF16 + 78.8 MB layout | OXR License (Apache-2.0 + commercial/use restrictions) — **ineligible** | **excluded** | BF16 + custom vLLM plugin; no official ONNX export found | Revision `c708407`, checked 2026-11-27; guide requires 24 GB VRAM to start and recommends ≥48 GB; license has revenue/funding and competing hosted-API restrictions |
| PaddleOCR-VL / 1.5 | transcription VLM | 0.959B; 1.917 GB BF16 (both v1 and v1.5) | Apache-2.0 (verified LICENSE) | GPU pack: challenger; CPU: int4 probe | Paddle/safetensors + Transformers; community split-graph ONNX with int4 exists for 1.5; official ONNX not found | Revisions `dae2996` / `1e52160`, checked 2026-11-27; 109-language claim includes multilingual coverage; export parity still requires measurement |
| Florence-2 base / large | encoder-decoder transcription VLM | 0.232B / 0.777B | MIT (verified LICENSE) | CPU: challenger; **large is WP-0.6 ~1B-class proxy** | Official safetensors; `onnx-community` split graphs for base/large (fp32/fp16/int8/q4) verified | Revisions `5ca5edf` / `21a599d`, checked 2026-11-27; OCR task only under ADR-0021; card does not declare pt, so diacritic coverage remains an eligibility check |
| DeepSeek-OCR, dots.ocr | VLM | DeepSeek: 3.336B / 6.67 GB BF16; dots: 3.039B / 6.08 GB BF16 | DeepSeek: MIT (verified LICENSE); dots: MIT + supplemental use policy — **review** | ceiling | Custom Transformers/vLLM reference runtimes; no official ONNX found; split export unverified | Revisions `9f30c71` / `c0111ce`, checked 2026-11-27; GPU quality reference; dots is not license-Allowed for the WP-0.6 portfolio |
| olmOCR-7B-0825 | VLM | 8.292B checkpoint (product name 7B); 16.58 GB BF16 | Apache-2.0 (model card; responsible-use guidance linked) | ceiling | Qwen2.5-VL safetensors via olmOCR/sglang; no official ONNX found | Revision `f146341`, checked 2026-11-27; English card; GPU-class offline reference only |
| `gety-ocr-v0` | — | — | proprietary, encrypted | excluded | — | Not usable or redistributable |

Stage 0 primary-source evidence, checked 2026-11-27 (sizes use decimal MB/GB;
parameter counts and file bytes come from the linked repositories and Hugging
Face `?blobs=true` metadata):

- PP-OCR: [official model list](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/model_list.md),
  [Paddle2ONNX deployment guide](https://github.com/PaddlePaddle/PaddleOCR/blob/main/deploy/paddle2onnx/readme.md),
  [Apache-2.0 LICENSE](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE),
  and [`oar-ocr` supported families](https://docs.rs/crate/oar-ocr/latest).
- OCRia: [OCRia-1 card and LICENSE](https://huggingface.co/llamaindex/OCRia-1),
  [OCRia-nano-1 card and LICENSE](https://huggingface.co/llamaindex/OCRia-nano-1),
  and the [LlamaIndex public model listing](https://huggingface.co/api/models?author=llamaindex&search=OCRia&limit=100).
- MiniCPM-OCR: [weight repository/card](https://huggingface.co/openbmb/MiniCPM-OCR-1.0)
  and [source LICENSE](https://github.com/OpenBMB/MiniCPM-OCR/blob/main/LICENSE).
- OXR: [weight repository/card](https://huggingface.co/SoMarkAI/OXR-1.0) and its
  [custom LICENSE](https://huggingface.co/SoMarkAI/OXR-1.0/blob/main/LICENSE).
- PaddleOCR-VL: [v1 card/LICENSE](https://huggingface.co/PaddlePaddle/PaddleOCR-VL),
  [v1.5 card/LICENSE](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.5), and the
  [community 1.5 split ONNX conversion](https://huggingface.co/lbm364dl/PaddleOCR-VL-1.5-ONNX).
- Florence-2: [base](https://huggingface.co/microsoft/Florence-2-base),
  [large](https://huggingface.co/microsoft/Florence-2-large), and their
  [base](https://huggingface.co/onnx-community/Florence-2-base) /
  [large](https://huggingface.co/onnx-community/Florence-2-large) ONNX conversions.
- DeepSeek-OCR: [card and MIT LICENSE](https://huggingface.co/deepseek-ai/DeepSeek-OCR);
  dots.ocr: [card](https://huggingface.co/dots-studio/dots.ocr) and
  [supplemental agreement](https://huggingface.co/dots-studio/dots.ocr/blob/main/dots.ocr%20LICENSE%20AGREEMENT);
  olmOCR: [7B-0825 card and license statement](https://huggingface.co/allenai/olmOCR-7B-0825).

## 6. Extractors

| Format | Baseline (as built) | Challengers | Excluded |
|---|---|---|---|
| PDF | PDFium via `pdfium-render` | `lopdf`/`pdf-extract` (speed), other pure-Rust parsers *(verify)* | MuPDF (AGPL) |
| DOCX / PPTX | zip + XML (custom) | `docx-rs`, `kreuzberg` core *(verify license)* | Apache Tika (JVM) |
| XLSX / ODS | `calamine` | — | — |
| ODT, RTF, EPUB, EML/MBOX, HTML | — (to add) | `quick-xml`, `mail-parser`, `html5ever`/`scraper` class | — |

## 7. Lexical engines and analyzers

| Candidate | License | Role | Notes |
|---|---|---|---|
| SQLite FTS5 `unicode61 remove_diacritics 2` | Public domain | baseline | As built; transactional with metadata |
| SQLite FTS5 trigram tokenizer | Public domain | challenger | Substring/identifier matching |
| Tantivy with per-language analyzers (Snowball pt/en, ASCII folding) | MIT | challenger | Segment-based, mmap, fast; separate index files |
| Stemming / stopwords on vs off per language | — | ablation | Portuguese morphology likely benefits *(measure)* |

## 8. Filename/path index

| Candidate | License | Role |
|---|---|---|
| Lexical-engine field (FTS5/Tantivy) | — | baseline |
| `fst` (prefix + Levenshtein automata) | MIT/Unlicense | challenger |
| Trigram/n-gram inverted index (in-memory) | ours | challenger |
| Fuzzy matcher over an in-memory path table (nucleo class) | MPL-2.0 *(verify)* | challenger |

## 9. Vector stores and quantization

| Candidate | License | Role | Notes |
|---|---|---|---|
| Exact f32 scan over SQLite BLOBs | — | baseline | As built; loads all vectors per query |
| Flat memory-mapped int8 scan + f32 rescoring (SIMD) | ours | challenger | Trivial updates; no graph maintenance |
| Binary (1-bit) Hamming first pass + int8/f32 rescoring | ours | challenger | Leading CPU-first candidate at 1M passages |
| USearch HNSW (f16/i8/b1) | Apache-2.0 | challenger | ANN for L-scale; mmap views; predicate filtering |
| sqlite-vec | MIT/Apache-2.0 | challenger | Single-file simplicity |
| LanceDB (embedded) | Apache-2.0 | conditional | Only if lighter options miss budget (dependency weight, binary size) |
| Qdrant/Milvus/pgvector servers, FAISS | — | excluded | Server processes or heavy native deps with no benefit at target scale |
| `memista` | GPL-3.0 | excluded | License |

Matryoshka truncation (for example 768 → 256) is evaluated jointly with
quantization.

## 10. Fusion

| Candidate | Role |
|---|---|
| RRF, `k = 60` | baseline |
| RRF `k ∈ {10, 30, 100}`, weighted RRF | challenger |
| Convex combination of normalized scores (min-max, z-score) | challenger |
| Query-class-specific weights (router) | challenger |
| Gety-style fixed raw-score weights (0.2/0.8) | reference only |

## 11. Chunking

| Candidate | Role |
|---|---|
| 1,200 characters / 200 overlap (as built) | baseline |
| Token windows 128 / 256 / 384 × overlap 0 / 32 / 64 | challenger grid |
| Structure-aware (headings, paragraphs, pages, slides, sheets, code blocks) | challenger |
| + in-document heading path as contextual header (never the filename) | ablation |

## 12. Supporting libraries

| Need | Baseline | Challengers |
|---|---|---|
| Language ID | — | `whatlang` (MIT), `lingua` (Apache-2.0) |
| Sentence segmentation | — | `unicode-segmentation`, ICU4X segmenter (Unicode-3.0) |
| Directory walk | `walkdir` | `ignore` (parallel), `jwalk` |
| Change detection | `notify` | Windows USN journal, macOS FSEvents replay |
| Hashing | `blake3` | — |
| Near-duplicate signatures | — | SimHash, MinHash-LSH (ours or permissive crates) |
| Tokenizers | `tokenizers` (Apache-2.0) | — |

## 13. Inference engines

ONNX Runtime is the single inference engine ([ADR-0019](../adr/0019-single-inference-engine.md)),
validated by the gate in [methodology §8.7](methodology.md). The others are
measured only for a role where a kill criterion fires (plan WP-2.3). Every
engine below can run encoders (embedders, cross-encoder rerankers) and
decoders; the file format does not imply a generative model.

| Candidate | Format | License | Role | Notes |
|---|---|---|---|---|
| ONNX Runtime (`ort` crate) | ONNX | MIT | selected | Runs the PoC; execution providers for Intel (OpenVINO), Qualcomm (QNN), AMD (VitisAI), Apple (CoreML) NPUs; int8/QDQ and int4 `MatMulNBits` |
| llama.cpp / ggml | GGUF | MIT | conditional (WP-2.3) | Compact CPU build; k-quants; encoder embeddings and reranking; multimodal projectors for VLMs; Rust bindings and NPU backends *(verify maturity)* |
| OpenVINO (native API) | OpenVINO IR (reads ONNX too) | Apache-2.0 | conditional (WP-2.3, WP-5.2) | Converts PyTorch/ONNX/TF/Paddle to IR; NNCF int8/int4; CPU plugin on x86-64 and ARM64; strongest on Intel NPU; GenAI pipelines for VLMs *(verify per model)* |
| candle / burn / tract | safetensors / ONNX | MIT / Apache-2.0 | conditional | Joins only if CPU kernels and NPU coverage qualify at Stage 0 |
| vLLM, MLX, TensorRT | various | various | excluded (default path) | Server-, GPU-, or platform-specific; may be priced only for a GPU opt-in pack |

## 14. Visual and multimodal embedders (optional visual pack)

Seeds the visual bake-off (plan Phase 10,
[methodology §8.9](methodology.md)) under
[ADR-0023](../adr/0023-multimodal-ready-engine.md). Configurations compared:
**A** text-only (no pack), **B** unified (one space for text and images),
**C** specialized (default text embedder + a separate visual channel).
Only non-generative embedding encoders are eligible; models that generate
captions or descriptions are excluded by
[ADR-0021](../adr/0021-no-generative-models-in-product.md). All figures are
vendor-reported until reproduced in Stage A; no candidate publishes
Portuguese text-to-image results.

| Candidate | Type | Size | Text context | License | Role | Notes |
|---|---|---|---|---|---|---|
| `google/embeddinggemma-2` (text + vision components) | Unified; images enter the shared backbone as soft tokens | Text 270M, vision 170M (audio 300M, not used). ONNX q8: text 314 MB, vision 195 MB; q4: 175 / 109 MB | 8,192 (shared with image tokens) | Apache-2.0 + Gemma Prohibited Use Policy → **review** | challenger (B; also a §1 text candidate) | 768-d, MRL 512/256/128 (vendor: "close to lossless" to 256; 128 degrades multimodal quality). Visual token budget 70–1120, default 280: an image costs the vision encoder plus the backbone over a few hundred tokens. ONNX export targets Transformers.js; q4 worst-case cosine vs fp32 0.975 (text 0.988). Published: MTEB multilingual v2 mean 61.36 (all tasks, not retrieval-only), MMEB v2 overall 59.01, MMEB v2 visual documents nDCG@5 67.84 |
| `google/siglip2-base-patch16-224` | Two-tower (CLIP-like) | ~375M total *(verify split; large 256k-vocabulary text embedding table)* | 64 | Apache-2.0 | challenger (C: visual channel) | Independent towers: images embedded at index time, short text tower at query time. Multilingual training. Vocabulary pruning to cut pack size is allowed only with parity and pt/en quality checks |
| Other SigLIP 2 sizes (base 256/384, so400m) | Two-tower | larger | 64 | Apache-2.0 | challenger / ceiling | Resolution and size sweep |
| `nomic-ai/nomic-embed-vision-v1.5` + `nomic-embed-text-v1.5` | Vision tower aligned to an existing text space | 92M vision + 137M text | 8,192 | Vision: Apache-2.0 per Nomic (relicensed 2025-01), but the model card was seen listing CC-BY-NC — **verify**; text: Apache-2.0 | probe | English-centric text tower (risk to principle P5, multilingual-first); simple, independent encoders |
| OpenCLIP ViT-B/32 (LAION-2B) | Two-tower | ~151M | 77 | MIT code; weights *(verify)* | baseline (C) | Classic reference point for text-to-image quality and speed |
| `apple/MobileCLIP2-*` | Two-tower | very small | 77 | Apple AMLR (research use) | excluded | License (ADR-0022); community ONNX conversions do not change the terms |
| `jinaai/jina-clip-v2`, `jinaai/jina-embeddings-v5-omni-*` | Two-tower / unified | 0.9B / 1.0B | 8,192 | CC-BY-NC | excluded | Non-commercial license |
| ColPali / ColQwen class | Late-interaction visual document retrieval | 2–3B | — | various | ceiling | Multi-vector; beyond CPU budgets; offline quality reference for visual documents only |

Sources checked 2026-11-27:
[EmbeddingGemma 2 model card](https://huggingface.co/google/embeddinggemma-2),
[developer guide](https://developers.googleblog.com/embeddinggemma-2-the-developer-guide/),
[ONNX exports](https://huggingface.co/onnx-community/embeddinggemma-2-ONNX),
[Nomic Embed Vision announcement](https://home.nomic.ai/blog/posts/nomic-embed-vision),
[nomic-embed-vision-v1.5 card](https://huggingface.co/nomic-ai/nomic-embed-vision-v1.5).
Stage 0 re-verifies every license file and revision.
