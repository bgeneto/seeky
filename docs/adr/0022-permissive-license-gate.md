# ADR-0022 — Permissive-license gate for code, models, and data

- **Status:** Accepted
- **Date:** 2026-11-27

## Decision

Anything shipped in the app or published to the asset bucket must be
redistributable under terms compatible with an MIT application:

- **Allowed:** MIT, Apache-2.0, BSD-2/3, ISC, Zlib, Unicode-3.0, MPL-2.0 (file-level
  copyleft, unmodified), CC0, CC-BY-4.0 (with attribution).
- **Review required:** model-specific licenses with use policies (for example
  Gemma Terms), OpenRAIL variants, models trained on non-commercial data.
- **Forbidden in shipped artifacts:** GPL, AGPL, LGPL static linking,
  CC-BY-NC/ND/SA for models, "research only", unclear or missing licenses.

Evaluation datasets may carry research-only terms if they are downloaded by
scripts for internal benchmarking and never redistributed in this repository.

## Consequences

- `cargo-deny` (licenses, advisories, bans) runs in CI.
- [`../benchmarks/candidates.md`](../benchmarks/candidates.md) records license
  status per candidate; an ineligible model is excluded regardless of quality.
- Each provisioned asset carries license and notice files in the manifest.
