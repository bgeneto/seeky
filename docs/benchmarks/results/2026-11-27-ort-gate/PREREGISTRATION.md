# WP-0.6 ORT validation gate — preregistration

| Field | Value |
|---|---|
| Frozen before measurement | 2026-11-27 |
| Work package | WP-0.6 |
| Protocol | `docs/benchmarks/methodology.md` §8.7 at commit `5943bc61a3354978fe93750af71c1a3a3d16eb44` |
| Decision authority | This run reports evidence only. The maintainer decides whether ADR-0019 stands or WP-2.3 starts (gate H5). |
| Measurement label | **T1-emulated, provisional** until the maintainer accepts the profile (gate H3) |

No latency, throughput, memory, NPU, or model-output measurements were made before
this file was committed. Changing a model, revision, input set, variant matrix,
target, or analysis rule after measurement requires a separately committed
amendment that identifies the affected results; results collected under different
rules will not be pooled.

**Pre-measurement amendment 1 (2026-11-27):** upstream MIRACL metadata has no
Portuguese configuration. The MIRACL sample below is therefore English `dev`;
mMARCO remains the Portuguese sample. No model or dataset rows had been run or
acquired when this correction was made, and no result is affected.

## 1. Fixed proxy portfolio

Only license-Allowed models under ADR-0022 are included. Revisions are immutable
commit prefixes from the upstream weight repositories; full revisions and SHA-256
file hashes will be captured at download. These are engine proxies, not proposed
Seeky defaults and not Stage A quality winners.

| Role | Model and revision | Why it represents the role | License evidence |
|---|---|---|---|
| e5-small-class multilingual embedder | `intfloat/multilingual-e5-small` @ `614241f622f53c4eeff9890bdc4f31cfecc418b3` | 117.65M-parameter XLM-R encoder, 384-d output, pt/en support | MIT in the upstream model card |
| ModernBERT-class embedder | `ibm-granite/granite-embedding-97m-multilingual-r2` @ `835ad14087e140460703cf0fae09f97d469d65c2` | 97.44M-parameter ModernBERT encoder, 384-d output, pt/en support | Apache-2.0 in the upstream model card |
| Cross-encoder reranker | `Alibaba-NLP/gte-multilingual-reranker-base` @ `9ba3cad4568fc0c9299265c963d1eb11df23840d` | 305.96M-parameter encoder-only sequence classifier, pt/en support | Apache-2.0 in the upstream model card |
| Classic OCR detection + recognition | PP-OCRv5 mobile detector + `latin_PP-OCRv5_mobile_rec`, using the immutable PaddleOCR model URLs and hashes captured at download | DB detector + CTC recognizer; Latin script includes Portuguese | Apache-2.0 PaddleOCR LICENSE |
| ~1B-class transcription VLM | `microsoft/Florence-2-large` @ `21a599d414c4d928c9032694c424fb94458e3594`; ONNX graphs from `onnx-community/Florence-2-large` @ `b7751295927207b2a8c2f354af8baadea5b0404b` | 776.72M-parameter vision encoder + text encoder + autoregressive decoder; split graphs and KV cache; fixed `<OCR>` transcription task | MIT LICENSE in both repositories |

Florence-2-large is the preregistered ~1B-class proxy because it is the smallest
license-Allowed candidate in the registry with published fp32 split ONNX graphs.
It is used only for the fixed OCR task, never for captioning or any other
generative feature. OCRia-1/OCRia-nano-1 and OXR-1.0 are excluded by their
additional commercial/use restrictions. dots.ocr is excluded from this portfolio
because its supplemental use policy requires review. MiniCPM-OCR and PaddleOCR-VL
remain registry candidates but are not additional proxies: one VLM is fixed to
keep the gate bounded.

## 2. Variants and runtime

The product pins `ort = 2.0.0-rc.10`; that wrapper's source identifies ONNX
Runtime **1.22** and ORT API 22. The CPU harness will therefore use Python
`onnxruntime==1.22.0`. If the provisioned product DLL is available and has a
different version, both versions will be recorded and the difference will be
reported. NPU checks use `onnxruntime-openvino==1.22.0` in a separate environment
so its native OpenVINO EP does not get confused with the CPU-only wheel.

| Role | fp32 | int8 dynamic | int8 static QDQ | int4 MatMulNBits | OpenVINO EP on Intel NPU |
|---|---|---|---|---|---|
| Both embedders | Export or official fp32 ONNX | Yes | Yes; MinMax calibration, 128 public-dev passages | Not applicable to encoder weights under the preregistered matrix | Static sequence buckets 32 (query) and 384 (passage); fp32 and static QDQ where supported |
| Reranker | `torch.onnx.export` or Optimum fp32 | Yes | Yes; MinMax calibration, 128 public-dev query/passage pairs | Not applicable to encoder weights | Static sequence bucket 384; fp32 and static QDQ where supported |
| PP-OCR detector + recognizer | Official fp32 ONNX | Attempt on each graph | Attempt on each graph with 8 rendered public-domain calibration pages | Not applicable to convolutional/recurrent graphs | Static detector and recognition shapes where supported; report per graph, never infer NPU execution from a request alone |
| Florence-2-large | Published split fp32 graphs: vision encoder, text encoder, token embedding, merged decoder with KV cache | Attempt on decoder and encoder MatMuls | Attempt static QDQ only where shape/provider support exists | Published decoder/encoder q4 graphs; block size and graph hashes recorded | Best effort per static component; dynamic KV decode remains CPU if the EP cannot execute it |

All graph optimizations are enabled. Dynamic quantization uses ORT's integer
MatMul path with weights quantized once. Static QDQ uses only the calibration
samples below, per-channel weights where ORT supports them, and no test or SDC
inputs. An unsupported variant is a reported export result, not silently replaced
by a different model or engine. A speed result counts only after that same
variant passes parity.

The reference implementation is PyTorch/Transformers for encoders and Florence,
and PaddleOCR/Paddle inference for PP-OCR where the Windows runtime is available.
If Paddle cannot run on the pinned Python/platform, the official fp32 Paddle
ONNX graph is the deployment reference and the limitation is explicit; outputs
from a quantized variant are never used as their own reference.

## 3. Frozen public data

Raw datasets, renders, model weights, ONNX files, caches, and reference outputs
live under `%LOCALAPPDATA%\seeky-dev\wp06`, outside every repository worktree.
Only aggregate metrics, per-run timings, IDs, revisions, sizes, and hashes may be
committed. No document text, private path, or user name is committed.

### 3.1 Text samples

- **MIRACL**: `miracl/miracl`, English configuration, `dev` split, upstream
  revision recorded at acquisition. Use the first 32 query IDs after sorting by
  ID, their judged passages, and enough corpus rows to complete 512 unique
  passages. This subset is used only for public-dev parity/quantization checks.
- **mMARCO-pt**: `unicamp-dl/mmarco`, Portuguese configuration, validation/dev
  split as published, upstream revision recorded at acquisition. Select passages
  and queries with SHA-256 seeded ordering (`seeky-wp06-v1`) until the frozen set
  contains 512 additional unique passages and 32 additional queries. If that
  dataset layout is unavailable, the acquisition failure is reported; no
  substitute dataset is introduced without a preregistration amendment.
- Combined text set: **1,024 unique passages and 64 queries**, disjoint between
  the two sources after exact-text deduplication. Query prefix is `query: ` and
  passage prefix is `passage: ` only for e5. Other models use their published
  input recipe. Truncation is right-side; padding follows each tokenizer.
- Calibration: the first 128 passages and first 128 query/passage pairs from the
  frozen mMARCO-pt ordering. Parity/evaluation never uses an item's calibration
  output to tune another parameter.
- Embedding query latency: 64-token maximum, batch 1. Passage throughput:
  384-token maximum, batch 8, sequential batches. Neighbor parity uses all 1,024
  passages and the 64 queries, exact cosine search in float64.
- Reranker lists: for each of the first 30 MIRACL queries, take the frozen fp32
  e5 embedding ranking's top 50 passages. Identical lists are scored by every
  variant at 384-token maximum. Depth-50 latency is one complete list, batch 1.

### 3.2 OCR samples

- Public-domain source text: Project Gutenberg English *The Time Machine* and
  Portuguese *Dom Casmurro*. Exact source URLs, revisions where available, and
  SHA-256 checksums are recorded at acquisition. Gutenberg headers/license text
  are excluded from the rendered ground truth.
- Render **8 English + 8 Portuguese A4 pages at 300 dpi** (2480 × 3508 px), black
  DejaVu Serif text on white, 11 pt equivalent body text, deterministic line
  wrapping and pagination. The pinned font file and its hash are recorded. Clean
  printed pages are the K1 speed set; their known text is the CER/WER reference.
- Add **4 blank/no-text pages** for the transcription-model no-text check. No
  private scans or photographs are used. These synthetic clean pages do not
  establish OCR Stage A quality or O4 on degraded scans.
- Static-QDQ calibration: the first 8 rendered pages (4 per language). Parity
  and CER are reported on the remaining 8 pages as well as the full set; no
  calibration-based selection touches SDC or a public test split.
- Florence uses fixed prompt `<OCR>`, greedy decoding (`do_sample=false`,
  temperature 0), EOS/stop tokens from its processor, and a 1,024-token output
  bound. Two runs on the same page must produce identical token IDs.

### 3.3 Checksums and environment

The acquisition manifest stores dataset IDs/splits/revisions, selected row IDs,
SHA-256 of the frozen serialized samples, OCR source/font checksums, every model
file checksum, and package versions. The environment capture includes OS build,
CPU and instruction-set evidence, logical/physical cores, RAM, power source and
plan, NPU/driver/OpenVINO details, free disk, commit, tool source hashes, and
other-process load. Configuration hash is SHA-256 over this preregistration, the
acquisition manifest, and the measurement scripts.

## 4. Hardware profiles and hygiene

### 4.1 Proposed T1-emulated profile for H3

| Setting | Frozen proposal |
|---|---|
| Host | Intel Core Ultra 7 265KF workstation, 20 logical processors, 64 GB RAM, Windows 11; this is a T2 host, never relabeled physical T1 |
| Core subset | Logical processors **0–7 only** (8 CPUs), enforced on the harness and inherited children; ORT intra-op threads 8, inter-op threads 1, sequential execution |
| Memory cap | **12 GiB process memory**, enforced with a Windows Job Object before model load; physical host RAM remains visible in the environment capture |
| Power | AC power, Windows **High performance** scheme for each timed series; record the prior scheme and restore it afterward |
| Storage | Local NVMe; model files and cache on the same local drive for every compared variant |
| Priority | Normal priority for query measurements; below-normal for sustained indexing/OCR measurements |
| Repetitions | Discard 3 warm-up batches per model/variant; 30 timed depth-50 lists or query-set repetitions; 3 complete warm sustained-throughput passes over the frozen 1,024 passages |
| Statistics | Nearest-rank p50/p95 plus 10,000-resample bootstrap 95% CIs, seed `6006`; a difference whose CIs overlap is not claimed as a win |

All CPU numbers are labeled **T1-emulated, provisional** until H3. The host's
actual hybrid-core mapping and instruction sets are captured; no claim is made
that affinity recreates a particular laptop's frequency or memory bandwidth.

### 4.2 T0 functional check

This is functional, not a T0 performance claim. Repeat one e5 embedding query,
one depth-50 reranker list, one PP-OCR page, and one short Florence OCR crop on
logical processors **0–3**, 4 ORT intra-op threads, and a **6 GiB** process
memory cap. Use the best parity-passing CPU variant that fits. Record whether
the host exposes AVX2 without AVX-512 and whether ORT falls back or fails. Do not
publish T0 timings as budget evidence.

### 4.3 Quiet-window rule

Every timed series is serialized. Immediately before it, sample process CPU
counters twice over two seconds. Any `cargo` or `rustc` process owned by another
lane, or any other `node`/`python` process consuming more than 0.25 CPU-second
in that window, blocks the run. The harness waits and retries; it never times
through an active compilation. The blocking PIDs (without command lines or user
paths), sampled load, and eventual quiet-window result are recorded. The current
lane-A/lane-B Rust builds therefore take precedence over this lane's timing.

## 5. Parity and output analysis

| Area | Frozen rule from methodology §8.4 |
|---|---|
| Embedder | Mean cosine to the same model's fp32 reference vectors ≥0.99; neighbor Recall@100 against the fp32 exact-cosine neighbor lists ≥0.98. Retrieval nDCG change is reported when public qrels permit it and must be ≤0.5 points; no relevance judgment is created for this gate. |
| Reranker | Kendall τ on each frozen depth-50 list ≥0.95; nDCG@10 change versus fp32 on MIRACL public dev qrels ≤0.5 points. Also record maximum/mean absolute logit delta as diagnostics, not as a replacement tolerance. |
| OCR | CER increase ≤0.5 percentage points absolute after NFC + whitespace normalization; inserted-word/hallucination rate not higher inside 95% CI. Report diacritic-sensitive and insensitive CER, WER, exact deterministic-token match, and no-text output rate. |
| NPU | Same area tolerance against the same model/variant on ORT CPU. Inspect ORT verbose/provider logs and OpenVINO device placement; a session that silently runs only on CPU is not NPU reach. |

For Florence, component logits/embeddings are compared on fixed inputs before
full decode. End-to-end CER and exact greedy token IDs are then compared with
the fp32 ONNX deployment reference and, where feasible, PyTorch. Quantization
quality is not inferred from cosine alone.

## 6. K1–K4 decision rules

Targets are copied from methodology §8.7 and the provisional §5 budgets. K1 is
evaluated per role using the best parity-passing ORT CPU variant under the
T1-emulated profile. A parity-failing variant cannot rescue a role.

| ID | Target and firing rule |
|---|---|
| **K1 embedder** | **≥56 passages/s sustained** over the 1,024-passage warm set and **batch-1 query p95 ≤20 ms**. The embedder role passes if either preregistered embedder proxy has a parity-passing ORT CPU variant meeting both; otherwise K1 fires for this role. |
| **K1 reranker** | Frozen **depth 50 pairs, p95 ≤250 ms**. Fires if no parity-passing ORT CPU variant meets it. |
| **K1 PP-OCR** | **O1 p95 ≤2.0 s/page**, **O2 added peak RSS ≤1.0 GB**, and **O3 model + OCR-specific runtime delta ≤150 MB**, on A4 300-dpi pages under background priority. Fires if any of O1–O3 is missed by every parity-passing ORT CPU variant. O4 remains a later OCR bake-off gate; the clean/no-text diagnostics here cannot clear it. |
| **K1 Florence probe** | Apply O1–O3 to the VLM. K1 fires only when the best parity-passing ORT result misses O1 but measured end-to-end time is **within 2× O1 (≤4.0 s/page)**, so another engine could plausibly close the gap. If three distinct timed pages all exceed 4.0 s, the VLM is out of the CPU tier on any engine, the remaining repetitions are not burned, and K1 does **not** fire for this reason. The PP-OCR class then serves the CPU role. Export/parity failure is reported separately and is not relabeled K2 without a Stage A leader comparison. |
| **K2** | Requires a Stage A leader and a quality margin, which WP-0.6 does not select. Record **not evaluable / deferred to the relevant Stage A**, not pass. A proxy export failure alone does not fire K2. OCR K2 is explicitly deferred to WP-2.11. |
| **K3** | Fires if no production-relevant static graph can execute on the Intel NPU through ORT's OpenVINO EP with the manifest parity tolerance and verified device placement. Per-model/provider failures are reported even when another graph establishes reach. |
| **K4 / D2** | Compare **ORT CPU runtime download + best parity-passing e5-class embedder + best parity-passing reranker** with **250 MB**, using raw downloadable bytes and also reporting installed bytes. K4 fires only if the total exceeds 250 MB while the same model total **without ORT** is ≤250 MB; if models alone already exceed D2, report that separate model-budget miss rather than falsely attributing it to ORT. ModernBERT and optional OCR/VLM packs are not added to the default-path arithmetic. |

A fired criterion is not waived or retuned. Finish the evidence report and
recommend WP-2.3 **for that role only**. Challenger engines are not measured in
this lane. If no criterion fires, recommend that ADR-0019 stand subject to H3/H5
and the explicitly deferred K2 checks.

## 7. Runtime size, memory, and reporting

- K4 runtime bytes come from the official ONNX Runtime 1.22.0 Windows x64
  distribution actually used, including every DLL needed by the CPU harness.
  OpenVINO EP bytes are reported separately and never counted in the CPU default.
- Peak RSS is the harness process peak after subtracting the recorded pre-model
  baseline; cold load and warm load are separate from steady-state inference.
- Model bytes include all ONNX external-data files, tokenizer/dictionary files,
  and required graph components. Raw CSV/JSON contains one row per run with
  variant, provider, profile, iteration, latency, throughput, RSS, and return
  status; no input text is included.
- The final report follows `_report-template.md`, includes K1–K4 verdicts per
  role, failed/unsupported exports and effort, environment and quiet-window
  evidence, CIs, threats to validity, and exact reproduction commands. Large raw
  outputs remain outside the repository with regeneration instructions.
