# SPEC-0002 — Engine API (v1 headless; v1.1 evaluation extension Draft)

| Field | Value |
|---|---|
| Status | Implemented (v1); v1.1 evaluation extension Draft (not accepted) |
| Version | 0.3 (API v1; v1.1 evaluation extension Draft; API v2 adds progressive search in WP-4.3) |
| Owner | Maintainer |
| Phase / work packages | Phase 0 — WP-0.2, WP-0.3; Phase 1 — prerequisite for WP-1.2, WP-1.6, and B0 (SPEC-0003 H1) |
| Crates touched | `seeky-core`, `seeky-extract`, `seeky-infer`, `seeky-store`, `seeky-search`, `seeky-engine`, `seeky-desktop`; v1.1 adds no crate and no shell change |
| Governing docs | [ADR-0015](../adr/0015-engine-first-architecture.md); [ADR-0006](../adr/0006-narrow-webview-capabilities.md); [ADR-0019](../adr/0019-single-inference-engine.md); [ADR-0023](../adr/0023-multimodal-ready-engine.md); [ADR-0024](../adr/0024-source-code-indexing-opt-in.md); [ADR-0016](../adr/0016-cpu-first-npu-ready-execution.md); [architecture overview](../architecture/overview.md) §3, §6; [retrieval engine](../architecture/retrieval-engine.md) §3, §10; [methodology](../benchmarks/methodology.md) §3.2; [SPEC-0001](SPEC-0001-workspace-and-crate-boundaries.md); [SPEC-0003](SPEC-0003-evaluation-harness.md); [conformance audit](../validation/poc-conformance-audit.md) A7–A9 |
| Benchmark gates | v1: None. Ranked output must be identical to the pre-extraction snapshot (R3, R4). v1.1: enables Q3 Recall@100 and the S1–S5 / query-embedding measurements for SPEC-0003 but defines and claims no budget |

## 1. Problem and goal

All engine behavior lives behind Tauri commands in one crate, so nothing can be
tested or benchmarked headlessly, and the webview can ask the backend to open
any path with the OS default handler (audit A8).

API v1 extracts the PoC into the crates of SPEC-0001 behind one `Engine`
façade in `seeky-engine`, **without changing behavior**: same results, same
storage, same events, same UI. The Tauri shell becomes a thin adapter that
resolves Tauri paths, forwards events, and calls the engine. One deliberate
behavior change is in scope, the security fix for A8: files are opened by
document ID, never by a path from the webview.

Done means: a test can open an engine on a temporary directory, index a corpus,
and search it without Tauri; a golden test proves the ranked results match the
PoC; and the shell has no SQLite, model, or filesystem access of its own.

## 2. Scope

- **In:** the `Engine` API v1 and its types; moving PoC code per SPEC-0001
  §4.5; `thiserror` error types replacing `anyhow` in libraries; `tracing`
  spans per stage; the golden search test; the thin shell; opening files by
  document ID.
- **Out (kept as documented deviations, closed later):** progressive and
  cancellable multi-stage search, `subscribe`, `capabilities`, and
  `reindex(scope)` (API v2, WP-4.3); the concurrency model (one database mutex
  and one inference mutex, audit A7 → WP-2.1, WP-2.4, WP-3.1); vector parity
  and re-embedding on backend change (A5 → WP-2.1, WP-3.7); lexical-first
  indexing without a model (A6 → WP-3.2); hardcoded model constants and Gety
  discovery (WP-2.1); CSP (WP-7.9).

## 3. Requirements (EARS)

| ID | Requirement | Verification | Status |
|---|---|---|---|
| SPEC-0002-R1 | `seeky-engine` shall expose an `Engine` type whose methods (§4.2) cover every PoC command: status, roots, watching, backend selection and probing, indexing and its cancellation, search, document view, and document path resolution. | compile-time: the shell calls only these methods | Implemented (WP-0.3) |
| SPEC-0002-R2 | No public item of an engine crate shall take or return a Tauri type, and `Engine` shall be `Clone + Send + Sync`. | inspection; static assertion test `engine_is_send_sync_clone` | Implemented (WP-0.2) |
| SPEC-0002-R3 | When the golden corpus is indexed and the golden queries are run, the engine shall return, per query, the same ranked list (relative path, chunk start and end, page, matched channels, rank) as the snapshot captured from the PoC, with scores equal within 1e-9 for the lexical-only run and 1e-6 for the hybrid run. | `seeky-engine` tests `golden_lexical` (hardware-free) and `golden_hybrid_cpu` (`hw-tests`) | Implemented (WP-0.2) |
| SPEC-0002-R4 | The golden snapshot shall be captured on the PoC before any code moves, by a capture test added to the PoC in WP-0.2's first commit, and committed with its corpus and query list. | inspection of commit order; snapshot file header records the source commit | Implemented (WP-0.2) |
| SPEC-0002-R5 | The shell shall keep every PoC command name, argument name, and JSON payload shape unchanged, except that `open_local_file(path)` is replaced by `open_document(id)`. | inspection; the React UI works with only the `open_document` call changed; `npm run build` | Implemented (WP-0.3) |
| SPEC-0002-R6 | When `open_document` is called with an ID that is not in the index, the shell shall return an error and open nothing. | integration test on `Engine::document_path` returning `None`; shell code review | Implemented (WP-0.3) |
| SPEC-0002-R7 | When `open_document` resolves a document whose extension is not in the open allowlist (§5.4), the shell shall reveal the file in the system file manager instead of opening it. | unit test of the allowlist function; manual check on Windows | Implemented (WP-0.3) |
| SPEC-0002-R8 | The shell shall not accept a filesystem path from the webview for any file action, and shall not depend on `rusqlite`, `ort`, `notify`, `walkdir`, or any extractor crate. | inspection; `cargo deny check bans` (SPEC-0001-R13) | Implemented (WP-0.3) |
| SPEC-0002-R9 | While indexing, the engine shall report progress and health through the `EngineEvents` sink with the PoC payloads, and the shell shall forward them as the Tauri events `index-progress` and `index-health` unchanged. | unit test with a recording sink; UI progress works | Implemented (WP-0.2) |
| SPEC-0002-R10 | When `cancel_indexing` is called during indexing, the running `index_path` call shall return a summary with `cancelled = true`, as in the PoC. | integration test `cancel_returns_cancelled_summary` | Implemented (WP-0.2) |
| SPEC-0002-R11 | While one `index_path` call runs, a second call shall wait for it to finish (PoC behavior); indexing shall never run twice concurrently. | integration test with two threads | Implemented (WP-0.2) |
| SPEC-0002-R12 | Engine library crates shall return `thiserror` errors; `Engine` methods shall return `Result<T, EngineError>` with the variants in §4.3, and the shell shall map them to strings with `Display`. | inspection; `cargo tree -i anyhow` (SPEC-0001-R18) | Implemented (WP-0.2) |
| SPEC-0002-R13 | The engine shall emit `tracing` spans for each stage named in §5.3, and shall not record document content or unredacted paths in span fields or log messages. | test with a capturing subscriber; review | Implemented (WP-0.2) |
| SPEC-0002-R14 | When `Engine::shutdown` is called, the engine shall stop all watchers and join its worker threads before returning. | integration test: no watcher event is processed after shutdown | Implemented (WP-0.2) |
| SPEC-0002-R15 | Every PoC test shall exist and pass in its new crate, and the hardware-free suite shall need no Tauri runtime. | `cargo test --workspace`; `cargo test --workspace --features hw-tests -- --test-threads=1` | Implemented (WP-0.2) |
| SPEC-0002-R16 | When the engine opens, it shall resolve the database, model, NPU IR, and PDFium locations exactly as the PoC did, given the app-data directory and resource directory passed by the shell. | integration test on `EngineConfig::resolve`; the app opens an existing index | Implemented (WP-0.2; manual existing-index check pending) |

v1.1 adds SPEC-0002-R17–R25 in §9.3. Those rows are **Draft** and do not
change, supersede, or renumber R1–R16. The extension is not accepted and must
not be implemented until the maintainer accepts it.

## 4. Interfaces

### 4.1 Types (in `seeky-core`, re-exported by `seeky-engine`)

The following PoC types move unchanged (field names, serde names, and order):
`Root`, `Counts`, `DocumentView`, `SearchHit`, `IndexProgress`,
`IndexSummary`, `IndexHealth`, `Backend`, `EngineInfo`, `SearchResponse`. The
PoC `Status` is renamed `EngineStatus` and keeps its JSON shape.

```rust
pub type RootId = String;   // PoC root ID (unchanged format)
pub type DocId = String;    // PoC document ID (unchanged format)

pub struct SearchRequest {
    pub query: String,
    pub limit: Option<usize>, // PoC default 20, clamped to 1..=50
}
```

`EngineStatus` keeps the PoC `Status` fields, including `model_root`,
`npu_model`, `pdfium`, and `db_path` as display strings (redaction of these is
SPEC-0014's job, not v1's).

### 4.2 `Engine` (in `seeky-engine`)

```rust
#[derive(Clone)]
pub struct Engine { /* Arc<Inner> */ }

pub struct EngineConfig {
    pub data_dir: PathBuf,             // app-data directory; seeky.db lives here
    pub resource_dir: Option<PathBuf>, // bundled resources (PoC NPU IR)
}

pub trait EngineEvents: Send + Sync + 'static {
    fn index_progress(&self, progress: &IndexProgress);
    fn index_health(&self, health: &IndexHealth);
}

impl Engine {
    pub fn open(config: EngineConfig, events: Arc<dyn EngineEvents>) -> Result<Engine, EngineError>;

    pub fn status(&self) -> Result<EngineStatus, EngineError>;

    pub fn add_root(&self, path: &Path) -> Result<Root, EngineError>;
    pub fn remove_root(&self, id: &RootId) -> Result<(), EngineError>;
    pub fn list_roots(&self) -> Result<Vec<Root>, EngineError>;
    pub fn set_root_watching(&self, id: &RootId, enabled: bool) -> Result<Root, EngineError>;

    pub fn set_backend(&self, backend: Backend) -> Result<EngineStatus, EngineError>;
    pub fn probe_backend(&self, backend: Backend) -> Result<EngineInfo, EngineError>;

    /// PoC `start_index`: add (or reuse) the root at `path`, start watching it
    /// if enabled, then index it. Blocking; call from a worker thread.
    pub fn index_path(&self, path: &Path) -> Result<IndexSummary, EngineError>;
    pub fn cancel_indexing(&self);

    /// Blocking; single stage (v2 adds progressive stages).
    pub fn search(&self, request: &SearchRequest) -> Result<SearchResponse, EngineError>;
    pub fn document(&self, id: &DocId) -> Result<Option<DocumentView>, EngineError>;
    /// Path of an indexed document, for the shell's open/reveal action only.
    pub fn document_path(&self, id: &DocId) -> Result<Option<PathBuf>, EngineError>;

    pub fn shutdown(self) -> Result<(), EngineError>;
}
```

### 4.3 Errors

```rust
#[derive(Debug, thiserror::Error)]
pub enum EngineError {
    #[error("not found: {0}")]            NotFound(String),
    #[error("invalid input: {0}")]        InvalidInput(String),
    #[error("model unavailable: {0}")]    ModelUnavailable(String),
    #[error("storage error: {0}")]        Storage(#[from] seeky_store::Error),
    #[error("inference error: {0}")]      Inference(#[from] seeky_infer::Error),
    #[error("extraction error: {0}")]     Extraction(#[from] seeky_extract::Error),
    #[error("watcher error: {0}")]        Watcher(String),
    #[error("io error: {0}")]             Io(#[from] std::io::Error),
    #[error("internal error: {0}")]       Internal(String), // poisoned lock, joined thread panic
}
```

Each library crate defines its own `Error` and `type Result<T> = std::result::Result<T, Error>`.
Error message texts may differ from the PoC; error conditions may not.

### 4.4 Shell commands (`seeky-desktop`)

| Command | Engine call | Change from PoC |
|---|---|---|
| `get_status` | `status` | none |
| `add_root(path)` | `add_root` | none (the path comes from the native folder dialog) |
| `remove_root(id)` | `remove_root` | none |
| `list_roots` | `list_roots` | none |
| `set_root_watching(id, enabled)` | `set_root_watching` | none |
| `set_backend(backend)` | `set_backend` | none |
| `probe_backend(backend)` | `probe_backend` | none |
| `start_index(path)` | `index_path` (in `spawn_blocking`) | none |
| `cancel_index` | `cancel_indexing` | none |
| `search_documents(query, limit)` | `search` (in `spawn_blocking`) | none |
| `get_document(id)` | `document` | none |
| `open_document(id)` | `document_path`, then open or reveal (§5.4) | replaces `open_local_file(path)` |

Each command body is a call plus error mapping; no other logic.

## 5. Behavior details

### 5.1 Ownership

The engine owns the database connection, the inference engine, the watcher
manager, health state, the index lock, and the cancellation flag (the PoC
`AppState` minus Tauri). The shell stores one `Engine` in Tauri state and an
`EngineEvents` implementation that holds the `AppHandle` and calls `emit`.

### 5.2 Concurrency (unchanged from the PoC)

v1 keeps the PoC model on purpose: one mutex around the SQLite connection, one
around the inference engine, an index lock, and an atomic cancellation flag.
This keeps audit deviation A7 (search can wait for indexing) visible and
measurable until WP-2.1, WP-2.4, and WP-3.1 replace it. No new lock may be held
across inference or user-file I/O.

### 5.3 Tracing spans

`index.path`, `index.scan`, `index.file`, `index.extract`, `index.chunk`,
`index.embed`, `index.store`, `watch.batch`, `search`, `search.lexical`,
`search.filename`, `search.dense`, `search.fuse`, `search.snippets`. Fields are
counts, sizes, durations, IDs, and extension; never content or full paths. No
subscriber is installed by the engine; the shell installs none in v1, so
runtime behavior is unchanged.

### 5.4 Opening documents (audit A8)

1. The webview sends a document ID.
2. The engine returns the indexed path, or `None`.
3. If the extension (lowercased) is in the open allowlist, the shell opens the
   file with the OS default handler; otherwise it reveals the file in the
   system file manager. Open allowlist (document types only):
   `txt md markdown rst log pdf docx xlsx xls pptx csv json jsonl xml yaml yml toml html htm`.
   Source code of any language (`c cpp h hpp for f90 py js ts rs go java cs sh
   ps1 sql …`, the source-code class of
   [ADR-0024](../adr/0024-source-code-indexing-opt-in.md)) is never opened
   directly, because some default handlers execute it (for example `.js` with
   Windows Script Host, `.py` with the Python launcher); neither is any type
   outside the allowlist.
4. If the file no longer exists, the shell returns an error.

### 5.5 Golden test

- **Corpus:** `apps/desktop/demo/` (five files, committed), indexed into a fresh
  temporary data directory.
- **Queries:** at least 10, committed with the snapshot: single and multi-term
  English, Portuguese, a filename-only match, a query with FTS5 special
  characters, an accented Portuguese term, and a no-hit query.
- **Runs:** `golden_lexical` with no model (the semantic channel is disabled)
  and PDFium pointed at a nonexistent path, so the PDF is skipped on every
  machine; `golden_hybrid_cpu` (`hw-tests`) with the local model on the CPU
  backend and the local PDFium.
- **Comparison:** per query, the ordered list of (relative path, chunk start,
  chunk end, page, matched channels) must be identical, and scores within the
  tolerance of R3. Items whose scores tie within the tolerance may swap order.
- **Snapshot:** JSON under `crates/seeky-engine/tests/golden/`, with a header
  recording the PoC commit, backend, and Seeky version. Re-capturing it later
  requires a reason in the commit message and a CHANGELOG entry.

## 6. Acceptance

### 6.1 Tests (written before the move)

| Test | Requirement IDs |
|---|---|
| PoC capture test → committed snapshot | R4 |
| `golden_lexical`, `golden_hybrid_cpu` | R3, R15 |
| `engine_is_send_sync_clone` (static assertion) | R2 |
| `open_allowlist_reveals_code_and_unknown_types` | R7 |
| `document_path_unknown_id_is_none` | R6 |
| `events_sink_receives_progress_and_health` | R9 |
| `cancel_returns_cancelled_summary` | R10 |
| `index_path_calls_are_serialized` | R11 |
| `spans_carry_no_content_or_paths` | R13 |
| `shutdown_stops_watchers` | R14 |
| `config_resolves_poc_locations` | R16 |
| The 9 PoC tests in their new crates | R15 |

### 6.2 Benchmark gates

None. Phase 0 has no performance gate; the golden test guards ranking
behavior. Index and search timings must not be claimed better or worse.

### 6.3 Inspection

- `apps/desktop/src-tauri` contains only commands, the event sink, path
  resolution from Tauri, and `run()` (R1, R8).
- Every shell command is a single engine call plus error mapping (§4.4).
- The React UI changed only the `open_document` call (R5).
- `cargo tree` confirms the shell's dependencies (R8) and no `anyhow` in
  libraries (R12).

## 7. Risks and open questions

| # | Item | Decides | When | Blocking |
|---|---|---|---|---|
| 1 | ~~Open allowlist in §5.4~~ **Resolved 2026-11-27:** source files of any language are never opened directly, and code indexing becomes opt-in ([ADR-0024](../adr/0024-source-code-indexing-opt-in.md)) | Maintainer | Done | No |
| 2 | Hybrid golden determinism: ONNX Runtime CPU results can vary slightly with thread count; if the 1e-6 tolerance flakes, fix intra-op threads in the test rather than loosening the tolerance | Implementer | WP-0.2 | No |
| 3 | Error texts shown in the UI may change with `thiserror` (§4.3); acceptable for a PoC, noted in CHANGELOG | Maintainer | WP-0.2 | No |
| 4 | The audited `unsafe` PATH mutation (SPEC-0001 §5.3, A9) moves into `seeky-infer` unchanged until WP-2.1 | Implementer | WP-0.2 | No |

## 8. Changelog

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-11-27 | Initial draft of API v1 |
| 0.2 | 2026-11-27 | Accepted; open allowlist decided: source files are never opened directly (ADR-0024) |
| 0.2 | 2026-11-27 | WP-0.2 implemented R2-R4, the engine halves of R1/R6, and R9-R16; R5, R7, R8, and the shell halves of R1/R6 remain for WP-0.3 |
| 0.2 | 2026-11-27 | WP-0.3 implemented R1 and R5-R8: the shell calls only Engine, accepts document IDs instead of paths, opens only the §5.4 allowlist, and reveals source/unknown types. All v1 requirements are implemented |
| 0.3 | 2026-11-27 | Draft v1.1 evaluation extension (R17–R25): depth to 1,000 with deterministic ordering, in-process stage telemetry, an uncached query-embedding probe, exact extension/date/folder/size filters with push-down/post reporting and typed unavailable-metadata errors, and a canonical configuration snapshot for hashing. Not accepted; no v1 requirement changed |

## 9. API v1.1 evaluation extension (Draft)

> **Status: Draft — not accepted and not implemented.** This section is the
> behavior-preserving extension requested by SPEC-0003 H1 questions 1–3. It adds
> evaluation-only capability. §1–§8 remain the accepted v1 contract and are not
> changed. Do not implement any requirement here until the maintainer accepts
> the extension.

### 9.1 Problem and goal

`seeky-bench` (SPEC-0003 WP-1.2, WP-1.6, B0) needs engine capabilities that API
v1 does not expose:

1. Recall@100 (methodology Q3) needs more than the 50-hit v1 cap.
2. `perf` needs stage and query-embedding timings from the headless engine
   rather than from logs, which would violate the API boundary (ADR-0015).
3. Mixed semantic/metadata queries (SPEC-0004 R15) carry extension, date,
   folder, and size predicates; post-filtering a truncated list can starve the
   ranking and cannot establish Q2 for that category.
4. SPEC-0003 R16 needs a privacy-safe, stable semantic configuration snapshot
   to hash.

`seeky-eval` already computes arbitrary cutoffs, but `seeky-bench` must fail
closed with `INSUFFICIENT_DEPTH` when the engine cannot supply enough depth.
This extension removes that blocker without changing product search, progressive
search, or any v1 payload.

Done means: a lexical or hybrid evaluation can request up to 1,000 ranked hits,
receive a deterministic order, measure per-stage and batch-1 query-embedding
latency, apply the four filter classes exactly and see whether they were pushed
down or applied after retrieval, and hash the effective engine configuration —
all through `Engine`, with no Tauri, logging, or path leakage.

### 9.2 Scope

- **In:** evaluation search mode with depth 1–1,000 and candidate-depth
  reporting; a deterministic total order; opt-in in-process stage timing;
  an uncached batch-1 query-embedding probe; exact structured metadata filters
  with push-down/post reporting and typed unavailable-metadata errors; a
  canonical, privacy-safe configuration snapshot and its SHA-256.
- **Out:** progressive Instant/Hybrid/Refined delivery, `subscribe`, and
  cancellable multi-stage search (API v2, WP-4.3); product filter syntax
  (`ext:`, `in:`, date expressions), UI, and shell commands; document-layer
  aggregation, deduplication, reranking, or diversity changes (later phases);
  scoring, chunking, embedding, and model changes; index migration or metadata
  backfill (absent metadata fails closed); new dependencies; any new budget,
  quality claim, or inference engine.

### 9.3 Requirements (EARS)

These rows are Draft. On acceptance each moves to `Open`; no v1 row changes.

| ID | Requirement | Verification | Status |
|---|---|---|---|
| SPEC-0002-R17 | When `Engine::search_with` runs with `SearchMode::Evaluation` and `SearchRequest.limit = n`, the engine shall accept `1 <= n <= 1000`, ask every enabled first-stage retriever for at least `n` candidates (or its configured floor when larger), return at most `n` unique chunk hits, and report the effective candidate depths, the returned hit and distinct-document counts, and whether any candidate cap was reached; `n = 0` or `n > 1000` shall fail with `InvalidInput`, and `SearchMode::Interactive` shall keep the v1 clamp to `1..=50`. | `eval_depth_accepts_1000_and_rejects_1001`; `eval_depth_fills_requested_hits_when_matches_exist`; `depth_report_counts_distinct_documents_and_cap`; `interactive_search_keeps_v1_depth_clamp` | Draft |
| SPEC-0002-R18 | The engine shall order search hits by score descending, then document ID ascending (bytewise), then chunk start ascending, chunk end ascending, and chunk ID ascending, so that for a fixed index, configuration, query, mode, and filter the serialized hit list is identical on every call. | `equal_scores_order_by_document_then_offsets`; `repeated_search_is_byte_identical`; property `candidate_insertion_order_does_not_change_ranking` | Draft |
| SPEC-0002-R19 | When `SearchOptions.telemetry` is true, the engine shall return a `SearchTelemetry` value with the schema version, `delivery_stage = single`, total duration, one timing record per executed search stage in canonical order, the query-embedding timing when the semantic channel runs, and the requested and returned hit counts; enabling telemetry shall not change any hit, score, order, filter outcome, or error, and no record shall contain query text or a query hash, document ID, title, path, snippet, absolute path, or user data. | `telemetry_records_each_executed_stage_once`; `telemetry_does_not_change_hits_or_filter_outcome`; `telemetry_omits_query_document_and_path_fields`; `telemetry_emits_single_delivery_stage_only` | Draft |
| SPEC-0002-R20 | When `Engine::probe_query_embedding` is called, the engine shall perform exactly one batch-1 query embedding with cache bypass and return its duration and public model identity, or `Unavailable` when no semantic model is available; it shall not return the vector or text, shall not read or write the query-embedding cache, and shall not change the hits of a later search. | `query_embedding_probe_is_batch_one_and_uncached`; `query_embedding_probe_reports_unavailable_without_model`; `query_embedding_probe_does_not_change_search_results` | Draft |
| SPEC-0002-R21 | When `SearchOptions.filters` is present in evaluation mode, the engine shall evaluate every predicate against indexed document metadata — extension equal to one of the listed lowercase extensions, `modified_after_ns` inclusive, `modified_before_ns` exclusive, `folder` as a complete-segment bytewise prefix of the path relative to the named root, and `min_bytes`/`max_bytes` inclusive — return only hits whose document satisfies all active predicates, and never ignore a predicate; filters combined with `SearchMode::Interactive` shall fail with `InvalidInput`. | `extension_filter_matches_case_insensitively_and_exactly`; `modified_filter_uses_inclusive_after_and_exclusive_before`; `folder_filter_matches_complete_root_relative_segments`; `size_filter_uses_inclusive_bounds`; `combined_filters_are_conjunctive`; `interactive_filters_are_rejected` | Draft |
| SPEC-0002-R22 | The engine shall report every active predicate's application mode (`pushdown` or `post`), an aggregate mode that is `pushdown` only when all predicates were applied before candidate truncation, the examined and matched candidate counts, the returned count, and `possibly_incomplete`; post filtering shall examine the candidate pool before the final limit truncation and preserve the relative order of surviving hits; `possibly_incomplete` shall be exactly `DepthReport::candidate_cap_reached && FilterReport::matched < DepthReport::requested_hits`, so a bounded raw pool is never reported as a complete filtered ranking; a filter that matches nothing shall return an empty successful response rather than an error. | `filter_report_records_pushdown_and_post_per_predicate`; `post_filter_examines_pool_before_limit_truncation`; `post_filter_at_configured_depth_is_possibly_incomplete`; `filtered_search_at_exhausted_depth_is_complete`; `filtered_search_with_no_matches_is_empty_success` | Draft |
| SPEC-0002-R23 | If an active predicate requires metadata that is absent, not representable, or not complete for the indexed documents, then the engine shall fail the request with `EngineError::MetadataUnavailable` naming only the metadata field and return no partial hits; a malformed filter (no predicate, invalid extension, non-normalized folder, `min_bytes > max_bytes`, or `modified_after_ns >= modified_before_ns`) shall fail with `InvalidInput`, and an unknown folder root shall fail with `NotFound`. | `missing_filter_metadata_is_metadata_unavailable`; `malformed_filter_is_invalid_input`; `unknown_filter_root_is_not_found`; `filter_error_names_field_not_path` | Draft |
| SPEC-0002-R24 | `Engine::config_snapshot` shall expose the effective semantic configuration as canonical JSON and its lowercase SHA-256, identical for two engines with the same effective configuration regardless of data, resource, or output paths, changing when a semantic setting or an active model's content changes, excluding paths, credentials, timestamps, logging destinations, and user or host identity, and failing with `MetadataUnavailable` when an active model has no content hash. | `config_snapshot_is_canonical_and_stable`; `config_snapshot_is_path_independent`; `config_snapshot_changes_when_semantic_setting_changes`; `config_snapshot_requires_active_model_hash`; `config_snapshot_contains_no_paths_or_user_data` | Draft |
| SPEC-0002-R25 | `Engine::search`, `SearchResponse`, `SearchHit`, `EngineStatus`, the §4.4 shell commands, and every v1 JSON payload shape shall keep their v1 signatures, fields, and result semantics; `Engine::search` shall keep its v1 clamp, hits, and scores, with the defined order of score ties (R18) as the only permitted difference; the v1.1 methods shall not be exposed as Tauri commands; and no v1.1 return value, error, or log record shall contain document content, titles, file names, absolute or user paths, query text, or secrets. | `v1_search_results_and_payload_are_unchanged`; existing `golden_lexical` and `golden_hybrid_cpu`; `v1_1_methods_are_not_shell_commands` (inspection); `new_outputs_contain_no_content_or_paths` | Draft |

Dependency map for the requesting spec:

| SPEC-0003 | Engine capability |
|---|---|
| R15 | R17: evaluation depth and typed limit failures; the CLI remains harness-side |
| R16 | R24: semantic snapshot and hash |
| R17 | unchanged v1 index, root, and status API; the sidecar is `seeky-bench`'s |
| R18 | R17, R18, R21: depth, deterministic order, filters |
| R22 | R19, R24, R25: no content, paths, or identifiers in new outputs |
| R25 | R19, R20: stage timings and batch-1 query-embedding latency |
| R26 | R20 plus the unchanged search and status APIs; time-to-searchable and interference need no new surface |
| R31 | R18: repeat-run order determinism |
| R32 | R21–R23: exact filters, mode/truncation reporting, typed errors |

### 9.4 Interfaces

#### 9.4.1 Search types (in `seeky-core`, re-exported by `seeky-engine`)

`SearchRequest` (§4.1) stays exactly as it is. `SearchMode` and `SearchOptions`
are new and default to v1 behavior.

```rust
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum SearchMode {
    #[default]
    Interactive, // v1 semantics, including the 1..=50 clamp
    Evaluation,  // v1.1 evaluation depth and filters
}

#[derive(Clone, Debug, Default)]
pub struct SearchOptions {
    pub mode: SearchMode,
    pub filters: Option<MetadataFilter>, // Some => mode must be Evaluation
    pub telemetry: bool,                 // false => no timing overhead
}

pub struct SearchOutcome {
    pub response: SearchResponse,        // §4.1, unchanged shape
    pub depth: DepthReport,
    pub filter: Option<FilterReport>,
    pub telemetry: Option<SearchTelemetry>,
}

pub struct CandidateDepths {
    pub filename: usize, // 0 when the retriever is disabled
    pub lexical: usize,
    pub dense: usize,
}

pub struct DepthReport {
    pub requested_hits: usize,
    pub returned_hits: usize,
    pub distinct_documents: usize,
    pub candidate_depths: CandidateDepths,
    /// True when a retriever returned exactly its requested depth or the
    /// ranked pool was truncated before the final response, so lower-ranked
    /// eligible hits may exist.
    pub candidate_cap_reached: bool,
}
```

`SearchResponse` and `SearchHit` are not extended: the shell's JSON payload
shape stays byte-compatible (R5, R25).

#### 9.4.2 Engine methods

```rust
impl Engine {
    // v1 signature and behavior, unchanged.
    pub fn search(&self, request: &SearchRequest) -> Result<SearchResponse, EngineError>;

    /// Evaluation and perf entry point. Never a shell command.
    pub fn search_with(
        &self,
        request: &SearchRequest,
        options: &SearchOptions,
    ) -> Result<SearchOutcome, EngineError>;

    /// One uncached batch-1 query embedding; no vector is returned.
    pub fn probe_query_embedding(
        &self,
        text: &str,
    ) -> Result<QueryEmbeddingProbe, EngineError>;

    /// Canonical semantic configuration for hashing (SPEC-0003 R16).
    pub fn config_snapshot(&self) -> Result<EngineConfigSnapshot, EngineError>;
}
```

`search(request)` shall be exactly `search_with(request, &SearchOptions::default()).response`
in behavior, including the v1 clamp and JSON shape. Sharing one pipeline is
required; a second ranking implementation is not. The inherently variable
`took_ms` field is not part of an equality test; hits, scores, order, and
errors are.

#### 9.4.3 Metadata filters

```rust
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MetadataFilter {
    /// Exact extensions, ORed, lowercase without a leading dot.
    /// Empty means no extension constraint.
    pub extensions: Vec<String>,
    /// Inclusive lower bound on the indexed modified time, UTC ns.
    pub modified_after_ns: Option<i64>,
    /// Exclusive upper bound on the indexed modified time, UTC ns.
    pub modified_before_ns: Option<i64>,
    /// Root-scoped, corpus-relative folder prefix.
    pub folder: Option<FolderFilter>,
    /// Inclusive size bounds in bytes.
    pub min_bytes: Option<u64>,
    pub max_bytes: Option<u64>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FolderFilter {
    pub root_id: RootId,        // §4.1; the corpus root registered by the harness
    pub relative_prefix: String, // POSIX, no leading '/', trailing '/'
}
```

The harness maps SPEC-0004 query filters (§4.5 of SPEC-0004) to this type:

| SPEC-0004 key | Engine field |
|---|---|
| `extensions` | `extensions`, lowercased, dots removed |
| `modified_after` | `modified_after_ns`, RFC 3339 parsed to UTC ns, inclusive |
| `modified_before` | `modified_before_ns`, RFC 3339 parsed to UTC ns, exclusive |
| `folder_prefix` | `FolderFilter { root_id, relative_prefix }`, root resolved from the `Root` returned by `add_root` |
| `min_bytes` / `max_bytes` | `min_bytes` / `max_bytes`, inclusive |

Filter validation is part of the request contract:

- At least one predicate must be present; an all-empty filter is `InvalidInput`.
- An extension is 1–24 ASCII bytes, lowercase `[a-z0-9+_-]`, without a dot or
  separator; the list is deduplicated and sorted.
- `modified_after_ns < modified_before_ns` when both are present.
- `min_bytes <= max_bytes`, and both fit the index's signed byte range.
- `relative_prefix` is nonempty, uses `/`, ends with `/`, has no leading `/`,
  no empty, `.` or `..` segment, and no backslash or NUL.
- `root_id` must name an existing root; otherwise `NotFound`.

#### 9.4.4 Filter report

```rust
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FilterKind { Extension, Modified, Folder, Size }

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FilterMode { Pushdown, Post }

pub struct FilterApplication {
    pub kind: FilterKind,
    pub mode: FilterMode,
}

pub struct FilterReport {
    /// Pushdown only when every active predicate is Pushdown.
    pub mode: FilterMode,
    /// One entry per active predicate, in FilterKind order.
    pub applications: Vec<FilterApplication>,
    /// Candidates examined by the filter stage before the final limit.
    pub examined: usize,
    /// Candidates satisfying all active predicates before the final limit.
    pub matched: usize,
    /// Hits returned after applying the requested depth.
    pub returned: usize,
    /// True when an eligible lower-ranked hit may have been omitted.
    pub possibly_incomplete: bool,
}
```

`FilterMode::Pushdown` means the predicate was applied inside every enabled
first-stage retriever, before that retriever's candidate cap, so a cap acts on
the already-filtered stream. `FilterMode::Post` means it was applied after
candidate generation or fusion. A mixed request reports `Post` as the aggregate
mode and each predicate's own mode in `applications`.

#### 9.4.5 Search telemetry

This is in-process diagnostic data returned to the caller, not analytics:
nothing is collected, persisted, logged, or sent over a network (P3, ADR-0010).

```rust
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DeliveryStage { Single } // v1.1 emits only Single

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SearchStage {
    Filename,
    Lexical,
    Dense,
    Fuse,
    Snippets,
}

pub struct StageTiming {
    pub stage: SearchStage,
    pub duration_ns: u64,       // monotonic clock, nonnegative
    pub items_in: Option<u64>,  // candidate count entering the stage
    pub items_out: Option<u64>, // candidate count leaving the stage
}

pub struct ModelIdentity {
    pub task: String,            // "embedder", "reranker", ...
    pub id: String,              // public model ID
    pub revision: String,
    pub variant: String,         // deployed precision/provider variant
    pub dimension: Option<u32>,
}

pub struct QueryEmbeddingTiming {
    pub duration_ns: u64,
    pub cache_hit: bool,
    pub model: Option<ModelIdentity>,
}

pub struct SearchTelemetry {
    pub schema_version: u16,             // 1
    pub delivery_stage: DeliveryStage,  // Single
    pub total_ns: u64,                  // request entry to response construction
    pub query_embedding: Option<QueryEmbeddingTiming>,
    pub stages: Vec<StageTiming>,       // canonical order, at most one per stage
    pub results_requested: usize,       // effective depth after mode clamping
    pub results_returned: usize,
}
```

#### 9.4.6 Query-embedding probe

```rust
#[derive(Clone, Debug)]
pub enum QueryEmbeddingProbe {
    Available {
        model: ModelIdentity,
        duration_ns: u64,
    },
    Unavailable,
}
```

`Unavailable` is a successful result, not an error: the perf harness reports
`null` with a warning per SPEC-0003 §4.10. An inference failure is
`EngineError::Inference`.

#### 9.4.7 Configuration snapshot

```rust
pub struct EngineConfigSnapshot(/* normalized fields, §9.5.7 */);

impl EngineConfigSnapshot {
    /// Canonical JSON: sorted keys, compact separators, no trailing newline.
    pub fn canonical_json(&self) -> String;
    /// Lowercase SHA-256 of canonical_json()'s UTF-8 bytes.
    pub fn sha256(&self) -> String;
}
```

#### 9.4.8 Errors

§4.3 is unchanged except for one additive variant:

```rust
#[error("metadata unavailable: {0}")] MetadataUnavailable(String),
```

The argument is a metadata field name (`extension`, `modified`, `folder`,
`size`, `model.sha256`), never a path, title, or document content. Existing
variants and their conditions are unchanged.

### 9.5 Behavior details

#### 9.5.1 Mode, depth, and candidates

- `SearchMode::Interactive` preserves v1 exactly: `None` means 20 and the
  request is clamped to `1..=50`; candidate depths are the v1 configured
  defaults. Telemetry is the only addition, and it does not change retrieval.
- `SearchMode::Evaluation` requires `Some(n)` with `1 <= n <= 1000`;
  `None`, `0`, and values above 1,000 are `InvalidInput`. A request is never
  silently clamped in this mode, because clamping would misreport depth.
- `SearchOptions.filters` is valid only with `SearchMode::Evaluation`; filters
  with the interactive mode are `InvalidInput` in v1.1, because product filter
  syntax and UI are out of scope.
- In evaluation mode, every enabled retriever requests
  `max(n, configured_floor)` candidates. The floor and effective request are
  recorded in `DepthReport::candidate_depths`. This is a deliberate depth
  increase outside product budgets; it must not be used to claim S1–S5.
- `distinct_documents` is the number of unique `doc_id` values among the
  returned hits. It is a diagnostic, not a depth guarantee; a single document
  may contribute several chunks.
- `requested_hits` is the effective depth after mode clamping; `returned_hits`
  is `response.hits.len()`. `candidate_cap_reached` concerns candidate
  generation, not the final response.
- `candidate_cap_reached` is conservative: true when any enabled retriever
  returned exactly its requested depth, or when any stage truncated the ranked
  pool below the configured depth before the final response. It means "a lower
  ranked eligible hit may exist", not "a lower ranked hit does".
- Hits are unique by `chunk_id`; duplicates are removed before ranking output.
  Chunks from the same document remain separate hits, so `distinct_documents`
  can be smaller than `returned_hits`. Document-level aggregation stays out of
  scope (§9.2).
- Fewer hits than requested is not an error by itself. It is complete when a
  cap was not reached; it is potentially incomplete when one was.

#### 9.5.2 Deterministic order

The total order is:

1. `score` descending, comparing the serialized `f64` values exactly;
2. `doc_id` ascending, bytewise;
3. `start` ascending, then `end` ascending;
4. `chunk_id` ascending.

Scores are finite; a non-finite score is an engine bug and an `Internal` error,
never a silent reordering. The v1 golden contract already allows items whose
scores tie within tolerance to swap (R3); this rule makes that tie order
defined. It is deterministic for a fixed index and root, not across roots,
because the v1 document ID is derived from the indexed path.

#### 9.5.3 Telemetry

- Stages are timed at the same boundaries as the §5.3 spans. A stage that did
  not run is omitted; no zero-filled row is invented. Each stage appears at
  most once and in the enum order listed in §9.4.5.
- `total_ns` uses a monotonic clock and covers request entry through response
  construction, including snippets. `duration_ns` is per stage. Durations are
  variable by nature; only their structure and meaning are stable.
- `query_embedding` is present when the semantic channel embeds the query. A
  search-cache hit sets `cache_hit = true`; the duration then covers lookup and
  reuse. `search_with` never populates the cache differently because telemetry
  is on.
- Enabling telemetry must not alter hits, scores, order, filter results, or
  errors. A test compares the `SearchResponse` from otherwise identical calls.
- `delivery_stage` is always `Single` in v1.1. `Instant`, `Hybrid`, and `Refined`
  belong to API v2 and are never fabricated; adding them bumps
  `schema_version`.
- No telemetry field carries query text or a query hash, document ID, title,
  snippet, path, file name, absolute root, process command line, or user data.
  Counts, durations, stage names, and public model identity are the whole
  vocabulary. `ModelIdentity::id` is the manifest's public model identifier; a
  filesystem path is never used as a model ID. The engine does not persist
  telemetry, install a subscriber, or change logging.

#### 9.5.4 Query-embedding probe

- Bypasses the query-embedding cache and does not create or refresh an entry.
- Performs exactly one batch-1 embedding of `text`, so the perf harness can
  report query-embedding latency separately from indexing throughput
  (SPEC-0003 §5.5 step 5).
- Returns only duration and model identity. The vector and text are dropped;
  neither is logged or exposed in an error.
- `Unavailable` when no semantic model is active; an inference failure is a
  typed `Inference` error.
- Running the probe must not change a later search's hits. Session warm-up is
  permitted; results and cache contents are not.

#### 9.5.5 Metadata filters

All active predicates are ANDed. Predicate semantics:

- **Extension.** Compare the lowercase indexed file extension without a leading
  dot against the set. Matching is exact; `pdf` does not match `.pdf` or
  `application/pdf`. For rendered corpus files this is the output file suffix,
  so a scanned PDF still has `pdf` even when the corpus `format` is
  `scanned-pdf`; the corpus `format` field is not consulted. A document whose
  extension is empty when an extension predicate is active is unavailable
  metadata (R23), not a non-match.
- **Modified time.** Compare the indexed UTC timestamp in nanoseconds.
  `modified_after_ns` is inclusive; `modified_before_ns` is exclusive, matching
  SPEC-0004 §4.5. A document with no representable timestamp (including the
  legacy zero sentinel) is unavailable metadata when a date predicate is active.
- **Folder.** Normalize the indexed path to `/`, make it relative to the named
  root, and require a bytewise prefix match with `relative_prefix`. The
  trailing `/` makes matching segment-complete: `a/b/` matches `a/b/c.txt`, not
  `a/bc.txt`. A document outside the root is a non-match. Symlink resolution
  follows the indexed canonical root; `..` is rejected at validation.
- **Size.** Compare the indexed file size in bytes. Both bounds are inclusive.
  A negative or absent size is unavailable metadata.
- Filters do not rewrite scores. In `Post` mode, the surviving hits keep their
  relative order from the unfiltered ranking. In `Pushdown` mode, candidate
  ranks and therefore fused scores may legitimately differ because retrieval
  sees only matching documents; the report says so.
- Filters apply to the candidate pool before the final `limit` truncation.
  Filtering the already-truncated top-`n` list is prohibited, because it hides
  starved depth (R22, SPEC-0003 R32).
- An evaluation query with filters is still evaluated against the unfiltered
  qrels; filtering constrains retrieval, not relevance. Matching metadata is
  necessary but not sufficient for a positive grade (SPEC-0004 §4.5).

#### 9.5.6 Filter reporting and truncation

- `applications` has one entry per active predicate. The aggregate `mode` is
  `Pushdown` only if every entry is `Pushdown`.
- `examined` counts candidates the filter stage saw before the final limit;
  `matched` counts those satisfying every predicate; `returned` is
  `min(matched, requested_hits)`. In `Pushdown` mode `examined` is the filtered
  stream that ranking saw, so it may equal `matched`.
- `possibly_incomplete` is exactly
  `depth.candidate_cap_reached && filter.matched < depth.requested_hits`. It is
  false when retrieval examined every eligible candidate and the filter simply
  matched fewer than requested. A filter that matches nothing returns `Ok` with
  zero hits; it is "possibly incomplete" only when a cap was reached. This is
  the fail-closed signal for SPEC-0003 §5.1.
- `DepthReport::returned_hits` and `FilterReport::returned` are equal for a
  filtered request.
- Consumer rule: `seeky-bench` fails `INSUFFICIENT_DEPTH` before writing a
  quality artifact when `possibly_incomplete` is true and `returned` is below
  the largest metric cutoff, and it never treats a starved list as a quality
  result. `distinct_documents` is recorded as a diagnostic; document-depth
  guarantees belong to a later document-layer spec, not this extension.

#### 9.5.7 Configuration snapshot

`EngineConfigSnapshot` covers every engine-owned setting that can change
ranking, filter behavior, or a measured search latency. The JSON shape is:

```json
{
  "schema_version": 1,
  "search": {
    "default_limit": 20,
    "interactive_max_hits": 50,
    "evaluation_max_hits": 1000,
    "candidate_depths": {"filename": 40, "lexical": 80, "dense": 80},
    "fusion": {"kind": "rrf", "k": 60.0,
               "weights": {"filename": 1.0, "lexical": 1.0, "dense": 1.0}},
    "document": {"enabled": false, "passages_per_document": null},
    "rerank": {"enabled": false, "depth": null, "token_budget": null},
    "diversity": {"enabled": false, "lambda": null},
    "snippets": {"enabled": true},
    "query_cache": {"enabled": false, "capacity": null},
    "filters": {
      "pushdown": ["extension", "modified", "folder", "size"],
      "post_fallback": true,
      "metadata_fields": ["extension", "modified", "folder", "size"]
    }
  },
  "models": [],
  "execution": {
    "provider": "cpu",
    "intra_op_threads": 1,
    "inter_op_threads": 1,
    "query_batch": 1
  }
}
```

The values above illustrate the current v1 implementation; they are not new
defaults and change only with a benchmark report. Keys, types, ordering, and
exclusions are normative. An active model adds one entry per model, sorted by
task then ID:

```json
{"task": "embedder", "id": "<public-id>", "revision": "<revision>",
 "variant": "<precision/provider variant>", "dimension": 384,
 "sha256": "<64 lowercase hex>", "provider": "cpu",
 "preprocessing": "<recipe-id>"}
```

- Canonical JSON means sorted keys, compact separators, UTF-8, no trailing
  newline, and shortest round-trippable numbers (SPEC-0003 §4.9, SPEC-0004
  §4.1). Arrays have a fixed order: models by `(task, id)`, filter lists in
  `FilterKind` order.
- `sha256` is the lowercase digest of those exact bytes. Two engines with the
  same effective configuration produce the same JSON and hash; changing any
  semantic value or active model's bytes changes it.
- Excluded: data, resource, model, database, NPU IR, PDFium, output, cache, and
  temp paths; credentials; timestamps; logging destinations; host name, user
  name, and environment identity. Model IDs remain public identifiers; a
  filesystem path is never used as a model ID, even when a model was loaded from
  a file.
- An active model without a content hash makes `config_snapshot` fail with
  `MetadataUnavailable("model.sha256")`. A lexical-only engine reports
  `"models": []`.
- The harness owns evaluation settings that the engine does not: requested
  limit, metric cutoffs, seed, `code_enabled`, and split. It merges the engine
  snapshot with those values and hashes the combined canonical document, as
  SPEC-0003 R16 requires. `EngineConfigSnapshot::sha256()` is a component, not
  a replacement for that combined `config_hash`.

#### 9.5.8 Consumption by `seeky-bench` and `seeky-eval`

The implemented `seeky-eval` API (WP-1.1) is used directly; no metric is
reimplemented:

- Parse `Query::filters` (`Option<serde_json::Value>`) into `MetadataFilter`
  before opening the engine; unknown or malformed keys are `EvalError` `SCHEMA`.
  Resolve the corpus root to the `RootId` returned by `add_root` during `index`,
  or found by exact path through `list_roots` during `eval`.
- Call `search_with` with `SearchMode::Evaluation`, `limit = Some(--limit)`,
  the parsed filter, and telemetry for `perf` or a diagnostic eval run.
- Map `SearchHit.path` to a document with `Dataset::document_by_path` after
  normalizing separators and stripping the corpus root; a miss or an
  out-of-root path is an error and the path never enters a report.
- Build the document run from the first rank per document. For the passage run,
  build `seeky_eval::ChunkHit` from each hit (`start_char`/`end_char` from
  `SearchHit.start`/`end`, checked nonnegative and `start < end`; `page` from
  `SearchHit.page`, checked into `u32`) and call `map_chunk_run`, which uses
  `Dataset::map_chunk_to_passage`. Count `unmapped_chunks` from its result.
- Apply the `INSUFFICIENT_DEPTH` rule of §9.5.6 and SPEC-0003 §5.1 before
  writing artifacts.
- Use `SearchTelemetry` for `PerformanceReport::search` stage rows and
  `probe_query_embedding` for `query_embedding` latency; a null model is
  `Unavailable`, never a fabricated zero.
- Put `config_snapshot().canonical_json()` into the combined config document
  written as `config.snapshot.json`, and hash that combined document for
  `system.config_hash`.

#### 9.5.9 Privacy, concurrency, and side effects

- The new surface is local and in-process. No telemetry, analytics, network
  call, persisted history, or identifier is introduced; "telemetry" here means
  timing records returned to the caller (P3, ADR-0010).
- No new lock is held across inference or user-file I/O. The probe uses the
  existing inference synchronization; it does not remove the v1 concurrency
  limitations (SPEC-0002 §5.2, audit A7).
- No engine crate gains a Tauri or UI dependency; the shell does not call the
  new methods (ADR-0015).
- Evaluation depth may be slow and memory-heavy by design. It is not a product
  path and is never budget-eligible; interactive latency is unchanged.

### 9.6 Acceptance

#### 9.6.1 Tests to write first

Write these before the implementation, hardware-free unless marked, with the
requirement ID in the name or a doc comment. Use temporary directories, fixed
fixtures, and no network.

| Test | Requirement IDs |
|---|---|
| `eval_depth_accepts_1000_and_rejects_1001` | R17 |
| `eval_depth_fills_requested_hits_when_matches_exist` | R17 |
| `depth_report_counts_distinct_documents_and_cap` | R17 |
| `interactive_search_keeps_v1_depth_clamp` | R17, R25 |
| `equal_scores_order_by_document_then_offsets` | R18 |
| `repeated_search_is_byte_identical` | R18 |
| Property: `candidate_insertion_order_does_not_change_ranking` | R18 |
| `telemetry_records_each_executed_stage_once` | R19 |
| `telemetry_does_not_change_hits_or_filter_outcome` | R19 |
| `telemetry_omits_query_document_and_path_fields` | R19, R25 |
| `telemetry_emits_single_delivery_stage_only` | R19 |
| `query_embedding_probe_is_batch_one_and_uncached` (fake embedder) | R20 |
| `query_embedding_probe_reports_unavailable_without_model` | R20 |
| `query_embedding_probe_does_not_change_search_results` | R20 |
| `extension_filter_matches_case_insensitively_and_exactly` | R21 |
| `modified_filter_uses_inclusive_after_and_exclusive_before` | R21 |
| `folder_filter_matches_complete_root_relative_segments` | R21 |
| `size_filter_uses_inclusive_bounds` | R21 |
| `combined_filters_are_conjunctive` | R21 |
| `interactive_filters_are_rejected` | R21, R25 |
| `filter_report_records_pushdown_and_post_per_predicate` | R22 |
| `post_filter_examines_pool_before_limit_truncation` | R22 |
| `post_filter_preserves_survivor_order` | R22 |
| `post_filter_at_configured_depth_is_possibly_incomplete` | R22 |
| `filtered_search_at_exhausted_depth_is_complete` | R22 |
| `filtered_search_with_no_matches_is_empty_success` | R22 |
| `missing_filter_metadata_is_metadata_unavailable` | R23 |
| `malformed_filter_is_invalid_input` | R23 |
| `unknown_filter_root_is_not_found` | R23 |
| `filter_error_names_field_not_path` | R23, R25 |
| `config_snapshot_is_canonical_and_stable` | R24 |
| `config_snapshot_is_path_independent` | R24 |
| `config_snapshot_changes_when_semantic_setting_changes` | R24 |
| `config_snapshot_requires_active_model_hash` | R24 |
| `config_snapshot_contains_no_paths_or_user_data` | R24, R25 |
| `v1_search_results_and_payload_are_unchanged` | R25 |
| `new_outputs_contain_no_content_or_paths` | R25 |
| `v1_1_methods_are_not_shell_commands` (inspection) | R25 |
| Existing `golden_lexical` and `golden_hybrid_cpu` (`hw-tests`) | R3, R25 |

#### 9.6.2 Gates and compatibility

- No new benchmark gate and no quality claim. The extension makes Q3
  Recall@100 and SPEC-0003 §3.2 performance metrics measurable; WP-1.7/B0 owns
  their evidence and ADR budget locking.
- Interactive defaults, candidate depths, and the §4.1 JSON payloads are
  unchanged; the v1 golden tests pass without a new snapshot.
- Evaluation depth and filters are not eligible for S1–S5 or any product
  budget. `perf` measures the interactive path through
  `search_with(..., SearchMode::Interactive)`.
- No new dependency, model, or inference engine. If an implementation needs
  one, stop and report rather than adding it.
- Green: `cargo fmt --all --check`,
  `cargo clippy --workspace --all-targets -- -D warnings` with and without
  `hw-tests`, `cargo test --workspace`, `cargo test --workspace --features hw-tests -- --test-threads=1`,
  and `cargo deny check`. No TypeScript change is expected.

#### 9.6.3 Inspection

- `apps/desktop` contains no `search_with`, `probe_query_embedding`, or
  `config_snapshot` call and no new command (R25).
- `SearchResponse`, `SearchHit`, `EngineStatus`, and their serde shapes are
  unchanged (R25).
- Telemetry, snapshots, and errors contain no content, titles, paths, query
  text, or user data (R19, R24, R25).
- No engine crate depends on `tauri`; no new dependency appears (R25,
  SPEC-0001).
- No new lock is held across inference or user-file I/O (§5.2).

### 9.7 Risks and open questions

None of these conflicts with the vision, an accepted ADR, or the methodology;
they need maintainer confirmation before acceptance, not before drafting.

| # | Item | Proposal | Decides | Blocking |
|---|---|---|---|---|
| 1 | Tie-break uses the v1 document ID, which is derived from the indexed path, so equal-score order can differ across roots or machines. | Guarantee determinism for a fixed index and root only; SPEC-0003 repeat runs use one data directory. A corpus-relative tie-break can replace it in a later API version. | Maintainer | No |
| 2 | Evaluation `limit` counts ranked hits, not distinct documents; repeated chunks can make `distinct_documents` smaller than the cutoff. | Report both; the harness fails closed on caps, and document-layer aggregation stays out of scope. Confirm that Recall@100 is measured on the deduplicated document run as SPEC-0003 §5.1 already defines. | Maintainer | No |
| 3 | "Pushdown" is only meaningful if the predicate is applied before each retriever's cap; a filter applied to a fused candidate pool is post with residual depth risk. | Report `Post` unless every predicate meets the pushdown definition; never claim pushdown for a pool-level filter. | Implementer + maintainer | No |
| 4 | The engine snapshot is one component of SPEC-0003's combined config hash. | Harness merges engine snapshot plus evaluation settings and hashes the combined canonical JSON; the engine digest is recorded but not called `config_hash`. | Maintainer | No |
| 5 | The PoC may have an active model without a manifest hash. | Hash the deployed model bytes; if unavailable, fail `config_snapshot` with `MetadataUnavailable("model.sha256")`; lexical-only runs report no models. | Implementer | No |
| 6 | Adding `MetadataUnavailable` to `EngineError` changes a public enum. | Additive variant only; no existing variant, message condition, or shell mapping changes. | Maintainer | No |
| 7 | Effective thread counts in the snapshot can differ across hardware, so the same logical configuration hashes differently. | Include effective values; comparisons already require the same hardware tier and environment (SPEC-0003 R28/R29). | Maintainer | No |
| 8 | A corpus root may be nested under another indexed root, making a folder predicate's root ambiguous. | The harness registers the dataset root itself and passes that exact `RootId`; the engine never guesses among roots. | Implementer | No |
| 9 | Old indexes can have empty extensions or zero timestamps. | Fail closed with `MetadataUnavailable` when the predicate needs them; do not silently exclude or backfill. | Implementer | No |
| 10 | Telemetry stage boundaries need refactoring the PoC search function. | Reuse the §5.3 span boundaries; if a boundary cannot be measured without changing behavior, omit that stage rather than inventing a value. | Implementer | No |
| 11 | A SPEC-0004 `extensions` filter could mean the file suffix or the corpus `format`; they differ for `scanned-pdf` and `scanned-image`. | Filter the indexed file suffix (the user's `ext:` intent); the harness validates that every declared filter token is a real suffix in the corpus. Change the definition only if the maintainer reads `format` as normative. | Maintainer | No |
