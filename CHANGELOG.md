# Changelog

All notable changes to Seeky are recorded here.

## Unreleased

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
