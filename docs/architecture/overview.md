# Seeky Architecture Overview

| Field | Value |
|---|---|
| Status | Accepted target architecture |
| Date | 2026-11-27 |
| Governs | Workspace layout, engine API, process and concurrency model, storage layout |
| Related | [ADR-0015](../adr/0015-engine-first-architecture.md), [indexing](indexing.md), [retrieval engine](retrieval-engine.md), [inference and models](inference-and-models.md), [provisioning](distribution-and-provisioning.md) |

This document describes the **target**. The as-built PoC (the Tauri crate in
`apps/desktop`, moving into `crates/` during Phase 0) is described in [`../../apps/desktop/README.md`](../../apps/desktop/README.md);
the implementation plan moves it to this architecture without behavior loss.

## 1. Design stance

Seeky is a search engine with a desktop interface. Concretely:

1. The **engine** is a set of Rust crates with no dependency on Tauri, the
   webview, or UI types. It can be driven headlessly by tests and by
   `seeky-bench`.
2. The **desktop app** is a thin Tauri shell: each command is a one-line call
   into the engine API; progressive results flow through Tauri channels.
3. Every performance-relevant subsystem sits behind a trait so that the
   benchmark program can swap implementations (models, lexical engine, vector
   index, OCR) without touching callers.

Five subsystems, mirroring the reference architecture for semantic file search:

| # | Subsystem | Responsibility | Crates |
|---|---|---|---|
| 1 | Filesystem intelligence | Scan, watch, reconcile, change detection, exclusions | `seeky-engine` |
| 2 | Document intelligence | Extraction, normalization, language ID, OCR, chunking, visual-unit selection, source offsets | `seeky-extract` |
| 3 | Indexing engine | Metadata, lexical, filename, vector indexes; embedding cache; embedding channels and generations | `seeky-store`, `seeky-infer` |
| 4 | Neural retrieval engine | Query analysis, candidate generation, fusion, reranking, document ranking | `seeky-search`, `seeky-infer` |
| 5 | Semantic presentation | Extractive snippets, highlights, locators, result shaping | `seeky-search` |

## 2. Repository and workspace layout (target)

```text
Cargo.toml                 workspace manifest (shared lints, profiles, versions)
crates/
  seeky-core/              types, IDs, config, errors, traits (no heavy deps)
  seeky-extract/           extractors, normalization, language ID, chunker, OCR adapter
  seeky-infer/             ONNX Runtime sessions, EP selection, tokenizers, model registry
  seeky-store/             SQLite metadata/migrations, job queue, embedding cache,
                           LexicalIndex / FilenameIndex / VectorIndex implementations
  seeky-search/            query analysis, retrieval, fusion, ranking stages, snippets
  seeky-engine/            Engine façade, scheduler, watcher, reconcile, pipeline, status
  seeky-provision/         asset manifest, downloader, verifier, asset cache
  seeky-eval/              dataset loaders, qrels, metrics, statistics, report writer
tools/
  seeky-bench/             internal CLI: build index, run eval/perf, compare reports
  model-export/            offline export/quantization + parity tests (Python allowed)
apps/
  desktop/                 Tauri 2 shell + React/TypeScript UI
bench/
  datasets/                dataset manifests and download scripts (no bulk data in git)
  corpora/sdc/             Seeky Desktop Corpus generator + small committed smoke subset
  qrels/                   relevance judgments (committed)
  configs/                 pipeline configurations under test
docs/                      product, architecture, ADRs, specs, benchmarks, plans
```

Dependency direction (enforced in review and by `cargo-deny` bans):

```text
apps/desktop ──► seeky-engine ──► seeky-search ──► seeky-store ──► seeky-core
                     │                 │               ▲
                     │                 └──► seeky-infer┘
                     ├──► seeky-extract ─────────────► seeky-core
                     └──► seeky-provision ───────────► seeky-core
tools/seeky-bench ──► seeky-engine, seeky-eval
```

`seeky-core` depends on nothing heavy (no SQLite, no ORT). No engine crate
depends on `tauri`.

## 3. Engine API (sketch)

The authoritative signature lives in the engine API spec; this sketch fixes the
shape.

```rust
pub struct Engine { /* Arc<inner> */ }

impl Engine {
    pub fn open(config: EngineConfig) -> Result<Engine>;

    // Roots
    pub fn add_root(&self, path: &Path) -> Result<Root>;
    pub fn remove_root(&self, id: RootId) -> Result<()>;
    pub fn list_roots(&self) -> Result<Vec<RootStatus>>;
    pub fn set_root_watching(&self, id: RootId, enabled: bool) -> Result<()>;
    pub fn reindex(&self, scope: ReindexScope) -> Result<JobHandle>;

    // Search: progressive and cancellable
    pub fn search(&self, req: SearchRequest, sink: Box<dyn SearchSink>) -> SearchHandle;
    pub fn document(&self, id: DocId) -> Result<DocumentView>;

    // Observability
    pub fn status(&self) -> EngineStatus;          // cheap, lock-free snapshot
    pub fn subscribe(&self) -> EventReceiver;      // index progress, health, provisioning
    pub fn capabilities(&self) -> Capabilities;    // lexical / semantic / rerank / ocr / visual / npu

    pub fn shutdown(self) -> Result<()>;
}
```

A `SearchRequest` carries a text query or, when the visual pack is active, an
image query ([ADR-0023](../adr/0023-multimodal-ready-engine.md)); both flow
through the same stages.

`SearchSink` receives one `SearchUpdate` per stage:

| Stage | Contents | Typical trigger |
|---|---|---|
| `Instant` | Filename/path + lexical results, document-grouped | Always first |
| `Hybrid` | + dense retrieval, fusion, aggregation, dedupe, diversity | When semantic capability is active |
| `Refined` | + cross-encoder reranking and final snippets for visible results | When rerank budget/capability allows |

Each update carries the full ordered result list (not a diff), the query
generation number, stage timings, and capability flags. A newer query cancels
older work cooperatively; the UI discards updates whose generation is stale.

## 4. Process and concurrency model

```text
┌──────────────────────── Seeky process ────────────────────────┐
│ WebView (React)  ◄── Tauri commands / channels ──►  Shell      │
│                                                     │          │
│                                              Engine façade     │
│   ┌──────────────┬───────────────┬───────────────┬─────────┐  │
│   │ Query pool   │ Index pipeline│ Watcher +     │ Store    │  │
│   │ (high prio)  │ (low prio)    │ reconcile     │ writer   │  │
│   │ search stages│ extract/chunk │ notify / OS   │ actor    │  │
│   │ query embed  │ embed batches │ journals      │ (single) │  │
│   └──────┬───────┴──────┬────────┴───────────────┴────┬────┘  │
│          ▼              ▼                              ▼       │
│   read connections (WAL)   inference sessions   index files   │
└────────────────────────────────────────────────────────────────┘
```

Rules:

1. **Search never waits for indexing.** The query path runs on a dedicated
   high-priority pool with its own inference session(s) configured for batch-1
   latency. Indexing runs on a low-priority pool (OS background priority where
   available) with throughput-configured sessions. Vision-encoder sessions
   exist only for visual indexing and image queries; the text query path never
   loads them ([ADR-0023](../adr/0023-multimodal-ready-engine.md)).
2. **Single writer, many readers.** One store-writer actor owns all writes
   (SQLite transactions and index commits); readers use pooled WAL connections
   and immutable index snapshots. No lock is held across inference or I/O to
   user files.
3. **Cooperative cancellation** via cancellation tokens checked between stages
   and between batches.
4. **Backpressure.** Pipeline stages are connected by bounded channels; the
   resource governor throttles indexing when the user is searching, on battery
   (configurable), or under memory pressure.
5. **Crash safety.** Jobs are durable and idempotent; derived indexes carry
   generation markers and can be rebuilt from SQLite + the embedding cache.

## 5. Storage layout (target)

```text
<app-data>/                          e.g. %APPDATA%\ai.seeky.desktop\
  seeky.db                           SQLite (WAL): source of truth
  index/
    components/<build-key>/          one external index instance (lexical, filename, or vectors), shared by
                                     every generation with the same build key; FTS5 and as-built indexes live in seeky.db
    gen-<id>/GENERATION.json         one per index generation (one lineage per embedding channel):
                                     recipe, space key, referenced instances, checksums
  cache/embeddings/                  content-addressed embedding cache (if outside SQLite)
  assets/                            provisioned runtimes/models (versioned, immutable)
  logs/                              rotating, redacted
```

Core tables in `seeky.db` (detailed in the storage spec):

| Table | Purpose |
|---|---|
| `roots` | Watched folders, watch state, exclusion rules |
| `files` | Path, file identity, signature (size, mtime_ns, optional file ID), type, language, content hash, SimHash, duplicate cluster, length statistics, status |
| `passages` | File, ordinal, compressed text, offsets, locator (page/slide/sheet/line), heading path, token length, passage hash, source (extracted or OCR) |
| `visual_units` | File, ordinal, kind (image, slide, figure, page region), locator, pixel size, content hash; populated only when the visual pack is enabled ([ADR-0023](../adr/0023-multimodal-ready-engine.md)) |
| `embedding_cache` | (space key, embed key) → vector, for passages and visual units; reused by every generation of the same embedding space |
| `jobs` | Durable, idempotent indexing jobs with priority and attempts |
| `generations` | Index generations per embedding channel: channel, recipe and space keys, referenced index instances, coverage, status ([SPEC-0006](../specs/SPEC-0006-storage-index-backends-and-generations.md)) |
| `models` | Installed model manifests and verification state |
| `settings` | Key/value user settings |

## 6. Desktop shell contract

- Tauri commands map 1:1 to `Engine` methods; payloads are serde types defined
  in `seeky-core` and mirrored in TypeScript (generated, not hand-written, once
  the API stabilizes).
- Progressive search uses `tauri::ipc::Channel<SearchUpdate>`.
- Events: `index-progress`, `index-health`, `provisioning-progress`,
  `capabilities-changed`.
- Webview capabilities stay at `core` + `dialog`; all file actions are Rust
  commands ([ADR-0006](../adr/0006-narrow-webview-capabilities.md)); a strict
  CSP is set before 1.0.

## 7. Cross-cutting requirements

| Concern | Requirement |
|---|---|
| Observability | Structured `tracing` spans per pipeline stage; local only; timings feed `seeky-bench` |
| Configuration | One typed `EngineConfig` + `RankingConfig`; defaults versioned; every tunable has a benchmark owner |
| Errors | `thiserror` in libraries, `anyhow` only at binary edges; no panics on user data |
| Security | Untrusted-input parsers isolated, fuzzed, time- and memory-bounded; no unsafe outside audited modules |
| Portability | Windows first; macOS/Linux compile in CI from Phase 0, validated before 1.0 |
| Privacy | No content in logs or network requests; no telemetry |
