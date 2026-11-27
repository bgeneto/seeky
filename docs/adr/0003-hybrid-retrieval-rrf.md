# ADR-0003 — Hybrid retrieval with filename/path signal and RRF

- **Status:** Accepted (baseline fusion; alternatives are benchmarked per [ADR-0017](0017-spec-and-benchmark-driven-development.md))
- **Date:** 2026-11-26

## Context

BM25 handles exact phrases, identifiers, and rare terms; dense retrieval handles
meaning and paraphrase; filename/path matching handles file-oriented queries.
Gety fuses BM25 and cosine with fixed raw-score weights (`0.2 * bm25 + 0.8 *
cosine`), which is brittle because the scales are incomparable.

## Decision

Fuse lexical, dense, and filename/path rankings with Reciprocal Rank Fusion
(`k = 60`) as the **baseline**. RRF stays the default until a benchmarked
alternative (weighted RRF, normalized convex combination, query-type-aware
weights) wins on the evaluation protocol without a latency regression.

## Consequences

- Fused scores are relative, not calibrated probabilities.
- Every fusion change requires an ablation report.
- Fixed raw-score weighting is not used.
