# Seeky Implementation Plan

| Field | Value |
|---|---|
| Status | Active |
| Version | 1.1 |
| Date | 2026-11-26 |
| Owner | Seeky engineering |
| Supersedes | Archived minimal-RAG plans under `docs/archive/` |
| Current release | 0.1.0 PoC |

## 1. Executive summary

Seeky is a **Local Neural Information Retrieval Engine** and **Semantic Desktop
Search Engine**. It indexes local files, ranks passages and documents with a
multilingual hybrid retrieval pipeline, and presents evidence in a minimal
desktop UI.

The implementation is a single Tauri 2 process with a Rust backend and a React
19/TypeScript frontend. SQLite is the source of truth for roots, documents,
chunks, FTS5, and vector blobs. There is no sidecar service, local HTTP API, or
external database.

The PoC and live-index milestone are complete. The product direction now adds
four major commitments:

1. **Open source:** MIT-licensed code; third-party assets keep their own licenses.
2. **No account or license key:** no sign-up, activation, subscription, or
   entitlement check.
3. **Slim setup:** runtimes, model weights, tokenizers, and native libraries are
   downloaded on first run from the seeky Cloudflare R2 bucket, then cached for
   offline use.
4. **SOTA multilingual retrieval:** benchmark-gated embedding and reranking
   models with hierarchical document/passage ranking, aggregation, per-document
   limits, diversity, near-duplicate detection, and length-bias correction.

The UI target is equally explicit: exactly light and dark themes (OS default),
English and Portuguese from the start, minimal controls, and no AI-style clutter.

## 2. Product definition

### 2.1 Product statement

> Seeky is a Local Neural Information Retrieval Engine and Semantic Desktop Search
> Engine. It finds the right local file and passage, fast, without cloud
> dependency or accounts.

### 2.2 Primary users

- Individual knowledge workers with large local document collections.
- Developers and researchers searching mixed folders of PDFs, Office files,
  notes, and source code.
- Privacy-sensitive users who will not send documents to a cloud service.
- Multilingual users whose files and queries span several languages.

### 2.3 Core jobs

1. Add one or more local folders.
2. Provision the required runtime and model assets on first run.
3. Index folders without blocking the UI.
4. Search by keyword, filename, phrase, or meaning in any content language.
5. Inspect the best passages and open the original file.
6. Keep the index current as files change.
7. Use the application with no account, activation, or commercial license key.

### 2.4 Accepted product decisions

| Decision | Direction |
|---|---|
| License | MIT for Seeky source code; third-party licenses preserved |
| Accounts | None |
| Commercial license key | None |
| Packaging | Slim installer; first-run R2 provisioning |
| Runtime/model storage | App data cache after verified download |
| Offline behavior | Fully offline after provisioning |
| UI themes | Light and dark only; OS default |
| UI languages | English and Portuguese; OS detection, English fallback |
| UI density | Minimal; no dashboards, chat, or decorative AI UI |
| Content languages | Multilingual required for retrieval |
| Hardware | CPU, NVIDIA CUDA, AMD GPU, Intel NPU where validated |
| Retrieval | SOTA benchmark-gated hierarchical neural IR |

The detailed product record is
[`../product/seeky-product-decisions.md`](../product/seeky-product-decisions.md).

### 2.5 Non-goals

- Cloud sync, accounts, teams, multiuser access.
- External connectors, marketplace, plugin SDK, or connector sandbox.
- MCP server, public REST API, or public CLI.
- AI-client integrations and API-key management.
- Generative chat, agents, answer generation, or conversational history.
- Theme customization or a settings-heavy dashboard.
- LAN access, telemetry, or analytics.

An optional answer layer is deferred and requires an explicit product scope
change.

## 3. Current baseline

### 3.1 Verified implementation

| Area | Current implementation |
|---|---|
| Shell | Tauri 2.12.7 |
| Frontend | React 19, TypeScript, Vite 8 |
| Backend | Rust 2024 edition, Tauri commands |
| Storage | SQLite (bundled `rusqlite`), FTS5, f32 embedding BLOBs |
| CPU | `ort` 2.0.0-rc.10, Gety uint8 ONNX |
| CUDA | ORT CUDA execution provider, Gety FP16 ONNX |
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
- Current temporary OpenVINO IR is 118.6 MB, tracked with Git LFS.
- Final recorded NPU UI search: 5 results in 26 ms on the demo corpus.
- Live watcher moves the demo from 5 → 6 → 5 documents on create/delete.
- Cancellation stops a 500-file index after 6 files.
- Portable `seeky.exe + resources/` resolves the bundled OpenVINO model.

### 3.3 Transitional gaps

The current PoC does not yet meet the target product decisions:

- Requires a local Gety installation for models/runtimes.
- Ships a temporary bundled OpenVINO IR instead of first-run download.
- UI is dark-only and English-only.
- Settings exposes backend/model internals rather than an automatic minimal view.
- Retrieval is chunk-level BM25 + filename + dense + RRF; it lacks the required
  SOTA hierarchy, aggregation, diversity, duplicate handling, and length
  correction.
- No multilingual model evaluation or golden-set harness.
- No AMD GPU backend validation.
- No cross-encoder reranker or pruner.
- No signed installer or R2 asset pipeline.
- Frontend automated tests are minimal.

## 4. Target architecture

### 4.1 Process model

```text
Tauri WebView (React + TypeScript)
        │ invoke / events
        ▼
Rust application process
  ├─ command + provisioning layer
  ├─ indexing controller + watcher worker
  ├─ extraction and chunking
  ├─ inference engine (CPU / CUDA / AMD / NPU)
  ├─ SQLite repository
  ├─ hierarchical retrieval + ranking
  └─ first-run asset resolver
        │
        ├─ downloaded ONNX / OpenVINO assets
        ├─ downloaded runtimes and native libraries
        └─ local SQLite database
```

All backend logic runs in Rust inside the Tauri process. No sidecar service,
local HTTP API, or secondary runtime is part of the architecture.

### 4.2 Rust modules

| Module | Responsibility |
|---|---|
| `lib.rs` | Commands, state, watcher, index health, cancellation |
| `provisioning.rs` | First-run manifest, download, verify, cache (target) |
| `inference.rs` | Backend selection, asset resolution, tokenizer, runtimes |
| `indexer.rs` | Scan, extraction, chunking, incremental per-file indexing |
| `extract.rs` | PDF/DOCX/XLSX/PPTX/HTML/text extraction |
| `db.rs` | Schema, migrations, documents/chunks/FTS/embeddings |
| `retrieval/*` | Lexical, filename, dense candidate generation (target) |
| `ranking/*` | Aggregation, reranking, diversity, dedupe, calibration (target) |
| `search.rs` | Orchestration and response shaping |

### 4.3 First-run asset layout

```text
%APPDATA%\ai.seeky.desktop\
  seeky.db
  provisioned.json
  runtime\<asset-id>\<version>\
  models\<asset-id>\<revision>\
  cache\manifests\
  logs\
```

The target product does not require Gety to be installed. The current PoC paths
are transitional.

### 4.4 Architectural invariants

1. Search remains usable while indexing.
2. One SQLite connection guarded by a mutex; locks are short and never held
   across model inference.
3. Embeddings remain model-compatible across backends; backend switching never
   requires reindexing for the same model.
4. No document content leaves the machine.
5. No account, activation, or license key exists.
6. Downloaded assets are checksummed/signature-verified before loading.
7. No webview capability broader than necessary; file opening stays behind a
   narrow Rust command.
8. Large runtimes/models are external assets, not compiled into the binary.
9. UI copy and layout stay minimal; no AI-slop surfaces.
10. Third-party licenses and notices ship with downloaded assets.

## 5. Data model

### 5.1 Current tables

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
  modified INTEGER NOT NULL,
  modified_ns INTEGER NOT NULL,
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

### 5.2 Target retrieval additions

Before SOTA ranking work, add benchmark-backed fields/tables:

- document content hash and SimHash/MinHash signature;
- normalized document length and document-level statistics;
- duplicate cluster ID and canonical flag;
- chunk content hash and an embedding cache keyed by chunk hash + model/tokenizer
  revision;
- optional document-level embedding aggregate;
- model/asset revision on documents and embeddings;
- ranking/feature cache only if measurements justify it.

Every schema change needs a migration test and a reindex or dual-index plan when
the embedding model changes.

### 5.3 Migration policy

- Migrations run before commands are served.
- Additive columns use `ALTER TABLE ... ADD COLUMN`.
- Every migration is safe for the previous user database.
- Tests cover opening the previous release schema.
- Destructive migrations require a backup and release note.

## 6. Indexing pipeline

### 6.1 Full reindex

1. Lock the indexing mutex.
2. Scan the root with WalkDir, excluding ignored directories and unsupported
   extensions.
3. For each file:
   - Compare `size + modified_ns`; skip unchanged.
   - Extract text without holding DB/engine locks.
   - Detect language/encoding metadata where needed.
   - Chunk with a model-aware size and overlap.
   - Hash normalized chunks and reuse cached embeddings when the chunk hash and
     model/tokenizer revision are unchanged. A rename must not re-embed an
     unchanged file.
   - Embed only new or changed chunks.
   - Compute duplicate signatures.
   - Upsert document/chunks/signatures in one transaction.
4. Prune documents whose paths disappeared.
5. Publish progress and final health.
6. Release the lock.

### 6.2 Live watcher

- One recursive `notify` watcher per enabled root.
- Worker thread with 600 ms debounce and path deduplication.
- Create/Modify → upsert; Remove → exact + descendant delete.
- Rename Both/From/To/Any → remove old, index new.
- Directory create/rename → subtree scan.
- Per-file locks keep search and status responsive.
- Pause/resume persisted in `roots.watch_enabled`.

### 6.3 Failure semantics

- Extraction failure keeps the previous document and records health.
- Missing file is pruned or skipped by phase.
- Embedding failure records the error and continues.
- Cancellation stops before the next file and skips pruning.
- Watcher failure disables the root and reports health.
- Provisioning failure blocks search with an actionable repair flow; it never
  silently uses an incompatible model.

### 6.4 Offline changes

Files changed while Seeky is closed do not emit events. **Reindex** is required;
unchanged files are skipped. A startup reconcile may be added later behind a
benchmark and UX decision.

## 7. Retrieval and ranking

### 7.1 Target pipeline

1. Query analysis and optional metadata filters.
2. Candidate generation:
   - BM25 top passages;
   - filename/path top documents;
   - dense top passages;
   - exact-match preservation.
3. Cross-encoder passage reranking on a bounded set.
4. Document-level score aggregation.
5. Hierarchical document → passage retrieval and re-aggregation.
6. Per-document candidate limits.
7. Near-duplicate detection and collapsing.
8. Cross-document diversity (MMR or xQuAD).
9. Length-bias correction and calibrated fusion.
10. Final documents + best passages + snippets.

The full ranking contract, formulas, defaults, and ablation gates are in
[`../architecture/retrieval-engine.md`](../architecture/retrieval-engine.md).

### 7.2 Required mechanisms

- Passage-level ranking.
- Document-level score aggregation.
- Hierarchical document retrieval.
- Per-document candidate limits.
- Cross-document diversity.
- Near-duplicate detection and collapsing.
- Length-bias correction.

These are required architecture, not later nice-to-haves. Each mechanism needs
an implementation, a unit test, and an ablation result on the multilingual
golden set.

### 7.3 Model selection

The embedding and reranker models must be multilingual and benchmark-gated. The
current `gety-embed-v0` integration is a compatibility baseline, not proof of
SOTA. Candidate models, backend policy, quantization, and license gates are in
[`../architecture/model-strategy.md`](../architecture/model-strategy.md).

### 7.4 Backend switching

CPU, CUDA, AMD, and NPU must use the same embedding model and vector space for a
given index. Switching execution providers does not re-embed. Changing the model
requires a versioned reindex.

## 8. Inference strategy

| Backend | Primary runtime | Notes |
|---|---|---|
| CPU | ONNX Runtime | Always supported fallback |
| NVIDIA CUDA | ONNX Runtime CUDA EP | FP16, validated |
| AMD GPU | DirectML (Windows), ROCm (Linux research) | Benchmark-gated |
| Intel NPU | OpenVINO | Current PoC path |
| Intel GPU | OpenVINO/DirectML | Decision pending benchmarks |

Rules:

- Auto mode selects the fastest validated backend, then falls back to CPU.
- Backend availability reflects runtime and hardware, not only files.
- Reranker failure fails open to fused retrieval.
- First-run provisioning selects only the assets appropriate for the machine.
- No model/runtime is loaded from an unverified path.

## 9. Distribution and first-run provisioning

Seeky's slim setup is a product requirement:

- small installer;
- public read-only Cloudflare R2 bucket `seeky`;
- manifest with versions, URLs, sizes, SHA-256, license metadata, and optional
  signature;
- platform/backend asset selection;
- resumable, retried, atomic downloads;
- offline use after provisioning;
- no account or license key.

The complete contract is in
[`../architecture/distribution-and-provisioning.md`](../architecture/distribution-and-provisioning.md).

## 10. Frontend and UX

### 10.1 Minimal UI

- Search, results, preview, folders, and a small settings surface only.
- Backend/model internals are automatic by default and hidden behind an advanced
  diagnostics action.
- No dashboards, onboarding carousels, AI badges, chat, generated summaries, or
  decorative metrics.
- Errors and empty states state the next action in one sentence.
- The UI behaves like a precise search tool, not an AI assistant.

### 10.2 Themes

- Exactly two themes: light and dark.
- Default follows the OS.
- Optional user override stored locally.
- No custom palettes, theme editor, or per-panel theme.

### 10.3 Internationalization

- English (`en`) and Portuguese (`pt`) from the start.
- OS locale detection; regional variants map to base locales.
- Fallback to English when the locale is unsupported or a key is missing.
- All user-facing strings live in locale catalogs.
- No feature gated by locale.
- Future locales use the same catalog contract.

### 10.4 Views

- **Search:** query, result list, snippet, match tags, preview.
- **Files:** folders, Watching/Paused, Index/Reindex, index health, errors.
- **Settings:** language, theme, minimal indexing controls, third-party notices;
  advanced backend/model diagnostics are secondary.

### 10.5 UX acceptance

- Keyboard and screen-reader essentials covered.
- Both themes pass contrast checks.
- No untranslated hardcoded strings.
- Backend/model details do not occupy the default screen.
- Search remains usable during indexing.

## 11. Tauri command and event contract

| Command | Purpose |
|---|---|
| `get_status` | Roots, counts, engine, asset state, health |
| `add_root` | Add and watch a folder |
| `remove_root` | Remove folder and watcher |
| `list_roots` | List folders |
| `set_root_watching` | Pause/resume a watcher |
| `start_index` | Incremental scan + prune |
| `cancel_index` | Cancel between files |
| `search_documents` | Hybrid/hierarchical search |
| `get_document` | Preview document text |
| `open_local_file` | Open with OS default app |
| `provision_assets` | First-run download/verify (target) |
| `get_provisioning_status` | Provisioning state (target) |

Events:

- `index-progress` — phase, current, total, file, message.
- `index-health` — indexing, watching, pending, last time, errors.
- `provisioning-progress` — asset, bytes, phase, error (target).

Additive fields are preferred. Breaking payload changes require a coordinated
frontend update and tests.

## 12. Performance and capacity targets

Reference hardware: Windows 11, RTX 3090, Intel AI Boost NPU, 64 GB RAM. AMD
validation uses a supported DirectML device.

| Metric | Target |
|---|---|
| Search p95, warm accelerator, 100k chunks | ≤ 150 ms |
| Search p95, warm CPU, 100k chunks | ≤ 300 ms |
| Filename/BM25-only query | ≤ 50 ms |
| Incremental update visible | ≤ 2 s after debounce |
| `get_status` p95 during indexing | ≤ 50 ms |
| UI responsiveness during indexing | no main-thread blocking |
| Indexing memory | ≤ 1.5 GB at 100k chunks |
| Idle memory | ≤ 400 MB including WebView |
| First-run CPU asset download | product budget recorded per release |
| First-run full asset download | product budget recorded per release |

Benchmarks are reproducible and committed under `docs/audits/evaluations/`.

## 13. Quality and evaluation

### 13.1 Golden set

- 200+ queries with graded relevance.
- English, Portuguese, Spanish, French, German, and mixed-language files.
- Exact phrase, filename, semantic paraphrase, long-document, and duplicate cases.
- Query categories: known-item, conceptual, exact identifier, cross-language,
  needle-in-a-haystack, exploratory, mixed semantic+metadata, and code search.
- Manual and synthetic near-duplicate pairs.
- Queries that require passage-level evidence.

### 13.2 Metrics

- Document Recall@10/20.
- Passage Recall@10.
- nDCG@10 at document and passage level.
- MRR@10.
- Duplicate rate in top 10.
- Aspect coverage and diversity.
- Length-bias error by length bucket.
- p50/p95 latency and memory.

### 13.3 Gates

- Reranker: +5 nDCG@10, no passage Recall regression.
- Near-duplicate collapse: ≥50% duplicate reduction without recall loss.
- Diversity: no more than 1 nDCG point loss.
- Per-document limits: reduce source monopolization without Recall@10 loss.
- Embedding model: no language slice drop >2 points; overall +3 nDCG or material
  latency/memory gain at equal quality.
- All ranking changes require before/after evidence.

## 14. Testing strategy

### 14.1 Rust

- Unit tests for extraction, chunking, signatures, filename matching, RRF.
- CPU/CUDA/AMD/NPU embedding tests on supported hardware.
- Index lifecycle tests: create, modify, rename, delete, skip, prune.
- Watcher event mapping tests.
- Migration tests.
- Ranking mechanism tests: aggregation, per-doc limits, diversity, dedupe,
  length correction.
- Provisioning tests: manifest parsing, checksum mismatch, retry, atomic install.
- Benchmark harness.

### 14.2 Frontend

- TypeScript build and Vite production build.
- Component tests for search, results, preview, files, settings, health.
- Locale catalog completeness and fallback tests.
- Theme snapshot/contrast checks.
- Mocked Tauri IPC.
- Optional Tauri WebDriver/CDP release smoke.

### 14.3 Hardware matrix

| Environment | Coverage |
|---|---|
| CPU-only Windows | Build, tests, search |
| CUDA Windows | Embedding/search smoke |
| AMD DirectML Windows | Embedding/search smoke |
| Intel NPU Windows | Embedding/search smoke |
| macOS/Linux | Build check; support decision pending |

CI without hardware runs formatting, linting, TypeScript, pure Rust tests, and
frontend tests. Hardware jobs run on labeled runners.

## 15. Security, privacy, and licensing

- Seeky source is MIT-licensed; third-party assets retain their licenses.
- No account, activation, or commercial license key.
- No outbound network calls except first-run/update asset requests to R2.
- No document content in asset requests or logs.
- Downloaded assets are checksummed and optionally signed.
- Only Tauri core and dialog capabilities are exposed to the webview.
- File opening is a Rust command, not a broad opener allowlist.
- Users choose folders explicitly; ignored directories and 25 MB file cap apply.
- Do not add telemetry or analytics.
- Review model/runtime licenses before publishing assets or installers.
- Include third-party notices with downloaded assets.

## 16. Milestones

### M0 — Runnable PoC (complete)

Local indexing, extraction, embeddings, hybrid search, preview, CPU/CUDA/NPU,
Tauri UI, tests, release executable.

### M1 — Live incremental indexing (complete)

Watcher, debounce, rename/delete, per-file incremental indexing, per-folder pause,
health, cancellation, filename/path signal.

### M2 — SOTA retrieval core (next)

**Scope:**

1. Multilingual golden-set and Rust benchmark harness.
2. Model evaluation for multilingual embedding candidates.
3. Passage-level cross-encoder reranking.
4. Document-level aggregation and hierarchical document retrieval.
5. Per-document candidate limits.
6. Near-duplicate signatures and collapsing.
7. Cross-document diversity.
8. Length-bias correction and calibrated fusion.
9. Ranking module refactor and ablation reports.
10. Minimal result explanations for the new stages.

**Acceptance:**

- Every required mechanism implemented and ablated.
- Reranker improves nDCG@10 by ≥5 points.
- Duplicate rate reduced ≥50%.
- Diversity/length corrections within accepted quality bounds.
- Search p95 within budget.
- No single-language slice regresses more than 2 points.

### M3 — Product UX foundation

**Scope:**

1. Light/dark themes with OS default.
2. English/Portuguese locale catalogs and OS detection.
3. Minimal UI pass: remove default backend/model internals; advanced diagnostics.
4. Essential metadata filters: root, extension, modified date, size.
5. Keyboard/accessibility pass.
6. Search cancellation/stale-request handling.
7. Component and locale tests.

**Acceptance:**

- No hardcoded user-facing strings.
- Theme and locale follow OS by default.
- Missing locale falls back to English.
- Default UI has only essential controls.
- Both themes pass contrast checks.
- Filters preserve retrieval recall (retrieve-then-filter).

### M4 — Slim setup and hardware matrix

**Scope:**

1. R2 bucket `seeky`, manifests, signing, checksums, notices.
2. First-run download/verify/cache/repair UI.
3. Remove Gety installation and bundled IR dependency.
4. CPU/CUDA asset selection.
5. AMD DirectML validation (ROCm research).
6. Intel NPU asset selection.
7. Offline/retry/disk-full failure handling.
8. Clean-VM validation.

**Acceptance:**

- Clean machine with no Gety install can provision and search.
- No account or license key requested.
- Interrupted downloads and checksum failures are safe.
- App works offline after provisioning.
- Failed update keeps the previous verified assets.
- CPU fallback always works.

### M5 — Scale and storage

**Scope:**

1. 10k documents / 100k chunks benchmark.
2. Batch embedding and transaction tuning.
3. Content-addressable embedding cache and multi-resolution indexing evaluation.
4. ANN decision gate: `sqlite-vec` or USearch only if exact cosine misses budget.
5. Database maintenance and integrity checks.
6. Startup reconcile evaluation for offline edits.
7. Storage growth and quantized-vector evaluation.

**Acceptance:**

- 100k-chunk latency targets met.
- Memory/throughput measured.
- ANN introduces no recall regression beyond the accepted threshold.
- Backward-compatible migrations.

### M6 — Packaging and release

**Scope:**

1. Windows installer and portable archive.
2. Code signing and SHA-256 checksums.
3. R2 asset publication pipeline and release checklist.
4. First-run diagnostics for missing network/assets.
5. Local rotating logs with redaction.
6. Versioning, release notes, rollback.
7. No auto-updater unless scope changes.

**Acceptance:**

- Signed installer and portable build reproduce.
- Clean-VM install works with documented prerequisites.
- Asset manifest and licenses published together.
- Missing assets produce actionable repair paths.
- Release artifacts checksummed.

### M7 — Optional answer layer (deferred)

Only after explicit scope approval:

- extract cited passages from the pruned result set;
- optionally call a local LLM adapter;
- preserve not-found behavior and citation checks;
- keep the default product search-only.

## 17. Work breakdown and sequencing

| Order | Workstream | Depends on |
|---|---|---|
| 1 | Golden set + benchmark harness | M1 |
| 2 | Embedding candidate evaluation | 1 |
| 3 | Hierarchical ranking + mechanisms | 1, 2 |
| 4 | Reranker/pruner gates | 3 |
| 5 | UI themes + i18n + minimal pass | M1 |
| 6 | Metadata filters | 3, 5 |
| 7 | R2 provisioning + asset pipeline | 2 |
| 8 | AMD/NPU backend validation | 7 |
| 9 | Scale/ANN decision | 3, 8 |
| 10 | Installer/signing/release | 5–9 |
| 11 | Optional answer layer | Explicit scope change |

M2, M3, and M4 can overlap where dependencies allow. M4 must not publish assets
for a model that has not passed M2's evaluation gate.

## 18. Release and versioning

- SemVer for the application.
- Every release updates `CHANGELOG.md`.
- Every release records commit SHA, toolchain versions, tests, benchmarks,
  artifact sizes, SHA-256, model/runtime manifest versions, and licenses.
- Release builds use `tauri build`.
- The app and its R2 manifest are released together.
- A new embedding model requires a migration/reindex plan.
- No telemetry or silent network calls in release builds.

## 19. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| R2 outage | First run blocked | Cached manifest, retry, manual import, status page |
| Corrupt/malicious asset | Security | SHA-256, signatures, HTTPS, atomic install |
| Model license incompatibility | Distribution blocked | License gate before asset publication |
| Gety dependency migration | Regressions | Keep current fallback until clean-VM provisioning passes |
| CUDA/AMD/OpenVINO runtime mismatch | Backend failure | Provisioning selection, diagnostics, CPU fallback |
| Multilingual quality variance | Poor recall | Language-stratified evaluation |
| Reranker latency | Slow search | Bounded candidates, quantization, fail-open |
| Aggressive dedupe/diversity | Relevant docs hidden | Ablations, thresholds, manual review |
| Exact cosine at scale | Latency | Benchmark gate, ANN migration |
| Watcher storms | Index churn | Debounce, dedupe, ignore rules, pause |
| SQLite contention | UI stalls | Short locks, WAL, per-file transactions |
| Large downloads | Poor first-run UX | Slim profiles, resume, progress, size reporting |

## 20. Open decisions

1. Final embedding model/dimension and reranker model.
2. AMD Windows path: DirectML first; ROCm support decision.
3. Reranker enabled by default on CPU or only accelerated backends.
4. ANN trigger threshold and library.
5. Whether startup reconcile is enabled by default.
6. Installer format and signing certificate.
7. R2 asset signing key management.
8. Whether an optional answer layer is ever in scope.

## 21. Definition of done

A milestone is done only when:

- Implementation matches this plan and product decisions.
- Commands, events, types, and assets are documented.
- Tests and evaluation gates pass.
- No known data-loss or migration regression exists.
- Performance is measured against the budget.
- UI strings are localized and both themes work (from M3 onward).
- User-facing behavior is reproducible from the README.
- Evidence is added under `docs/validation/` or `docs/audits/`.
- `CHANGELOG.md` and the implementation plan are updated.

## 22. Immediate next actions

1. Build the multilingual golden-set/corpus generator and Rust benchmark harness.
2. Evaluate `gety-embed-v0` and multilingual candidates on quality, CPU latency,
   accelerator latency, memory, download size, and license.
3. Implement document aggregation and hierarchical retrieval behind tests.
4. Add near-duplicate signatures, per-document limits, diversity, and length
   correction with ablations.
5. Start the UI i18n/theme foundation in parallel.
6. Define and publish the R2 manifest schema and signing flow.
