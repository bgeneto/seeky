# Gety reverse-engineering research

Clean-room notes about the installed Gety application (a proprietary desktop
search app). They document observed interfaces, schemas, and algorithms so that
Seeky can be designed independently. They are **context, not contracts**:
several recommendations here (Python snippets, "minimal app" designs, model
suggestions) were written before Seeky's architecture was decided and are
superseded by [`../../architecture/`](../../architecture/README.md) and the
[benchmark program](../../benchmarks/README.md).

Do not copy Gety source, decompiled code, binaries, or private weights; see
[`../../../NOTICE.md`](../../../NOTICE.md).

| Document | Topic |
|---|---|
| [`verified-architecture.md`](verified-architecture.md) | Verified Gety stack, processes, storage, search, interfaces |
| [`data-model-and-storage.md`](data-model-and-storage.md) | Gety SQLite schema, vector storage, scale estimates |
| [`models-and-inference.md`](models-and-inference.md) | `gety-embed-v0`, encrypted OCR weights, ONNX/OpenVINO notes |
| [`retrieval-ranking-and-reranking.md`](retrieval-ranking-and-reranking.md) | Gety's weighted fusion vs RRF; reranking and pruning notes |
| [`technical-report-verification.md`](technical-report-verification.md) | Claim-by-claim review of a supplied Gety technical report |
| [`evidence-ledger.md`](evidence-ledger.md) | Evidence IDs, hashes, commands, limitations |
| [`sources/gety-technical-report.html`](sources/gety-technical-report.html) | The supplied report, preserved as source material |
| [`sql/gety-schema-reference.sql`](sql/gety-schema-reference.sql) | Representative observed Gety schema (comparison only) |
| [`local-model-paths.example.json`](local-model-paths.example.json) | Gety model/runtime layout used by the PoC (machine-local example) |

Key verified facts that shaped Seeky: Gety is Tauri + Rust + React; it stores
vectors in SQLite and searches them exactly; it fuses BM25 and cosine with fixed
weights; it has no reranker and no learned pruner.
