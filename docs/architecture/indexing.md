# Indexing Architecture

| Field | Value |
|---|---|
| Status | Accepted target architecture |
| Date | 2026-11-27 |
| Governs | Filesystem intelligence, document intelligence, indexing pipeline, embedding reuse, index generations |
| Related | [overview](overview.md), [ADR-0005](../adr/0005-incremental-watcher.md), [ADR-0018](../adr/0018-lexical-first-availability.md), [ADR-0019](../adr/0019-single-inference-engine.md) |

Indexing is where a semantic desktop search engine differs most from a RAG
pipeline: the corpus is a dynamic filesystem of heterogeneous, duplicated,
constantly changing files that the user never "prepares". The indexer must
behave like a search-engine crawler for one machine — continuous, incremental,
resumable, and invisible.

## 1. Core idea: two-speed indexing

On CPU, neural embedding costs orders of magnitude more than extraction and
lexical indexing. Therefore:

| Lane | What it builds | Latency goal | Notes |
|---|---|---|---|
| **Fast lane** | Metadata, filename/path index, lexical index, duplicate signatures | Seconds | Makes a file findable by name and words almost immediately |
| **Semantic lane** | Passage embeddings (and optional sparse/learned representations) | Background, prioritized | Fills in meaning; coverage is reported per folder |
| **Visual lane** (optional pack) | Visual-unit embeddings ([ADR-0023](../adr/0023-multimodal-ready-engine.md)) | Background, lowest priority | Never delays text semantic coverage; visual coverage reported separately |

A file is **lexically searchable** after the fast lane commits and
**semantically searchable** after its embeddings commit. Search results merge
both transparently ([ADR-0018](../adr/0018-lexical-first-availability.md)).

## 2. Pipeline

```text
discover ─► change set ─► jobs (SQLite, durable) ─► extract ─► normalize ─► chunk
   ▲                                                                         │
   │  watcher (live)                                                         ▼
   │  reconcile (startup / resume)                         ┌── fast lane commit ──┐
   │  manual reindex                                       │  metadata, filename, │
   │                                                       │  lexical, signatures │
   │                                                       └──────────┬───────────┘
   │                                                                  ▼
   │                                       embed queue (priority) ─► cache lookup
   │                                                                  │ miss
   │                                                                  ▼
   │                                                   batched embedding (CPU/NPU)
   │                                                                  ▼
   └──────────────────────────────────────────── semantic lane commit (vectors)
```

### 2.1 Discovery

- **Initial scan:** parallel directory walk (`ignore`/`jwalk` class, benchmark
  decides) with exclusion rules applied during the walk.
- **Live watching:** one recursive watcher per enabled root; debounce and path
  dedupe; rename/move handling; directory events trigger subtree scans
  ([ADR-0005](../adr/0005-incremental-watcher.md)).
- **Startup reconcile (required):** on launch and on watcher resume, compare the
  filesystem with stored signatures and enqueue differences. Baseline is a
  parallel stat walk; OS change journals (Windows USN journal, macOS FSEvents
  event-ID replay) are benchmark-gated accelerators. Linux uses the stat walk.
- **Exclusions:** default ignore set (VCS metadata, dependency/build folders,
  caches, OS/system folders, temp files), optional `.gitignore` honoring,
  per-type size caps, binary detection. User exclusions per root.

### 2.2 Jobs

- Durable rows in `jobs` keyed by `(root, path)`; latest change wins; jobs are
  idempotent and safe to replay after a crash.
- Priority: user-opened/recently-modified files and small files first; bulk
  initial-index files last.
- Attempts and backoff for transient failures; permanent failures recorded in
  health with the reason (encrypted, corrupt, too large, unsupported).

### 2.3 Extraction (document intelligence)

- Extractors implement a common trait returning **structured text**: blocks
  with kind (heading, paragraph, list, table cell, code, slide, sheet row),
  locators (page, slide, sheet/row/col, line), and byte/char offsets.
- Untrusted input: every extractor runs with timeouts, memory caps, panic
  isolation, and fuzzing in CI. If fuzzing shows crashes that cannot be
  contained in-process, extraction moves to a same-binary worker process under a
  dedicated ADR ([ADR-0008](../adr/0008-no-sidecar-no-http-api.md)).
- Normalization: Unicode NFC (NFKC for matching keys), whitespace and hyphenation
  repair, boilerplate markers (repeated headers/footers).
- Language identification per document and per block (for analyzers and
  evaluation slices).
- OCR: optional asset pack; applied to image-only PDF pages and images; runs in
  the semantic lane's priority scheme so it never blocks lexical indexing of
  text documents. OCR text records the OCR engine and revision as provenance,
  so an engine change re-OCRs only affected files.
- **Visual units** (only when the visual pack is enabled,
  [ADR-0023](../adr/0023-multimodal-ready-engine.md)): image files, slides,
  embedded figures, and pages with little extractable text are recorded as
  visual units with locators and content hashes. Selection is adaptive and
  rule-based (the rules are benchmark-owned): a text-only page gets no visual
  unit, and the pages of a document are never all rendered for embedding. An
  image can carry both OCR passages and a visual unit; they are complementary
  representations of the same file.

### 2.4 Chunking

Goal: **discriminative passages that localize information precisely**, not
self-contained context for an LLM.

- Structure-aware: never split inside a sentence when avoidable; respect
  headings, pages, slides, sheets, and code blocks.
- Token-budgeted using the active embedding model's tokenizer (target size and
  overlap chosen by benchmark; candidate grid in the methodology).
- **Stable boundaries**: chunk boundaries depend on local structure, not on
  global offsets, so an edit re-chunks only the affected region.
- **Embedding input recipe** = optional in-document heading path + passage text.
  The filename and folder path are **never** part of the embedding input, so
  renames and moves never invalidate embeddings; filename relevance is handled
  by the filename retriever.
- Chunker version is part of the index generation.

### 2.5 Fast-lane commit

One store-writer transaction per batch (bounded by size and ≤ ~500 ms): file
row, passages, lexical postings, filename entry, content hash, SimHash, and
length statistics. After commit, the file is lexically searchable.

### 2.6 Semantic lane

- **Content-addressed embedding cache:** key = `blake3(embedding input recipe
  output)` + generation. Identical passages across copies, versions, and renames
  are embedded once.
- **Dynamic batching** by token length to minimize padding; batch size tuned per
  execution provider (CPU vs NPU static-shape buckets).
- **Resource governor:** background thread priority; CPU share cap; preemption
  by interactive search (the query pool always wins); optional pause on battery;
  memory ceiling.
- Commit vectors in batches to the active generation's vector index.
- **Visual lane** (optional pack): visual units are decoded, resized, and
  embedded in a separate queue below text passages in priority, with its own
  throughput session and budgets (V1–V2 in the methodology). Image decoding
  runs inside the governed pool, because it can cost as much as the model.
  Visual units use the same content-addressed cache, so copies and renames are
  never re-embedded.

## 3. Index generations (blue/green)

An index generation is identified by its **recipe**: embedding model ID +
revision + dimension/precision, tokenizer revision, chunker version, embedding
input recipe version.

- Changing any recipe element creates a new generation built in the background
  while the current generation keeps serving.
- The embedding cache is keyed per generation; passages unchanged under a new
  chunker version still reuse lexical data.
- When the new generation reaches full coverage (and passes integrity checks),
  it is atomically promoted; the old one is garbage-collected later.
- Vectors from different generations are never compared.
- **One lineage per embedding channel**
  ([ADR-0023](../adr/0023-multimodal-ready-engine.md)). The text channel's
  generation owns the lexical, filename, and text-vector indexes; a visual
  channel's generation (specialized design only) owns only visual vectors and
  records the visual recipe (model, revision, dimension, preprocessing,
  visual-unit selection rules). Rebuilding one channel never rebuilds another.
  With a unified model, image vectors live in the text channel's generation
  and are reused through the embedding cache when only text-side recipe
  elements (for example the chunker) change.

## 4. Failure semantics

| Event | Behavior |
|---|---|
| Extraction failure | Keep the previous version of the document; record health with reason |
| File vanished mid-job | Drop the job; delete stale entries |
| Embedding failure | Retry with backoff; document stays lexically searchable |
| Crash or power loss | Replay durable jobs; derived indexes verified by generation markers |
| Watcher failure | Mark root degraded; fall back to periodic reconcile; surface in health |
| Disk full | Pause indexing; keep serving search; actionable message |
| Model assets missing/corrupt | Semantic lane pauses; lexical lane continues; repair flow offered |
| Visual pack missing/corrupt | Visual lane pauses; text lanes and text search are unaffected; repair flow offered |
| Undecodable or oversized image | No visual unit; file stays findable by name (and OCR text, if any); health records the reason |

## 5. Metrics (owned by the benchmark program)

- Files/s and MB/s extracted per format; passages/s embedded per provider;
  images/s embedded including decode (visual pack) and visual coverage.
- Time-to-lexically-searchable and time-to-semantically-searchable.
- Re-embedding avoided by the cache (hit rate) on rename/copy/edit workloads.
- Search latency under concurrent indexing (interference ratio).
- Peak/idle RSS, disk per 1k passages, CPU share, energy per 1k passages (NPU vs
  CPU).
- Index freshness after offline edits (reconcile correctness and duration).
