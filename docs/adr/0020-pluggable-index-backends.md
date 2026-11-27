# ADR-0020 — Pluggable lexical/vector index backends; SQLite as metadata source of truth

- **Status:** Accepted
- **Date:** 2026-11-27
- **Supersedes:** ADR-0002

## Context

Performance-first at 1M passages on CPU needs the best lexical and vector index
engines for a desktop workload: small frequent writes, frequent deletes, fast
cold start, low RAM, metadata pre-filtering, and stable latency during
continuous indexing. The right choice is an empirical question.

## Decision

- **SQLite (WAL)** is the source of truth for roots, files, passages, signatures,
  jobs, index generations, models, and settings. All derived indexes can be
  rebuilt from it plus the embedding cache.
- **Lexical index** behind a `LexicalIndex` trait. Baseline: SQLite FTS5 (as
  built). Challenger: Tantivy. Chosen by bake-off.
- **Filename/path index** behind its own trait, optimized for instant
  prefix/substring/fuzzy matching.
- **Vector index** behind a `VectorIndex` trait. Baseline: exact f32 scan (as
  built). Challengers: flat memory-mapped int8/binary scans with rescoring,
  USearch HNSW, sqlite-vec. Chosen by bake-off; ANN only if exact/flat scans
  miss budget at target scale.
- No external database server, ever.

## Consequences

- Index backends are swappable without touching ranking code.
- Each choice is recorded in its own ADR with a benchmark report.
- Crash consistency between SQLite and external index files is a spec-level
  requirement (generation markers, idempotent rebuild).
