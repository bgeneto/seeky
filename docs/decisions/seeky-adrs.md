# Seeky Architecture Decisions

Status: active. These ADRs describe the implementation that exists in
`apps/seeky`. Historical decisions from the research phase are archived under
`docs/archive/`.

## ADR-001 — Tauri 2 with a Rust backend and React/TypeScript frontend

**Decision:** Ship Seeky as a single Tauri 2 desktop application. Backend logic
lives in Rust; the UI is React 19 + TypeScript + Vite.

**Rationale:**
- Native filesystem and model-runtime access without a local server.
- Small release footprint compared with bundling a browser and service.
- One process boundary for state, database, watcher, and inference.
- Matches the verified Gety architecture and keeps the stack focused.

**Consequences:**
- Rust changes require a rebuild; there is no hot-reload backend service.
- UI/backend contracts are Tauri commands and events, not HTTP.

## ADR-002 — SQLite + FTS5 as the only storage engine

**Decision:** Store roots, documents, chunks, FTS5 indexes, and embedding BLOBs
in one SQLite database. Do not add an external vector database for the current
scale.

**Rationale:**
- One file, one transaction boundary, simple backup and portability.
- FTS5 provides BM25 without an additional dependency.
- The verified Gety build uses the same class of storage.
- Exact cosine is sufficient until benchmarks show otherwise.

**Consequences:**
- Exact dense retrieval scans the embedding table.
- Introducing ANN later requires a migration and an explicit performance gate.

## ADR-003 — Hybrid retrieval with filename/path and RRF

**Decision:** Fuse BM25, filename/path matches, and dense cosine rankings with
reciprocal rank fusion at chunk level (`k = 60`).

**Rationale:**
- BM25 handles exact phrases and rare terms.
- Filename/path matching handles file-oriented queries that content-only search
  misses.
- Dense retrieval handles meaning and paraphrase.
- RRF avoids calibrating incomparable score scales.

**Consequences:**
- Result scores are relative, not calibrated probabilities.
- Reranking/pruning are separate stages and must preserve fallback behavior.

## ADR-004 — CPU/CUDA/NPU backend mapping

**Decision:** Use Gety's model artifacts directly:
- CPU: uint8 ONNX through ONNX Runtime.
- CUDA: FP16 ONNX through the ORT CUDA execution provider.
- NPU: Gety OpenVINO IR through OpenVINO on Intel AI Boost.

Auto mode resolves CUDA → NPU → CPU and falls back on load failure.

**Rationale:**
- Avoids training or re-exporting models for the PoC.
- Uses hardware already available on the validated machine.
- Keeps one compatible 384-d embedding space across backends.

**Consequences:**
- Runtime and driver availability are external prerequisites.
- NPU first load compiles the model and is slower.
- Model path discovery must handle Gety revisions and environment overrides.

## ADR-005 — Incremental watcher with per-file indexing

**Decision:** Run one recursive `notify` watcher per enabled root, debounce events
for 600 ms, deduplicate by path, and index changed files individually.

**Rationale:**
- Avoids full rescans for normal edits.
- Per-file DB/engine locks keep search and status responsive.
- Size + nanosecond-mtime signatures make reindexing cheap.
- Per-folder pause gives users control over noisy or synced folders.

**Consequences:**
- Files changed while the app is closed require Reindex.
- Watcher behavior depends on OS event delivery.
- Directory creates/renames require subtree scans.

## ADR-006 — Narrow webview capabilities and Rust-side file opening

**Decision:** Do not grant the webview a broad filesystem or opener path scope.
Open files through a dedicated Rust command; keep the webview capability to Tauri
core and dialog.

**Rationale:**
- Reduces the attack surface of the UI.
- Handles Windows verbatim paths in one place.
- Avoids maintaining a broad opener allowlist.

**Consequences:**
- File-opening behavior is tested through IPC.
- Future file actions must be added as explicit Rust commands.

## ADR-007 — Large OpenVINO asset tracked with Git LFS

**Decision:** Track the bundled OpenVINO `model.bin` with Git LFS and mark
binary assets in `.gitattributes`.

**Rationale:**
- The NPU path needs the 118.6 MB IR in release resources.
- Plain Git would bloat every clone and diff.
- LFS keeps the asset available while allowing normal source review.

**Consequences:**
- Contributors need Git LFS installed for the NPU path.
- Publishing requires LFS support and license review.
- CPU/CUDA models remain external Gety installation files.

## ADR-008 — No sidecar service or HTTP API

**Decision:** All backend behavior runs in the Rust Tauri process. Do not add a
local web framework, public REST API, or sidecar process.

**Rationale:**
- Less memory, fewer ports, fewer lifecycle failures.
- No cross-process serialization of search/index operations.
- The desktop UI is the only supported client.

**Consequences:**
- Internal tooling must call Rust functions or Tauri commands.
- External automation would require a separate, explicitly scoped interface.
