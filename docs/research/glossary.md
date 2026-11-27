> **Research note.** This is reverse-engineering context, not the active build contract. Code snippets are illustrative; Seeky is implemented in Rust/Tauri/TypeScript. See the [implementation plan](../plans/seeky-implementation-plan.md).

# 11 — Glossary

Terms used across the docs.

| Term | Meaning |
|---|---|
| **BM25** | A lexical ranking function based on term frequency, inverse document frequency, and document length. SQLite FTS5 exposes `bm25()`. |
| **FTS5** | SQLite's full-text search extension; supports virtual tables, tokenizers, and ranking functions. |
| **Bi-encoder** | An embedding model that encodes query and passage independently; fast, used for candidate retrieval. |
| **Cross-encoder / reranker** | A model that reads a query–passage pair jointly and outputs a relevance score; slower but more accurate, used on a small candidate set. |
| **Pruner** | A stage that removes irrelevant passages or shrinks context before generation. Gety has no learned pruner; the minimal app starts with heuristics. |
| **RRF** | Reciprocal Rank Fusion: combines ranked lists using `Σ w/(k+rank)`, independent of raw score scales. |
| **Weighted score fusion** | Combining raw scores with fixed weights (Gety: 0.2 BM25 + 0.8 semantic). Requires comparable scales. |
| **ANN** | Approximate nearest neighbor search (e.g. HNSW, IVF); trades recall for speed at scale. |
| **HNSW** | A graph-based ANN index. Not used by Gety. |
| **Exact cosine** | Computing cosine similarity against every candidate vector; deterministic, no recall loss. Gety's SQLite path. |
| **q4** | A compact embedding representation used by Gety's in-memory index; likely 4-bit, exact packing not recovered. |
| **f32 / i8** | 32-bit float / 8-bit integer vector storage. Gety migrates embeddings from f32 to i8. |
| **MRL** | Matryoshka Representation Learning: an embedding model that supports truncated dimensions (e.g. Qwen3 32–1024). |
| **Chunk** | A passage of a document used for retrieval; typically 200–800 tokens with overlap. |
| **Embedding** | A dense vector representation of text. |
| **RAG** | Retrieval-Augmented Generation: retrieve passages, then generate an answer grounded in them. |
| **Context window** | The maximum tokens an LLM can process; context building must fit sources + question + answer. |
| **MCP** | Model Context Protocol; a JSON-RPC interface for AI tools to call search/document tools. |
| **SSE** | Server-Sent Events; a streaming HTTP response format used for answer tokens. |
| **WAL** | SQLite write-ahead logging; allows concurrent readers with one writer. |
| **Per-connector sharding** | Gety's design of creating physical `index_*`/`blocks_*` tables per connector/index. The minimal app uses one table with `root_id`. |
| **OCR** | Optical Character Recognition; text extraction from images/scans. |
| **Contentless FTS5** | FTS5 table that stores only the index (`content=''`), not the original text. Gety uses this. |
| **External-content FTS5** | FTS5 table that reads text from a content table (`content='chunks'`); the minimal app uses this with triggers. |
