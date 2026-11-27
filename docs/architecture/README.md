# Architecture

Target architecture of the Seeky engine and desktop shell. These documents are
contracts: specs refine them, code implements them, and benchmark reports set
their numeric defaults. The as-built PoC is described in
[`../../apps/seeky/README.md`](../../apps/seeky/README.md).

| Document | Governs |
|---|---|
| [`overview.md`](overview.md) | Engine-first workspace, crate boundaries, engine API, concurrency, storage layout, shell contract |
| [`indexing.md`](indexing.md) | Discovery, watcher, reconcile, extraction, chunking, two-speed indexing, embedding cache, index generations |
| [`retrieval-engine.md`](retrieval-engine.md) | Query analysis, candidate generation, fusion, document layer, reranking, diversity, snippets, progressive stages |
| [`inference-and-models.md`](inference-and-models.md) | ONNX Runtime, execution providers (CPU-first, NPU-ready), model manifest, lifecycle, quantization |
| [`distribution-and-provisioning.md`](distribution-and-provisioning.md) | Slim installer, R2 assets, manifest, verification, offline use, updates |

Decisions behind these documents are in [`../adr/`](../adr/README.md).
