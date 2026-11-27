# Changelog

All notable changes to Seeky are recorded here.

## Unreleased

### Fixed

- HTML and HTM files are extracted again; extraction previously failed for every
  HTML file because of an unsupported regular-expression backreference.

### Changed

- Auto backend selection resolves NPU → CPU and never selects a GPU
  (ADR-0016); CUDA remains available only when chosen explicitly.
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
- Proposed (ADR-0023): image search is planned as an optional, separately
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
