# ADR-0011 — Slim first-run provisioning from Cloudflare R2

- **Status:** Accepted (amended by [ADR-0018](0018-lexical-first-availability.md))
- **Date:** 2026-11-26

## Decision

Ship a small installer. Download inference runtimes, model weights, tokenizers,
and optional asset packs (for example OCR) on first run from the public `seeky`
Cloudflare R2 bucket, selected per platform/hardware by a signed manifest.
Verify SHA-256 and signatures, install atomically into a versioned cache, run
offline afterward.

ADR-0018 amends the failure mode: lexical and filename search work before and
without provisioning; semantic features activate once verified assets exist.

## Consequences

- Provisioning UI, manifest schema, resumable downloads, repair, offline
  import, and rollback are required.
- R2 availability and asset licensing become release-critical.
- The Gety dependency and the bundled OpenVINO IR are removed.

Contract: [`../architecture/distribution-and-provisioning.md`](../architecture/distribution-and-provisioning.md).
