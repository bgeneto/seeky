# Seeky Scope

See [`seeky-product-decisions.md`](seeky-product-decisions.md) for the current
product decisions and [`seeky-scope-pt-br.md`](seeky-scope-pt-br.md) for the
original Portuguese scope source.

## Product

Seeky is a **Local Neural Information Retrieval Engine** and **Semantic Desktop
Search Engine** for local files. It is optimized around retrieval quality,
latency, indexing speed, and computational efficiency.

## In scope

- Local filesystem indexing only.
- Hybrid retrieval: lexical, filename/path, dense semantic, fusion, reranking.
- Multilingual document content and multilingual query understanding.
- Passage-level ranking and document-level result aggregation.
- Hierarchical document → passage retrieval.
- Per-document candidate limits, cross-document diversity, near-duplicate
  detection, and length-bias correction.
- Semantic snippets and direct preview of extracted text.
- Incremental local indexing and live filesystem watching.
- Embedded vector storage; no external vector server.
- CPU, CUDA, AMD, and NPU acceleration where available.
- Two UI themes (light/dark, OS default).
- English and Portuguese UI, with OS-locale detection and English fallback.
- Slim first-run provisioning of runtimes, models, and native libraries from the
  seeky Cloudflare R2 bucket; fully offline after provisioning.
- Open-source MIT source code with no account or commercial license key.

## Out of scope

- Cloud sync, accounts, multiuser support, and license enforcement.
- MCP server, public REST API, public CLI, connector SDK, or marketplace.
- External connectors and third-party data sources.
- AI-client integrations, API-key management, and LAN access.
- Chat, generative answers, agent runtimes, and conversational history.
- Plugin ecosystem and theme marketplace.
- A settings-heavy dashboard or AI-style decorative UI.

## Quality priorities

1. Retrieval quality and multilingual recall.
2. Search latency and responsiveness during indexing.
3. Indexing throughput and incremental update latency.
4. CPU/GPU/NPU efficiency and memory use.
5. Minimal, predictable desktop UX.

Model and pipeline choices are benchmark-gated; no model is declared SOTA
without evidence on the project evaluation corpus.
