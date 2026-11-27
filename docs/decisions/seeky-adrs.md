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

## ADR-007 - Temporary LFS asset during the PoC (superseded by ADR-011)

**Status:** transitional. This decision applies only to the current PoC.

**Decision:** Track the temporary bundled OpenVINO `model.bin` with Git LFS while
the first-run provisioning pipeline does not exist.

**Rationale:**
- The current NPU validation path needs the 118.6 MB IR in release resources.
- Plain Git would bloat every clone and diff.

**Consequences:**
- Contributors need Git LFS for the current NPU path.
- The target slim product removes this bundled asset and downloads it from R2
  under ADR-011.

## ADR-008 - No sidecar service or HTTP API

**Decision:** All backend behavior runs in the Rust Tauri process. Do not add a
local web framework, public REST API, or sidecar process.

**Rationale:**
- Less memory, fewer ports, fewer lifecycle failures.
- No cross-process serialization of search/index operations.
- The desktop UI is the only supported client.

**Consequences:**
- Internal tooling must call Rust functions or Tauri commands.
- External automation would require a separate, explicitly scoped interface.

## ADR-009 - MIT license for Seeky source

**Decision:** License Seeky source code under the MIT License. Keep third-party
libraries, runtimes, and model weights under their own licenses.

**Rationale:**
- MIT is permissive and compatible with the permissive dependencies and model
  families used by Seeky.
- It minimizes friction for contributors, downstream users, and distribution.
- It does not relicense third-party assets.

**Consequences:**
- Include `LICENSE` and third-party notices.
- Review every model/runtime license before adding it to the R2 bucket or an
  installer.
- Non-commercial or incompatible model licenses are ineligible.

## ADR-010 - No account, activation, or license key

**Decision:** Seeky does not require an account, sign-up, activation,
subscription, or commercial license key.

**Rationale:**
- The product is a local tool; identity adds no value.
- Entitlement checks conflict with offline, account-free use.
- The MIT source license is not an activation mechanism.

**Consequences:**
- No auth UI or entitlement client.
- Public read-only asset downloads.
- No telemetry or identity calls.

## ADR-011 - Slim first-run provisioning from Cloudflare R2

**Decision:** Ship a small application and download runtimes, models, tokenizers,
and native libraries on first run from the public **seeky** Cloudflare R2 bucket.
Verify hashes/signatures, cache locally, and run offline afterward.

**Rationale:**
- Keeps installer size small and avoids a multi-gigabyte bundle.
- Allows platform/backend-specific asset selection.
- Removes the requirement to install Gety.
- Allows model upgrades without shipping a new installer.

**Consequences:**
- A provisioning UI, manifest, retry, checksum, repair, and offline error paths
  are required.
- The current LFS OpenVINO IR is transitional and must be removed from the
  shipped package.
- R2 availability and asset licensing become release-critical.

## ADR-012 - Two themes, minimal UI, and English/Portuguese localization

**Decision:** Support exactly light and dark themes (OS default), a minimal
search-focused UI, and English/Portuguese locales from the start. OS locale
selection falls back to English.

**Rationale:**
- Two themes cover the product without a theme maintenance burden.
- A minimal UI keeps the product a precise search tool rather than an AI
  dashboard.
- Early localization prevents hardcoded UI debt.

**Consequences:**
- All user-facing strings live in locale catalogs.
- Backend/model internals move behind an advanced/diagnostics surface.
- No theme editor, marketplace, or AI-style decorative panels.

## ADR-013 - SOTA multilingual hierarchical retrieval

**Decision:** Implement document aggregation, passage ranking, hierarchical
document retrieval, per-document limits, cross-document diversity, near-duplicate
detection, and length-bias correction as required parts of the retrieval engine,
using multilingual benchmark-gated models.

**Rationale:**
- Chunk-only ranking does not represent document relevance.
- Multilingual files require multilingual embedding and reranking.
- Diversity, deduplication, and length correction prevent common ranking
  failures.
- SOTA claims require evaluation, not model names.

**Consequences:**
- Ranking code is split into explicit stages with tests and ablations.
- The golden set includes multiple languages and duplicate/length cases.
- Model or dimension changes require a reindex/migration plan.
- The retrieval pipeline is described in
  [`../architecture/retrieval-engine.md`](../architecture/retrieval-engine.md).

## ADR-014 - Multilingual model and backend policy

**Decision:** Select embedding and reranker models by multilingual quality, CPU
practicality, accelerator latency, memory, and license. CPU is the universal
fallback; CUDA, AMD (DirectML/ROCm), and Intel NPU are validated accelerated
paths. Model changes require reindexing.

**Rationale:**
- The content language is independent of the UI language.
- The best model is hardware- and corpus-dependent.
- A single vector space per index is mandatory.

**Consequences:**
- Benchmark-gated model selection, including license review.
- Per-backend runtime assets and diagnostics.
- No silent mixing of embedding models.
- Details are in [`../architecture/model-strategy.md`](../architecture/model-strategy.md).
