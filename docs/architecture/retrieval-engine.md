# Seeky Retrieval Engine


Audience: Rust backend, ranking, and evaluation work

Seeky is a **Local Neural Information Retrieval Engine** for desktop files. The
retrieval engine must optimize document discovery first, then passage quality,
then diversity and redundancy, while remaining fast enough for interactive
search on CPU and accelerated hardware.

This document defines the target pipeline and the mechanisms that must be
implemented and measured. It does not claim that every stage is in the current
PoC.

Source context: the supplied report
[`traditional-rag-vs-local-neural-information-retrieval.html`](../research/traditional-rag-vs-local-neural-information-retrieval.html)
discusses the distinction between RAG and local neural IR; this document is the
English engineering contract.

## 1. Definitions

- **Passage/chunk**: a contiguous span of extracted text with source offsets.
- **Document**: one indexed file; may have many passages.
- **Candidate set**: passages and documents produced by lexical, filename, and
  dense retrievers before reranking.
- **Reranker**: multilingual cross-encoder that scores `(query, passage)` pairs.
- **Document aggregation**: a function that turns passage scores into a
  document-level relevance score.
- **Near-duplicate**: a document or passage that is substantially redundant with
  another result, including repeated files, versions, boilerplate, or copies.

## 2. Target pipeline

```text
Query
  │
  ├─ language/token analysis and filters
  │
  ├─ passage candidates
  │    ├─ BM25 over FTS5
  │    ├─ filename/path matches
  │    └─ dense passage retrieval
  │
  ├─ document candidates
  │    ├─ document aggregation
  │    └─ hierarchical document retrieval
  │
  ├─ multilingual cross-encoder passage reranking
  │
  ├─ document-level score aggregation after reranking
  │
  ├─ per-document candidate limits
  │
  ├─ near-duplicate detection and collapsing
  │
  ├─ cross-document diversity
  │
  ├─ length-bias correction and calibrated fusion
  │
  └─ final document ranking + best passages + snippets
```

The stages are ordered so expensive neural work runs on a bounded candidate set,
while cheap lexical and metadata signals can still rescue exact matches.

## 3. Passage-level ranking

### 3.1 Candidate generation

- BM25: top 100 passages.
- Dense passage retrieval: top 100 passages.
- Filename/path: top 40 documents, first relevant passage per document.
- Exact phrase and quoted searches: exact-match candidates are preserved even if
  their dense score is low.
- Candidate depth is configurable and benchmarked.

### 3.2 Cross-encoder reranking

- Rerank a bounded set of `(query, passage)` pairs, initially top 100–200.
- The reranker must be multilingual.
- Scores are calibrated per model/length bucket before fusion.
- Reranker failure fails open to the fused pre-rerank ordering.
- Batch size and sequence length are tuned per backend (CPU/CUDA/AMD/NPU).

### 3.3 Passage limits

- Default: at most 3 passages per document in the final presentation.
- Optional configurable cap per document for power users; default stays small.
- Passages below a minimum score or outside the query language distribution may
  be dropped only after evaluation.

### 3.4 Adaptive reranking and early exit

- Use a cascaded retrieval funnel: cheap candidates first, cross-encoder only on
  the bounded set.
- Exact filename/identifier matches may skip or reduce reranking.
- Ambiguous conceptual queries may receive a larger rerank budget.
- The budget adapts to hardware, query type, and observed latency.
- Every adaptive path must preserve deterministic fallback ordering.

### 3.5 Multi-resolution indexing and embedding reuse

- Retrieval units: document, section, passage, sentence.
- Do not necessarily embed every level; start with passage embeddings plus
  document aggregates, and derive sentence-level snippets at query time.
- Hash normalized chunk content and reuse embeddings when the hash,
  tokenizer revision, and model revision are unchanged.
- Renaming or moving a file must not re-embed unchanged chunks.
- An edited paragraph should ideally re-embed only affected chunks, subject to
  stable segmentation.
- Multiresolution embeddings are benchmark-gated; storage cost is a first-class
  metric.

### 3.6 Query-aware extractive snippets

- The file-search equivalent of a pruner is a query-aware extractive snippet
  engine, not a context compressor for an LLM.
- Preserve original sentence boundaries, readability, and source offsets.
- Return the best evidence passages, not a generated summary.
- Highlight query terms without rewriting content.
- Keep enough context to open the file at the right page/line when supported.

## 4. Document-level score aggregation

Document retrieval is a first-class stage, not a byproduct of sorting passages.

### 4.1 Signals

For each document:

- `p_max`: best passage score.
- `p_topk_mean`: mean of the top `k` passage scores.
- `p_coverage`: fraction of query terms/aspects covered across passages.
- `title_score`: filename/path relevance.
- `lexical_score`: calibrated BM25 document signal.
- `length_prior`: correction for document length.
- `source_consensus`: agreement across independent retrievers.
- `rerank_score`: aggregated cross-encoder evidence after reranking.

### 4.2 Aggregation form

A benchmarked weighted aggregation, initially:

```text
doc_score =
    w_max      * normalize(p_max)
  + w_topk     * normalize(p_topk_mean)
  + w_coverage * p_coverage
  + w_title    * normalize(title_score)
  + w_consensus* normalize(source_consensus)
  + w_length   * length_correction
```

Constraints:

- Every component is normalized to a stable range before weighting.
- Weights are tuned on the golden set, not guessed in production.
- `w_max` prevents missing a single highly relevant passage; `w_topk` prevents a
  one-chunk fluke from dominating.
- Ablations must show which signals add value.

## 5. Hierarchical document retrieval

1. **Document candidate retrieval**: use lexical, filename, and aggregated dense
   scores to select `D` documents (for example 100–200).
2. **Passage retrieval within documents**: rank passages inside those documents,
   plus any globally strong passages attached to them.
3. **Passage reranking**: cross-encode the bounded passage set.
4. **Document re-aggregation**: recompute document scores using reranked passage
   scores and the same aggregation contract.
5. **Final document ordering**: apply diversity, duplicate collapsing, and
   per-document limits.

The hierarchy keeps the reranker budget bounded and makes document quality
explicit instead of relying on whichever chunk happened to rank highest.

## 6. Per-document candidate limits

Purpose: prevent long, repetitive, or highly chunked documents from occupying
the result list.

- Hard default: 3 passages per document in final results.
- Candidate-stage cap: configurable, e.g. top 8 passages per document entering
  reranking.
- A document can contribute multiple distinct passages only when they cover
  different query aspects.
- Limits are applied after scoring but before diversity selection.

## 7. Cross-document diversity

Diversity operates at both document and passage level.

### 7.1 Document diversity

Use MMR-style selection or xQuAD-style aspect coverage:

```text
MMR(d) = λ * relevance(d) - (1 - λ) * max_similarity(d, selected)
```

- `relevance` is the aggregated document score.
- Similarity is computed from document embeddings or aggregated passage vectors.
- Default `λ` is tuned on the golden set; relevance remains dominant.
- Diversity must never promote an irrelevant document merely to fill quota.

### 7.2 Passage diversity

- If two passages from the same document are near-identical, keep the higher
  scoring one.
- If passages cover different query aspects, both may be shown within the
  per-document cap.
- Diversity penalties are reported in evaluation ablations.

## 8. Near-duplicate detection

Near-duplicate handling is required at both indexing and query time.

### 8.1 Signals

- Exact content hash (fast path).
- Normalized text SimHash/MinHash for near-duplicate documents.
- Embedding cosine similarity above a tuned threshold.
- Same title/filename with high text overlap (versions/copies).
- Boilerplate/template detection for repeated headers and footers.

### 8.2 Policy

- Collapse exact duplicates immediately.
- Group near-duplicates into clusters; choose the canonical document by
  freshness, path quality, and score.
- Keep alternate versions discoverable through a cluster indicator, not by
  filling the top results with copies.
- Deduplicate passages before reranking to save neural budget.
- Store duplicate signatures during indexing; query-time checks use them.

Thresholds must be evaluated for false collapses: two different contracts with
small changes must not be treated as the same result.

## 9. Length-bias correction

Length bias appears in BM25, dense similarity, and cross-encoder scores.

- BM25 keeps its length normalization; `b` is tuned per corpus.
- Dense passage scores are normalized by length bucket or a calibrated prior
  rather than raw cosine alone.
- Cross-encoder scores are calibrated by passage length and query type.
- Document scores include a document-length prior so long files do not win by
  having more chances to match.
- Corrections are evaluated with length-stratified queries and reported as an
  ablation.

## 10. Final result presentation

Each result contains:

- document title, path, extension, size, modified date;
- aggregated relevance score normalized for display;
- up to the per-document passage limit;
- highlighted query terms;
- source tags for lexical, semantic, filename, reranker, and diversity where
  useful;
- duplicate-cluster indicator when applicable.

The UI must remain minimal. Ranking internals are diagnostics, not default
content.

## 11. Configuration defaults

Initial values are starting points for benchmarks, not final truth:

| Parameter | Initial value |
|---|---:|
| BM25 candidate depth | 100 |
| Dense passage depth | 100 |
| Filename candidate depth | 40 |
| Rerank passage depth | 150 |
| Rerank batch size | backend-specific |
| Document candidate depth | 150 |
| Passages per document (final) | 3 |
| Passages per document (candidate) | 8 |
| RRF `k` | 60 |
| Diversity λ | 0.75 |
| Duplicate cosine threshold | tune per model |
| Length correction | tuned per model |

All values live in one ranking configuration module and are covered by tests.

## 12. Evaluation gates

### 12.1 Golden set

- 200+ queries with graded relevance.
- English, Portuguese, Spanish, French, German, and mixed-language documents.
- Exact phrase, filename-only, semantic paraphrase, long document, and duplicate
  queries.
- Manual and synthetic near-duplicate pairs.

### 12.2 Metrics

- Document Recall@10/20.
- Passage Recall@10.
- nDCG@10 at document and passage level.
- MRR@10.
- Duplicate rate in top 10.
- Aspect coverage / diversity.
- Latency p50/p95 and memory.
- Length-bias error by document-length bucket.

### 12.3 Acceptance

- Every required mechanism has an implementation and an ablation result.
- Reranker improves nDCG@10 by at least 5 points, or is not enabled by default.
- Near-duplicate collapsing reduces duplicate rate by at least 50% without
  lowering recall.
- Diversity does not reduce nDCG@10 by more than 1 point.
- Per-document limits reduce source monopolization and keep Recall@10.
- p95 latency remains within the budgets in the implementation plan.

## 13. Rust module plan

The current `search.rs` pipeline will be split into explicit stages:

| Module | Responsibility |
|---|---|
| `retrieval/lexical.rs` | FTS query construction and BM25 candidates |
| `retrieval/filename.rs` | Title/path candidates |
| `retrieval/dense.rs` | Embedding scan / ANN adapter |
| `ranking/aggregate.rs` | Document-level aggregation |
| `ranking/rerank.rs` | Cross-encoder adapter and batching |
| `ranking/diversity.rs` | MMR/xQuAD and per-document limits |
| `ranking/dedupe.rs` | Hash, SimHash/MinHash, embedding duplicate clusters |
| `ranking/calibrate.rs` | Length and backend score calibration |
| `search.rs` | Orchestration and response shaping |

The module split is a target; the current PoC has a compact search module and
must be refactored behind tests before adding the full pipeline.

## 14. Risks

- Reranker latency on CPU can dominate search; keep candidate depth bounded and
  quantization evaluated.
- Multilingual quality varies by language; evaluate each language separately.
- Aggressive diversity can hide relevant documents.
- Near-duplicate thresholds can collapse distinct contracts or versions.
- AMD/NPU execution-provider coverage is less mature than CUDA.
- Adding signals without ablation can produce a more complex but worse ranking.
