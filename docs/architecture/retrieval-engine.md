# Retrieval Engine

| Field | Value |
|---|---|
| Status | Accepted target contract (stages exist; defaults are benchmark-owned) |
| Date | 2026-11-27 (v2; supersedes v1 of 2026-11-26) |
| Governs | Query analysis, candidate generation, fusion, ranking stages, snippets, progressive delivery |
| Related | [ADR-0003](../adr/0003-hybrid-retrieval-rrf.md), [ADR-0013](../adr/0013-hierarchical-multilingual-retrieval.md), [methodology](../benchmarks/methodology.md), [candidates](../benchmarks/candidates.md) |

The retrieval engine optimizes, in order: **finding the right documents**, then
**showing the right passages**, then **avoiding redundancy** — while meeting
interactive latency budgets on CPU. It is a cascade: cheap, high-recall stages
first; expensive neural stages on a bounded candidate set; results delivered
progressively.

Every numeric value in this document is an **initial value for benchmarking**,
not a final default. Final defaults live in `RankingConfig` and change only with
a benchmark report.

## 1. Definitions

| Term | Meaning |
|---|---|
| Passage | Contiguous span of extracted text with source offsets and a locator (page/slide/sheet/line) |
| Document | One indexed file; one or more passages |
| Candidate set | Passages/documents produced by first-stage retrievers |
| Retriever | Filename/path, lexical (BM25), dense, and (gated) learned-sparse first-stage search |
| Reranker | Multilingual cross-encoder scoring `(query, passage)` pairs |
| Aggregation | Function mapping passage evidence to a document score |
| Near-duplicate | Substantially redundant document/passage (copies, versions, boilerplate) |
| Snippet engine | Query-aware extractive selection of original sentences for display (the search-engine "pruner") |

## 2. Pipeline

```text
query
  │
  ├─ 0. Query analysis & routing (no LLM)
  │      normalize · language ID · quoted phrases · identifiers · filename-like ·
  │      inline filters (ext:, in:, date) · query class → stage budget
  │
  ├─ 1. Candidate generation (parallel)
  │      filename/path ─┐
  │      lexical BM25 ──┼─► fusion (RRF baseline) ─► passage candidates
  │      dense ANN/flat ┘            │
  │      [learned sparse: gated]     ▼
  │                         ═══ Stage "Instant" emitted after filename+lexical ═══
  │
  ├─ 2. Document layer
  │      group by document · per-document candidate cap · aggregation ·
  │      exact/near-duplicate collapsing · length-bias correction
  │                         ═══ Stage "Hybrid" emitted ═══
  │
  ├─ 3. Refinement (bounded, adaptive)
  │      cross-encoder on best passages of top documents ·
  │      document re-aggregation · diversity (MMR) · final per-document limits
  │
  └─ 4. Presentation
         extractive snippets + highlights for visible results · locators
                            ═══ Stage "Refined" emitted ═══
```

## 3. Query analysis and routing

Deterministic, sub-millisecond, multilingual:

- Unicode normalization; case folding and diacritic folding for lexical keys
  (the original query is kept for dense/reranker input).
- Quoted phrases → exact phrase constraints; must be preserved through every
  stage (exact-match candidates are never dropped by neural stages).
- **Identifier detection** (UUIDs, hashes, codes, version strings, e-mail-like
  tokens, paths) → lexical/filename emphasis, dense optional.
- **Filename-like detection** (extensions, path separators, camel/snake case) →
  filename retriever emphasis.
- Inline filters: `ext:pdf`, `in:<folder>`, date expressions (pt/en) → metadata
  pre-filters pushed into every retriever (filtering after retrieval destroys
  recall).
- Query class (navigational / identifier / conceptual / mixed) sets the stage
  budget: navigational queries may stop after the Instant or Hybrid stage;
  conceptual queries get the full reranking budget.

Routing rules are evaluated per query category in the benchmark program; a rule
that hurts any category beyond tolerance is removed.

## 4. Candidate generation

| Retriever | Unit | Initial depth | Notes |
|---|---|---:|---|
| Filename/path | document | 40 | Prefix/substring/fuzzy over names and path segments; instant |
| Lexical BM25 | passage | 200 | Language-aware analyzers (stemming for pt/en is benchmark-gated); phrase support |
| Dense | passage | 200 | Quantized first pass + rescoring if selected; metadata pre-filtering |
| Learned sparse (gated) | passage | 200 | Inference-free document-side models only if they beat BM25 at equal latency |

### 4.1 Fusion

- **Baseline:** RRF, `k = 60`, equal weights ([ADR-0003](../adr/0003-hybrid-retrieval-rrf.md)).
- **Challengers:** weighted RRF; convex combination of normalized scores
  (min-max/z-score per retriever, tuned on the dev split); query-class-specific
  weights.
- Per-retriever ranks are kept for diagnostics and result tags.

## 5. Document layer

### 5.1 Grouping and candidate caps

- Group passage candidates by document.
- Candidate-stage cap: at most **8** passages per document enter later stages,
  preventing long documents from monopolizing the budget.

### 5.2 Document-level aggregation

Document retrieval is a first-class stage, not a side effect of sorting chunks.

Signals per document:

| Signal | Definition |
|---|---|
| `p_max` | Best passage score |
| `p_topk` | Mean of the top-k passage scores (k ∈ {2, 3}) |
| `coverage` | Fraction of query terms/aspects matched across the document's passages |
| `title` | Filename/path relevance |
| `consensus` | Number of independent retrievers that surfaced the document |
| `length_prior` | Correction term for document length (see §5.4) |

Initial form (normalized components, weights tuned on the dev split):

```text
doc_score = w_max·p_max + w_topk·p_topk + w_cov·coverage
          + w_title·title + w_cons·consensus + w_len·length_prior
```

`w_max` protects a single highly relevant passage (needle in a haystack);
`w_topk` prevents a one-passage fluke from dominating. Few parameters on purpose:
the golden set is small and overfitting is the main risk. Ablations decide which
signals stay.

### 5.3 Near-duplicate collapsing

- Exact: content hash (BLAKE3) — collapse immediately.
- Near-duplicate documents: SimHash (64-bit over word shingles) computed at
  index time; Hamming threshold tuned; optional MinHash-LSH clusters.
- Near-duplicate passages: passage hash + embedding cosine threshold.
- Boilerplate: passages whose hash appears in many documents are down-weighted.
- Canonical selection by score, then freshness, then path quality; alternates
  remain reachable through a duplicate-cluster indicator.
- False-collapse guard: documents with small but meaningful differences (two
  contract versions) must not merge; thresholds are tuned on labeled pairs.

### 5.4 Length-bias correction

- BM25 keeps its length normalization; `k1` and `b` are tuned per analyzer.
- Dense: very short passages (titles, fragments) produce spuriously high
  cosines → minimum-length handling and length-bucket calibration.
- Cross-encoder: score calibration by passage length bucket.
- Document level: `length_prior` so long files do not win by having more
  chances to match.
- Evaluated on length-stratified queries; reported as its own ablation.

## 6. Refinement

### 6.1 Cascaded, adaptive reranking

- Rerank the **best 1–2 passages of the top N documents** (initial N = 30;
  depth is a benchmark knob), not all passages.
- Passage input truncated to a tuned token budget (initial 192 tokens) — the
  cost driver on CPU.
- Adaptive budget by query class and observed latency; skip for confident
  navigational/identifier queries (exact filename hit with a strong margin).
- Score caching per `(query, passage-hash)` for incremental typing.
- **Fail open:** reranker absent, slow, or failing → keep the Hybrid ordering.
- Optionally offloaded to the NPU when validated.

### 6.2 Re-aggregation and diversity

- Recompute document scores with reranked passage evidence (same aggregation
  contract).
- Cross-document diversity with MMR over document vectors (mean of passage
  vectors):
  `MMR(d) = λ·rel(d) − (1−λ)·max_sim(d, selected)`, initial `λ = 0.8`.
  Diversity never promotes an irrelevant document to fill a quota.
- Final per-document passage limit: **3** shown passages, and only when they
  cover different aspects.

## 7. Presentation: query-aware extractive snippets

The file-search equivalent of a pruner selects original text for a human; it
never compresses, summarizes, or rewrites.

- Sentence segmentation (Unicode rules, multilingual).
- Candidate sentences scored by lexical overlap plus semantic similarity
  (reusing the embedder or, if a bake-off proves it worth the cost, a small
  scorer model) — only for **visible** results.
- Readable windows (initial 200–320 characters), original boundaries, exact
  term highlights, best-sentence highlight for semantic-only matches.
- Locators let the shell open the file at the page/line when the OS app
  supports it.
- Evaluated with snippet evidence-hit rate and span F1 on annotated passages.

## 8. Progressive delivery and latency

| Stage | Includes | Budget source |
|---|---|---|
| Instant | Analysis, filename, lexical, grouping | P1 in methodology |
| Hybrid | + dense, fusion, document layer | P2 |
| Refined | + reranking, diversity, snippets | P3 |

Performance techniques required by design: resident models; query embedding in
parallel with lexical/filename retrieval; LRU cache of query embeddings; bounded
candidate sets; cancellation between stages; reranking and snippet extraction
only for visible results; memory-mapped indexes.

## 9. Configuration

All knobs live in one versioned `RankingConfig` with defaults owned by benchmark
reports:

| Parameter | Initial value |
|---|---:|
| Filename depth | 40 |
| Lexical depth | 200 |
| Dense depth | 200 |
| RRF `k` | 60 |
| Passages per document entering refinement | 8 |
| Documents reranked (N) | 30 |
| Passages reranked per document | 1–2 |
| Reranker passage token budget | 192 |
| MMR `λ` | 0.8 |
| Passages shown per document | 3 |
| SimHash Hamming threshold | tuned |
| Passage duplicate cosine threshold | tuned per model |

## 10. Invariants (property-tested)

1. Quoted exact matches present in the corpus appear in results.
2. No document appears twice in a result list; cluster alternates are hidden.
3. Each stage's output is a re-ordering/subset of its input plus documented
   additions; stages never invent documents.
4. Disabling any optional stage yields the previous stage's ordering
   (fail-open).
5. Metadata filters are honored by every stage.
6. Results are deterministic for a fixed index, config, and query.

## 11. Module plan (`crates/seeky-search`)

| Module | Responsibility |
|---|---|
| `query/` | Normalization, classification, filter parsing, routing |
| `retrieve/` | Filename, lexical, dense, (sparse) adapters over `seeky-store` traits |
| `fuse.rs` | RRF and challengers |
| `document/` | Grouping, aggregation, dedupe, length correction |
| `rerank.rs` | Cross-encoder orchestration, budgets, caching, fail-open |
| `diversity.rs` | MMR, final limits |
| `snippet/` | Sentence segmentation, scoring, highlighting, locators |
| `pipeline.rs` | Stage orchestration, progressive emission, cancellation |
| `config.rs` | `RankingConfig` and defaults |

The PoC's `search.rs` is refactored into this structure behind golden tests
before any new stage is added.
