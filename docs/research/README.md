# Research

These documents are reverse-engineering research notes about the installed Gety
application and the retrieval ideas that informed Seeky. They are not the active
build contract and may contain illustrative snippets in languages or runtimes
that Seeky does not use.

The active implementation is Rust + Tauri + TypeScript. See
[`../plans/seeky-implementation-plan.md`](../plans/seeky-implementation-plan.md).

| Document | Topic |
|---|---|
| [`gety-verified-architecture.md`](gety-verified-architecture.md) | Verified Gety stack, processes, storage, search, APIs |
| [`data-model-and-storage.md`](data-model-and-storage.md) | SQLite schema, vectors, storage tradeoffs |
| [`models-and-inference.md`](models-and-inference.md) | Gety models, ONNX/OpenVINO formats, model strategy |
| [`retrieval-ranking-and-reranking.md`](retrieval-ranking-and-reranking.md) | BM25, dense retrieval, fusion, reranking, evaluation |
| [`glossary.md`](glossary.md) | Retrieval and inference terminology |
