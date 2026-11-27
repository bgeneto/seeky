# Changelog

All notable changes to Seeky are recorded here.

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
