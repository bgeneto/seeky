# ADR-0005 — Incremental watcher with per-file indexing

- **Status:** Accepted (extended by [`../architecture/indexing.md`](../architecture/indexing.md))
- **Date:** 2026-11-26

## Decision

One recursive `notify` watcher per enabled root; debounce (600 ms in the PoC,
tunable); deduplicate by path; index changed files individually; skip unchanged
files by size + nanosecond-mtime signature; persist per-root pause/resume.

## Consequences

- Behavior depends on OS event delivery; directory creates/renames need subtree
  scans.
- The watcher cannot see edits made while Seeky is closed. The indexing
  architecture adds a mandatory **startup reconcile** (parallel stat walk, with
  OS change journals as a benchmark-gated accelerator), so a manual Reindex is
  no longer the recovery path.
