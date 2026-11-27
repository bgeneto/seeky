# 02 — Verification of `gety-technical-report.html`

This document checks the attached independent report against the installed
Gety artifacts using REA 6.10.1 + Ghidra 12.2, local SQLite/schema inspection,
WebView2 cache inspection, runtime logs, and local model files.

**Verdict in one sentence:** the report is directionally correct about Gety
being a local retrieval system with a 384-d E5-family encoder, but it is
**wrong or outdated** on four material points — the desktop stack, BM25,
vector storage/ANN, and rank fusion. It is **right** that no reranker or
neural pruner is present.

---

## 1. Scoring summary

| # | Report claim | Verdict | What the artifacts show |
|---:|---|---|---|
| 1 | Gety is a retrieval system, not a generative assistant | **Confirmed** | No LLM/chat model shipped; MCP/REST/CLI return documents/snippets. Only embedding + OCR models are installed. |
| 2 | Embedding is 384-dimensional, 512 tokens | **Confirmed** | `config.json`: hidden 384, 12 layers, 12 heads, max positions 512, vocab 250,037; ONNX output `sentence_embedding`. |
| 3 | `gety-embed-v0` is fine-tuned from `multilingual-e5-small`, ~118M params, MIT | **Base/license confirmed by model card; ~118M consistent with config** | Public HF card states the base and MIT license; installed `BertModel` (384/12/12, 250k vocab) is consistent with the ~118M e5-small family. Exact parameter count/training provenance is not proven by the binary alone. |
| 4 | CPU UINT8 ONNX ≈112 MB, CUDA FP16 ≈224 MB, CoreML/OpenVINO exports exist | **Confirmed** | Installed CPU file 118,130,759 B (112.6 MiB), CUDA file 235,074,703 B (224.2 MiB); binary strings contain CoreML/OpenVINO variants and NPU OCR variants. |
| 5 | Desktop UI may be Tauri/WebView2 but exact framework not established | **Corrected** | Tauri **2.9.5**, `wry 0.53.5`, `tao 0.34.5`, Rust `gety-client`/`gety-core`, React **19.1.0** frontend in the 0.6.3 WebView2 cache. |
| 6 | Backend language/framework not established | **Corrected** | Rust; `gety-client` and `gety-core` module paths and Rust panic metadata throughout `Gety.exe`. |
| 7 | Storage engine/schema/index structures undisclosed | **Corrected** | SQLite (`rusqlite` + `r2d2`), WAL, FTS5, dynamic per-connector tables, `chunks` embedding BLOBs; schema read from the live DB. |
| 8 | Lexical + semantic search; exact scoring formula undisclosed | **Partially corrected** | Hybrid is confirmed; exact SQL is `0.2 * -bm25() + 0.8 * (semantic score)`. |
| 9 | BM25/TF-IDF not confirmed | **Corrected** | BM25 is confirmed: SQLite FTS5 `bm25()` plus custom `bm25_v2` and `min_interval_rank`; Chinese `jieba` and pinyin support. |
| 10 | Rank fusion/RRF not disclosed | **Corrected** | Fixed weighted score fusion (0.2/0.8). **No RRF** evidence. |
| 11 | Cross-encoder reranker: no verified model/implementation | **Confirmed** | No reranker model, crate, or string; only `gety-embed-v0` and `gety-ocr-v0` are installed. |
| 12 | Neural context pruner: no verified model | **Confirmed** | No pruner model. “Q4 pruning” is an embedding-index maintenance task, not context pruning. Snippets are block/highlight heuristics. |
| 13 | ANN/HNSW/vector DB not disclosed | **Corrected** | No ANN/vector DB. SQLite BLOB + `cosine_sim_f32`/`cosine_sim_i8` UDFs + `rarray` ID lists; exact cosine over candidate chunks. |
| 14 | Passage extraction confirmed; segmentation undisclosed | **Confirmed and extended** | `blocks` table stores page, bbox, block type, byte offsets, text, source, content hash; `chunks` stores byte/char offsets. Spreadsheet cell anchors map UTF-16 ranges to sheet/row/column. |
| 15 | MCP endpoint `http://127.0.0.1:31226/mcp`, Bearer, tools Search/GetDoc/ListConnectors | **Confirmed with scope note** | Runtime log shows `127.0.0.1:31226`; `rmcp` uses Streamable HTTP + Bearer; `search`/`get_document` are observed tool literals. Connector listing and file retrieval exist in the API/UI surface; exact MCP names for those were not fully recovered. |
| 16 | REST routes and search schema | **Confirmed** | `/api/v1/search`, `/api/v1/connectors`, `/api/v1/connectors/{id}/docs/{doc_id}`, `.../file`; request fields as documented, with internal names such as `semantic_search`/`no_semantic_search`. |
| 17 | Connectors can be installed from npm/GitHub/local, with permission review | **Confirmed for 0.7.0** | New modules `catalog`, `github`, `npm`, `package`, `versions`, `changelog`, `consent`, `permissions`; UI strings for permission fingerprints, added permissions, review, downgrade/version switch. |
| 18 | Free/Pro quotas, unlimited Pro | **Plausible; not billing-verified** | `daily_usage`, `quota` module, quota commands and UI strings exist. Licensing/plan enforcement was not exercised. |
| 19 | “Results as fast as 0.01 seconds” | **Unverified product claim** | No benchmark was run. The inspected DB is 2.26 GB / ~1M chunks; latency depends on mode and hardware. |
| 20 | “Index is not intended to be transplanted to another machine” | **Unverified** | No migration experiment; the DB is machine-local and path-dependent, but portability was not tested. |
| 21 | “Encryption at rest, enterprise identity, audit guarantees not verified” | **Confirmed as unverified; some local encryption exists** | Credentials use AES-GCM (`AesEncrypted` nonce/ciphertext); OCR weights are encrypted; the SQLite DB itself is not encrypted. No enterprise identity/audit evidence. |
| 22 | No public application-core repository | **Not established** | Binary paths reference private `gety-private` and `gety-client` checkouts. No public core repository was confirmed in this review. |
| 23 | Three desktop OS families (Windows/macOS/Linux) | **Public claim; only Windows inspected** | Windows x64 behavior verified locally. macOS CoreML and Linux WebKitGTK paths exist in code/strings but were not executed here. |
| 24 | Supported formats: text/markdown/HTML, PDF, Word/WPS, Excel, PowerPoint, images | **Confirmed** | File-type registry/extractor modules and the Local Files screenshot show Text, Markdown, PDF, Word, PowerPoint, Excel, HTML, WPS, Image, each with OCR/Semantic toggles. |
| 25 | Progressive indexing (title → text → OCR → semantic) | **Confirmed** | `extraction_status` values (`pending`, `fast_complete`, `awaiting_deep`, `full_complete`, `failed`), two task queues, and the UI status popover (Fast search / Content search / AI indexing / OCR / Semantic). |
| 26 | Storage lifecycle, data-directory migration, offline asset packages | **Confirmed** | Settings/data-migration modules, `data_migration/executor`, offline export/import UI, and the screenshot showing per-component sizes. |

---

## 2. Detailed corrections

### 2.1 Desktop stack — it is Tauri + Rust + React, not “unknown”

Evidence:

- `tauri 2.9.5`, `tauri-runtime-wry 2.9.3`, `wry 0.53.5`, `tao 0.34.5` appear
  in the Rust crate paths embedded in `Gety.exe`.
- Tauri plugins: autostart 2.5.1, clipboard-manager 2.3.2, deep-link 2.4.6,
  dialog 2.6.0, drag 2.1.1, global-shortcut 2.3.1, opener 2.5.3, os 2.3.2,
  shell 2.3.4, single-instance 2.3.7, updater 2.9.0, window-state 2.4.1.
- Rust source paths: `gety-client/src-tauri/src/**` and
  `gety-core/src/**`.
- WebView2 cache code contains React internals (`__REACT_DEVTOOLS_GLOBAL_HOOK__`,
  `Minified React error`, `react-dom`, `useEffectEvent`, `react.transitional.element`),
  React Router (`__reactRouterVersion`, `navigate()` warning), i18next, Radix,
  `cmdk`, `sonner`, `virtua`, PostHog, Sentry.
- The cache reports React `19.1.0`.

The report's note that WebView2/WebKitGTK dependencies are “compatible with a
Tauri-based application” is correct but understated; the binary contains the
Tauri crates and generated IPC code directly.

### 2.2 BM25 is present and is a core part of the hybrid score

Recovered SQL:

```sql
(0.2 * -bm25() + 0.8 * (?, ?, ?)) AS total_score
```

Additional lexical machinery:

- `FullTextIndexingStrategy_1` / `_2` are FTS5 contentless tables
  (`content=''`, `contentless_delete=1`, `tokenize='simple'`).
- `sqlite/fts5/bm25.rs`, `bm25_v2.rs`, `min_interval_rank.rs`.
- `jieba-rs` for Chinese segmentation, custom pinyin search/matcher,
  NFKC normalization.

The report said BM25 was “not confirmed.” It is confirmed, with a custom
ranking layer rather than vanilla SQLite BM25 alone.

### 2.3 No vector database — SQLite is the vector store

The definitive storage path:

```
chunks.embedding BLOB
  + embedding_version (f32/i8 representation)
  + embedding_status (pending/ready)
  → SQLite scalar function cosine_sim_f32 / cosine_sim_i8
  → ORDER BY cosine_similarity DESC
```

`rarray(?)` expands candidate ID arrays for `WHERE rowid IN rarray(?)` and
`doc_iid IN rarray(?)`. It is an array helper, not an ANN index.

No `sqlite-vec`, `sqlite-vss`, `usearch`, `hnsw`, `faiss`, `annoy`, `qdrant`,
`lancedb`, or `duckdb` appears in the 0.7.0 crate inventory or binary strings.

The `semantic/q4_embedding_index.rs` module is a separate **in-memory q4**
embedding index (likely 4-bit; exact packing not recovered) used for
pruning/shrinking. The strings “failed to join the
Q4 pruning task” and “failed to join the Q4 shrink task” refer to that
structure, not to context pruning or ANN persistence.

**Implication for the report:** replace “ANN/HNSW/vector DB not disclosed” with
“no ANN/vector DB; exact cosine over SQLite BLOBs.” This is a stronger and more
useful finding.

### 2.4 Fusion is weighted linear, not RRF

The score is a fixed linear combination:

```
score = 0.2 * lexical_bm25 + 0.8 * semantic_similarity
```

(the lexical term is written as `-bm25()` because SQLite FTS5 returns a negative
BM25 score). There is no reciprocal-rank term, no rank-based normalization, and
no RRF implementation in the binary.

For the new app, RRF is still a reasonable design choice because it is robust to
score-scale differences, but it must be presented as an improvement, not a
reproduction of Gety.

### 2.5 No reranker, no neural pruner

- No `rerank`, `cross-encoder`, `bge-reranker`, or `Qwen3` strings.
- No reranker model files in the installed model directory.
- Only `gety-embed-v0` and `gety-ocr-v0` are present.
- Snippets are built from `blocks` and match offsets; there is no evidence of a
  learned passage-pruning model.

The report's caution is confirmed. This is the main quality gap the new app can
close.

---

## 3. What the report got right

- **Retrieval, not generation.** Gety exposes search results and document
  content; answer synthesis is left to the connected AI tool.
- **384-d, 512-token embedding.** Confirmed by config and ONNX I/O.
- **E5-small lineage and MIT license.** Confirmed by the public model card;
  the installed architecture is consistent.
- **Hardware acceleration story.** CUDA, OpenVINO NPU, CoreML and CPU exports
  are real code paths; the inspected Windows machine used
  `[OrtCuda, OrtOpenVino, OrtCpu]`.
- **No reranker/pruner/ANN proof.** Correctly cautious.
- **MCP/REST/CLI contract.** Endpoint, Bearer auth, tools and routes broadly
  match.
- **Privacy caveat.** Local index does not mean local downstream AI; the
  REST/MCP layer can return snippets or full file bytes.
- **Connector permission complexity.** 0.7.0 adds review/consent and version
  switching; the report's warning about community connector permissions is
  appropriate.
- **Earlier model artifacts.** The report mentions
  `granite-embedding-107m-multilingual-onnx` as an earlier artifact. It is not
  installed in this machine's model directory; only `gety-embed-v0` and
  `gety-ocr-v0` are present. Current production use of Granite is not
  established.

---

## 4. Claims that remain unverified (in the report and here)

- Exact FTS5 tokenizer/BM25 constants and weights beyond the observed SQL.
- Exact query/document prefixes for `gety-embed-v0` in production.
- Chunk size/overlap and token budget constants.
- Semantic score normalization and missing-modality behavior.
- `gety-service` RPC method names/IOCTL codes.
- OCR architecture and language coverage (weights encrypted).
- 0.7.0 frontend runtime behavior (the 0.7.0 bundle was not loaded/cached).
- Actual search latency/recall/nDCG on the inspected 2.26 GB corpus.
- Billing/quota enforcement and multi-device licensing.
- Network traffic/privacy audit.

---

## 5. Recommended edits to the HTML report

If the report is republished, update these sections:

1. **04 Architecture:** replace “exact frontend framework/backend language not
   established” with Tauri 2.9.5, Rust, React 19.1, WebView2, Axum, SQLite.
2. **06 Ranking:** move BM25 from “not confirmed” to “confirmed”; replace
   “rank fusion/RRF not disclosed” with “weighted linear 0.2 BM25 + 0.8
   semantic; no RRF.”
3. **06 Vector storage:** replace “ANN/HNSW/vector DB not disclosed” with
   “SQLite BLOB + exact cosine UDF; q4 in-memory index; no ANN.”
4. **06 Reranker/pruner:** keep “no verified implementation,” but state that
   this was checked against the installed 0.7.0 build and no model/crate/string
   exists.
5. **04/09:** add the actual schema distinction: per-connector
   `index_*`/`blocks_*`/`spreadsheet_cell_anchors_*`, FTS5, `chunks`.
6. **08 MCP:** add `get_file` and the exact `/api/v1` REST routes.
7. **12 Privacy:** mention that credentials use AES-GCM and OCR weights are
   encrypted, but the SQLite index itself is not encrypted.
8. **14 Evidence gaps:** remove “binary inspection not performed” and replace
   with the specific REA/Ghidra evidence and remaining unknowns.

---

## 6. Evidence key

| Evidence | ID / source |
|---|---|
| 0.7.0 service Ghidra overview (11,291 procedures, 1,496 strings) | `ev_99c7f992239035052c01733d647417a1dd07be214ee36bfefb3e4b9cc5a7213f` |
| 0.7.0 service entry decompilation | `ev_7984f440462c662d6200ad1d51705d39339c74c9262f684fce948b0a292bb2e3` |
| 0.7.0 `NtDeviceIoControlFile` xrefs | `ev_1a896c9bbce7661a48da7ae9dee34d979e9c5208f4d21158ed24697a75976051` |
| 0.7.0 containing function / device-I/O call | `ev_6ad57d7b1bf004d7deec2a0f4c8a9d271e776f0ffbe613076986275e07839880` |
| 0.6.3 service overview / entry chain | `ev_71533714f009cc0511e93b48628c48197d63016cdf83b36c8f1a6fc057848855`, `ev_eead68849a7971e5a4ec57928cacabb282ada07667d992115b78fac74d65e2f7`, `ev_259e884459f02be9258969b6526aea60db9d35e1380edb437f36adfe95d8972a`, `ev_84a3d62931b1f06529f0c537919e239352290583a97569645aa4a619ba896d61`, `ev_dda40401aeda3cdcaf852085a872c3fcc21dedcc7d15a0b204239b6ba607455b` |
| DB schema/counts | Local read-only SQLite inspection of `gety_data_v1.db` (no REA evidence record; commands and counts in `04` and `08`). |
| Frontend stack | WebView2 `Code Cache\js` strings, 0.6.3; hashed asset keys in 0.7.0 `Gety.exe`. |
| Model card | `https://huggingface.co/gety-ai/gety-embed-v0` |
| Qwen3 model cards | `https://huggingface.co/Qwen/Qwen3-Embedding-0.6B`, `https://huggingface.co/Qwen/Qwen3-Reranker-0.6B` |

See [`evidence-ledger.md`](evidence-ledger.md) for full paths, hashes,
timestamps, and limitations.
