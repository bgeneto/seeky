# Changelog

All notable changes to Seeky are recorded here.

Entries go under **Unreleased** in the same commit as the change
([`AGENTS.md`](AGENTS.md) §4 step 8): anything a user, contributor, or agent
would notice, including product decisions and process rules; pure internal
refactors need none. When a phase's exit evidence is committed, the maintainer
moves the Unreleased entries under that phase's version from the plan's
roadmap (§6), with the date.

## Unreleased

### Added
- WP-1.7 performance prep and Gate H3 approval (`T1-emulated`: CPUs `0-7`,
  `12 GiB` Windows Job Object cap, High Performance): `seeky-bench index` now
  validates SDC corpora directly when frozen qrels are not yet published,
  `seeky-bench perf --queries-file <path>` accepts dev-only query files without
  requiring frozen qrels (rejecting `test`-named or `test`-only files before
  opening the engine), and `tools/seeky-bench/scripts/run-t1-emulated.ps1` plus
  `b0-poc-{cpu,lexical}.json` and `docs/benchmarks/wp17-perf-runbook.md` prepare
  the budget-eligible B0 performance runs.
- WP-1.8 CI smoke gate activation prep (`Smoke gate (WP-1.8)`): pinned and
  SHA-256-verified Linux x64 PDFium (`chromium/8179`, Apache-2.0) cached on
  the runner via `SEEKY_PDFIUM_DLL`, documented OCR absence until WP-3.8,
  and added `--allow-config-change <ADR-NNNN>` (plus maintainer-labeled
  `smoke-rebaseline` PR/dispatch support and runbook
  `docs/benchmarks/smoke-gate-activation.md`) for intentional default changes
  while keeping repeat config equality, R30/R31 invariants, and the `<= 1.0`
  nDCG@10 drop ceiling enforced.
- WP-1.5 public evaluation datasets complete (SPEC-0003 R23–R24): pinned
  `beir-trec-covid`, `mldr-en`, `mmarco-pt`, `mmarco-pt-en`, `mmarco-en-pt`,
  `miracl-es`, and `quati-pt` (CC-BY-4.0) with real upstream/local SHA-256
  digests in `files_root: null` Stage A mode (~2–4 KB manifests) and
  deterministic 50/50 SHA-256 carve-outs for single-split sources, bringing
  `bench/datasets/` to 11 offline-verified public datasets alongside new
  `miracl` and `quati` recipes and streaming `corpus.jsonl` hashing in
  `tools/dataset-fetch/`.
- `seeky-bench compare --gate wp1.8` enforces the WP-1.8 smoke gate
  (SPEC-0003 R29–R31): verified, frozen `sdc-smoke-v1` only; same corpus,
  judgments, config, and environment; no code results; ranking invariants and
  repeat determinism; the candidate's macro nDCG@10 over the eight non-code
  categories may drop at most 1.0 point from `main`. Every outcome is a typed
  gate reason in a `smoke_gate` report. A new `Smoke gate (WP-1.8)` workflow
  runs it on pull requests and stays dormant (a passing notice) until
  `sdc-smoke-v1` is published (H6).
- Desktop light and dark themes (SPEC-0014 R10–R15, WP-7.2). Seeky follows
  the OS theme by default and live; Settings → Theme overrides it (System
  default / Light / Dark), saved locally. The native window and titlebar
  match, and the window stays hidden until the theme is applied, so there is
  no startup flash. All colors come from two semantic token sets checked for
  WCAG 2.2 AA contrast by the new `npm run theme:check`, which CI runs.
- `tools/qrels-drafter` drafts the `sdc-v1` query set offline from templates for
  the six template-faithful categories and the pinned Qwen3-0.6B model for
  `conceptual`, `exploratory`, and `cross_language`. The committed
  `bench/qrels/sdc/drafts/sdc-v1/` holds 732 queries (366 dev / 366 test) and
  2,572 document plus 2,572 passage judgments; every record is an unverified
  draft (`verified_by: []`, `test_exposure: unexposed`), and human verification
  (gate H6) is required before any benchmark-eligible split (WP-1.4,
  SPEC-0004 R15–R22, R25).
- `qrels_drafter draft --smoke` drafts the dev-only `sdc-smoke-v1` set over the
  committed smoke corpus: 45 queries, five per category, 144 document and 144
  passage judgments, no `test` split, and a smoke-specific tool config hash.
  It is the H6 subset that unblocks WP-1.8 and WP-1.2; every record is still an
  unverified draft (SPEC-0004 R26 remains open).
- `seeky-bench perf` measures warm-idle and warm-indexing search latency
  (p50/p95/p99 with fixed-seed bootstrap CIs), batch-1 query-embedding
  latency, bulk indexing throughput, lexical/semantic time-to-searchable, the
  S5 interference ratio, RSS, index size and disk per 1k passages, and cold
  start. It validates `--tier`/`--cpus`/`--memory-limit` against the host,
  records the quiet window, and sets `qualifies_for_budget = false` with an
  explicit reason for every undersampled, non-T1, noisy, or synthetic run
  (WP-1.6, SPEC-0003 R25–R28).
- The desktop UI is localized in English and Portuguese (WP-7.1): it follows
  the OS language, offers a Language preference, falls back to English per
  message, and CI checks catalog parity and runs the frontend unit tests.
- The preview panel can be resized by dragging or with the keyboard, and its
  close button stays visible for long file names.
- The maintainer accepted SPEC-0014 v0.2, an addendum that adds R17: a
  resizable preview panel (drag or keyboard, 300 px to 60% of the content
  area, width kept in `seeky.ui.previewWidth.v1`) to WP-7.1.
- The maintainer accepted SPEC-0006 v0.2 (storage, index backends,
  generations, embedding channels) at gate H7. PoC vectors are dropped on
  migration and re-embedded. A generation is promoted once its coverage
  matches the active one, so the first model turns semantic search on
  progressively. Index components with equal build keys are shared
  between generations under `index/components/<build-key>/`. The Q4–Q14
  defaults stand, and the architecture docs and glossary now match the
  spec.

- `tools/model-export` implements the WP-0.6 ORT validation gate with
  per-gate bounded timeouts (default 1800 s), timeout artifacts that cannot
  produce K1-K4 verdicts, parity/quantization/NPU/OCR/VLM probes, and
  preregistered kill criteria. The final K1–K4 report
  (`docs/benchmarks/results/2026-11-27-ort-gate/summary.md`) finds: K1 fires
  for the embedder and reranker proxies (the supplementary Bekko and gety
  embedders meet the embedder targets on ORT; no measured cross-encoder comes
  within 20× of the depth-50 / 250 ms reranker budget); PP-OCRv6 tiny replaces
  PP-OCRv5 mobile as the OCR proxy and passes O1 and O3, with O2 passing only
  on the new isolated `ocr-memory` probe; Florence-2-large is out of the CPU
  tier; K3 fires (the NPU runs the fp32 embedder but misses parity); K4 does
  not fire because the models alone exceed D2. The NPU gate now needs the
  pinned `openvino` wheel (telemetry opted out). H5 is the maintainer's.
- `seeky-bench` implements WP-1.2: `index`, `eval`, `perf` (skeleton),
  `compare`, and `report`; environment capture and semantic config hashing;
  atomic, reproducible artifacts; fail-closed depth; test confirmation and an
  exposure ledger; exact metadata filters with pushdown/post reporting. The
  engine gains the accepted SPEC-0002 v1.1 evaluation API: depth to 1,000,
  deterministic order, stage telemetry, an uncached query-embedding probe,
  structured filters, and a config snapshot, plus an additive lexical-only
  constructor and `Embedder` identity seam for the harness.
- The maintainer accepted the SPEC-0002 v1.1 evaluation extension (R17-R25:
  evaluation depth to 1,000, stage and query-embedding telemetry, exact
  metadata filters, configuration snapshot) with its §9.7 proposals as
  written. WP-1.2 (`seeky-bench`) and WP-1.6 may start.
- The maintainer accepted SPEC-0014 v1 at gate H2: English/Portuguese
  localization through an in-house module with no production i18n library,
  one `pt` catalog with `pt-BR` formatting, and light/dark themes. WP-7.1
  and then WP-7.2 may start.
- The maintainer approved the `deny.toml` license exceptions (bzip2-1.0.6,
  Apache-2.0 WITH LLVM-exception, BSL-1.0) and the seven temporary advisory
  ignores at gate H4; WP-0.4 is Done.
- Full-scale `sdc-s` was generated and verified: 10,000 rendered files,
  109,689 passages, 112.5 MB, corpus hash `1d65b8ff…`. The tree is generated
  on demand and remains uncommitted.
- `tools/dataset-fetch` and `bench/datasets/` pin four download-only public
  datasets (SciFact, NFCorpus, FiQA, and MLDR-pt) with versioned manifests,
  upstream and local hashes, license/terms notices, offline verification, and
  deterministic BEIR transforms. No bulk data is committed; cross-lingual and
  large-corpus pins remain blocked.
- `sdc-generator judgments validate|freeze-split|publish` implement the
  SPEC-0004 judgment-set lifecycle: draft quarantine, offline schema and
  target-hash validation, stratified split freezing with immutable query
  digests, provenance/minima/pool checks, and atomic publication.
- SPEC-0002 has a Draft v1.1 evaluation extension for `seeky-bench`:
  evaluation depth to 1,000 with a deterministic order, in-process stage and
  query-embedding timings, exact metadata filters with push-down/post reporting,
  and a canonical engine configuration snapshot. It is not accepted and changes
  no v1 behavior.
- `seeky-eval` implements the SPEC-0003 evaluation harness for WP-1.1: BEIR and
  SDC loaders, graded document and passage judgments, document and passage
  nDCG/MRR/Recall/Success, duplicate and diversity metrics, seeded paired
  randomization and bootstrap statistics with Holm adjustment, and versioned
  JSON and Markdown reports. It depends on no engine, UI, Tauri, or hardware
  code.

### Fixed

- `seeky-eval` now loads published judgments drafted by a tool: it accepted no
  `tool_config_sha256` provenance field and would have rejected every
  tool-drafted record of `sdc-smoke-v1` and `sdc-v1`. A tool draft without that
  hash is still refused.
- HTML and HTM files are extracted again; extraction previously failed for every
  HTML file because of an unsupported regular-expression backreference.

### Changed

- `compare --gate wp1.8` now writes a `smoke_gate` report (candidate quality,
  gate row, run, and config snapshot) instead of a `comparison` report, and
  always records a gate row, including for incompatible inputs; paired
  statistics come from `compare` without `--gate`.
- The report's `performance` object follows SPEC-0003 §4.10:
  `query_embedding` is `{batch, samples, latency_ms}`, RSS values may be null,
  and `warnings` lists every unavailable or not-budget-eligible value (schema
  version unchanged; no committed report had a performance payload).
  SPEC-0003 0.2 corrects the §5.8 D disk-per-1k reference to 2,500,000 and
  names the interference-ratio bootstrap keys.

- SPEC-0004 0.2 accepts `tool:<id>@<version>` draft provenance with
  `tool_config_sha256`. Tool drafts are candidate data only: they have no
  authority over a relevance grade, and every item still requires human
  verification (H6). LLM drafting remains offline with local, permissively
  licensed open-weight models.
- SPEC-0004 0.3 limits tool drafts to the template-faithful categories
  (`known_item`, `exact_identifier`, `needle_in_haystack`,
  `mixed_semantic_metadata`, `filename_partial`, `code_search`) and never a
  `cross_lingual` slice; `judgments validate` rejects a tool draft for a
  semantic paraphrase or a pt↔en pair.
- Added the deterministic SPDX-clean SDC generator and committed a 200-file,
  3.7 MB synthetic `sdc-smoke` corpus with all fourteen renderer formats,
  canonical passages, extraction truth, duplicates, versions, boilerplate, and
  a disjoint opt-in code root. `sdc-s` is generated on demand and not committed.
- Search results open through the engine by document ID instead of sending a
  file path from the webview. Source code and other non-document formats are
  revealed in the system file manager, and stale index entries return an error
  (SPEC-0002, ADR-0024).
- ADR-0025 (Accepted): the execution provider is chosen automatically per
  workload (measured, power-aware, never a fixed order); the model is never
  chosen automatically. Adds a temporary, user-started "Full speed" indexing
  mode and an opt-in GPU quality tier (reranker first, embedder only with
  CPU query fallback). Recorded in a partial SPEC-0007 draft (governor
  modes) and in SPEC-0014 §7.3 as forward decisions for UI v2.
- Candidate registry: the third-party ONNX exports of Qwen3-Embedding-0.6B
  and Qwen3-Reranker-0.6B (n24q02m) are recorded as as-deployed variants of
  the existing ceiling entries; jina-embeddings-v5-text-nano is recorded as
  excluded (CC-BY-NC-4.0, ADR-0022).
- The PoC engine is extracted into `seeky-core`, `seeky-extract`,
  `seeky-infer`, `seeky-store`, `seeky-search`, and `seeky-engine` behind the
  `Engine` API (SPEC-0002). The Tauri crate now only resolves paths, forwards
  events, and maps commands. Ranking is unchanged (golden lexical and CPU
  hybrid runs); library error messages shown in the UI may differ because
  libraries now use `thiserror`.
- CI now enforces clippy `-D warnings` (including `hw-tests` code),
  hardware-free tests on Windows and Linux, cargo-deny bans, licenses,
  advisories, and sources, the TypeScript build, and compilation on Windows,
  Linux, and macOS. `deny.toml` implements ADR-0022; its scoped license
  exceptions and temporary advisory ignores await maintainer gate H4 (WP-0.4).
- The repository is a Cargo workspace (SPEC-0001): engine crate stubs under
  `crates/`, the app moved from `apps/seeky` to `apps/desktop`, the Rust
  toolchain is pinned to 1.99.1, and Rust checks run from the root
  (`cargo test --workspace`). The executable is still `seeky.exe`, now built
  into `<repo>/target/`; the app identity and data folder are unchanged.
- Crate boundaries are checked with `cargo deny check bans` (`deny.toml`).
- Agent briefs for the parallel waves after WP-0.1 (orchestrator prompt,
  worker preamble, one brief per lane, maintainer gates) are in
  `docs/plans/agent-briefs.md`.
- Auto backend selection uses the CPU only: ADR-0016 allows automatic
  NPU use only once the NPU path is validated (WP-5.1/WP-5.2). NPU and CUDA
  remain available when chosen explicitly.
- Search budgets renamed P1–P5 → S1–S5 so they no longer collide with the
  product principles P1–P8.
- Extraction regular expressions are compiled once instead of per file and per
  text run.
- Tests that need local model files, PDFium, CUDA, or an NPU run only with the
  `hw-tests` cargo feature; `cargo test` is hardware-free.
- Code formatted with `rustfmt`; `cargo clippy -- -D warnings` passes.
- Formatting is enforced: `rustfmt.toml` and Prettier (pinned dev
  dependency, `npm run format` / `format:check`) with a check-only
  pre-commit hook enabled by `npm install`, and a CI `format` job.
  Frontend sources reformatted with Prettier (no behavior change).

### Product decisions

- Evaluation judgments may be verified by a model instead of a human
  (ADR-0026, SPEC-0004 0.4): `verified_by` and `adjudicated_by` accept
  `llm:<model-id>@<pinned-snapshot>` reviewers in `judgments validate`,
  `freeze-split`, `publish`, the `seeky-eval` loader, and the WP-1.8 gate, with
  no mandatory human sample. A model never verifies its own draft, and a hosted
  model may review only synthetic, redistributable corpora such as SDC. The
  versioned reviewer instruction is
  [`docs/benchmarks/judgment-review-prompt.md`](docs/benchmarks/judgment-review-prompt.md);
  reports on a model-verified set name the reviewer and the prompt version.
- Source code is indexed only when the user turns on "Index source code"
  (off by default), and source files are never opened with the OS default
  handler; Seeky reveals them in the file manager instead (ADR-0024).
- Seeky source is now MIT-licensed; no account or commercial license key is
  required.
- Target distribution is a slim installer with first-run downloads of runtimes,
  model weights, tokenizers, and native libraries from the public seeky
  Cloudflare R2 bucket.
- UI target is limited to light and dark themes (OS default), with English and
  Portuguese locales from the start.
- UI direction is minimal search-first, with backend/model internals behind an
  advanced diagnostics surface.
- Retrieval target is SOTA multilingual hierarchical neural IR: passage ranking,
  document aggregation, per-document limits, diversity, near-duplicate handling,
  and length-bias correction.
- Added architecture, model strategy, and provisioning documents.
- Principles formalized: CPU-first, NPU-ready, local-first, performance-first,
  multilingual-first, search-only, benchmark-driven, model-agnostic core.
- GPU acceleration is optional and no longer on the default path; NPUs are the
  designed-for accelerator (ADR-0016).
- Filename and lexical search work before model provisioning (ADR-0018).
- The optional answer layer is removed from the roadmap; no generative features
  ship (ADR-0021). OCR may use a transcription model of any architecture,
  including small VLMs, only with deterministic decoding, a fixed prompt, and a
  hallucination gate.
- ADR-0023: image search is planned as an optional, separately
  downloaded visual pack that ships only if its own bake-off passes, and never
  slows text search. The engine's data model, model manifest, and index
  generations become modality-aware from Phase 2. The default text embedding
  model is still chosen on text quality; image support only breaks ties.
- ONNX Runtime is the single inference engine for embeddings, reranking,
  snippet scoring, and OCR (ADR-0019), validated by a priority-zero gate with
  predeclared kill criteria (plan WP-0.6). Challenger engines (llama.cpp/GGUF,
  native OpenVINO) are measured only for a role where a criterion fires; a
  second engine needs a predeclared margin and full deployment-cost
  accounting.
- GPU support may come only as opt-in asset packs (for example a GPU OCR pack)
  when a bake-off justifies them; never required, never the default (ADR-0016).

### Documentation and process

- Added SPEC-0003 defining the evaluation and benchmark harness: loaders,
  metrics and fixed-seed statistics, report writers, test-split protection,
  performance measurement, and the WP-1.8 smoke gate. Accepted with maintainer
  pre-approval in /goal; depth/telemetry/filter API needs are a prerequisite
  for WP-1.2, WP-1.6, and B0 only.
- Added SPEC-0004 defining deterministic Seeky Desktop Corpus generation,
  query splits, and human-verified graded relevance judgments. Accepted with
  maintainer pre-approval in /goal: default benchmarks exclude source code,
  code-enabled results are separate, and WP-1.8 requires verified smoke qrels.
- Drafted SPEC-0014 v1 for WP-7.1 English/Portuguese localization and WP-7.2
  light/dark themes, including requirement-linked acceptance tests and the
  current UI string inventory. It remains Draft pending maintainer gate H2.
- `AGENTS.md` §4 "Parallel agents": one worktree, branch, and work package
  per worker; owned paths per assignment; shared records (plan status,
  CHANGELOG, indexes, audit) written only by the orchestrator before merge;
  a fixed brief for every worker.
- Accepted SPEC-0001 (workspace and crate boundaries) and SPEC-0002 v1
  (headless engine API, golden test, opening files by document ID) for
  Phase 0.
- Added `AGENTS.md` (agent operating manual) and `CLAUDE.md`.
- Adopted Spec-Driven + Benchmark-Driven Development (ADR-0017): spec process
  and template (`docs/specs/`), benchmark methodology, budgets, candidate
  registry, and report template (`docs/benchmarks/`).
- Rewrote the implementation plan (v2.0): engine-first phases 0–9 with work
  packages, bake-offs, gates, and a rejected-options log.
- Added the model bake-off protocol (methodology §8): a Stage 0/A/B/C funnel,
  comparison of deployment variants (ONNX variant + quantization + provider),
  ONNX export with alternatives priced only on demand, quantization matrix
  with tolerances, deployment-cost accounting, new-engine margin, the ORT
  validation gate with kill criteria K1–K4, and OCR specifics; added OCR
  budgets O1–O4.
- Candidate registry: OCR tiers (CPU default, GPU opt-in) with OCRia,
  MiniCPM-OCR 1.0, OXR-1.0, PaddleOCR-VL, and Florence-2 candidates; new
  inference-engine section.
- New architecture documents: `overview.md` (engine-first workspace) and
  `indexing.md` (two-speed indexing); revised retrieval engine, inference and
  models (formerly model strategy), and provisioning contracts.
- Split ADRs into one file per decision under `docs/adr/` (ADR-0015 to
  ADR-0022 added; 0002, 0004, 0014 superseded).
- Consolidated product decisions and scope into `docs/product/vision.md`;
  archived the original Portuguese scope brief.
- Moved Gety reverse-engineering research, audits, and SQL references under
  `docs/research/gety/`; removed duplicated READMEs; normalized personal paths.
- Added a pull request template.
- Progress tracking made explicit (plan v2.2): one status row per work
  package with fixed status values and evidence (plan §15), per-requirement
  status in specs and a status column in the specs index, a "record it"
  checklist in `AGENTS.md` §4 step 8 applied in the same commit as the work,
  a `Refs: WP-x.y, SPEC-NNNN` commit trailer, a maintenance rule for the PoC
  conformance audit, and the scope and release cut of this changelog.
- Test and commit rules in `AGENTS.md`: required tests per kind of change
  (regression test for every fix, characterization before refactors,
  malformed-input tests for parsers), hermetic and hardware-free tests,
  fixtures, and no weakening of failing tests (§6 Tests); commit every green
  logical step and push, never leave work uncommitted, stage only your own
  changes, and semantic subjects with an explanatory body (§9).

## 0.1.0 — 2026-11-26

### Added

- Tauri 2.12.7 desktop application with Rust backend and React 19/TypeScript UI.
- Local folder indexing with SQLite + FTS5 persistence.
- PDF, DOCX, XLSX, PPTX, HTML, text, Markdown, and source-code extraction.
- `gety-embed-v0` embeddings on CPU (ONNX Runtime uint8), CUDA (FP16), and Intel
  NPU (OpenVINO IR).
- Hybrid retrieval: BM25 + filename/path + dense cosine + RRF.
- Search results with snippets, match tags, preview, and native file opening.
- Live filesystem watcher with 600 ms debounce, create/modify/rename/delete
  handling, per-folder pause/resume, and subtree scans.
- Incremental reindexing using size + nanosecond-mtime signatures.
- Index health, progress events, cancellation, and stale-document pruning.
- Backend selection persisted across launches.
- Portable release layout with bundled OpenVINO IR.
- Rust test suite covering inference, extraction, incremental indexing, and
  watcher event mapping.

### Documentation

- Active Rust/Tauri implementation plan.
- As-built architecture decisions.
- PoC validation evidence.
- Archived pre-implementation research plans.
