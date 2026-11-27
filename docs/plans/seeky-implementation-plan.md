# Seeky Implementation Plan

| Field | Value |
|---|---|
| Status | Active |
| Version | 2.2 (work-package status tracking in §15) |
| Date | 2026-11-27 |
| Supersedes | Plan v1.1 (2026-11-26) and the archived Python-era plans |
| Current release | 0.1.0 PoC (milestones M0 "runnable PoC" and M1 "live incremental index" complete) |
| Target | 1.0.0 — CPU-first, NPU-ready local neural IR engine with a thin desktop shell |

Precedence: [`../product/vision.md`](../product/vision.md) → Accepted
[ADRs](../adr/README.md) → Accepted [specs](../specs/README.md) →
[architecture](../architecture/README.md) → this plan. If this plan conflicts
with a higher document, the higher document wins and this plan is corrected.

---

## 1. Mission and definition of success

Build the best **Local Neural Information Retrieval Engine** for ordinary
computers: exceptionally fast, accurate, multilingual (pt and en first) semantic
search over the user's files, CPU-first, NPU-ready, private, offline, and
search-only.

Seeky 1.0 is successful when, on CPU-only reference hardware (tier T1) with
~1M indexed passages:

1. Results start appearing within **30 ms** and the hybrid ranking within
   **120 ms** (p95); refined results within **400 ms**.
2. The default pipeline is **significantly better** than BM25-only, the PoC, and
   any single retriever on the Seeky Desktop Corpus, with no language slice
   regressing.
3. A changed file is findable by words in **≤ 2 s** and by meaning in
   **≤ 10 s**; renames never trigger re-embedding; offline edits are reconciled
   at startup.
4. The installer is **≤ 25 MB**, search works immediately after install, and the
   default model download is **≤ 250 MB**.
5. Every one of those claims is backed by a committed benchmark report.

Budget and gate IDs (S1–S5, I1–I5, R1–R6, D1–D2, O1–O4, V1–V5, Q1–Q8) are defined in
[`../benchmarks/methodology.md`](../benchmarks/methodology.md); they are
provisional until locked by ADR at the end of Phase 1.

## 2. Principles → engineering consequences

| Principle | What it forces in this plan |
|---|---|
| CPU-first | Budgets measured CPU-only on T1; models selected for batch-1 latency and indexing throughput on CPU; GPU work frozen |
| NPU-ready | ONNX Runtime EPs (OpenVINO, QNN, VitisAI, CoreML); Intel NPU reach checked in the WP-0.6 gate (K3); parity-on-load; static shapes; compiled caches; Phase 5 |
| Local-first | No content in network requests or logs; provisioning is the only network use |
| Performance-first | Budgets defined before code; perf harness in Phase 1; interference and stage latency are gates |
| Multilingual-first | Language-sliced evaluation; pt/en analyzers; cross-lingual queries; en/pt UI |
| Search-only | No generative features; VLMs only as gated OCR transcribers (ADR-0021); no generated image captions; answer layer removed from the roadmap; no HTTP/MCP/CLI product surface |
| Benchmark-driven | Harness and baseline precede retrieval work; every component chosen by bake-off with an ADR; the inference engine (ONNX Runtime) validated by a priority-zero gate with predeclared kill criteria (WP-0.6); models compared as deployed (ONNX variant + quantization + provider) |
| Model-agnostic core | Model manifest + traits; index generations; modality-aware contracts and embedding channels (ADR-0023, WP-2.13); no hardcoded dimensions or paths |
| Engine-first | Cargo workspace with UI-independent engine; Tauri becomes a thin shell in Phase 0 |

## 3. Methodology: Spec-Driven + Benchmark-Driven Development

### 3.1 The loop (every work package)

```text
1. Pick a work package (WP) whose dependencies are done.
2. Spec:   ensure its SPEC is Accepted (write/extend it first if not).
3. Gate:   state tests and benchmark gates before coding.
4. Tests:  write failing tests (unit, property, integration, fuzz) for the spec IDs.
5. Build:  implement the smallest change that passes; keep crates within boundaries.
6. Check:  fmt, clippy -D warnings, tests, cargo-deny, TS build, smoke eval.
7. Prove:  run seeky-bench when the WP touches quality/perf; write the report.
8. Record: in the same commit, the WP's row in §15.3, spec requirement status, ADR (if a
          default changed), audit rows, CHANGELOG (checklist: AGENTS.md §4 step 8).
```

### 3.2 Roles

| Role | Typical actor | Responsibility |
|---|---|---|
| Product owner / maintainer | Human | Accepts specs and ADRs; approves bake-off decisions; verifies judgments |
| Spec author | Agent or human | Writes specs from architecture + plan |
| Implementer | Agent | Implements an Accepted spec within named crates |
| Benchmark runner | Agent on reference hardware, or human | Runs `seeky-bench`, writes reports |
| Reviewer | Agent + human | Checks spec conformance, invariants, evidence |

WPs marked **[human]** need a human input (hardware, judgments, a decision);
everything else is agent-ready once its spec is Accepted.

### 3.3 Work package format

Each WP below lists: goal, spec, dependencies, deliverables, and exit evidence.
WPs inside a phase may run in parallel unless a dependency says otherwise; two
WPs that edit the same crate module are sequenced by the maintainer.

## 4. Baseline and gap analysis (as built, 0.1.0)

| Area | As built | Gap to target |
|---|---|---|
| Structure | Single Tauri crate `apps/seeky/src-tauri`; engine and UI coupled | Engine-first workspace (Phase 0) |
| Storage | One SQLite connection behind a mutex; FTS5; f32 BLOBs | Single-writer actor + WAL readers; pluggable indexes; generations (Phase 2–3) |
| Retrieval | Chunk-level BM25 + filename + exact cosine + RRF | Query routing, document layer, dedupe, length correction, reranking, diversity, snippets, progressive stages (Phase 4) |
| Models | `gety-embed-v0` read from a Gety install; `DIM = 384` hardcoded | Manifest-driven, benchmark-selected models (Phase 2) |
| Inference | ORT CPU, ORT CUDA, native OpenVINO NPU (two engines) | ONNX Runtime only (ADR-0019), validated by WP-0.6; CPU-first session design; NPU via ORT EPs; CUDA frozen (Phases 0, 2, 5) |
| Indexing | Full scan + watcher; size/mtime skip; per-file transactions | Durable jobs, two-speed lanes, embedding cache, reconcile, governor (Phase 3) |
| Extraction | PDFium, DOCX, XLSX, PPTX, HTML, text; char-based chunks | Structured blocks, locators, more formats, fuzzing, token/structure-aware chunks, OCR (Phase 3) |
| Evaluation | None | Harness, SDC corpus, public sets, perf harness, B0 (Phase 1) |
| Distribution | `--no-bundle` exe + LFS OpenVINO IR | Slim installer, signed R2 assets, lexical-first (Phase 6) |
| UI | Dark-only, English-only, backend picker on main settings | en/pt, light/dark, progressive results, diagnostics hidden (Phase 7) |
| Tests | 9 Rust tests: 4 hardware-free, 5 behind the `hw-tests` feature (local assets/hardware) | CI matrix, property/fuzz/integration/E2E, smoke eval gate |

Verified PoC evidence: [`../validation/seeky-poc-validation.md`](../validation/seeky-poc-validation.md).
Conformance of the PoC with the ADRs, including deviations not listed above
(mixed vector spaces across backends, indexing blocked without a model, search
waiting on indexing locks, arbitrary-path file opening) and the WP that closes
each one: [`../validation/poc-conformance-audit.md`](../validation/poc-conformance-audit.md).

## 5. Target architecture (summary)

```text
apps/desktop (Tauri shell, React UI)  ──commands/channels──►  seeky-engine
                                                                 │
     ┌─────────────── seeky-search ◄────────────┐                │
     │  query routing · retrieval · fusion ·     │                │
     │  document layer · rerank · diversity ·    │      scheduler · watcher · reconcile
     │  snippets · progressive stages            │      two-speed indexing pipeline
     └──────┬──────────────────────┬────────────┘                │
            ▼                      ▼                              ▼
       seeky-store            seeky-infer                   seeky-extract
  SQLite (truth) · lexical ·  ORT sessions · EPs ·      extractors · lang ID ·
  filename · vectors · cache  manifests · tokenizers    chunker · OCR adapter
            ▲
     seeky-provision (assets)      seeky-eval + tools/seeky-bench (measurement)
```

Details: [overview](../architecture/overview.md) ·
[indexing](../architecture/indexing.md) ·
[retrieval engine](../architecture/retrieval-engine.md) ·
[inference and models](../architecture/inference-and-models.md) ·
[provisioning](../architecture/distribution-and-provisioning.md).

## 6. Roadmap overview

| Phase | Name | Version | Track | Depends on |
|---|---|---|---|---|
| 0 | Foundations: engine extraction, CI, ORT validation gate | 0.2.0 | Engine | — |
| 1 | Measurement first: harness, corpus, baseline B0 | 0.2.x | Engine | 0 |
| 2 | Engine core v2: model abstraction, storage, component bake-offs | 0.3.0 | Engine | 1 |
| 3 | Indexing engine v2 | 0.4.0 | Engine | 2 |
| 4 | Ranking engine v2: hierarchical and progressive | 0.5.0 | Engine | 2 (3 for dedupe signatures) |
| 5 | NPU acceleration | 0.5.x | Acceleration | WP-2.1 |
| 6 | Slim provisioning and distribution | 0.6.0 | Distribution | WP-2.1 (6.1–6.3), WP-2.6 (6.4) |
| 7 | Desktop experience | 0.7.0 | UX | Phase 0 (7.1, 7.2), WP-4.3 (7.3) |
| 8 | Scale, hardening, cross-platform (beta) | 0.9.0 | All | 3, 4, 5, 6, 7 |
| 9 | Release 1.0 | 1.0.0 | All | 8 |
| 10 | Visual retrieval (optional pack) | 1.1.0, or 1.0 if pulled in | Visual (optional) | WP-2.13; 3, 4, 6 (10.1–10.2 can start after WP-1.3 and WP-2.2) |

Critical path: **0 → 1 → 2 → 3 ∥ 4 → 8 → 9**. Tracks Acceleration,
Distribution, and UX run in parallel once their dependencies land. Phase 10 is
**off the 1.0 critical path** ([ADR-0023](../adr/0023-multimodal-ready-engine.md));
its only Phase 2 cost is WP-2.13 (modality-aware contracts).

```text
Phase 0 ─► Phase 1 ─► Phase 2 ─┬─► Phase 3 ─┐
   │                    │      └─► Phase 4 ─┼─► Phase 8 ─► Phase 9
   │                    ├─► Phase 5 ────────┤
   │                    └─► Phase 6 ────────┤
   └─► Phase 7 (7.1–7.2 early; rest after WP-4.3) ┘

Phases 3 + 4 + 6 ─► Phase 10 (optional visual pack; 10.1–10.2 screening may start early)
```

---

## 7. Phases and work packages

### Phase 0 — Foundations: engine extraction, CI, ORT validation gate

**Goal:** make the engine a headless, testable workspace without changing
behavior, give agents a reliable build/test loop, and validate the inference
engine before anything is built on it (priority zero).

| WP | Work package | Spec | Depends | Deliverables |
|---|---|---|---|---|
| 0.1 | Cargo workspace skeleton; shared lints (`clippy` pedantic subset, `unsafe_code = "deny"` outside audited modules), profiles, toolchain pin; rename `apps/seeky` → `apps/desktop` (update paths in `.githooks/pre-commit` and `.github/workflows/ci.yml`) | SPEC-0001 | — | `Cargo.toml` workspace, `rust-toolchain.toml`, crate stubs |
| 0.2 | Extract engine crates from the PoC (`core`, `extract`, `infer`, `store`, `search`, `engine`) with **no behavior change**; add a golden search test (fixed corpus → identical ranked output) | SPEC-0001, SPEC-0002 v1 | 0.1 | Crates; PoC tests pass in new locations; golden test |
| 0.3 | Tauri shell becomes a thin adapter over the `Engine` API; no SQLite/model/filesystem access from the shell; files are opened by document ID, never by a path supplied by the webview (audit A8) | SPEC-0002 v1 | 0.2 | `apps/desktop/src-tauri` reduced to commands + wiring |
| 0.4 | CI: format checks (rustfmt + Prettier, `format` job and pre-commit hook), clippy `-D warnings`, hardware-free tests, `cargo-deny` (licenses/advisories/bans), TypeScript typecheck + build; compile check on Windows, Linux, macOS; hardware tests behind a feature flag | — | 0.1 | CI workflow; green on `main` |
| 0.5 | Process scaffolding: AGENTS.md, ADR/spec/report templates, PR template | — | — | `AGENTS.md`, `CLAUDE.md`, templates, PR template |
| 0.6 | **[human: T1 access or T1-emulated profile] Priority zero — ORT validation gate:** first version of `tools/model-export`; one representative model per role (two embedders, a reranker, a PP-OCR-class pipeline, a ~1B transcription VLM as split graphs) exported to ONNX in fp32/int8/int4 variants; parity; speed, RSS, load time, and runtime size on T1 CPU-only; Intel NPU through the OpenVINO EP; kill criteria K1–K4 ([methodology §8.7](../benchmarks/methodology.md)) | report | — | Gate report in `docs/benchmarks/results/`; ADR-0019 stands, or WP-2.3 is triggered for the failing role |

**Exit evidence:** golden test identical before/after; app runs from
`apps/desktop`; `cargo tree` shows no engine crate depending on `tauri`; CI
green; WP-0.6 gate report committed with its outcome.

### Phase 1 — Measurement first: harness, corpus, baseline

**Goal:** be able to measure quality and performance of any pipeline
headlessly, and measure where the PoC stands (B0). No ranking work starts
before this phase exits.

| WP | Work package | Spec | Depends | Deliverables |
|---|---|---|---|---|
| 1.1 | `seeky-eval`: BEIR-layout + SDC loaders, graded qrels, nDCG/MRR/Recall/Success, duplicate and diversity metrics, paired randomization/bootstrap, JSON + Markdown report writer | SPEC-0003 | 0.2 | Crate with unit-tested metrics (checked against reference values) |
| 1.2 | `tools/seeky-bench`: `index`, `eval`, `perf`, `compare`, `report` over the `Engine` API; environment capture; config hashing | SPEC-0003 | 1.1, SPEC-0002 v1.1 evaluation extension (accepted) | CLI; reproducible runs |
| 1.3 | SDC generator v1 from pinned, redistributable sources; format renderers (incl. scanned variants); duplicate/version/boilerplate injection; `sdc-smoke` committed, `sdc-s` generated | SPEC-0004 | 0.2 | `bench/corpora/sdc/` |
| 1.4 | **[human]** Queries and graded document/passage judgments v1 (≥ 600 queries, 9 categories, dev/test split); LLM-drafted items human-verified | SPEC-0004 | 1.3 | `bench/qrels/` |
| 1.5 | Public dataset scripts (MLDR, MIRACL, mMARCO-pt with constructed pt↔en pairs, Quati after license check, BEIR subsets) | SPEC-0003 | 1.1 | `bench/datasets/` manifests + scripts |
| 1.6 | Perf harness: per-stage latency, query-embedding latency, throughput, time-to-searchable, interference, RSS, disk, startup | SPEC-0003 | 1.2 | `seeky-bench perf`; inherits the SPEC-0002 v1.1 evaluation extension |
| 1.7 | **[human: T1 access]** **B0 report**: PoC pipeline vs BM25-only, dense-only, filename-only, Gety-style 0.2/0.8 reference; all budgets measured; then **lock budgets** by ADR | — | 1.3–1.6 | `docs/benchmarks/results/<date>-baseline-b0/`, ADR "Locked budgets v1" |
| 1.8 | CI smoke gate: `sdc-smoke` nDCG@10 over the eight non-code categories (≤ 1.0 drop vs `main`) + ranking invariants; code-enabled results reported separately | SPEC-0003 | 1.2, 1.3, 1.4 (`sdc-smoke-v1` verified) | CI job |

**Pre-WP-1.2 evaluation API extension:** before WP-1.2, WP-1.6, or B0 claims
results, accept a behavior-preserving SPEC-0002 v1.1 extension providing
evaluation result depth ≥100 (recommended ≤1,000), read-only stage and
query-embedding telemetry, and structured metadata filters. Default single-stage
search and all product behavior remain unchanged until progressive API v2.

**Exit evidence:** B0 report committed; budgets locked; CI smoke gate active.

### Phase 2 — Engine core v2: model abstraction, storage, component bake-offs

**Goal:** replace PoC shortcuts with the model-agnostic runtime and pluggable
storage, then select the core components by bake-off.

| WP | Work package | Spec | Depends | Deliverables |
|---|---|---|---|---|
| 2.1 | Model manifest (ONNX variants per precision and provider); `Embedder`/`Reranker`/`OcrEngine` traits; ONNX Runtime latency vs throughput sessions; greedy decode loop for transcription models; tokenizer from manifest; parity tests; remove `DIM = 384` and Gety path discovery (dev overrides only) | SPEC-0005 | Phase 1 | `seeky-infer` v2 |
| 2.2 | `tools/model-export` v2 and the **bake-off toolchain**: ONNX export (incl. split graphs for transcription models), quantization matrix (fp16, int8 dynamic/QDQ, int4), provider variants, parity vectors, `model.toml`; Stage A screening runner (reference runtime, cached outputs scored by `seeky-eval`); `seeky-bench bakeoff` | SPEC-0005 | 2.1, 1.2, 0.6 | Reproducible export + screening scripts ([methodology §8](../benchmarks/methodology.md)) |
| 2.3 | **Conditional — only if WP-0.6 fires a kill criterion:** challenger-engine bake-off for the failing role only (llama.cpp/GGUF, native OpenVINO IR, …), with full deployment cost and the new-engine margin ([methodology §8.6](../benchmarks/methodology.md)) | report | 0.6, 2.2 | Report + superseding ADR for that role, or confirmation of ADR-0019 |
| 2.4 | Store v2: schema (`files`, `passages`, `jobs`, `generations`, `embedding_cache`, `models`), migration from the PoC DB, single-writer actor, WAL reader pool | SPEC-0006 | Phase 1 | `seeky-store` v2 + migration tests |
| 2.5 | `LexicalIndex`, `FilenameIndex`, `VectorIndex` traits with as-built implementations behind them | SPEC-0006 | 2.4 | Trait-based retrieval adapters |
| 2.6 | **Bake-off: embedding models** (incl. Matryoshka dims, quantization matrix) per [candidates §1](../benchmarks/candidates.md), on ONNX Runtime; multimodal-capable candidates compete on text merit only, with image capability as the ADR-0023 tie-breaker ([methodology §7](../benchmarks/methodology.md)) | report | 2.1, 2.2 (2.3 if triggered) | Report + ADR "Default embedding model" |
| 2.7 | **Bake-off: lexical engine and analyzers** (FTS5 vs Tantivy; pt/en stemming, stopwords, trigram) | report | 2.5 | Report + ADR |
| 2.8 | **Bake-off: filename/path index** | report | 2.5 | Report + ADR |
| 2.9 | **Bake-off: vector store and quantization** (exact, flat int8, binary + rescoring, USearch, sqlite-vec) at `sdc-s` and synthetic 1M | report | 2.5, 2.6 | Report + ADR |
| 2.10 | **Bake-off: chunking grid** (size, overlap, structure-aware, heading-path header) | report | 2.6 | Report + ADR |
| 2.11 | **OCR screening** (Stage 0 + Stage A) over [candidates §5](../benchmarks/candidates.md): license and name verification, then CER/WER, hallucination, and retrieval impact on the OCR screening set in reference runtimes; select ≤ 4 finalists per tier (CPU default, GPU opt-in) | report | 1.1, 1.3, 2.2 | Screening report; finalists for WP-3.8 |
| 2.12 | Implement winners behind traits; **B1 report** (new components, RRF fusion, no new ranking stages) | — | 2.6–2.10 | Report B1 |
| 2.13 | **Modality-aware contracts, no visual model** ([ADR-0023](../adr/0023-multimodal-ready-engine.md)): `modality` and locator on retrieval units and a `visual_units` table; embedding channels with one generation lineage each; manifest `modalities`, `space`, per-component variants, and `[image]` preprocessing; the image capability on `Embedder`; fusion over N retrievers; text-only behavior unchanged | SPEC-0005, SPEC-0006 | 2.1, 2.4 | Contracts + tests proving the text path is unchanged and never opens a vision session |

WP-2.11 runs in parallel with the other bake-offs; it needs no T1 time.
WP-2.13 adds fields and capabilities only; it selects no visual model and
moves no visual work onto the 1.0 critical path.

**Exit evidence:** component ADRs accepted; B1 beats B0 on Q1;
S1/S2 met at `sdc-s` on T1 CPU-only; OCR finalists named.

### Phase 3 — Indexing engine v2

**Goal:** a continuous, resumable, invisible indexer with two-speed lanes.

| WP | Work package | Spec | Depends | Deliverables |
|---|---|---|---|---|
| 3.1 | Durable job queue, scheduler, resource governor (background priority, CPU share, search preemption, battery policy, memory ceiling; modes default/full speed/paused per ADR-0025) | SPEC-0007 | 2.4 | Scheduler + governor |
| 3.2 | Two-speed pipeline: fast lane (metadata, lexical, filename, signatures) and semantic lane (dynamic batching by token length) | SPEC-0007 | 3.1, 2.12 | Pipeline; gates I1, I2, S5 |
| 3.3 | Content-addressed embedding cache; rename/move/copy without re-embedding | SPEC-0007 | 3.2 | Gate I5 + cache hit-rate report |
| 3.4 | Structured extraction (blocks, locators, offsets) for all formats; add ODT, RTF, EPUB, EML/MBOX; extractor bake-off where alternatives exist; document vs source-code file classes with code indexing off by default ([ADR-0024](../adr/0024-source-code-indexing-opt-in.md)) | SPEC-0008 | 2.4 | Extractors + fidelity report |
| 3.5 | Extraction hardening: timeouts, memory caps, panic isolation, `cargo-fuzz` targets per format, malformed-file corpus | SPEC-0008 | 3.4 | Fuzz targets in CI (time-boxed) |
| 3.6 | Startup reconcile (parallel stat walk); bake-off of OS journals (USN, FSEvents) as accelerators | SPEC-0007 | 3.1 | Gate I4; ADR if a journal is adopted |
| 3.7 | Index generations: background blue/green rebuild, promotion, garbage collection | SPEC-0006 | 3.2 | Model swap without search downtime |
| 3.8 | **Bake-off: OCR, Stages B + C** on the WP-2.11 finalists (ONNX export, quantization matrix, O1–O4 on T1 CPU-only; GPU pack measured separately against the methodology §8.6 margin); `OcrEngine` integration as an optional pack with OCR provenance per file | SPEC-0009 | 2.11, 3.4 | Report + ADR (CPU default OCR; GPU pack yes/no); OCR lane |
| 3.9 | Language ID + per-language analyzer wiring | SPEC-0008 | 2.7, 3.4 | Language-aware lexical indexing |

**Exit evidence:** I1–I5 and S5 met at `sdc-s` on T1; fuzzing clean for the
agreed CPU-hours; crash-recovery tests pass; B2 report.

### Phase 4 — Ranking engine v2: hierarchical and progressive

**Goal:** the full retrieval contract, every mechanism ablated, progressive
delivery within budgets.

| WP | Work package | Spec | Depends | Deliverables |
|---|---|---|---|---|
| 4.1 | Refactor into `seeky-search` stage modules; `RankingConfig`; property tests for the invariants | SPEC-0010 | 2.12 | Stage pipeline; invariants green |
| 4.2 | Query analysis and routing (quoted, identifier, filename-like, inline filters incl. pt/en dates, query class) | SPEC-0010 | 4.1 | Router + per-category report |
| 4.3 | Progressive search sessions (Instant/Hybrid/Refined), cancellation, query-embedding LRU | SPEC-0002 v2 | 4.1 | Gates S1, S2, S4 |
| 4.4 | Document layer: grouping, candidate caps, aggregation (signal ablations) | SPEC-0010 | 4.1 | Ablation report |
| 4.5 | Near-duplicate detection and collapsing (index-time SimHash, passage dedupe, boilerplate down-weighting) | SPEC-0010 | 4.4, 3.2 | Gate Q4 |
| 4.6 | Length-bias correction (BM25 tuning, dense/rerank calibration, document prior) | SPEC-0010 | 4.4 | Ablation report |
| 4.7 | **Bake-off: fusion** (RRF variants, convex combination, query-class weights) | report | 4.2 | Report + ADR (supersedes ADR-0003 only if a challenger wins) |
| 4.8 | **Bake-off: reranker** + integration (adaptive budget, score cache, fail-open, CPU vs NPU-only decision) | report | 4.4 | Gate Q6; ADR |
| 4.9 | Diversity (MMR) and final per-document limits | SPEC-0010 | 4.8 | Gate Q7 |
| 4.10 | Snippet engine + **bake-off: snippet scorer** (heuristic, bi-encoder, cross-encoder) | SPEC-0011 | 4.8 | Snippet report; ADR |
| 4.11 | *(gated)* **Bake-off: learned sparse retrieval** | report | 4.7 | Report; adopt only if it wins at equal latency |
| 4.12 | **B3 report**: full pipeline + leave-one-out ablations of every mechanism at `sdc-m` | — | 4.1–4.10 | Report B3 |

**Exit evidence:** Q1–Q7 and S1–S4 met at `sdc-m` on T1 CPU-only; every
mechanism has an ablation result; failing mechanisms ship disabled by config.

### Phase 5 — NPU acceleration (parallel track)

| WP | Work package | Spec | Depends | Deliverables |
|---|---|---|---|---|
| 5.1 | Execution-provider abstraction: hardware detection, parity-on-load, measured power-aware per-workload selection (ADR-0025), CPU fallback | SPEC-0012 | 2.1 | Provider layer |
| 5.2 | **[human: hardware]** Intel NPU: OpenVINO EP vs PoC native OpenVINO bake-off; shape buckets; compiled-model cache | SPEC-0012 | 5.1 | Report + ADR (native path kept only if it wins) |
| 5.3 | **[human: hardware]** Qualcomm QNN EP (Snapdragon X, Windows ARM64) | SPEC-0012 | 5.1 | Report |
| 5.4 | **[human: hardware]** AMD VitisAI EP (Ryzen AI) | SPEC-0012 | 5.1 | Report |
| 5.5 | Apple CoreML EP (with Phase 8 macOS port) | SPEC-0012 | 5.1 | Report |
| 5.6 | Windows ML as an EP supplier: evaluation | SPEC-0012 | 5.1 | Report + decision |
| 5.7 | Freeze the PoC CUDA path: remove from auto-selection and defaults; keep code only behind a dev feature until removal | — | 5.1 | ADR-0016 compliance |

**Exit evidence:** at least Intel NPU validated with vector parity; auto mode
never selects a provider slower than CPU for a workload; R6 met with compiled
caches; energy per 1k passages reported.

### Phase 6 — Slim provisioning and distribution (parallel track)

| WP | Work package | Spec | Depends | Deliverables |
|---|---|---|---|---|
| 6.1 | Manifest schema v2, Ed25519 signing, CI-only publishing pipeline to R2 | SPEC-0013 | 2.1 | Schema, signer, publisher |
| 6.2 | `seeky-provision`: resumable download, verify, atomic install, versioned cache, repair, offline bundle import | SPEC-0013 | 6.1 | Crate + fault-injection tests |
| 6.3 | Capability model: lexical-first availability, semantic coverage per root, capability events | SPEC-0013, SPEC-0002 | 6.2, 3.2 | ADR-0018 behavior |
| 6.4 | Remove Gety dependency, bundled IR, and model LFS rule; PDFium in installer | SPEC-0013 | 2.6, 6.2 | Clean repository; D1 measured |
| 6.5 | License and notice pipeline (`cargo-deny`, asset notices, third-party notices view) | SPEC-0013 | 6.1 | Notices shipped with every asset |
| 6.6 | **[human: VMs]** Clean-machine validation: Windows x64 CPU-only, Windows x64 + Intel NPU, Windows ARM64 + Qualcomm NPU | — | 6.2–6.5 | Validation record |

**Exit evidence:** provisioning acceptance criteria pass; D1/D2 met; no request
contains user data (verified by traffic capture).

### Phase 7 — Desktop experience (parallel track)

| WP | Work package | Spec | Depends | Deliverables |
|---|---|---|---|---|
| 7.1 | i18n: en/pt catalogs, OS-locale detection, English fallback, CI catalog-parity check | SPEC-0014 | Phase 0 | No hardcoded strings |
| 7.2 | Light/dark themes, OS default, override, contrast checks | SPEC-0014 | Phase 0 | Themes |
| 7.3 | Progressive results UI over Tauri channels; stable reordering between stages; keyboard-first navigation; instant cancellation | SPEC-0014 | 4.3 | Search view v2 |
| 7.4 | Folders view: lexical/semantic coverage, health, pause/resume, exclusions | SPEC-0014 | 3.2, 6.3 | Folders view |
| 7.5 | Filters UI (folder, type, date, size) pushed into retrieval | SPEC-0014 | 4.2 | Filters |
| 7.6 | Settings and advanced diagnostics (providers, models, generation, self-check); "Index source code" control, off by default (ADR-0024) | SPEC-0014 | 5.1, 6.3 | Settings |
| 7.7 | Preview with highlights; open file at locator where supported | SPEC-0014 | 4.10 | Preview |
| 7.8 | Accessibility pass; component tests with mocked IPC; E2E smoke via WebDriver | SPEC-0014 | 7.1–7.7 | UI test suite |
| 7.9 | Strict Content Security Policy | SPEC-0014 | 7.3 | CSP enabled |

**Exit evidence:** UX acceptance (keyboard, screen reader essentials,
contrast, no untranslated strings, diagnostics off the default screen, search
usable during indexing).

### Phase 8 — Scale, hardening, cross-platform (0.9 beta)

| WP | Work package | Depends | Deliverables |
|---|---|---|---|
| 8.1 | `sdc-m` (1M passages) full budget run on T0/T1; L-scale exploration (ANN only if flat scans miss budget) | 4, 5 | Report; ADR if ANN adopted |
| 8.2 | Soak (72 h watcher churn), crash-injection during commits, integrity checks, idle maintenance (vacuum/compaction) | 3 | Hardening report |
| 8.3 | macOS port (FSEvents, CoreML EP, Vision OCR) and Linux port (inotify, PP-OCR) | 3, 5 | Platform validation |
| 8.4 | Security review: fuzz hours, dependency audit, path handling, CSP, asset loading | 3, 6, 7 | Review record |
| 8.5 | Energy and battery policy tuning (CPU vs NPU) | 5 | Report |

### Phase 9 — Release 1.0

| WP | Work package | Spec | Deliverables |
|---|---|---|---|
| 9.1 | Installers (Windows MSI/NSIS, macOS DMG, Linux AppImage/deb), code signing, reproducible builds, SHA-256 | SPEC-0015 | Signed artifacts |
| 9.2 | Release checklist: budgets, quality gates, reports, licenses, CVEs, notes, manifest published together | SPEC-0015 | Checklist executed |
| 9.3 | User documentation (en/pt): getting started, privacy, troubleshooting | — | Docs |
| 9.4 | **1.0 GA gate**: all locked budgets and Q gates on the T0/T1 matrix | — | GA report |

### Phase 10 — Visual retrieval (optional pack)

**Goal:** text-to-image and image-to-image search as an optional pack that
never weakens the text engine ([ADR-0023](../adr/0023-multimodal-ready-engine.md)).
Off the 1.0 critical path; the maintainer decides whether it ships in 1.0 or
1.1.

| WP | Work package | Spec | Depends | Deliverables |
|---|---|---|---|---|
| 10.1 | **[human: judgments]** SDC visual slice: photos, screenshots, diagrams and charts, slides, scans with figures; pt/en text queries, cross-language and image-as-query; graded judgments; text categories re-run with the pack on | SPEC-0004 | 1.3, 1.4 | Visual slice + qrels |
| 10.2 | **Visual screening** (Stage 0 + Stage A) over [candidates §14](../benchmarks/candidates.md): license review (Gemma Prohibited Use Policy; Nomic vision license), reference-runtime quality on the visual screening set, XM3600 pt/en, MMEB v2 subsets, ViDoRe; configurations A/B/C | report | 2.2, 10.1 | Screening report; ≤ 4 finalists per configuration |
| 10.3 | Write and accept SPEC-0016: visual-unit selection rules, preprocessing, channel layout, fusion and calibration, image-query API, failure semantics | SPEC-0016 | 2.13, 10.2 | Accepted spec |
| 10.4 | **Bake-off: visual architecture, Stages B + C** on T1 CPU-only: ONNX export of vision graphs with Rust preprocessing parity, quantization per component with cross-modal alignment checks, Matryoshka dims, visual token budget, resolution; V1–V5 and Q8 | report | 10.2, 10.3, 2.12 | Report + ADR "Visual architecture and model" (or "pack not shipped") |
| 10.5 | Visual lane in the indexing pipeline (decode, resize, embed under the governor), visual channel generations, visual retriever, rank fusion or calibration, image queries | SPEC-0016 | 10.4, 3.2, 3.7, 4.7 | Engine support; V1, V2, V4, V5 measured |
| 10.6 | Visual-pack provisioning: asset class, manifest entries, notices, repair | SPEC-0013 | 10.4, 6.2 | Pack installable and removable offline-safe |
| 10.7 | UI: image-search setting, locally generated thumbnails, image-as-query input, modality filter; en/pt strings; both themes | SPEC-0014 | 10.5, 7.3 | UI support |
| 10.8 | **B4 report**: full pipeline with and without the pack at `sdc-s` | — | 10.5–10.7 | Report B4 |

**Exit evidence:** Q8 and V1–V5 met on T1 CPU-only; Q2 holds with the pack
enabled; the visual ADR is accepted. If Q8 fails, the pack does not ship and
the WP-2.13 contracts stay in place for a later attempt.

---

## 8. Benchmark program summary

| Bake-off | WP | Decides |
|---|---|---|
| ORT validation gate (priority zero) | 0.6 | Whether ADR-0019 stands (kill criteria K1–K4) |
| Challenger engines (conditional) | 2.3 | Only for a role where a kill criterion fired |
| Embedding models | 2.6 | Default embedder, dimension, precision |
| Lexical engine and analyzers | 2.7 | FTS5 vs Tantivy; stemming/stopwords |
| Filename index | 2.8 | Instant filename/path structure |
| Vector store and quantization | 2.9 | Flat vs HNSW; f32/int8/binary; rescoring |
| Chunking | 2.10 | Size, overlap, structure, headers |
| OCR screening (Stages 0 + A) | 2.11 | OCR finalists per tier |
| Extractors | 3.4 | Per-format extractors |
| OS change journals | 3.6 | Reconcile accelerators |
| OCR deployment (Stages B + C) | 3.8 | CPU default OCR pack; GPU opt-in pack yes/no |
| Fusion | 4.7 | Fusion function and weights |
| Reranker | 4.8 | Default reranker; CPU vs NPU-only |
| Snippet scorer | 4.10 | Heuristic vs model |
| Learned sparse | 4.11 | Whether a sparse retriever joins |
| NPU providers | 5.2–5.6 | Provider per vendor; native OpenVINO fate |
| Visual screening (Stages 0 + A) | 10.2 | Visual finalists per configuration (A/B/C) |
| Visual architecture (Stages B + C) | 10.4 | Unified vs specialized; visual model; pack shipped or not |

Protocol, datasets, statistics, and the decision rule:
[`../benchmarks/methodology.md`](../benchmarks/methodology.md). Seeds:
[`../benchmarks/candidates.md`](../benchmarks/candidates.md). Each bake-off
starts by refreshing the candidate list.

Every model bake-off runs the same funnel
([methodology §8](../benchmarks/methodology.md)), so decisions come from
numbers and stay fast:

| Stage | What happens | Typical cost |
|---|---|---|
| 0 Paper screen | License, languages, size, published formats and ONNX export path, maintenance; kill ineligible candidates | Hours, no compute |
| A Quality screen | Every survivor in its reference runtime on a fixed `dev` screening set; outputs cached; metrics by `seeky-eval`; keep ≤ 4 finalists per tier | ≤ 1 h compute per candidate; agents in parallel |
| B Deployment bake-off | Finalists exported to ONNX and quantized, on T1 CPU-only (+ NPU/GPU tier); parity, speed, memory, deployment cost (runtime and model bytes, code paths) | ≤ 5 days on reference hardware |
| C Confirmation | Top 1–2 deployment variants on SDC `test` + public sets; decision rule; ADR | ≤ 1 day |

A candidate that needs a second inference engine must beat the best ONNX
Runtime candidate by the predeclared new-engine margin
([methodology §8.6](../benchmarks/methodology.md), ADR-0019).

## 9. Testing strategy

| Layer | Tooling | Where |
|---|---|---|
| Unit | `cargo test` | Every crate |
| Property-based | `proptest` (ranking invariants, fusion, dedupe, chunk stability) | `seeky-search`, `seeky-extract` |
| Golden | Fixed corpus → exact ranked output; snapshot of extraction blocks | `seeky-engine`, `seeky-extract` |
| Integration | Engine lifecycle: add root, index, edit/rename/delete, reconcile, crash recovery | `seeky-engine` |
| Fault injection | Disk full, corrupt assets, killed process mid-commit, provider failure | `seeky-store`, `seeky-provision`, `seeky-infer` |
| Fuzzing | `cargo-fuzz` per extractor and manifest parser | `seeky-extract`, `seeky-provision` |
| Quality smoke | `sdc-smoke` eval gate | CI |
| Microbenchmarks | Benchmark harness for hot paths (fusion, scoring, vector scan, tokenization) | Next to code |
| Hardware | ORT CPU parity in CI; NPU tests on labeled runners/manual | `seeky-infer` |
| Frontend | TypeScript strict, component tests with mocked IPC, locale parity, E2E smoke | `apps/desktop` |

## 10. CI/CD and tooling

- **Every PR:** rustfmt + Prettier (also a pre-commit hook), clippy `-D warnings`, tests (hardware-free), `cargo-deny`,
  TypeScript typecheck/build, locale parity, `sdc-smoke` gate, Windows +
  Linux + macOS compile.
- **Nightly/manual on reference hardware:** full evaluation and perf runs;
  reports committed by the benchmark runner.
- **Release:** signed installers, published manifest and assets, checksums,
  notices.

## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| No candidate meets CPU latency for reranking | Weaker refined stage | Adaptive budget; NPU-only rerank; distill a small reranker post-1.0; Hybrid stage is already strong |
| Initial semantic indexing too slow on CPU | Poor first-day experience | Two-speed indexing; priorities; small embedders; NPU throughput; lexical-first availability |
| Small golden set → overfitting | False wins | Dev/test split; few ranking parameters; public sets as cross-checks; significance tests |
| Judgment cost | Slow Phase 1 | LLM-drafted, human-verified judgments; pooling; prioritize test split |
| Extractor crashes on malformed files | App crash, data loss | Fuzzing, timeouts, panic isolation; worker-process ADR if needed |
| NPU driver/EP fragmentation | Flaky acceleration | Parity-on-load; per-vendor validation; CPU always correct |
| Model license surprises | Asset blocked | License gate before bake-off; registry status; ADR-0022 |
| ONNX Runtime proves inadequate for a role (for example VLM OCR decode speed or export) | Second engine or a weaker model | Priority-zero gate (WP-0.6) with predeclared kill criteria; engine hidden behind `seeky-infer` traits; challenger measured only for the failing role (WP-2.3) |
| OCR transcription model hallucinates text | False matches in the index | Hallucination gate O4; deterministic decoding; OCR provenance per file so a better engine re-OCRs only affected files |
| Quantized variant silently loses quality | Hidden regression | Tolerances versus the same model's reference (methodology §8.4); parity vectors on load |
| Vector-space drift on model change | Wrong results | Index generations; never mix vectors; blue/green promotion |
| SQLite ↔ index-file inconsistency after crash | Corrupt results | Generation markers; idempotent rebuild from SQLite + cache |
| R2 outage | First-run semantic delay | Lexical-first; cached manifest; offline bundle |
| Agent drift from contracts | Rework | Accepted specs only; requirement IDs in tests; reviewer checklist; per-WP status with evidence (§15) |
| A multimodal model is chosen for its image support at the expense of text | Core quality or latency regression | WP-2.6 judges text merit only; image capability is a tie-breaker inside the CI and the text budgets (ADR-0023, methodology §7) |
| Visual pack slows indexing or pollutes text results | Worse core experience | Lowest-priority visual lane; budgets V1, V2, V4; Q8 (b) re-runs every text category with the pack on; rank-based fusion; pack off until the user enables it |

## 12. Rejected options (decision log)

Options discussed in earlier documents that this plan deliberately drops:

| Option | Why rejected |
|---|---|
| GPU-first or CUDA as preferred backend | Violates CPU-first; huge downloads (ADR-0016) |
| Qwen3-Embedding-4B/8B or other GPU-class embedders as product tiers | Far beyond CPU budgets; GPU-only value |
| Different embedding models per hardware tier in one index | Breaks the single-vector-space rule |
| Two or more inference engines in the default product | Multiplies binary size, code paths, and test matrix; ONNX Runtime only (ADR-0019); a second engine only via the runtime-cost rule |
| Open three-way engine bake-off before deciding | Weeks of export and integration work to test unlikely winners; replaced by the WP-0.6 gate |
| Treating a file format (GGUF, ONNX, IR) as a model class | Formats carry encoders and decoders alike; ORT is chosen on measured merits and validated by WP-0.6 |
| Optional answer layer / local LLM | Search-only principle (ADR-0021) |
| LLM query rewriting, HyDE, GraphRAG, RAPTOR, agentic RAG | Generative, slow, unnecessary for file search |
| GPU-class OCR VLMs (for example 7B olmOCR) as product tiers | Beyond any CPU budget; kept as offline quality ceilings |
| Python backend | Retired; Python allowed only in offline tooling |
| Vector database servers (Qdrant, Milvus, pgvector), FAISS | Server processes or heavy deps with no gain at target scale |
| MuPDF, GPL/AGPL/NC components, Jina and Provence models | License gate (ADR-0022) |
| Fixed raw-score fusion (Gety 0.2/0.8) | Brittle across corpora; kept only as a reference baseline |
| Blocking search until provisioning completes | Replaced by lexical-first availability (ADR-0018) |
| Public CLI, REST API, MCP | Out of scope (ADR-0008) |
| Manual Reindex as the answer to offline edits | Replaced by startup reconcile |
| Filename/path inside the embedding input | Would force re-embedding on rename |
| DirectML as the universal accelerator | Maintenance-mode API, GPU-centric, Windows-only |
| "Multimodal-first" as a product principle; a unified multimodal model mandatory | Couples text quality to a secondary capability; a shared space still needs per-modality calibration (ADR-0023) |
| Generated image captions or tags to make images text-searchable | Generative content in the index (ADR-0021) |
| Embedding every document page as an image; late-interaction visual document retrieval as a product tier | CPU indexing cost and index size; OCR plus selective visual units cover the value (ADR-0023) |
| Multimodal reranker; audio and video embeddings | No evidence of gain worth the cost; outside the core user jobs (ADR-0023) |

## 13. Open decisions (resolved by bake-offs or the maintainer)

| Decision | Resolved by |
|---|---|
| Whether ONNX Runtime passes its validation gate (K1–K4) | WP-0.6 (WP-2.3 only if a criterion fires) |
| Default embedding model, dimension, precision | WP-2.6 |
| FTS5 vs Tantivy | WP-2.7 |
| Vector store and quantization | WP-2.9 |
| Reranker default on CPU or NPU-only | WP-4.8 (gate Q6) |
| Exact name, weights availability, and license of the OCRia variant to test; OXR-1.0 and MiniCPM-OCR licenses | WP-2.11 Stage 0 + maintainer |
| CPU default OCR model, OCR default on/off | WP-3.8 + maintainer |
| GPU opt-in OCR pack (offered or not) | WP-3.8 (new-engine/OCR margin) + maintainer |
| Native OpenVINO path kept or removed | WP-2.3, WP-5.2 |
| Extraction in-process vs worker process | WP-3.5 fuzz evidence + ADR |
| Windows ML as EP supplier | WP-5.6 |
| Installer formats, signing certificate, manifest key management | SPEC-0015 / SPEC-0013 + maintainer |
| macOS/Linux GA timing | Phase 8 results + maintainer |
| EmbeddingGemma 2 license (Gemma Prohibited Use Policy pass-through) | WP-10.2 Stage 0 (and WP-2.6 if it enters the text bake-off) + maintainer |
| Unified vs specialized visual architecture; visual model; pack shipped or not | WP-10.4 (gate Q8) + maintainer |
| Visual pack in 1.0 or 1.1 | Maintainer, after Phase 8 |

## 14. Definition of Done (any work package)

- Implements an Accepted spec; requirement IDs referenced by tests.
- Crate boundaries respected; no new dependency without license check.
- fmt, clippy, tests, `cargo-deny`, TypeScript build, smoke eval pass.
- Benchmark report attached when quality/performance can change; budgets held.
- ADR written/updated when a default or architectural rule changes.
- User-facing strings localized (en/pt) from Phase 7 on; both themes work.
- No document content, personal paths, or secrets in code, logs, or docs.
- Recorded in the same commit (AGENTS.md §4 step 8): the WP's row in §15.3
  with its evidence, the spec's requirement status, the ADR index, the
  conformance audit rows it closes, and `CHANGELOG.md`.

## 15. Status

This section is the only place that says what is done. Agents read §15.3 to
pick a work package whose dependencies are done (§3.1 step 1), and the commit
that changes a WP's state updates its row in the same commit (§3.1 step 8;
checklist in [AGENTS.md §4](../../AGENTS.md#4-how-to-work-the-sdd--bmdd-loop)
step 8). The §7 tables define work packages and never carry status.

### 15.1 Status values

| Status | Meaning | Required in Evidence / Notes |
|---|---|---|
| Not started | Nothing merged on `main` | — |
| In progress | Some deliverables merged on `main`, others open | Notes: what is done and what remains, precise enough for the next session to resume |
| Blocked | Cannot proceed | Notes: the blocker and who removes it (maintainer, hardware, another WP) |
| Done | Every deliverable merged and the WP's evidence committed | Evidence: spec and version, test or report paths, ADR. Commits are found with `git log --grep "WP-x.y"` (commit trailer, AGENTS.md §9) |
| Not triggered | Conditional WP whose condition did not occur (for example WP-2.3) | Evidence: the report or ADR showing the condition did not fire |
| Dropped | Removed from scope | Evidence: the ADR or plan revision that removed it |

Rules:

1. A WP is **Done** only when all its deliverables (§7) are merged; partial
   delivery is **In progress** with the remainder in Notes.
2. A phase is **Done** when every WP is Done, Not triggered, or Dropped and
   the phase's exit evidence (§7) is committed; the phase row in §15.2 then
   links that evidence.
3. Adding, splitting, or removing a WP in §7 adds, splits, or removes its row
   in §15.3 in the same commit.
4. Changes outside any WP (bug fixes, refactors, docs, tooling) get no row;
   they are recorded in `CHANGELOG.md` and, when they close a finding, in the
   [conformance audit](../validation/poc-conformance-audit.md).

### 15.2 Milestones and phases

| Phase | Status | Notes |
|---|---|---|
| M0 Runnable PoC | Done | 0.1.0 |
| M1 Live incremental index | Done | 0.1.0 |
| Phase 0 | In progress | WP-0.1, WP-0.2, WP-0.3, and WP-0.5 done; WP-0.4 implementation complete and awaiting H4 approval, WP-0.6 open (§15.3). Pre-flight fixes done outside any WP: fmt, clippy `-D warnings`, `hw-tests` feature, HTML fix, Auto is CPU-only until the NPU is validated ([conformance audit](../validation/poc-conformance-audit.md)). SPEC-0001 and SPEC-0002 v1 Implemented; manual Phase 0 app checks remain |
| Phase 1 | In progress | WP-1.1 `seeky-eval` merged (SPEC-0003 R1–R14); WP-1.3 generator merged with R1–R14 and a synthetic `sdc-smoke`, with full-scale `sdc-s` and the external-source scope remaining; SPEC-0002 v1.1 evaluation extension Draft awaits maintainer acceptance (§15.3) |
| Phases 2-9 | Not started | - |
| Phase 10 | Not started | Planned per ADR-0023, accepted 2026-11-27 (optional visual pack; off the 1.0 critical path) |

### 15.3 Work packages

| WP | Status | Evidence | Notes |
|---|---|---|---|
| 0.1 | Done | [SPEC-0001](../specs/SPEC-0001-workspace-and-crate-boundaries.md) v0.1 (R1–R12, R14–R17); root `Cargo.toml`, `rust-toolchain.toml`, `clippy.toml`, `deny.toml`, `crates/seeky-*` stubs, `apps/desktop`; commits: `git log --grep "WP-0.1"` | R13 completes when WP-0.2/WP-0.3 remove the PoC's heavy dependencies from the shell; R18 lands with WP-0.2 |
| 0.2 | Done | [SPEC-0002](../specs/SPEC-0002-engine-api.md) v0.2 (R2–R4, R9–R16); [SPEC-0001](../specs/SPEC-0001-workspace-and-crate-boundaries.md) v0.1 (R13, R18); engine crates `crates/seeky-{core,extract,infer,store,search,engine}`, thin `apps/desktop/src-tauri` shell; golden snapshots `crates/seeky-engine/tests/golden/`; [PR #4](https://github.com/bgeneto/seeky/pull/4); commits: `git log --grep "WP-0.2"` | WP-0.3 still owns `open_document`, the open allowlist, R1/R6 shell halves, and R5/R7/R8; the existing-index manual check remains for Phase 0 exit |
| 0.3 | Done | [SPEC-0002](../specs/SPEC-0002-engine-api.md) v0.2 (R1, R5–R8); thin `apps/desktop/src-tauri` shell; `open_document` resolves IDs through `Engine::document_path`, opens the §5.4 allowlist, reveals source/unknown types, and rejects unknown/stale IDs before any OS action; `deny.toml` heavy wrappers no longer list `seeky-desktop`; tests `open_allowlist_reveals_code_and_unknown_types`, `unknown_document_path_opens_nothing`, `missing_document_path_is_rejected`; [PR #6](https://github.com/bgeneto/seeky/pull/6) | CSP remains WP-7.9; source indexing opt-in remains WP-3.4/WP-7.6; manual PDF, `.py`, existing-index, and theme checks remain for Phase 0 exit |
| 0.4 | In progress | `.github/workflows/ci.yml` (`format`, `lint`, `test`, `deny`, `web`, `compile`), `.githooks/pre-commit`, `deny.toml`; [PR #1](https://github.com/bgeneto/seeky/pull/1) CI and local AGENTS §5 checks | Done: rustfmt + Prettier, clippy `-D warnings` with and without `hw-tests`, hardware-free tests on Windows/Linux, cargo-deny bans/licenses/advisories/sources, TypeScript build, and Windows/Linux/macOS compile jobs. Remaining: maintainer approval of the disclosed license exceptions and advisory ignores (H4), then mark Done |
| 0.5 | Done | `AGENTS.md`, `CLAUDE.md`, `docs/adr/_template.md`, `docs/specs/_template.md`, `docs/benchmarks/_report-template.md`, `.github/pull_request_template.md` | Repository reorganization |
| 0.6 | Not started | — | Fed by the OCR Stage 0 paper screen (§16) |
| 1.1 | Done | [SPEC-0003](../specs/SPEC-0003-evaluation-harness.md) v0.1 (R1–R14); `crates/seeky-eval/` (BEIR and SDC loaders, graded judgments, document and passage nDCG/MRR/Recall/Success, duplicate and diversity metrics, seeded paired randomization/bootstrap with Holm adjustment, versioned JSON and Markdown reports); reference fixtures `crates/seeky-eval/tests/fixtures/`; [PR #8](https://github.com/bgeneto/seeky/pull/8); commits: `git log --grep "WP-1.1"` | R15–R22, R32 remain with WP-1.2; R23–R24 with WP-1.5; R25–R28 with WP-1.6; R29–R31 with WP-1.8 |
| 1.2 | Not started | — | — |
| 1.3 | In progress | [SPEC-0004](../specs/SPEC-0004-sdc-corpus-and-judgments.md) R1–R14; `tools/sdc-generator/` (stdlib-only Python 3.12+), `bench/corpora/sdc/`, committed `sdc-smoke` with corpus hash `365511dd…`, 101 generator tests and real-engine renderer round trips; R14 `judgments validate`, `freeze-split`, and `publish` with the canonical drafts quarantine; [PR #7](https://github.com/bgeneto/seeky/pull/7), [PR #10](https://github.com/bgeneto/seeky/pull/10) | Remaining: materialize full-scale `sdc-s` once to prove the §4.4 range and decide the external public-domain/CC-BY source scope with maintainer license review; `sdc-m` is validated at reduced scale, JPEG scans and four future extractors remain deferred |
| 1.4 | Not started | — | — |
| 1.5 | Not started | — | — |
| 1.6 | Not started | — | — |
| 1.7 | Not started | — | — |
| 1.8 | Not started | — | — |
| 2.1 | Not started | — | — |
| 2.2 | Not started | — | — |
| 2.3 | Not started | — | Conditional on a WP-0.6 kill criterion |
| 2.4 | Not started | — | — |
| 2.5 | Not started | — | — |
| 2.6 | Not started | — | — |
| 2.7 | Not started | — | — |
| 2.8 | Not started | — | — |
| 2.9 | Not started | — | — |
| 2.10 | Not started | — | — |
| 2.11 | Not started | — | — |
| 2.12 | Not started | — | — |
| 2.13 | Not started | — | — |
| 3.1 | Not started | — | — |
| 3.2 | Not started | — | — |
| 3.3 | Not started | — | — |
| 3.4 | Not started | — | — |
| 3.5 | Not started | — | — |
| 3.6 | Not started | — | — |
| 3.7 | Not started | — | — |
| 3.8 | Not started | — | — |
| 3.9 | Not started | — | — |
| 4.1 | Not started | — | — |
| 4.2 | Not started | — | — |
| 4.3 | Not started | — | — |
| 4.4 | Not started | — | — |
| 4.5 | Not started | — | — |
| 4.6 | Not started | — | — |
| 4.7 | Not started | — | — |
| 4.8 | Not started | — | — |
| 4.9 | Not started | — | — |
| 4.10 | Not started | — | — |
| 4.11 | Not started | — | Gated |
| 4.12 | Not started | — | — |
| 5.1 | Not started | — | — |
| 5.2 | Not started | — | — |
| 5.3 | Not started | — | — |
| 5.4 | Not started | — | — |
| 5.5 | Not started | — | — |
| 5.6 | Not started | — | — |
| 5.7 | Not started | — | — |
| 6.1 | Not started | — | — |
| 6.2 | Not started | — | — |
| 6.3 | Not started | — | — |
| 6.4 | Not started | — | — |
| 6.5 | Not started | — | — |
| 6.6 | Not started | — | — |
| 7.1 | Not started | — | — |
| 7.2 | Not started | — | — |
| 7.3 | Not started | — | — |
| 7.4 | Not started | — | — |
| 7.5 | Not started | — | — |
| 7.6 | Not started | — | — |
| 7.7 | Not started | — | — |
| 7.8 | Not started | — | — |
| 7.9 | Not started | — | — |
| 8.1 | Not started | — | — |
| 8.2 | Not started | — | — |
| 8.3 | Not started | — | — |
| 8.4 | Not started | — | — |
| 8.5 | Not started | — | — |
| 9.1 | Not started | — | — |
| 9.2 | Not started | — | — |
| 9.3 | Not started | — | — |
| 9.4 | Not started | — | — |
| 10.1 | Not started | — | — |
| 10.2 | Not started | — | — |
| 10.3 | Not started | — | — |
| 10.4 | Not started | — | — |
| 10.5 | Not started | — | — |
| 10.6 | Not started | — | — |
| 10.7 | Not started | — | — |
| 10.8 | Not started | — | — |

## 16. Immediate next actions

Kept current by the commit that completes or changes an action: remove
finished items and add the next ones, so this list never points at done work.

1. Maintainer reviews and accepts this plan (the
   [vision](../product/vision.md) and ADR-0015 to ADR-0023 are Accepted).
2. Run **WP-0.6 (ORT validation gate, priority zero)** — it needs no corpus or
   judgments, only T1 (or T1-emulated) time. WP-0.4 awaits maintainer approval
   of its disclosed license exceptions and advisory ignores (H4).
3. The **SPEC-0002 v1.1 evaluation extension** Draft is merged (PR #9); the
   maintainer must accept it before WP-1.2/WP-1.6. Secure access to a T1
   reference laptop (or define the T1-emulated profile). SPEC-0003 and
   SPEC-0004 are Accepted with maintainer pre-approval in /goal.
4. WP-1.1 (`seeky-eval`) is Done; WP-1.3 now implements R1–R14, leaving only a
   full-scale `sdc-s` materialization and the external-source licensing
   decision. WP-1.5 is in progress. Schedule human time for WP-1.4 judgments,
   including the `sdc-smoke-v1` subset required by WP-1.8; the offline drafting
   route still needs a maintainer decision. WP-1.2 (and its R15–R22, R32) and
   WP-1.6 wait for the accepted SPEC-0002 v1.1 evaluation extension.
5. In parallel (UX track): WP-7.1 and WP-7.2 on the existing UI after Phase 0.
6. Start the OCR **Stage 0 paper screen now** (no code needed,
   [candidates §5](../benchmarks/candidates.md)): confirm the OCRia variant
   name, open-weight availability, each candidate's ONNX export path, and the
   OXR-1.0 and MiniCPM-OCR licenses; its findings choose the VLM for WP-0.6.
