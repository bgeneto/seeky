# ADR-0013 — SOTA multilingual hierarchical retrieval

- **Status:** Accepted
- **Date:** 2026-11-26

## Context

Chunk-only ranking does not represent document relevance: one long file can
monopolize results, duplicates crowd out distinct sources, and length biases
distort BM25, dense, and cross-encoder scores. User content is multilingual.

## Decision

The retrieval engine implements, as explicit stages with tests and ablations:
passage-level ranking, document-level score aggregation, hierarchical
document → passage retrieval, per-document candidate limits, cross-document
diversity, near-duplicate detection/collapsing, and length-bias correction —
using multilingual, benchmark-selected models.

## Consequences

- Ranking is split into individually testable stages behind one configuration.
- The evaluation corpus includes multiple languages, duplicates, and
  length-stratified documents.
- A mechanism that fails its ablation gate ships **disabled by configuration**;
  the stage contract stays so it can be re-evaluated.

Contract: [`../architecture/retrieval-engine.md`](../architecture/retrieval-engine.md).
