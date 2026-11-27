# Glossary

| Term | Meaning in Seeky |
|---|---|
| **Seeky Desktop Corpus (SDC)** | Seeky's own evaluation corpus of realistic multi-format, multilingual folders with graded judgments; `sdc-smoke`, `sdc-s`, `sdc-m` scales |
| **BmDD** | Benchmark-Driven Development: changes declare gates first and land with reproducible reports (never "Behavior-Driven Development" here) |
| **SDD** | Spec-Driven Development: work starts from an Accepted spec with EARS requirements |
| **EARS** | Easy Approach to Requirements Syntax ("When …, the engine shall …") |
| **Bake-off** | Reproducible comparison of candidates under the methodology, ending in an ADR |
| **Bake-off funnel** | Stage 0 paper screen → Stage A quality screen in the reference runtime → Stage B deployment bake-off → Stage C confirmation on `test` |
| **ORT validation gate** | Priority-zero measurement (plan WP-0.6) that keeps ADR-0019 falsifiable: one model per role on ONNX Runtime, checked against kill criteria K1–K4 |
| **Kill criterion** | A predeclared measurable condition that, if met, reopens a decision (for example K1: a role misses its budget on ONNX Runtime) |
| **Transcription model** | An OCR model that only transcribes visible text with deterministic decoding and a fixed prompt (ADR-0021); may be encoder-decoder or VLM-based |
| **OCR hallucination rate** | Share of OCR output words not present on the page, plus text emitted for pages without text; a hard OCR gate |
| **Tier T0/T1/T2** | Hardware tiers: floor laptop, reference laptop (budgets defined here, CPU-only), workstation (iteration only) |
| **Budget** | A locked numeric target (P*, I*, R*, D*, O*) such as Hybrid-stage p95 latency |
| **Passage** | Contiguous span of extracted text with offsets and a locator; the retrieval unit (a.k.a. chunk) |
| **Document** | One indexed file; the presentation unit |
| **Locator** | Where a passage lives: page, slide, sheet/row/column, or line |
| **Two-speed indexing** | Fast lane (metadata, filename, lexical) within seconds; semantic lane (embeddings) in the background |
| **Semantic coverage** | Fraction of a root's passages that have embeddings in the active generation |
| **Index generation** | All derived indexes built with one recipe (embedding model + revision + dimension + tokenizer + chunker); swapped blue/green |
| **Embedding input recipe** | Exactly what text is embedded for a passage (heading path + passage text; never the filename) |
| **Embedding cache** | Content-addressed store `hash(recipe output) → vector`, so copies, renames, and unchanged passages are never re-embedded |
| **Reconcile** | Startup/resume comparison of the filesystem with stored signatures to catch offline changes |
| **Instant / Hybrid / Refined** | Progressive search stages: filename+lexical; + dense, fusion, document layer; + reranking, diversity, snippets |
| **Query routing** | Deterministic classification of a query (navigational, identifier, conceptual, mixed) that sets its stage budget |
| **BM25** | Lexical ranking with term-frequency saturation and length normalization |
| **Dense retrieval** | Search by embedding similarity (bi-encoder) |
| **Learned sparse retrieval** | Neural term weighting stored in an inverted index (SPLADE-style); gated in Seeky |
| **RRF** | Reciprocal Rank Fusion: `Σ w / (k + rank)`; Seeky's baseline fusion |
| **Convex combination fusion** | Weighted sum of normalized retriever scores; a fusion challenger |
| **Cross-encoder / reranker** | Model reading `(query, passage)` jointly; accurate but expensive; used on a bounded set |
| **Document aggregation** | Turning passage evidence into a document score (max, top-k mean, coverage, title, consensus, length prior) |
| **Near-duplicate collapsing** | Grouping copies/versions/boilerplate so one canonical result appears |
| **MMR** | Maximal Marginal Relevance: diversity-aware selection |
| **Length-bias correction** | Calibrations so long or very short texts do not win unfairly |
| **Snippet engine** | Query-aware extractive selection of original sentences for display — the search-engine "pruner"; never rewrites text |
| **Matryoshka (MRL)** | Embeddings that remain useful when truncated to fewer dimensions |
| **Binary / int8 quantization** | 1-bit or 8-bit vector storage; usually followed by rescoring |
| **ANN / HNSW** | Approximate nearest-neighbor search / graph-based ANN index |
| **Execution provider (EP)** | ONNX Runtime backend for a device (CPU, OpenVINO, QNN, VitisAI, CoreML) |
| **Deployment variant** | A model as it would ship: ONNX variant + precision + execution provider on ONNX Runtime; the unit compared in Stage B of a bake-off (other engines only when pricing an alternative) |
| **Parity vectors** | Reference inputs/outputs used to verify an exported or accelerated model |
| **Model manifest** | Machine-readable description of a model's I/O, tokenizer, prompts, variants, license, and hashes |
| **Provisioning** | First-run/background download and verification of runtimes and models from the `seeky` R2 bucket |
| **Lexical-first availability** | Filename and lexical search work before any model is provisioned |
| **FTS5** | SQLite full-text search extension (as-built lexical index) |
| **WAL** | SQLite write-ahead logging: many readers, one writer |
| **RAG** | Retrieval-Augmented Generation; Seeky is retrieval only, not RAG |
