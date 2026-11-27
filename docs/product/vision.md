# Seeky — Product Vision and Principles

| Field | Value |
|---|---|
| Status | Accepted — the product "constitution" |
| Version | 2.1 (image search scope per [ADR-0023](../adr/0023-multimodal-ready-engine.md)) |
| Date | 2026-11-27 |
| Precedence | Highest. Every ADR, spec, plan, and line of code must comply. |

> **Seeky.** Find anything. By meaning.
> High-performance neural file search — instant, CPU-first, private, offline.

## 1. Formal definition

> **Seeky is a cross-platform, CPU-first, local neural information retrieval
> engine, delivered as a lightweight Tauri desktop application, designed to
> provide exceptionally fast, accurate, multilingual semantic search across the
> user's filesystem without requiring a dedicated GPU, cloud services, or
> generative language models.**

Seeky is born as **a high-performance search engine that has a desktop
interface — not a desktop app that has a search engine.** This inversion is
fundamental: the engine is designed, built, measured, and optimized first and
independently of the UI ([ADR-0015](../adr/0015-engine-first-architecture.md)).

Category: **Local Neural Information Retrieval Engine** / **Semantic Desktop
Search Engine**. Seeky is not RAG (there is no generation), not a chatbot, not an
agent backend, and not a document manager.

## 2. Non-negotiable principles

| # | Principle | Meaning | Engineering consequence |
|---|---|---|---|
| P1 | **CPU-first** | A dedicated GPU is never a requirement. | Every budget is defined and verified on CPU-only reference hardware. Models are chosen for CPU latency and throughput. ([ADR-0016](../adr/0016-cpu-first-npu-ready-execution.md)) |
| P2 | **NPU-ready** | Optional acceleration on low-power NPUs. | ONNX Runtime execution providers for Intel, Qualcomm, AMD, and Apple NPUs behind one inference API ([ADR-0019](../adr/0019-single-inference-engine.md)); static shapes; compiled-model cache; vector parity with CPU. |
| P3 | **Local-first** | Content, indexes, and inference stay on the computer. | No document content ever leaves the machine. The only network use is downloading public model/runtime assets. |
| P4 | **Performance-first** | Performance is an architectural requirement, not a later optimization. | Latency, throughput, memory, disk, and download budgets are specified up front and gated in CI and on reference hardware. |
| P5 | **Multilingual-first** | Portuguese and English are priority languages, without limiting others. | Every model and analyzer is evaluated per language slice and cross-lingually (pt↔en). The UI ships in en and pt. |
| P6 | **Search-only** | No chatbot, agents, MCP, connectors, or generative RAG. | No generative feature in the product; a vision-language model may appear only as a gated OCR transcriber (deterministic, fixed prompt, hallucination gate — [ADR-0021](../adr/0021-no-generative-models-in-product.md)). No HTTP API, public CLI, or sidecar ([ADR-0008](../adr/0008-no-sidecar-no-http-api.md)). |
| P7 | **Benchmark-driven** | No component is chosen for popularity or leaderboard position. | Every model, index engine, OCR engine, and ranking stage is chosen by a reproducible bake-off on Seeky's own protocol ([ADR-0017](../adr/0017-spec-and-benchmark-driven-development.md)). |
| P8 | **Model-agnostic core** | Models can be replaced without rewriting the engine. | Models are described by manifests and consumed through narrow traits; one vector space per index generation ([ADR-0019](../adr/0019-single-inference-engine.md)). |

Derived principles (equally binding):

- **Private by construction.** No telemetry, analytics, crash upload, or
  identity. No account or license key ([ADR-0010](../adr/0010-no-account-no-license-key.md)).
- **Open source.** MIT-licensed code; every shipped dependency, model, and
  runtime passes a permissive-license gate ([ADR-0009](../adr/0009-mit-license.md),
  [ADR-0022](../adr/0022-permissive-license-gate.md)).
- **Instant before perfect.** Results appear progressively: filename/lexical
  first, hybrid next, refined last. Lexical search works before any model is
  downloaded ([ADR-0018](../adr/0018-lexical-first-availability.md)).
- **Minimal, precise UI.** A search tool, not an AI assistant.

## 3. Users and jobs

**Primary users**

- Knowledge workers, researchers, students, lawyers, and engineers with large
  local collections (PDFs, Office files, notes, spreadsheets, code).
- Privacy-sensitive users who will not upload documents to a cloud service.
- Multilingual users whose files and queries mix Portuguese, English, and other
  languages.
- Users of ordinary laptops without a dedicated GPU.

**Core jobs**

1. Install a small app and search immediately — no account, no setup wizard.
2. Add folders; have them indexed in the background without slowing the machine.
3. Find a file by name, phrase, identifier, or **meaning**, in any content
   language, regardless of the query language.
4. See the best passages with highlighted evidence and open the file at the
   right place.
5. Trust that the index is current: edits, renames, deletes, and offline
   changes are reflected automatically.
6. Never wonder where the documents went: everything stays local.

## 4. Scope

### In scope

- Local filesystem indexing (user-selected folders), with live watching and
  startup reconciliation.
- Document extraction for the 20–30 most relevant formats (PDF, DOCX, XLSX,
  PPTX, ODF, RTF, HTML, EPUB, e-mail files, Markdown, plain text, source code),
  with structure and source offsets.
- Optional OCR for scanned PDFs and images (separately provisioned CPU asset
  pack); an opt-in GPU OCR pack only if its bake-off justifies it — never
  required, never the default.
- Optional **visual retrieval pack**: text-to-image and image-to-image search
  over images and selected visual units of documents (slides, embedded
  figures), using non-generative embedding encoders. Separately provisioned,
  outside the default download, never loaded on the text query path, and
  delivered only after the text engine meets its gates; the engine's contracts
  are modality-aware from the start ([ADR-0023](../adr/0023-multimodal-ready-engine.md)).
- Hybrid retrieval: lexical BM25, filename/path, dense semantic, fusion,
  cross-encoder reranking, and benchmark-gated learned sparse retrieval.
- Hierarchical ranking: passage ranking, document aggregation, per-document
  limits, near-duplicate collapsing, cross-document diversity, length-bias
  correction ([ADR-0013](../adr/0013-hierarchical-multilingual-retrieval.md)).
- Query-aware extractive snippets with highlights (the "pruner" of a search
  engine: it selects original text for a human, never rewrites it).
- Metadata filters: folder, extension/type, modified date, size.
- Embedded storage only (SQLite + embedded lexical/vector indexes).
- CPU inference everywhere; optional NPU acceleration.
- Slim installer; first-run download of models/runtimes from the `seeky`
  Cloudflare R2 bucket; fully offline afterward ([ADR-0011](../adr/0011-slim-first-run-provisioning.md)).
- Light and dark themes; English and Portuguese UI ([ADR-0012](../adr/0012-two-themes-minimal-ui-en-pt.md)).
- Windows first; macOS and Linux as cross-platform targets before 1.0 GA.

### Deferred (post-1.0, each needs a scope decision)

- Audio and video search or transcription.
- Search inside archives (zip, 7z), network drives, removable-drive indexes.
- Saved searches; search history beyond a small local recent-queries list.
- Other opt-in GPU asset packs (for example faster initial indexing).

### Out of scope (permanently, unless this document changes)

- Chat, generated answers, summaries, agents, conversational history, LLM query
  rewriting, HyDE, generated snippets, generated image captions or tags — any
  model that generates content (vision-language models only as gated OCR
  transcribers, ADR-0021).
- MCP server, public REST API, public CLI, connector SDK, external connectors,
  cloud sync, LAN access, AI-client integrations, API-key management.
- Accounts, multiuser support, activation, license enforcement, telemetry.
- Collections, tags, document management, universal file viewers (files open in
  the OS default application).
- Plugin ecosystems, theme marketplaces, theme editors, dashboards.

## 5. Product decisions

### 5.1 Distribution and first run

- A small installer (budget in [`../benchmarks/methodology.md`](../benchmarks/methodology.md)).
- On first launch, filename and lexical search work immediately.
- Inference runtimes, the default embedding model, and the reranker are
  downloaded in the background from public, signed, checksummed assets; semantic
  search activates when they are verified and as background embedding coverage
  grows.
- OCR is an optional asset pack.
- No account or license key at any point; downloads carry no user data.
- Air-gapped installs can import an offline asset bundle.

### 5.2 UI

- Three surfaces: **Search** (query, results, preview), **Folders** (roots,
  status, coverage, pause/resume), **Settings** (language, theme, indexing
  options, notices, advanced diagnostics).
- Progressive results; keyboard-first; cancel stale queries instantly.
- Exactly two themes (light/dark), OS default, optional override, accessible
  contrast and focus states.
- English and Portuguese catalogs from day one; OS locale detection; regional
  variants map to base locales; English fallback; no hardcoded strings.
- Backend/model internals live behind an advanced diagnostics surface; the
  default is automatic.
- No dashboards, onboarding carousels, AI badges, generated summaries, chat
  panels, or decorative metrics. Empty states and errors state the next action
  in one sentence.

### 5.3 Privacy

- Search, indexing, inference, and preview are local.
- Logs are local, rotating, and redacted (no document text; paths hashed or
  truncated by default).
- No document content is ever included in network requests.

## 6. Quality priorities

When goals conflict, resolve them in this order:

1. **Correctness and privacy** — never lose data, leak content, or show stale
   results as current.
2. **Retrieval quality** — multilingual relevance at document and passage level.
3. **Interactive latency** — search stays instant, including during indexing.
4. **Indexing efficiency** — throughput, time-to-searchable, low system impact.
5. **Resource footprint** — RAM, disk, download size, energy.
6. **UI polish.**

Measurable targets for each priority live in
[`../benchmarks/methodology.md`](../benchmarks/methodology.md). No model or
pipeline is called "state of the art" without a committed benchmark report.

## 7. Positioning

| Inspiration | What Seeky takes from it |
|---|---|
| Everything (voidtools) | Instant filename search, transparent indexing |
| Lucene / Tantivy | Mature lexical IR, segment-based indexing |
| Vespa | Multi-stage ranking and hybrid retrieval |
| ColBERT, SPLADE, Matryoshka embeddings | Modern neural IR techniques, evaluated for CPU cost |
| BEIR / MTEB / MIRACL / MLDR | Evaluation discipline — applied to desktop search, not QA |

*Semantic File Search SOTA = Filesystem Intelligence + Neural Information
Retrieval + Semantic Presentation.* Every millisecond saved in retrieval reaches
the user directly, because the search is the product.

## 8. Provenance

This document consolidates and replaces the former `seeky-product-decisions.md`
and `seeky-scope.md`. The original Portuguese scope brief is archived at
[`../archive/seeky-scope-pt-br.md`](../archive/seeky-scope-pt-br.md); where it
conflicts with this document (NPU deferral, multi-billion-parameter GPU
embedders, a local LLM answer layer, optional public CLI), this document wins.
