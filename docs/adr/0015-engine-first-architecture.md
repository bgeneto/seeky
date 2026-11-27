# ADR-0015 — Engine-first architecture: UI-independent Rust engine

- **Status:** Accepted
- **Date:** 2026-11-27
- **Related:** [`../architecture/overview.md`](../architecture/overview.md), ADR-0001, ADR-0008

## Context

Seeky must be born as a high-performance search engine that has a desktop
interface — not a desktop app that contains a search engine. In the PoC, the
engine lives inside the Tauri crate (`apps/seeky/src-tauri`): commands, watcher,
indexing, inference, and ranking share one crate and one mutex-guarded
connection, and the engine cannot be benchmarked without the UI.

## Decision

Restructure the repository into a Cargo workspace whose engine crates have **no
dependency on Tauri, the webview, or any UI type**:

- `crates/seeky-core` — domain types, IDs, configuration, errors, traits.
- `crates/seeky-extract` — format extraction, normalization, language ID,
  chunking, OCR adapter.
- `crates/seeky-infer` — ONNX Runtime sessions
  ([ADR-0019](0019-single-inference-engine.md)), execution-provider selection,
  tokenizers, model registry, embedder/reranker/OCR implementations.
- `crates/seeky-store` — SQLite metadata and migrations, job queue, embedding
  cache, lexical and vector index implementations.
- `crates/seeky-search` — query analysis, candidate generation, fusion,
  aggregation, reranking orchestration, dedupe, diversity, calibration,
  snippets.
- `crates/seeky-engine` — the `Engine` façade: roots, scheduler, watcher,
  reconcile, indexing pipeline, progressive search sessions, status.
- `crates/seeky-provision` — manifest, download, verification, asset cache.
- `crates/seeky-eval` — datasets, qrels, metrics, statistics, reports.
- `tools/seeky-bench` — internal CLI over the engine for evaluation and
  performance runs (never shipped).
- `apps/desktop` — Tauri shell: commands and channels map 1:1 to the `Engine`
  API; no business logic.

## Consequences

- Every retrieval/indexing change is measurable headlessly with `seeky-bench`,
  without WebView noise.
- Crate boundaries are review boundaries for AI agents: a work package touches
  a small, named set of crates.
- The UI cannot reach SQLite, models, or the filesystem except through the
  engine API.
- Phase 0 of the plan performs the extraction with no behavior change, guarded
  by the existing tests plus a new golden search test.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Keep one Tauri crate, use modules | Engine not benchmarkable headlessly; UI types leak into engine |
| One big `seeky-engine` crate | Slower builds, weak boundaries for parallel agent work |
| Many micro-crates (one per stage) | Coordination overhead with no measurable benefit yet |
