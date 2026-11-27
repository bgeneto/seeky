# Changelog

All notable changes to Seeky are recorded here.

Entries go under **Unreleased** in the same commit as the change
([`AGENTS.md`](AGENTS.md) §4 step 8): anything a user, contributor, or agent
would notice, including product decisions and process rules; pure internal
refactors need none. When a phase's exit evidence is committed, the maintainer
moves the Unreleased entries under that phase's version from the plan's
roadmap (§6), with the date.

## Unreleased

### Fixed

- HTML and HTM files are extracted again; extraction previously failed for every
  HTML file because of an unsupported regular-expression backreference.

### Changed

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
