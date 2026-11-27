# Benchmark Methodology

| Field | Value |
|---|---|
| Status | Accepted protocol (budgets provisional until locked by ADR after the Phase 1 baseline) |
| Date | 2026-11-27 |
| Governs | Datasets, metrics, hardware tiers, budgets, statistics, decision rules, model bake-off protocol, reporting |
| Related | [ADR-0017](../adr/0017-spec-and-benchmark-driven-development.md), [candidates](candidates.md), [report template](_report-template.md) |

Benchmark-Driven Development (**BmDD** in this repository, to avoid confusion
with Behavior-Driven Development) means: every change that can affect quality or
performance declares its gate first and lands with a reproducible report.
Components are chosen by bake-off under this protocol — never by popularity or
leaderboard rank. Public leaderboards (MTEB, BEIR) are used only to shortlist
candidates.

## 1. What is benchmarked

| Area | Decisions it drives |
|---|---|
| Embedding models | Default embedder, dimension (Matryoshka truncation), precision |
| Rerankers | Default reranker, depth, token budget, CPU vs NPU-only |
| Snippet scorers (pruner slot) | Heuristic vs model-based snippet selection |
| Learned sparse retrieval | Whether a sparse retriever joins the cascade |
| Inference engine | ORT validation gate (kill criteria K1–K4); challenger engines only for a role where a criterion fires ([ADR-0019](../adr/0019-single-inference-engine.md)) |
| OCR engines | CPU OCR pack contents, optional GPU pack, default on/off |
| Visual embedders (optional pack, [ADR-0023](../adr/0023-multimodal-ready-engine.md)) | Visual architecture (A text-only, B unified, C specialized), visual model, visual-unit selection, pack shipped or not |
| Extractors | Per-format extractor choice |
| Lexical engines and analyzers | FTS5 vs Tantivy; stemming/stopwords per language |
| Filename index | Instant filename/path search structure |
| Vector stores and quantization | Flat vs HNSW; f32/int8/binary; rescoring depth |
| Fusion | RRF vs challengers; weights |
| Chunking | Size, overlap, structure awareness, contextual headers |
| Ranking stages | Aggregation, dedupe, diversity, length correction, routing (ablations) |
| Execution providers | CPU threading; NPU providers per vendor |
| System | Indexing throughput, time-to-searchable, interference, memory, disk, startup, download size |

## 2. Datasets

### 2.1 Seeky Desktop Corpus (SDC) — the primary benchmark

Public IR datasets measure passage QA retrieval, not desktop search. SDC is
Seeky's own corpus, built to resemble a real user's folders.

- **Sources (redistributable):** public-domain books (for example Project
  Gutenberg, including Portuguese classics), official government publications
  (Brazilian official acts and US federal works are not copyright-protected),
  CC-BY scientific papers, CC-BY-SA encyclopedia articles (kept as a separately
  licensed dataset), permissively licensed source code, and synthetic office
  documents (contracts, invoices, spreadsheets, slide decks, e-mails).
- **Formats:** PDF (text and scanned), DOCX, XLSX, PPTX, ODT, RTF, HTML, EPUB,
  EML, MD, TXT, source code, images.
- **Languages:** pt and en (primary), es, fr, de (secondary), plus a small
  non-Latin sample (non-regression only).
- **Adversarial structure:** exact copies, near-duplicate versions, boilerplate
  templates, very long books next to short notes, scanned duplicates of text
  PDFs, renamed/moved copies.
- **Visual slice** (for the optional visual pack, ADR-0023): public-domain or
  CC0 photos, rendered screenshots, diagrams and charts (from CC-BY papers or
  generated plots), and slide decks with figures, pinned in the source
  manifests like every SDC file; photos of identifiable people are avoided.
- **Scales:** `sdc-smoke` (~200 files, committed, used in CI), `sdc-s`
  (~10k files / ~100k passages), `sdc-m` (~100k files / ~1M passages, extended
  with distractors).
- **Generator:** `bench/corpora/sdc/` builds the corpus deterministically from
  pinned source manifests (URL + SHA-256). Bulk data is never committed.

### 2.2 Queries and judgments

- Query categories (each a reported slice):

  | Category | Example |
  |---|---|
  | Known-item | the file whose name you forgot |
  | Conceptual | documents discussing electromagnetic induction |
  | Exact identifier | a UUID, invoice number, error code |
  | Cross-language | query in Portuguese, document in English (and vice versa) |
  | Needle in a haystack | one paragraph inside a 1,500-page book |
  | Exploratory | documents about a broad topic |
  | Mixed semantic + metadata | concept + type + date |
  | Code search | where a feature is implemented |
  | Filename/partial | prefix or typo of a file name (instant search) |
  | Visual: text → image *(visual pack)* | photo of a red car parked on a street |
  | Visual: diagram or chart *(visual pack)* | chart showing exponential growth; series RLC circuit diagram |
  | Visual: image as query *(visual pack)* | other photos of this place; slides with this figure |

  Visual categories are reported on their own and do not enter the text
  weighted primary score (§3.1). Every text category is also run with the
  visual pack enabled, so its effect on text-intent queries is measured (gate
  Q8).

- Judgments: graded 0–3 at **document** and **passage** level; snippet evidence
  spans for a subset; duplicate-cluster labels.
- Drafting: humans author queries; LLMs may draft additional queries and
  candidate judgments offline (development tooling only,
  [ADR-0021](../adr/0021-no-generative-models-in-product.md)); every judgment
  used for a gate is human-verified or adjudicated.
- Pooling: judgments are pooled from all systems under test (depth 20) to avoid
  favoring the baseline.
- **Splits:** `dev` (tuning allowed) and `test` (gate decisions only; never used
  for tuning). Target ≥ 600 queries total, ≥ 60 per category, ≥ 100 per primary
  language.

Source-code documents and `code_search` queries run only in the `code_enabled`
configuration (ADR-0024). Default Q1/Q2 reporting and the WP-1.8 smoke gate
cover the other eight query categories; code search is reported separately
against code-enabled baselines. The `sdc-smoke-v1` set is dev-only and must be
human-verified before WP-1.8 starts.

### 2.3 Public datasets (downloaded by script, never redistributed)

| Dataset | Use | Languages | License note |
|---|---|---|---|
| MLDR | Long-document, document-level retrieval | 13 incl. pt, en, es, fr, de | Permissive (verify per release) |
| MIRACL | Passage retrieval sanity, non-pt languages | es, fr, de, en, … | Apache-2.0 (verify) |
| mMARCO | Portuguese passage retrieval; constructed pt↔en cross-lingual pairs | pt, es, fr, de, … | MS MARCO terms — internal research use only |
| Quati | Native Brazilian Portuguese retrieval | pt | Verify license before use |
| BEIR subsets (SciFact, NFCorpus, FiQA, TREC-COVID) | English domain shift | en | Mixed — internal use only |
| XM3600 *(visual pack)* | Multilingual text → image retrieval | 36 incl. pt, en | Verify license (captions and images) |
| MMEB v2 image and visual-document subsets *(visual pack)* | Text ↔ image and visual-document retrieval | mostly en | Mixed per subset — internal use only |
| ViDoRe *(visual pack)* | Visually rich document retrieval | en, fr, others | Verify per release |
| COCO Captions, Flickr30k *(visual pack)* | Classic text ↔ image retrieval | en | Research terms — internal use only |

Public datasets complement SDC; the **SDC test split is the deciding dataset**
for product defaults. A candidate that wins SDC but collapses on public sets is
investigated before selection.

### 2.4 Private corpora

Developers may run `seeky-bench` on their own folders. Only aggregate metrics
may be committed — never content, file names, or paths.

### 2.5 Extraction and OCR ground truth

Generated from known text: SDC documents are rendered to each format (and to
scanned images with noise, skew, and compression), so extraction fidelity and
OCR CER/WER are measured against exact source text.

## 3. Metrics

### 3.1 Quality

| Metric | Level | Role |
|---|---|---|
| nDCG@10 | document | **Primary** |
| MRR@10 | document | Secondary |
| Success@1 | document | Known-item and filename slices |
| Recall@100 | document and passage | Candidate-generation stages |
| nDCG@10 | passage | Passage ranking |
| Snippet evidence-hit rate, span F1 | snippet | Snippet engine |
| Duplicate rate@10 | document | Dedupe |
| Distinct relevant@10 / α-nDCG@10 | document | Diversity |
| Length-bias error by length bucket | document | Length correction |
| Recall@k vs exact search | vector | Quantization/ANN fidelity |
| CER / WER, reading-order accuracy | OCR | OCR engines |
| Hallucination rate (inserted words; text on no-text images; repetition loops) | OCR | Hard gate O4 |
| Retrieval impact: nDCG@10 / Recall@100 on the scanned-document slice | OCR | OCR engines |
| Text fidelity (normalized edit similarity) | extraction | Extractors |
| nDCG@10, Recall@10 on visual slices | document / visual unit | Visual pack (gate Q8) |
| Cross-modal alignment: text → image Recall@10 of a deployed variant vs its fp32 reference pair | visual | Visual quantization, especially with different precisions per component |

Weighted primary score for selection: nDCG@10 averaged over language slices
with weights pt 0.35, en 0.35, cross-lingual 0.15, other languages 0.15, and
reported per category. Default Q1/Q2 use the eight non-code categories;
`code_search` is reported and compared only between `code_enabled`
configurations.

### 3.2 Performance and resources

| Metric | Notes |
|---|---|
| Search latency per stage (Instant, Hybrid, Refined) | p50/p95/p99; warm and cold; idle and under indexing |
| Query embedding latency (batch 1) | Separate from indexing throughput |
| Indexing throughput | files/s and MB/s (extraction), passages/s (embedding), per provider |
| Time-to-searchable | lexical and semantic, single-file and bulk |
| Interference ratio | search p95 under indexing ÷ idle p95 |
| Memory | idle and peak RSS (excluding OS page cache of mmapped files, reported separately) |
| Disk | bytes per 1k passages by component |
| Startup | cold start to Instant-capable; to semantic-capable |
| OCR throughput | s/page (p50/p95) and pages/s for A4 at 300 dpi, per tier and provider |
| Visual throughput | images/s by image-size bucket, with decode/resize time reported separately from inference |
| Image-query latency | p50/p95 with a warm vision encoder; cold load reported separately |
| Distribution | installer size; default download size; per-asset size; runtime bytes per engine and platform |
| Energy (where measurable) | joules per 1k passages, CPU vs NPU |

## 4. Hardware tiers

| Tier | Profile | Role |
|---|---|---|
| **T0 Floor** | 4 cores / 8 threads x86-64 with AVX2, no AVX-512, 8 GB RAM, SATA SSD, no NPU | Must work; budgets relaxed ×2 |
| **T1 Reference** | 2024–2025 mainstream laptop, 8–12 cores, 16 GB RAM, NVMe, with an NPU (Intel Core Ultra, AMD Ryzen AI, or Snapdragon X class) | **Budgets are defined and verified here, CPU-only**; NPU measured separately |
| **T2 Workstation** | Development machine (20 threads, 64 GB, Intel NPU, discrete GPU) | Iteration only; never used to claim a budget is met |

Until a physical T1 device is available, "T1-emulated" runs pin the process to
a documented core subset with a memory cap; reports must label them as such.
ARM64 (Snapdragon, Apple Silicon) joins the matrix in the cross-platform phase.

Measurement hygiene: AC power, fixed power plan, no other heavy processes,
warm-up runs discarded, environment captured automatically (CPU model, cores,
RAM, OS build, driver versions, inference-engine version, commit, config hash).

## 5. Budgets

**Provisional.** Locked by an ADR after the Phase 1 baseline (B0) is measured;
changing a locked budget requires a new ADR. Unless noted: T1, CPU-only, warm,
`sdc-m` scale (~1M passages).

### 5.1 Search

Search budgets use the `S` prefix; `P1`–`P8` are the product principles in
[`vision.md`](../product/vision.md).

| ID | Budget | Target |
|---|---|---|
| S1 | Instant stage (filename + lexical), p95 | ≤ 30 ms |
| S2 | Hybrid stage (+ dense, fusion, document layer), p95 | ≤ 120 ms |
| S3 | Refined stage (+ rerank, diversity, snippets), p95 | ≤ 400 ms |
| S4 | Stale-query cancellation | ≤ 5 ms |
| S5 | Interference ratio (S2 under indexing ÷ idle) | ≤ 1.5 |

### 5.2 Indexing

| ID | Budget | Target |
|---|---|---|
| I1 | Changed file lexically searchable (≤ 1 MB text), p95 after debounce | ≤ 2 s |
| I2 | Changed file semantically searchable, idle queue | ≤ 10 s |
| I3 | Initial semantic index of `sdc-s` (~100k passages), CPU-only | ≤ 30 min (stretch ≤ 10 min) |
| I4 | Startup reconcile of `sdc-s` with no changes | ≤ 5 s |
| I5 | Re-embedding on pure rename/move | 0 passages |

### 5.3 Resources and distribution

| ID | Budget | Target |
|---|---|---|
| R1 | Idle RSS (engine + webview), `sdc-s` | ≤ 300 MB |
| R2 | Idle RSS, `sdc-m` (excluding page cache) | ≤ 600 MB |
| R3 | Peak RSS during indexing, `sdc-m` | ≤ 1.5 GB |
| R4 | Index disk footprint per 1M passages (all components) | ≤ 2.5 GB |
| R5 | Cold start to Instant-capable | ≤ 1.5 s |
| R6 | Cold start to semantic-capable (CPU; NPU with compiled cache) | ≤ 3 s |
| D1 | Installer size | ≤ 25 MB |
| D2 | Default first-run download (runtime + embedder + reranker, CPU) | ≤ 250 MB |

### 5.4 OCR (optional pack)

Provisional; locked with the budgets ADR or, at the latest, before OCR Stage B
starts. Conditions: A4 page at 300 dpi, T1 CPU-only, background priority.

| ID | Budget | Target |
|---|---|---|
| O1 | CPU default tier, s/page p95 | ≤ 2.0 s |
| O2 | Peak RSS added by OCR | ≤ 1.0 GB |
| O3 | CPU OCR pack download (models + any runtime delta) | ≤ 150 MB |
| O4 | Hallucination: inserted-word rate on the clean slice; share of no-text images that produce text | ≤ 0.5 %; ≤ 1 % |

### 5.5 Quality gates

| ID | Gate |
|---|---|
| Q1 | The default pipeline beats BM25-only, the PoC baseline (B0), and the best single retriever on SDC-test weighted nDCG@10, statistically significant |
| Q2 | No language slice or query category regresses by more than 2.0 nDCG@10 points versus the current default; code search is compared only between `code_enabled` configurations |
| Q3 | Candidate generation document Recall@100 ≥ 0.95 on known-item, identifier, and needle slices |
| Q4 | Duplicate rate@10 ≤ 5 % on the duplicate-heavy slice, with Recall@10 not lower |
| Q5 | Vector quantization/ANN: Recall@100 ≥ 0.99 versus exact f32 after rescoring |
| Q6 | Reranker on by default on CPU only if it adds ≥ 3.0 nDCG@10 (significant) within S3; otherwise NPU-only or off |
| Q7 | Diversity costs ≤ 1.0 nDCG@10 while improving distinct relevant@10 |
| Q8 | Visual pack ships only if (a) its weighted nDCG@10 on the visual slices beats configuration A (OCR + filename + text, no pack) with statistical significance, and (b) with the pack enabled, no text category or language slice regresses beyond Q2 |

### 5.6 Visual retrieval (optional pack)

Provisional; locked before visual Stage B starts
([ADR-0023](../adr/0023-multimodal-ready-engine.md)). Conditions: T1 CPU-only,
background priority, photos up to 12 MP.

| ID | Budget | Target |
|---|---|---|
| V1 | Visual indexing throughput, including decode and resize | ≥ 5 images/s |
| V2 | Peak RSS added by the visual pack during indexing | ≤ 1.0 GB |
| V3 | Visual pack download (vision encoder + any separate text encoder) | ≤ 250 MB |
| V4 | Hybrid stage p95 for text queries with the visual channel enabled | S2 still met |
| V5 | Image-query latency p95, warm vision encoder | ≤ 400 ms |

## 6. Statistics

- Per-query paired comparison on the same split; **paired randomization test**
  (or paired bootstrap), 10,000 resamples, α = 0.05; report the 95 % confidence
  interval of the difference.
- Bake-offs with many candidates report Holm-adjusted p-values for claims of
  superiority; selection follows the decision rule below.
- Latency: ≥ 1,000 queries per stage or ≥ 30 repetitions of a fixed query set;
  percentiles with bootstrap CIs; never compare runs from different tiers.
- A difference inside the confidence interval is a tie.

## 7. Decision rule for bake-offs

1. **Eligibility:** passes the license gate ([ADR-0022](../adr/0022-permissive-license-gate.md)),
   runs on ONNX Runtime with parity ([ADR-0019](../adr/0019-single-inference-engine.md))
   or natively in Rust (or clears the new-engine margin, §8.6), passes parity,
   fits size limits.
2. **Constraints:** meets the relevant budgets on T1 CPU-only (and T0 functional).
3. **Objective:** maximize the weighted primary quality score on SDC-test,
   subject to gate Q2.
4. **Tie-breakers** (within CI): no new engine; then, for the default text
   embedder only, a candidate whose embedding space also serves images,
   provided it meets every text budget including D2
   ([ADR-0023](../adr/0023-multimodal-ready-engine.md)); then smaller
   download, lower RAM, higher indexing throughput, simpler integration.
   Image capability never offsets a text-quality loss outside the CI.
5. Commit the Pareto frontier (quality × latency × memory × download) and the
   deployment-cost table (§8.5) with the report; record the outcome in an ADR.

If no candidate satisfies the constraints, the budget or the architecture is
revisited explicitly (ADR), never silently relaxed.

## 8. Model bake-off protocol

Applies to every model bake-off (embedders, rerankers, snippet scorers, sparse
encoders, OCR, visual embedders) and to the ORT validation gate (§8.7). Goal: decisions in days,
from numbers, with expensive measurement spent only on finalists.

### 8.1 Unit of comparison: the deployment variant

Candidates are compared **as deployed** on ONNX Runtime
([ADR-0019](../adr/0019-single-inference-engine.md)): model + ONNX variant +
precision + execution provider. Another engine appears only when pricing an
alternative (§8.3, §8.6). Published scores and vendor claims only
shortlist. A file format says nothing about architecture: ONNX, GGUF, and
OpenVINO IR can all carry encoders (embedders, rerankers) and decoders.

### 8.2 The funnel

| Stage | Question | Runs on | Input | Kill rule | Timebox |
|---|---|---|---|---|---|
| **0 Paper screen** | Eligible and plausible? | Desk research | License file, model card, size, languages, architecture, available formats and export paths, maintenance | Ineligible license (ADR-0022); no Portuguese support; too large for every tier | ≤ 0.5 day per area |
| **A Quality screen** | Good enough to be worth porting? | Reference runtime (PyTorch/Transformers or vendor code, in `tools/`), reference precision, any T2 machine | Fixed **screening set** from the `dev` split, sized to run in ≤ 1 h per candidate | Primary metric below the leader with non-overlapping 95 % CIs, or a failed hard gate (for example OCR hallucination) | ≤ 2 days |
| **B Deployment bake-off** | What does it cost as shipped? | `seeky-bench` on T1 CPU-only, plus the NPU or GPU tier where relevant | ≤ 4 finalists per tier × ONNX export (§8.3) × quantization matrix (§8.4) | Parity failure, budget miss, or dominated on the Pareto frontier | ≤ 5 days |
| **C Confirmation** | Does the winner hold on unseen data? | `seeky-bench` | Top 1–2 variants on SDC `test` + public sets | Not significant or fails Q2 → back to B | ≤ 1 day |

Rules that keep the funnel fast and honest:

- Stage A outputs (vectors, scores, OCR text) are cached under the key
  `(candidate, revision, variant, input hash)` in a standard layout, and
  **metrics are always computed by `seeky-eval`**: Python in Stage A and Rust in
  Stage B share one metric implementation.
- Stage B reuses the Stage A cache as the parity reference: a deployed variant
  must reproduce its own reference within tolerance before its speed counts.
- Frozen inputs: rerankers and snippet scorers score identical cached
  first-stage candidate lists; OCR retrieval impact re-indexes cached OCR text
  without re-running OCR.
- Stage 0/A runs are independent per candidate (agents in parallel, any T2
  machine); Stage B/C performance runs are serialized on the reference device
  (measurement hygiene, §4).
- The `test` split is used once, in Stage C.
- One command per stage:
  `seeky-bench bakeoff <area> --stage screen|deploy|confirm --candidates <file>`,
  writing `results.json`, `summary.md`, the Pareto table, and the
  deployment-cost table.

### 8.3 ONNX export, and pricing alternatives

1. **Export to ONNX** (required) via the Optimum exporter or `torch.onnx.export`.
   Autoregressive transcription models are split into vision-encoder,
   embedding, and decoder-with-KV-cache graphs; the greedy decode loop lives in
   `seeky-infer`, so no extra runtime library is needed. One format, not one
   file: NPU providers may need their own variants (static shapes, static QDQ
   quantization, compiled EP context caches), each with parity.
2. **If export or parity fails**, try the other exporters and split-graph
   strategies within the timebox, and record unsupported operators and effort.
3. **Pricing alternatives** happens only when a kill criterion fires for the
   role (§8.7) or a candidate that cannot run on ONNX Runtime leads Stage A by
   more than the §8.6 margin:
   - **OpenVINO IR** via the OpenVINO model converter (`ovc` /
     `openvino.convert_model`, Optimum-Intel) with NNCF int8/int4. OpenVINO
     converts PyTorch, ONNX, TensorFlow, and PaddlePaddle models *into* IR (it
     does not emit ONNX) and reads ONNX directly, so the same ONNX file can be
     timed on ONNX Runtime's OpenVINO EP and on native OpenVINO, isolating the
     engine effect from the model effect.
   - **GGUF** via llama.cpp conversion tools (encoders and decoders, k-quants).
   - Every priced row carries the full deployment cost (§8.5).

Each attempt records success or failure, unsupported operators, conversion
effort in hours, and parity.

### 8.4 Quantization matrix and tolerance

| Variant | ONNX Runtime (default) | Priced alternatives only (§8.3) |
|---|---|---|
| Reference | fp32 | — |
| Half precision | fp16 (accelerators) | OpenVINO fp16/bf16; GGUF f16 |
| 8-bit | dynamic int8; static QDQ int8 (required by QNN and VitisAI NPUs); weight-only int8 | NNCF int8; GGUF Q8_0 |
| 4-bit weight-only | `MatMulNBits` int4 (mainly decoders) | NNCF int4; GGUF Q4_K_M / Q5_K_M |

Selection: the smallest, fastest variant whose loss versus the same model's
reference stays inside tolerance on the `dev` split:

| Area | Tolerance versus reference |
|---|---|
| Embedder | ≤ 0.5 weighted nDCG@10 points; mean cosine to reference vectors ≥ 0.99; neighbor Recall@100 versus reference ≥ 0.98 |
| Reranker, snippet scorer | ≤ 0.5 nDCG@10 points; Kendall τ on candidate lists ≥ 0.95 |
| OCR | ≤ 0.5 CER points absolute; hallucination rate not higher (inside CI) |

Calibration data comes from `dev` only. Speedups are measured per CPU tier (T0
AVX2 versus T1 VNNI/AMX or ARM i8mm), never assumed. Tolerances are provisional
and locked with the budgets ADR.

### 8.5 Deployment-cost accounting

Every Stage B row reports:

| Column | Meaning |
|---|---|
| Deployment variant | Engine, format, precision, provider |
| New engine? | Whether it adds an engine beyond ONNX Runtime (ADR-0019) |
| Runtime bytes | Added runtime download and installed size per platform (Windows x64/ARM64, macOS ARM64, Linux x64) |
| Model bytes | Download and on-disk size of the variant |
| Load time | Cold, and warm with compiled-model cache |
| Peak RSS | Steady-state inference |
| Speed | Area metric with CIs: batch-1 query latency, passages/s, s/page |
| Integration cost | New crates, FFI, native libraries, export pipeline, CI matrix entries; license of each |
| Coverage | Tiers, platforms, and NPUs/GPUs the variant runs on |

Default-path assets must fit D1/D2; opt-in packs report their own totals.

### 8.6 New-engine margin

A candidate that needs an engine other than ONNX Runtime (ADR-0019
runtime-cost rule) is adopted only if it is significantly better than the best
ONNX Runtime candidate by at least:

- **retrieval models:** +3.0 weighted nDCG@10 points, or ≥ 2× throughput at
  equal quality (inside CI);
- **OCR:** +2.0 nDCG@10 on the scanned-document slice, or ≥ 25 % relative CER
  reduction, with an equal or lower hallucination rate;

and its total deployment cost still fits the budgets. Margins are provisional,
locked with the budgets ADR, and never changed after a bake-off starts.

### 8.7 ORT validation gate (priority zero)

Keeps [ADR-0019](../adr/0019-single-inference-engine.md) falsifiable at low
cost (plan WP-0.6). It measures engine properties — speed, memory, size, NPU
reach, parity — which need no relevance judgments, so it runs before the SDC
corpus exists.

- **Proxy portfolio**, fixed before the run, one model per role: a small
  multilingual encoder embedder (e5-small class), a ModernBERT-class embedder,
  a cross-encoder reranker, a classic OCR detection + recognition pipeline
  (PP-OCR class), and one ~1B-parameter transcription VLM exported as split
  graphs with a greedy decode loop.
- **Variants:** fp32 reference, int8 (dynamic and static QDQ), int4
  `MatMulNBits` where it applies; the OpenVINO EP on an Intel NPU.
- **Data:** samples of public sets (MIRACL, mMARCO-pt) for quantization-loss
  checks; pages rendered from public-domain text, with known ground truth, for
  OCR CER and speed.
- **Tools:** export and parity in `tools/model-export`; timing with ORT's perf
  tooling or a minimal `ort` harness. `seeky-bench` re-verifies the numbers in
  Phase 2.
- **Hardware:** T1 CPU-only (or the documented T1-emulated profile), a T0
  functional check, and an Intel NPU for K3.

Kill criteria (predeclared; targets derived from the provisional budgets in §5
and locked with them):

| ID | Fires when | Derived target |
|---|---|---|
| K1 | A role misses its target with its best ONNX Runtime CPU variant on T1 | Embedder: ≥ 56 passages/s sustained (I3: 100k passages in 30 min) and batch-1 query p95 ≤ 20 ms (S2 headroom). Reranker: default depth (50 pairs) p95 ≤ 250 ms (S3 headroom). OCR CPU tier: O1–O3 |
| K2 | The Stage A leader of a role cannot run on ONNX Runtime with parity, and the best ORT-runnable candidate trails it by more than the §8.6 margin | — |
| K3 | The Intel NPU cannot be reached with parity through the OpenVINO EP (other NPUs are validated in Phase 5) | Manifest parity tolerance |
| K4 | The ONNX Runtime CPU runtime pushes the default first-run download past D2 | D2 |

For the transcription VLM, K1 fires only if another engine could plausibly
close the gap (measured time within 2× of O1); a model far beyond O1 is out of
the CPU tier on any engine, and the CPU OCR role is then served by the
detection + recognition class. K2 for OCR can only be checked after OCR Stage A
(plan WP-2.11); the gate is re-checked then.

**Outcome:** no criterion fires → ADR-0019 stands, the gate report is
committed, and plan WP-2.3 is skipped. A criterion fires → WP-2.3 measures
challenger engines (llama.cpp/GGUF, native OpenVINO, …) **for that role only**,
with full deployment cost; a second engine needs the §8.6 margin and a
superseding ADR.

### 8.8 OCR bake-off specifics

- **Ground truth:** SDC renders (§2.5) plus a real-scan subset (public-domain
  scanned books and government documents) with human-verified transcriptions.
- **Slices:** clean print; degraded scans (noise, skew, JPEG); phone photos of
  documents; screenshots; tables and forms; multi-column; Portuguese
  diacritics; English; handwriting (reported only); **no-text images** (photos,
  blank pages).
- **Metrics:** CER and WER after normalization (NFC, whitespace), reported
  diacritic-sensitive and diacritic-insensitive; reading-order accuracy;
  hallucination rate; retrieval impact (nDCG@10 and Recall@100 on the
  scanned-document query slice, index built from each candidate's cached OCR
  text); s/page p50/p95 and pages/s; peak RSS; download bytes; cold load.
- **Determinism:** two runs over the same pages produce identical text.
- **Tiers:** the CPU default tier must meet O1–O4. A GPU opt-in tier is
  measured on the reference GPU and must clear the §8.6 OCR margin over the
  CPU default tier to justify its download.

### 8.9 Visual bake-off specifics (optional pack)

Governed by [ADR-0023](../adr/0023-multimodal-ready-engine.md); candidates in
[candidates §14](candidates.md).

- **Configurations:** **A** text-only (OCR + filename + text channel, no
  pack) is the baseline for every visual metric. **B** unified: one channel
  whose text component is the default text embedder from WP-2.6. **C**
  specialized: the default text embedder plus a separate visual channel. If
  the WP-2.6 winner is not multimodal, a unified model can still serve as C's
  visual channel; its text component then embeds queries only, never
  passages, and its bytes count toward V3.
- **Slices:** photos, screenshots, diagrams and charts, slides, scanned
  documents with figures; pt and en text queries, cross-language queries, and
  image-as-query; plus every text category re-run with the pack enabled
  (gate Q8, part b).
- **Visual units:** the selection rules (which slides, figures, and pages
  become units) are part of the configuration under test; report units per
  1k pages and the recall they buy.
- **Parity:** image parity vectors start from raw bytes, so Rust decoding,
  resizing, and normalization are validated against the reference
  preprocessing. Report top-10 overlap on the visual slices, not only cosine.
  When the text and vision components use different precisions, gate on the
  cross-modal alignment metric (§3.1): per-component cosine can hide
  alignment loss.
- **Knobs:** Matryoshka dimension (re-normalize after truncation), visual
  token budget for models that feed images to a shared backbone (70 / 140 /
  280), input resolution, precision per component. Vocabulary pruning of
  large-vocabulary text towers is allowed only if parity and pt/en quality
  hold.
- **Fusion and presentation:** rank fusion vs per-modality calibration;
  interleaved vs grouped image results, each measured on visual and
  text-intent slices.
- **Public sets** (XM3600, MMEB v2 subsets, ViDoRe) shortlist and cross-check;
  the SDC visual slice decides.

## 9. Tooling

- `tools/seeky-bench` drives the real engine crates headlessly:
  `index`, `eval`, `perf`, `compare`, `report`, `bakeoff` (§8).
- `crates/seeky-eval` implements loaders (BEIR-style `corpus/queries/qrels`
  layout plus SDC metadata), metrics, statistics, and report writers.
- Microbenchmarks for hot paths use Rust benchmark harnesses (criterion/divan
  class) and live next to the code.
- Each run writes a machine-readable `results.json` and a human `summary.md`
  (see [`_report-template.md`](_report-template.md)).

## 10. CI gates versus reference runs

| Where | What | Authority |
|---|---|---|
| CI (every PR) | `sdc-smoke` quality (nDCG@10 drop ≤ 1.0 vs `main`), invariant tests, microbenchmarks (advisory thresholds) | Blocks merges on quality regressions and broken invariants |
| Reference hardware (per milestone and per bake-off) | Full SDC-s/m + public sets, all budgets | Decides defaults, locks budgets, gates milestones |

## 11. Reporting rules

- Reports live in `docs/benchmarks/results/YYYY-MM-DD-<area>-<slug>/`.
- Every report records commit SHA, configuration hash, dataset versions and
  checksums, model IDs and hashes, hardware tier and environment, metrics with
  CIs, baseline comparison, and the decision.
- Raw run outputs larger than a few MB are not committed; the report records how
  to regenerate them.
- A report never contains document content from private corpora.
