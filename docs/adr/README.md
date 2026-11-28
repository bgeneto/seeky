# Architecture Decision Records

One decision per file, numbered, never renumbered. ADRs record **why** the
architecture is the way it is. Accepted ADRs are immutable: to change a
decision, write a new ADR that supersedes the old one and update only the old
ADR's status line.

| Status | Meaning |
|---|---|
| Proposed | Under discussion; must not be implemented yet |
| Accepted | Binding for code, specs, and plans |
| Superseded | Replaced; kept for history (see the superseding ADR) |
| Deprecated | No longer relevant; nothing replaces it |

Every benchmark-selected component (embedding model, reranker, lexical engine,
vector store, OCR engine, extractor, …) gets its own ADR that cites the
benchmark report in [`../benchmarks/results/`](../benchmarks/results/README.md)
that justified it.

Template: [`_template.md`](_template.md).

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-tauri-rust-react-shell.md) | Tauri 2 shell, Rust backend, React/TypeScript UI | Accepted (amended by 0015) |
| [0002](0002-sqlite-fts5-only-storage.md) | SQLite + FTS5 as the only storage engine | Superseded by 0020 |
| [0003](0003-hybrid-retrieval-rrf.md) | Hybrid retrieval with filename/path signal and RRF | Accepted (baseline fusion) |
| [0004](0004-gety-artifact-backend-mapping.md) | CPU/CUDA/NPU mapping on Gety model artifacts | Superseded by 0016, 0019 |
| [0005](0005-incremental-watcher.md) | Incremental watcher with per-file indexing | Accepted |
| [0006](0006-narrow-webview-capabilities.md) | Narrow webview capabilities, Rust-side file opening | Accepted |
| [0007](0007-temporary-lfs-model-asset.md) | Temporary Git LFS model asset during the PoC | Accepted (transitional) |
| [0008](0008-no-sidecar-no-http-api.md) | No sidecar service or HTTP API | Accepted |
| [0009](0009-mit-license.md) | MIT license for Seeky source | Accepted |
| [0010](0010-no-account-no-license-key.md) | No account, activation, or license key | Accepted |
| [0011](0011-slim-first-run-provisioning.md) | Slim first-run provisioning from Cloudflare R2 | Accepted (amended by 0018) |
| [0012](0012-two-themes-minimal-ui-en-pt.md) | Two themes, minimal UI, English/Portuguese UI | Accepted |
| [0013](0013-hierarchical-multilingual-retrieval.md) | SOTA multilingual hierarchical retrieval | Accepted |
| [0014](0014-multilingual-model-backend-policy.md) | Multilingual model and backend policy | Superseded by 0016, 0019 |
| [0015](0015-engine-first-architecture.md) | Engine-first architecture: UI-independent Rust engine | Accepted |
| [0016](0016-cpu-first-npu-ready-execution.md) | CPU-first, NPU-ready, GPU-optional execution | Accepted (amended by 0025) |
| [0017](0017-spec-and-benchmark-driven-development.md) | Spec-Driven + Benchmark-Driven Development | Accepted |
| [0018](0018-lexical-first-availability.md) | Lexical-first availability before model provisioning | Accepted |
| [0019](0019-single-inference-engine.md) | ONNX Runtime as the single inference engine, with a validation gate | Accepted |
| [0020](0020-pluggable-index-backends.md) | Pluggable lexical/vector index backends; SQLite as metadata source of truth | Accepted |
| [0021](0021-no-generative-models-in-product.md) | No generative models in the shipped product | Accepted (amended by 0026) |
| [0022](0022-permissive-license-gate.md) | Permissive-license gate for code, models, and data | Accepted |
| [0023](0023-multimodal-ready-engine.md) | Multimodal-ready engine; visual retrieval as an optional, gated pack | Accepted |
| [0024](0024-source-code-indexing-opt-in.md) | Source-code indexing is opt-in; source files are never opened directly | Accepted |
| [0025](0025-automatic-provider-opt-in-gpu-tier-full-speed.md) | Automatic provider selection, opt-in GPU quality tier, and full-speed indexing (amends 0016) | Accepted |
| [0026](0026-model-verified-evaluation-judgments.md) | Model-verified evaluation judgments (amends 0021) | Accepted |
| [0027](0027-progressive-reranking-budget.md) | Progressive reranking with its own latency budget | Accepted |
