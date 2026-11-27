# ADR-0002 — SQLite + FTS5 as the only storage engine

- **Status:** Superseded by [ADR-0020](0020-pluggable-index-backends.md)
- **Date:** 2026-11-26

## Decision (historical)

Store roots, documents, chunks, FTS5 indexes, and f32 embedding BLOBs in one
SQLite database; exact cosine over all vectors; no external vector database.

## Why superseded

Performance-first and 1M-passage scale require the lexical and vector index
engines to be chosen by benchmark (FTS5 vs Tantivy; flat quantized scan vs HNSW
vs sqlite-vec). SQLite remains the metadata source of truth and the "no external
database server" rule stands; the index engines move behind traits.
