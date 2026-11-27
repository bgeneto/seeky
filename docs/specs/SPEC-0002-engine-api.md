# SPEC-0002 — Engine API (v1: headless engine, no behavior change)

| Field | Value |
|---|---|
| Status | Accepted |
| Version | 0.2 (API v1; API v2 adds progressive search in WP-4.3) |
| Owner | Maintainer |
| Phase / work packages | Phase 0 — WP-0.2, WP-0.3 |
| Crates touched | `seeky-core`, `seeky-extract`, `seeky-infer`, `seeky-store`, `seeky-search`, `seeky-engine`, `seeky-desktop` |
| Governing docs | [ADR-0015](../adr/0015-engine-first-architecture.md); [ADR-0006](../adr/0006-narrow-webview-capabilities.md); [ADR-0024](../adr/0024-source-code-indexing-opt-in.md); [ADR-0016](../adr/0016-cpu-first-npu-ready-execution.md); [architecture overview](../architecture/overview.md) §3, §6; [SPEC-0001](SPEC-0001-workspace-and-crate-boundaries.md); [conformance audit](../validation/poc-conformance-audit.md) A7–A9 |
| Benchmark gates | None. Ranked output must be identical to the pre-extraction snapshot (R3, R4) |

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
| SPEC-0002-R1 | `seeky-engine` shall expose an `Engine` type whose methods (§4.2) cover every PoC command: status, roots, watching, backend selection and probing, indexing and its cancellation, search, document view, and document path resolution. | compile-time: the shell calls only these methods | Open |
| SPEC-0002-R2 | No public item of an engine crate shall take or return a Tauri type, and `Engine` shall be `Clone + Send + Sync`. | inspection; static assertion test `engine_is_send_sync_clone` | Open |
| SPEC-0002-R3 | When the golden corpus is indexed and the golden queries are run, the engine shall return, per query, the same ranked list (relative path, chunk start and end, page, matched channels, rank) as the snapshot captured from the PoC, with scores equal within 1e-9 for the lexical-only run and 1e-6 for the hybrid run. | `seeky-engine` tests `golden_lexical` (hardware-free) and `golden_hybrid_cpu` (`hw-tests`) | Open |
| SPEC-0002-R4 | The golden snapshot shall be captured on the PoC before any code moves, by a capture test added to the PoC in WP-0.2's first commit, and committed with its corpus and query list. | inspection of commit order; snapshot file header records the source commit | Implemented (WP-0.2) |
| SPEC-0002-R5 | The shell shall keep every PoC command name, argument name, and JSON payload shape unchanged, except that `open_local_file(path)` is replaced by `open_document(id)`. | inspection; the React UI works with only the `open_document` call changed; `npm run build` | Open |
| SPEC-0002-R6 | When `open_document` is called with an ID that is not in the index, the shell shall return an error and open nothing. | integration test on `Engine::document_path` returning `None`; shell code review | Open |
| SPEC-0002-R7 | When `open_document` resolves a document whose extension is not in the open allowlist (§5.4), the shell shall reveal the file in the system file manager instead of opening it. | unit test of the allowlist function; manual check on Windows | Open |
| SPEC-0002-R8 | The shell shall not accept a filesystem path from the webview for any file action, and shall not depend on `rusqlite`, `ort`, `notify`, `walkdir`, or any extractor crate. | inspection; `cargo deny check bans` (SPEC-0001-R13) | Open |
| SPEC-0002-R9 | While indexing, the engine shall report progress and health through the `EngineEvents` sink with the PoC payloads, and the shell shall forward them as the Tauri events `index-progress` and `index-health` unchanged. | unit test with a recording sink; UI progress works | Open |
| SPEC-0002-R10 | When `cancel_indexing` is called during indexing, the running `index_path` call shall return a summary with `cancelled = true`, as in the PoC. | integration test `cancel_returns_cancelled_summary` | Open |
| SPEC-0002-R11 | While one `index_path` call runs, a second call shall wait for it to finish (PoC behavior); indexing shall never run twice concurrently. | integration test with two threads | Open |
| SPEC-0002-R12 | Engine library crates shall return `thiserror` errors; `Engine` methods shall return `Result<T, EngineError>` with the variants in §4.3, and the shell shall map them to strings with `Display`. | inspection; `cargo tree -i anyhow` (SPEC-0001-R18) | Open |
| SPEC-0002-R13 | The engine shall emit `tracing` spans for each stage named in §5.3, and shall not record document content or unredacted paths in span fields or log messages. | test with a capturing subscriber; review | Open |
| SPEC-0002-R14 | When `Engine::shutdown` is called, the engine shall stop all watchers and join its worker threads before returning. | integration test: no watcher event is processed after shutdown | Open |
| SPEC-0002-R15 | Every PoC test shall exist and pass in its new crate, and the hardware-free suite shall need no Tauri runtime. | `cargo test --workspace`; `cargo test --workspace --features hw-tests -- --test-threads=1` | Open |
| SPEC-0002-R16 | When the engine opens, it shall resolve the database, model, NPU IR, and PDFium locations exactly as the PoC did, given the app-data directory and resource directory passed by the shell. | integration test on `EngineConfig::resolve`; the app opens an existing index | Open |

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
