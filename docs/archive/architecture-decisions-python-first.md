> **Archived — superseded.** This document is historical research. The active Seeky implementation is Rust/Tauri/TypeScript; see [../plans/seeky-implementation-plan.md](../plans/seeky-implementation-plan.md).

# 09 — Architecture Decisions and Open Questions

Short decision records for the minimal app. Each one states the decision, the
reason, and what would change it.

---

## ADR-001 — SQLite is the source of truth; no vector DB in v1

**Decision:** store documents, blocks, chunks, FTS5, and vectors in one SQLite
database.

**Why:** Gety proves this design works for a desktop corpus; it is zero-ops,
portable, transactional, and easy to back up. Exact cosine is acceptable for
≤100k chunks. It avoids a second service and keeps citations/joins trivial.

**Revisit when:** p95 dense search exceeds your target, or the corpus exceeds
~1M chunks. Then add `sqlite-vec`, `usearch`, or Qdrant and keep SQLite as the
source of truth.

---

## ADR-002 — RRF for fusion, not Gety's 0.2/0.8 weighted scores

**Decision:** fuse BM25 and dense retrieval with Reciprocal Rank Fusion
(`k=60`, equal weights initially).

**Why:** RRF is rank-based and robust to score-scale differences; it needs no
calibration. Gety's fixed 0.2/0.8 score fusion is corpus-tuned and brittle.
RRF is the safer baseline for a new corpus.

**Revisit when:** a calibrated weighted fusion beats RRF on the gold set by a
meaningful margin. Keep both as an ablation.

---

## ADR-003 — Python backend first, Rust/Tauri later

**Decision:** build v1 with FastAPI + SQLite + ONNX Runtime; wrap in Tauri only
after the retrieval loop is validated.

**Why:** extraction, chunking, embedding, and reranking iterate much faster in
Python. The HTTP API contract keeps the UI independent; a Rust port can happen
later without rewriting the frontend.

**Revisit when:** packaging/latency/memory becomes a product blocker, or you
need a single small binary. The Rust path is documented in
[`03-minimal-rag-app-blueprint.md`](minimal-rag-app-blueprint-python.md).

---

## ADR-004 — Start with `gety-embed-v0`; evaluate Qwen3 before switching

**Decision:** use the installed 384-d Gety model for v1; add Qwen3-Embedding-0.6B
as a second model behind the same interface and migrate only if it wins.

**Why:** the Gety model is already on disk, MIT, small, and fast; it removes a
download blocker. Qwen3 is larger (0.6B) and 1024-d; it may improve quality but
changes storage/latency.

**Revisit when:** the gold-set nDCG@10 shows a clear Qwen3 lift and hardware can
handle indexing/query latency. Store `model_id` and `dim` on every vector.

---

## ADR-005 — External-content FTS5 with triggers

**Decision:** use `CREATE VIRTUAL TABLE chunks_fts USING fts5(text,
content='chunks', content_rowid='id')` and maintain it with insert/delete/update
triggers.

**Why:** text is stored once in `chunks`; FTS stays in sync automatically;
deletes/updates are correct. Gety uses contentless FTS5 plus application-level
bookkeeping; external content is simpler for a new app.

**Revisit when:** you need contentless FTS for storage reasons, or you partition
FTS per root. Then use `content=''` and explicit delete commands.

---

## ADR-006 — No OCR in v1

**Decision:** ship text extraction without OCR; add an open OCR engine later if
needed.

**Why:** Gety's OCR weights are encrypted/private and not reusable. OCR adds
significant indexing cost and language complexity. Text/PDF/DOCX/XLSX/PPTX
cover the first use case.

**Revisit when:** users need searchable scans/images; use RapidOCR/PaddleOCR or
Tesseract and store OCR text as blocks with bbox.

---

## ADR-007 — No connectors and no AI integrations

**Decision:** index local folders/drives only; no MCP/REST exposure to external
AI tools in v1.

**Why:** the goal is a focused local file search/RAG app. Connectors and
integrations multiply configuration, auth, permissions, and support surface.

**Revisit when:** the core retrieval loop is stable and a specific integration
is requested. The Gety API/MCP model is documented for reference, not required.

---

## ADR-008 — Reranker after RRF, not before

**Decision:** retrieve broad candidates, fuse with RRF, then rerank top 20–30.

**Why:** cross-encoders are expensive; reranking the whole corpus is
unnecessary. RRF handles recall; the reranker handles precision.

**Revisit when:** reranker latency is low enough to expand the candidate set, or
the retriever recall is the bottleneck.

---

## ADR-009 — Heuristic pruner first

**Decision:** implement dedupe + doc cap + neighbor expansion + MMR + token
budget before any learned pruner.

**Why:** Gety has no pruner; there is no off-the-shelf model with a clear
contract. A deterministic pruner is debuggable and provides a baseline for a
future model.

**Revisit when:** you have labeled query–passage–answer data and a measured
answer-quality gain from a learned pruner.

---

## ADR-010 — No telemetry by default

**Decision:** local-only logging; no PostHog/Sentry/analytics in v1.

**Why:** the app is local-first and handles personal files. Telemetry adds
privacy/compliance burden with little value before product-market fit.

**Revisit when:** you need crash diagnostics; make it opt-in, redact paths/text,
and document retention.

---

## Decisions pending measurement

| Question | Experiment | Decision rule |
|---|---|---|
| Exact vs ANN | p95 latency and recall at 100k/500k/1M chunks | Add ANN when p95 > 500 ms or recall@10 drops > 2%. |
| Gety vs Qwen3 embeddings | Same gold set, same chunking | Switch when nDCG@10 improves ≥ 3 points with acceptable latency. |
| Reranker blend | Reranker-only vs 0.7 blend | Choose higher nDCG@10; prefer simpler. |
| Chunk size | 384/512/768 tokens | Choose best nDCG@10 per storage/latency. |
| E5 prefixes | With/without `query:`/`passage:` | Choose higher recall@10; record in DB. |
| BM25 tokenizer | unicode61 vs trigram/jieba | Choose best for language mix; measure index size. |
| Pruner | heuristic vs none vs learned | Keep only if answer quality improves. |
| i8 quantization | f32 vs i8 | Accept if nDCG loss < 1% and storage/latency wins. |

---

## Open questions inherited from Gety

- Exact `gety-embed-v0` query/passage prefixes in production.
- Exact chunk size/overlap (`CHUNK_SIZE_MAX_BYTES` exists; value not recovered).
- Exact semantic-score normalization in Gety's 0.2/0.8 fusion.
- Exact `gety-service` RPC/IOCTL surface.
- OCR architecture/language coverage (encrypted).
- 0.7.0 frontend runtime behavior (bundle not loaded/cached at capture time).

None of these block the minimal app; they are research questions for fidelity,
not prerequisites.
