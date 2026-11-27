# Seeky Architecture

Design documents for the target product architecture. The current as-built code
is described in [`apps/seeky/README.md`](../../apps/seeky/README.md); these
documents define the target and the gaps to close.

| Document | Purpose |
|---|---|
| [`retrieval-engine.md`](retrieval-engine.md) | SOTA hierarchical retrieval, aggregation, diversity, deduplication, length correction |
| [`model-strategy.md`](model-strategy.md) | Multilingual model candidates, backend policy, evaluation gates |
| [`distribution-and-provisioning.md`](distribution-and-provisioning.md) | Slim first-run downloads from Cloudflare R2, checksums, offline behavior |
