# ADR-0018 — Lexical-first availability before model provisioning

- **Status:** Accepted
- **Date:** 2026-11-27
- **Amends:** ADR-0011 failure mode

## Context

The earlier product decision blocked search until provisioning completed.
Instant search is a core promise, and filename + full-text search needs no
neural model. Initial semantic indexing on CPU is also far slower than lexical
indexing, so a model-gated product would feel broken for its first minutes or
hours on large folders.

## Decision

- Filename/path and lexical (BM25) search work immediately after install,
  offline, with no model download. Tier-0 extraction dependencies needed for
  this (for example PDFium) ship in the installer if they fit the installer
  budget.
- Semantic retrieval, reranking, and OCR activate per stage as verified assets
  become available, and as background embedding coverage grows.
- The UI states plainly which capabilities are active and the semantic coverage
  per folder. The engine never substitutes a different or incompatible model
  silently.

## Consequences

- Indexing is two-speed: lexical within seconds, semantic in the background
  (see [`../architecture/indexing.md`](../architecture/indexing.md)).
- Search results carry stage/capability flags.
- The provisioning screen is not a blocking wall.
