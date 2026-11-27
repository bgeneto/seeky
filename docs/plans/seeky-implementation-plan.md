# Seeky Implementation Plan

| Field | Value |
|---|---|
| Status | Active |
| Version | 1.0 |
| Date | 2026-11-26 |
| Owner | Seeky engineering |
| Supersedes | Archived minimal-RAG plans under `docs/archive/` |
| Current release | 0.1.0 PoC |

## 1. Executive summary

Seeky is a local-first desktop search application. It indexes files from user
selected folders, extracts text, splits it into chunks, computes one 384-d
embedding per chunk, and serves hybrid retrieval through a Tauri desktop UI.

The implementation is a single Tauri 2 process with a Rust backend and a React
19/TypeScript frontend. There is no sidecar service, no local HTTP server, and no
external database. SQLite is the source of truth for documents, chunks, FTS5,
and vector blobs.

The PoC and the first post-PoC milestone are complete:

- CPU, CUDA, and Intel NPU inference work with Gety's `gety-embed-v0` models.
- The release UI searches through the NPU in tens of milliseconds on the demo.
- Live filesystem watching, debounced incremental indexing, cancellation, index
  health, and filename/path retrieval are implemented.

The next work is retrieval quality, metadata filtering, scale validation, and
packaging. This plan defines those milestones, acceptance gates, and the
technical constraints that must not regress.

## 2. Product definition

### 2.1 Product statement

> A high-performance, local-first semantic file search engine. No cloud, no
> chatbots, no agents. Just search.

### 2.2 Primary users

- Individual knowledge workers with large local document collections.
- Developers and researchers searching mixed folders of PDFs, Office files,
  notes, and source code.
- Privacy-sensitive users who will not send documents to a cloud service.

### 2.3 Core jobs

1. Add one or more local folders.
2. Index them without leaving the desktop application.
3. Search by keyword, filename, phrase, or meaning.
4. Inspect the matching passage and open the original file.
5. Keep the index current as files change.

### 2.4 Non-goals

The following are explicitly out of scope for the current product:

- Cloud sync, accounts, teams, or multiuser access.
- External connectors, marketplace, plugin SDK, or connector sandbox.
- MCP server, public REST API, or public CLI.
- AI-client integrations and API-key management.
- Generative chat or an agent runtime.
- LAN access.
- Telemetry or analytics.
- Mobile clients.

An optional answer layer is a deferred product decision. It is not part of the
current milestones and must not be added without an explicit scope change.

## 3. Current baseline

### 3.1 Verified implementation

| Area | Current implementation |
|---|---|
| Shell | Tauri 2.12.7 |
| Frontend | React 19, TypeScript, Vite 8 |
| Backend | Rust 2024 edition, Tauri commands |
| Storage | SQLite (bundled `rusqlite`), FTS5, f32 embedding BLOBs |
| CPU | `ort` 2.0.0-rc.10, Gety uint8 ONNX |
| CUDA | `ort` CUDA execution provider, Gety FP16 ONNX |
| NPU | `openvino` 0.11.2, Gety OpenVINO IR on Intel AI Boost |
| Model | `gety-embed-v0`, 384-d |
| Extraction | PDFium 7881, DOCX, XLSX, PPTX, HTML, text/source |
| Retrieval | BM25 + filename/path + exact cosine + RRF |
| Indexing | Full scan + live `notify` watcher, size/ns-mtime skip |
| UI | Search, preview, folder manager, backend selection, index health |
| Packaging | `tauri build --no-bundle` release executable + external resources |

### 3.2 Verified evidence

- 8/8 Rust tests pass.
- Release binary is 11.5 MB.
- Bundled OpenVINO IR is 118.6 MB (`model.bin`), tracked with Git LFS.
- Final recorded NPU UI search: 5 results in 26 ms on the demo corpus.
- Live watcher moves the demo from 5 → 6 → 5 documents on create/delete.
- Cancellation stops a 500-file index after 6 files.
- Portable `seeky.exe + resources/` resolves the bundled OpenVINO model.

### 3.3 Known gaps

- No cross-encoder reranker or pruner.
- No metadata filters in the UI.
- Exact cosine scans all embeddings; no ANN.
- Initial index of a folder is manual.
- Changes made while the app is closed require Reindex.
- XLSX/PPTX paths are compiled but not covered by demo fixtures.
- No signed installer, update channel, or automated release pipeline.
- Frontend automated tests are minimal.
- The current validated platform is Windows x64.

## 4. Target architecture

### 4.1 Process model

```text
Tauri WebView (React + TypeScript)
        │ invoke / events
        ▼
Rust application process
  ├─ command layer (lib.rs)
  ├─ indexing controller + watcher worker
  ├─ extraction and chunking
  ├─ inference engine (CPU / CUDA / NPU)
  ├─ SQLite repository
  └─ retrieval and ranking
        │
        ├─ Gety ONNX models (CPU/CUDA)
        ├─ Gety OpenVINO IR (NPU)
        └─ Gety PDFium / ONNX Runtime / OpenVINO runtime
```

All backend logic runs in Rust inside the Tauri process. There is no sidecar
service, local HTTP API, or secondary runtime.

### 4.2 Rust modules

| Module | Responsibility |
|---|---|
| `lib.rs` | Tauri commands, app state, watcher manager, index health, cancellation |
| `inference.rs` | Backend selection, model resolution, tokenizer, CPU/CUDA/NPU engines |
| `indexer.rs` | Scan, extraction pipeline, chunking, per-file incremental indexing |
| `extract.rs` | PDF/DOCX/XLSX/PPTX/HTML/text extraction |
| `db.rs` | Schema, migrations, documents/chunks/FTS/embeddings, filename lookup |
| `search.rs` | BM25, dense, filename/path, RRF, snippets |

### 4.3 Frontend structure

- `App.tsx`: application shell, views, search flow, index health, folder controls.
- `types.ts`: IPC contracts.
- `App.css`: Seeky visual system.
- Views: Search, Local Files, Settings.
- Event listeners: `index-progress`, `index-health`.
- Polling: lightweight `get_status` refresh for counts and watcher state.

### 4.4 Architectural invariants

1. Search must remain usable while indexing.
2. One SQLite connection guarded by a mutex; locks must be short and never held
   across model inference.
3. Embeddings are model-compatible across CPU, CUDA, and NPU; backend switching
   must never require reindexing.
4. No document content leaves the machine.
5. No webview filesystem capability broader than necessary; file opening stays
   behind a narrow Rust command.
6. Large model assets are external/resource files, not compiled into the binary.

## 5. Data model

### 5.1 Tables

```sql
roots(
  id TEXT PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  created_at INTEGER NOT NULL,
  watch_enabled INTEGER NOT NULL DEFAULT 1
)

documents(
  id TEXT PRIMARY KEY,
  root_id TEXT NOT NULL REFERENCES roots(id) ON DELETE CASCADE,
  path TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  ext TEXT NOT NULL,
  size INTEGER NOT NULL,
  modified INTEGER NOT NULL,       -- seconds, display/date
  modified_ns INTEGER NOT NULL,    -- incremental signature
  content TEXT NOT NULL,
  indexed_at INTEGER NOT NULL
)

chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  ord INTEGER NOT NULL,
  text TEXT NOT NULL,
  page INTEGER,
  start_offset INTEGER NOT NULL,
  end_offset INTEGER NOT NULL
)

chunks_fts USING fts5(
  text,
  content='chunks',
  content_rowid='id',
  tokenize='unicode61 remove_diacritics 2'
)

embeddings(
  chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
  dim INTEGER NOT NULL,
  vector BLOB NOT NULL
)

settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
)
```

### 5.2 Migration policy

- Migrations run on application start before commands are served.
- Additive columns use `ALTER TABLE ... ADD COLUMN`.
- Every migration must be safe for an existing user database.
- Tests must cover opening a database created by the previous release.
- Destructive migrations require a backup and an explicit release note.

### 5.3 Storage policy

- Vectors are normalized f32 BLOBs, 384 dimensions.
- FTS5 is kept synchronized by insert/delete/update triggers.
- Document rows store extracted text for preview and snippets.
- One database per OS user profile under the app data directory.
- WAL mode and `busy_timeout` are enabled.

## 6. Indexing pipeline

### 6.1 Full reindex

1. Lock the indexing mutex.
2. Scan the root with WalkDir, excluding ignored directories and unsupported
   extensions.
3. For each file:
   - Compare `size + modified_ns` against the stored signature.
   - Skip unchanged files.
   - Extract text without holding the database or engine lock.
   - Chunk at ~1,200 characters with 200-character overlap.
   - Embed all chunks for the file.
   - Upsert the document and chunks in one transaction.
4. Prune documents whose paths no longer exist.
5. Publish progress and final health.
6. Release the index lock.

### 6.2 Live watcher

- One recursive `notify` watcher per enabled root.
- Events are sent to a worker thread over an unbounded channel.
- The worker debounces for 600 ms and deduplicates by path.
- Event mapping:
  - Create/Modify → upsert.
  - Remove → delete exact document and descendants for directory removals.
  - Rename Both/From/To/Any → remove the old path and index the new path.
- Directory creates/renames trigger a subtree scan.
- Per-file DB/engine locks keep search and status responsive.
- Pause/resume is stored in `roots.watch_enabled`.

### 6.3 Failure semantics

- Extraction failure: keep the previous document, record the issue in health.
- Missing file during scan: prune or skip according to the phase.
- Embedding failure: record the error and continue with other files; do not
  corrupt previously indexed documents.
- Cancellation: stop before the next file and skip pruning, because the scan is
  incomplete.
- Watcher failure: disable the affected root and show the error in health.

### 6.4 Offline changes

Files changed while Seeky is closed do not emit events. The user must run
**Reindex**; unchanged files are still skipped using size/mtime signatures.
A future startup reconcile can be added if it does not violate the manual-first
initial-index contract.

## 7. Retrieval and ranking

### 7.1 Retrieval stages

1. **BM25** over FTS5, top 80.
2. **Filename/path** over title/path tokens, top 40, one representative chunk per
   document.
3. **Dense** exact cosine over stored embeddings, top 80.
4. **RRF** at chunk level with `k = 60`.
5. Context hydration: document metadata, page, offsets, snippet.
6. Future: rerank top 30 and prune to the presentation/context budget.

### 7.2 Score presentation

- UI scores are normalized against the top fused score.
- Match tags show `BM25`, `SEMANTIC`, and `FILENAME`.
- No calibrated relevance probability is claimed.

### 7.3 Backend switching

CPU, CUDA, and NPU share the same 384-d embedding space. Switching backends
reloads the engine but does not re-embed the index. The selected backend is
persisted in `settings`.

## 8. Inference strategy

| Backend | Artifact | Runtime | Notes |
|---|---|---|---|
| CPU | `onnx/model_uint8.onnx` | Gety ONNX Runtime | Universal fallback |
| CUDA | `onnx_cuda/model_fp16.onnx` | ORT CUDA EP | Requires Gety CUDA DLLs |
| NPU | Gety OpenVINO IR | OpenVINO runtime | 256-token bucket; first compile is slow |
| Auto | CUDA → NPU → CPU | Multiple | Falls back on load failure |

Model resolution order:

1. `SEEKY_GETY_MODEL_DIR`, `SEEKY_ORT_DLL`, `SEEKY_OPENVINO_DIR`, `SEEKY_NPU_DIR`
2. Installed Gety model/data directories
3. Bundled release resources for the NPU IR
4. Source resources for development

### 8.1 Reranker plan

- Add an ONNX cross-encoder reranker over the RRF top 30.
- Candidate models: Qwen3-Reranker-0.6B or bge-reranker-v2-m3.
- CPU/CUDA first; NPU evaluation after the CPU/CUDA path is stable.
- The reranker must be optional and fail open to RRF ordering.
- Do not add it to the default path until the evaluation gate is met.

## 9. Frontend plan

### 9.1 Search view

- Debounced query, latest-request-wins behavior.
- Highlighted snippets.
- Preview with path, size, modified date, and content excerpt.
- Open file through the Rust command.
- Result count and latency metadata.
- Match tags.

### 9.2 Local Files view

- Add/remove folders.
- Per-folder Watching/Paused toggle.
- Index/Reindex action.
- Index health: watcher count, pending changes, last index time,
  skipped/errors, current file, recent issues.
- Cancel while indexing.

### 9.3 Settings view

- Auto/CPU/CUDA/NPU selection with availability states.
- Active engine identity.
- Index counts.
- Model paths and database path.
- Backend notes.

### 9.4 UX milestones

- Metadata filter bar (root, extension, modified date, size).
- Keyboard shortcuts and focus management.
- Accessible labels, focus rings, and reduced-motion support.
- Empty/loading/error states for every view.
- Automated component tests for search, files, and settings.

## 10. Tauri command and event contract

### 10.1 Commands

| Command | Purpose |
|---|---|
| `get_status` | Roots, counts, engine, paths, health |
| `add_root` | Add and watch a folder |
| `remove_root` | Remove a folder and stop its watcher |
| `list_roots` | List folders |
| `set_root_watching` | Pause/resume a watcher |
| `set_backend` | Persist a backend selection |
| `probe_backend` | Load a backend and return engine info |
| `start_index` | Scan a folder, skip unchanged files, prune stale rows |
| `cancel_index` | Request cancellation between files |
| `search_documents` | Hybrid search |
| `get_document` | Full extracted document for preview |
| `open_local_file` | Open a file with the OS default app |

### 10.2 Events

| Event | Payload |
|---|---|
| `index-progress` | phase, current, total, file, message |
| `index-health` | indexing, watching, pending, last time, errors, details |

### 10.3 Compatibility

- Frontend and backend types live in `src/types.ts` and Rust `Serialize` structs.
- Breaking command payload changes require a coordinated frontend update and a
  test.
- Additive fields are preferred.

## 11. Performance and capacity targets

Reference hardware: Windows 11, RTX 3090, Intel AI Boost NPU, 64 GB RAM.

| Metric | Target |
|---|---|
| Search p95, warm CUDA/NPU, 100k chunks | ≤ 150 ms |
| Search p95, warm CPU, 100k chunks | ≤ 300 ms |
| Filename/BM25-only query | ≤ 50 ms |
| Incremental single-file update visible | ≤ 2 s after the 600 ms debounce |
| `get_status` p95 during indexing | ≤ 50 ms |
| UI responsiveness during indexing | no main-thread blocking; search can run |
| Indexing memory | ≤ 1.5 GB at 100k chunks |
| Idle memory | ≤ 400 MB including WebView |
| First NPU load | documented; not counted in warm search latency |

Benchmarks must be reproducible with a checked-in fixture generator and the
internal Rust benchmark harness. Regressions above 20% block a release unless
explicitly accepted.

## 12. Quality and evaluation

### 12.1 Golden set

Create a local evaluation corpus with:

- 200 queries with graded relevance judgments.
- Mixed formats: PDF, DOCX, XLSX, PPTX, Markdown, text, source code.
- Portuguese and English content.
- Queries by meaning, exact phrase, filename only, and metadata.

### 12.2 Metrics

- Recall@10 and Recall@20.
- MRR@10.
- nDCG@10.
- Zero-result rate.
- p50/p95 latency.
- Index throughput and peak memory.

### 12.3 Reranker gate

A reranker is accepted only if it improves nDCG@10 by at least 5 points on the
golden set without exceeding the latency budget. Otherwise it stays optional or
is removed.

### 12.4 Regression policy

- Ranking changes require before/after evaluation output.
- Retrieval, migration, and watcher changes require tests.
- Performance changes require a benchmark note.

## 13. Testing strategy

### 13.1 Rust

- Unit tests for extraction, chunking, signatures, filename matching, and RRF.
- Integration tests for CPU/CUDA/NPU embeddings when hardware is available.
- Index lifecycle tests: create, modify, rename, delete, unchanged skip, prune.
- Watcher event mapping tests, including rename modes.
- Migration test from the previous schema version.
- Cancellation and error-path tests.
- Benchmark harness for retrieval and indexing.

### 13.2 Frontend

- TypeScript build (`tsc`) and Vite production build in CI.
- Component tests for search, results, preview, files, settings, and health.
- Mocked Tauri IPC for deterministic tests.
- Optional Tauri WebDriver or CDP smoke test for the release binary.

### 13.3 Hardware matrix

| Environment | Required coverage |
|---|---|
| CPU-only Windows | Build, tests, search |
| CUDA Windows | Embedding + search smoke |
| Intel NPU Windows | Embedding + search smoke |
| macOS/Linux | Build check; inference support decision pending |

CI without model assets can run formatting, linting, TypeScript, and pure Rust
tests. Hardware inference jobs run on self-hosted or labeled runners.

## 14. Security, privacy, and licensing

- No outbound network calls in the application runtime.
- Only Tauri core and dialog capabilities are exposed to the webview.
- File opening is a Rust command, not a broad opener allowlist.
- Users explicitly select folders; no background scan of unselected paths.
- Ignore system/development directories and cap file size at 25 MB.
- Do not log document content.
- Do not add telemetry.
- Gety binaries are not redistributed.
- `gety-embed-v0` model card declares MIT; verify before redistribution.
- OpenVINO IR is tracked with Git LFS and requires license review before
  publishing installers.

## 15. Milestones

### M0 — Runnable PoC (complete)

**Scope:** local indexing, extraction, embeddings, hybrid search, preview,
CPU/CUDA/NPU support, Tauri UI, tests, release executable.

**Acceptance:** 7+ Rust tests; release UI search on NPU; portable resource
layout; documented validation.

### M1 — Live incremental indexing (complete)

**Scope:** watcher, debounce, rename/delete, per-file incremental indexing,
per-folder pause, health, cancellation, filename/path signal.

**Acceptance:** create/modify/rename/delete reflected live; unchanged files
skipped; 500-file cancellation works; release watcher verified.

### M2 — Retrieval quality (next)

**Scope:**

1. Internal Rust evaluation harness and golden-set fixtures.
2. Baseline BM25/dense/RRF metrics.
3. Cross-encoder reranker over RRF top 30, CPU/CUDA first.
4. Deterministic pruner: dedupe, MMR/token budget, fragment selection.
5. UI match explanations for reranked/pruned results.
6. Optional reranker toggle and failure fallback.

**Acceptance:**

- Reranker improves nDCG@10 by ≥5 points.
- Search p95 remains within budget on reference hardware.
- Reranker failure returns RRF results without breaking search.
- Before/after evaluation committed under `docs/audits/evaluations/`.

### M3 — Metadata filters and search UX

**Scope:**

1. Filter model: root, extension, modified date, size.
2. Backend filter plumbing through lexical, filename, and dense stages.
3. Filter chips and clear-all in the top bar.
4. Keyboard navigation and shortcuts.
5. Search cancellation and stale-result suppression.
6. Accessibility pass and empty/error states.

**Acceptance:**

- Filters do not silently drop valid candidates (retrieve-then-filter).
- Filter state is visible and removable.
- Keyboard-only search and preview flow works.
- Frontend component tests cover filters and result rendering.

### M4 — Scale, storage, and performance

**Scope:**

1. Benchmark 10k documents / 100k chunks.
2. Batch embedding across multiple files.
3. Transaction batching and WAL tuning where measured.
4. ANN decision gate: `sqlite-vec` or USearch if p95 exceeds budget.
5. Database maintenance: vacuum/optimize, integrity checks, backup guidance.
6. Startup reconcile option for offline changes.

**Acceptance:**

- 100k-chunk search meets latency targets.
- Indexing memory and throughput measured.
- ANN is added only if exact cosine fails the gate.
- Database remains backward compatible and repairable.

### M5 — Packaging and operations

**Scope:**

1. Windows installer (NSIS/MSI) and portable release archive.
2. Code signing and checksum publication.
3. Model asset strategy: external Gety models, bundled NPU IR, LFS/installer.
4. First-run diagnostics for missing models/drivers.
5. Local rotating logs with redaction.
6. Release checklist, versioning, and rollback notes.
7. No auto-updater in this milestone unless scope changes.

**Acceptance:**

- Clean Windows VM install works with documented prerequisites.
- Portable package runs with resources beside the executable.
- Missing model/runtime produces an actionable UI error.
- Release artifacts and checksums are reproducible.

### M6 — Optional answer layer (deferred)

Only if the product scope changes:

- Extract cited passages from the pruned result set.
- Optionally call a local LLM through an isolated adapter.
- Preserve "not found" behavior and citation checking.
- Keep the default product as search-only.

**Acceptance:** separate design review and explicit approval before work starts.

## 16. Work breakdown and sequencing

| Order | Workstream | Depends on |
|---|---|---|
| 1 | Golden-set and evaluation harness | M1 |
| 2 | Reranker integration and gate | 1 |
| 3 | Pruner and result explanations | 2 |
| 4 | Metadata filters backend + UI | M1 |
| 5 | Frontend component test suite | M1 |
| 6 | 100k-chunk benchmark and batching | 1 |
| 7 | ANN decision/implementation | 6 |
| 8 | Installer, signing, diagnostics | 4–7 |
| 9 | Optional local answer layer | Explicit scope change |

M2 and M3 may run in parallel after the evaluation harness exists.

## 17. Release and versioning

- SemVer for the application (`0.x` until the search experience is stable).
- Every release updates `CHANGELOG.md`.
- Every release records:
  - commit SHA,
  - Rust/Node/Tauri versions,
  - test and benchmark results,
  - artifact size and SHA-256,
  - model/runtime prerequisites.
- Release builds use `tauri build` with the appropriate bundle targets.
- The release binary and `resources/` are published together; the binary is not
  useful without its model resources.
- No release may silently change the embedding model without a reindex plan.

## 18. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Gety updates model paths/formats | Inference breaks | Env overrides, path discovery, compatibility tests, documented pin |
| CUDA/OpenVINO runtime mismatch | Backend load failure | Auto fallback, actionable health errors, pinned tested runtime |
| NPU driver unavailable | NPU unusable | CPU/CUDA fallback, explicit availability state |
| PDFium version mismatch | PDF extraction failure | Bindings feature pinned; startup diagnostics |
| Watcher storms or network filesystems | Index churn | Debounce, dedupe, ignore rules, per-folder pause |
| SQLite lock contention | UI stalls | Short locks, WAL, per-file transactions, status budget |
| Exact cosine at scale | Search latency | Benchmark gate, ANN migration plan |
| Large model assets | Repo/install size | Git LFS, external Gety models, installer resource split |
| Model licensing | Distribution risk | License review before publishing installers |
| Unrelated result volume | Poor perceived quality | Reranker, pruner, filters, evaluation |

## 19. Open decisions

1. Reranker model and quantization; CPU/CUDA/NPU coverage.
2. Whether metadata filters use UI controls, a query syntax, or both.
3. ANN trigger threshold and library choice.
4. Startup reconcile behavior for edits made while the app was closed.
5. Windows-only support boundary versus macOS/Linux inference backends.
6. Installer format and code-signing certificate.
7. Git LFS versus installer-only distribution for the OpenVINO IR.
8. Whether an optional answer layer is ever in scope.

## 20. Definition of done

A milestone is done only when:

- The implementation matches this plan and the product scope.
- Commands, events, and types are documented.
- Tests and evaluation gates pass.
- No known data-loss or migration regression exists.
- Performance is measured against the reference budget.
- User-facing behavior is reproducible from the README.
- Evidence is added under `docs/validation/` or `docs/audits/`.
- `CHANGELOG.md` and the implementation plan are updated.

## 21. Immediate next actions

1. Create the evaluation fixture generator and Rust benchmark harness.
2. Measure BM25-only, dense-only, filename-only, and RRF baselines.
3. Select and integrate the first cross-encoder reranker.
4. Add the deterministic pruner and UI explanations.
5. Start the metadata filter backend contract in parallel.
6. Define the 100k-chunk benchmark corpus.
