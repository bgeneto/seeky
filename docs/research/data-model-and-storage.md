> **Research note.** This is reverse-engineering context, not the active build contract. Code snippets are illustrative; Seeky is implemented in Rust/Tauri/TypeScript. See the [implementation plan](../plans/seeky-implementation-plan.md).

# 04 — Data Model and Storage

This document covers two things:

1. **Gety's actual storage model**, as observed in `gety_data_v1.db`.
2. **The recommended minimal schema** for the new app, including the vector
   storage decision.

---

## 1. Gety's database at a glance

| Property | Observed value |
|---|---|
| Engine | SQLite via `rusqlite` + `r2d2_sqlite` |
| File | `%APPDATA%\ai.gety\data\database\gety_data_v1.db` |
| Size at inspection | 2,262,179,840 bytes (2.26 GB) |
| Page size | 4,096 bytes |
| Page count | 552,306 |
| Journal mode | WAL |
| Encoding | UTF-8 |
| Auto-vacuum | off |
| `user_version` | 0 (Gety uses its own `migrations` table) |
| Migration rows | 15 |

The database is encrypted? **No.** Only credentials and OCR model weights are
encrypted. The SQLite file is plaintext on disk.

---

## 2. Gety table families

### 2.1 Connector metadata

`connectors` stores one row per source:

```sql
CREATE TABLE connectors (
  iid INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  version INTEGER,
  type TEXT,
  name TEXT NOT NULL UNIQUE,
  config TEXT,
  auth TEXT,
  index_meta TEXT,
  runtime_config TEXT,
  last_state TEXT,
  last_update_time TEXT,
  description TEXT,
  fs_connector_config TEXT,
  connector_settings TEXT
);
```

`last_state` is the connector's resumable poll checkpoint. `auth` may contain
encrypted credentials (`AesEncrypted` nonce/ciphertext), not plaintext.

### 2.2 Per-connector index tables

Gety creates physical tables per connector/index instance:

```
index_idx_<connector_key>          documents + metadata + content
blocks_idx_<connector_key>         layout blocks (pages, bbox, byte offsets)
spreadsheet_cell_anchors_idx_*     cell-level citations
FullTextIndexingStrategy_<n>       FTS5 virtual table
```

The suffix is an internal numeric index ID (`idx_folder_2`, `idx_ntfs_1`), not
the connector name. This design isolates connector data and makes
drop/rebuild cheap, at the cost of many tables and dynamic SQL.

`index_*` columns:

```
iid, id, parent_id, title, metadata, doc_updated_at, hide_from_search,
doc_type, original_file_size, extraction_status, content_format, content
```

`blocks_*` columns:

```
id, doc_iid, parent_block_id, page_num, block_type, bytes_offset,
bytes_length, bbox, original_id, text, source, content_hash
```

`spreadsheet_cell_anchors_*` columns:

```
id, doc_iid, content_utf16_start, content_utf16_end,
sheet_index, row_index, column_index
```

The block/offset model is what powers previews, highlights, and cell-level
citations. It is a better design than storing only flat text and is worth
copying in simplified form.

### 2.3 FTS5

Observed DDL:

```sql
CREATE VIRTUAL TABLE "FullTextIndexingStrategy_1" USING fts5(
  "content",
  content='',
  contentless_delete=1,
  tokenize='simple'
);
```

Notes:

- Contentless: the FTS table stores only the index, not the text.
- `contentless_delete=1` allows deletion without rebuilding.
- `tokenize='simple'` is SQLite's simple tokenizer; Gety layers custom BM25
  (`bm25`, `bm25_v2`, `min_interval_rank`) and Unicode/pinyin handling on top.
- Two FTS tables existed (`_1`, `_2`), one per active index.

### 2.4 Semantic chunks

```sql
CREATE TABLE chunks (
  chunk_id INTEGER PRIMARY KEY,
  index_iid INTEGER NOT NULL,
  doc_iid INTEGER NOT NULL,
  field_iid INTEGER NOT NULL,
  start_offset_bytes INTEGER NOT NULL,
  end_offset_bytes INTEGER NOT NULL,
  chunk_char_len INTEGER NOT NULL,
  embedding BLOB,
  embedding_version INTEGER,
  embedding_status INTEGER NOT NULL DEFAULT 0,
  chunk_idx INTEGER NOT NULL DEFAULT 0
);
```

Indexes:

```
(chunk_id) primary
(index_iid, doc_iid)
(index_iid, field_iid, doc_iid)
(embedding_status, chunk_idx, field_iid)
(index_iid, doc_iid) WHERE embedding_status = 0
```

`field_iid` identifies which indexed field the chunk belongs to (title/content
or connector-defined extra fields). `start_offset_bytes`/`end_offset_bytes`
map back to the document content for highlighting.

### 2.5 Task queues

```sql
CREATE TABLE task_queue_content (
  task_key TEXT,
  polled INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0,
  deferred INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE task_queue_deep_extraction (
  task_key TEXT,
  polled INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0,
  deferred INTEGER NOT NULL DEFAULT 0
);
```

These are simple, durable queues with priority and polling state. A minimal app
can use one `index_tasks` table with a `kind` column.

### 2.6 Usage, events, migrations

- `daily_usage(feature_type, usage_date, usage_count)` for quotas.
- `events(id, source, action, actor, payload, duration_ms, success, error_info, created_at)`
  for local activity/telemetry.
- `migrations(id, table_name, version, name, applied_at)` for schema versioning.
- `full_text_index_backfills(fts_table, target_version, cursor_iid, end_iid)`
  for resumable FTS backfills.
- `pinned_folder_filters` for UI shortcuts.

---

## 3. How Gety stores and searches vectors

### 3.1 Storage

`chunks.embedding` is a BLOB. The representation depends on
`embedding_version`:

- **f32** — 4 bytes/dimension; 384-d = 1,536 bytes/chunk.
- **i8** — 1 byte/dimension (quantized); 384-d = 384 bytes/chunk.
- A migration string shows the transition:
  `Starting migration to quantize embeddings from f32 to i8`.

The binary checks `blob size not divisible by 4` for f32 and exposes
`cosine_sim_f32` and `cosine_sim_i8` SQL functions. That is the full persistent
vector store.

### 3.2 Search

```sql
SELECT chunk_id, index_iid, doc_iid, field_iid,
       start_offset_bytes, end_offset_bytes,
       cosine_sim(embedding, ?) AS cosine_similarity
FROM chunks
WHERE embedding_status = 1
  AND embedding_version = ?
  AND (...)
ORDER BY cosine_similarity DESC
LIMIT ?;
```

Candidate ID filters use `rarray(?)`:

```sql
WHERE rowid IN rarray(?)
```

`rarray` is an array-expansion helper registered on the connection; it is not
an ANN index. The query is exhaustive over the filtered candidate set.

### 3.3 Q4 in-memory index

`semantic/q4_embedding_index.rs` builds a `q4` in-memory index for
faster pruning/shrinking (likely 4-bit; exact packing was not recovered).
Strings include:

- `embedding blob len < Q4_DIMS`
- `failed to join the Q4 pruning task`
- `failed to join the Q4 shrink task`

This is an in-process optimization; it is not the database format and not a
vector database. Do not describe it as “the vector DB.”

### 3.4 Why this works for Gety

- A desktop corpus is usually hundreds of thousands, not billions, of chunks.
- Filters (`index_iid`, `doc_iid`, date, type) reduce the candidate set before
  cosine.
- Native SQLite UDFs avoid per-row Python overhead.
- The q4 index reduces memory for hot candidates.

It will not scale to tens of millions of chunks without ANN. That is a design
boundary, not a flaw for the intended product.

---

## 4. Recommended minimal schema

The full DDL is in [`sql/minimal-schema.sql`](../../sql/minimal-schema.sql).
The rationale follows.

### 4.1 Design choices

| Choice | Decision |
|---|---|
| One `documents` table, no per-connector sharding | Simpler for a single-user local app; use `root_id` filters. |
| `blocks` table | Preserve layout/citations; optional but recommended. |
| `chunks` + external-content FTS5 | Stores text once; triggers keep the index in sync. Gety itself uses contentless FTS5. |
| Separate `chunk_embeddings` table | Keeps embedding metadata/model versions isolated; can move to an ANN table later. |
| `embedding_models` registry | Prevents mixing 384-d and 1024-d vectors; supports migration. |
| `index_tasks` table | Durable extraction/embedding queue. |
| `settings` key/value | Simple config; no accounts. |
| WAL + `busy_timeout` | Single-writer desktop workload. |

### 4.2 Tables

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE roots (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  display_name TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE documents (
  id TEXT PRIMARY KEY,
  root_id TEXT NOT NULL REFERENCES roots(id) ON DELETE CASCADE,
  rel_path TEXT NOT NULL,
  abs_path TEXT NOT NULL,
  title TEXT NOT NULL,
  ext TEXT,
  mime TEXT,
  doc_type TEXT,
  size_bytes INTEGER,
  mtime_ns INTEGER,
  content_hash BLOB,
  status TEXT NOT NULL DEFAULT 'pending',
  error TEXT,
  page_count INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  indexed_at TEXT,
  UNIQUE(root_id, rel_path)
);

CREATE INDEX idx_documents_root ON documents(root_id);
CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_documents_ext ON documents(ext);
CREATE INDEX idx_documents_updated ON documents(updated_at);

CREATE TABLE blocks (
  id INTEGER PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  kind TEXT NOT NULL,
  page INTEGER,
  bbox TEXT,             -- JSON [x0,y0,x1,y1]
  text TEXT,
  byte_start INTEGER,
  byte_end INTEGER,
  sheet INTEGER,
  row INTEGER,
  col INTEGER
);

CREATE INDEX idx_blocks_doc_page ON blocks(doc_id, page, ordinal);

CREATE TABLE chunks (
  id INTEGER PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  text TEXT NOT NULL,
  token_count INTEGER NOT NULL,
  page_start INTEGER,
  page_end INTEGER,
  block_start INTEGER,
  block_end INTEGER,
  byte_start INTEGER,
  byte_end INTEGER,
  content_hash BLOB,
  created_at TEXT NOT NULL,
  UNIQUE(doc_id, ordinal)
);

CREATE INDEX idx_chunks_doc ON chunks(doc_id);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  text,
  content='chunks',
  content_rowid='id',
  tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text)
    VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER chunks_au AFTER UPDATE OF text ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text)
    VALUES ('delete', old.id, old.text);
  INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
```

External-content FTS5 stores the indexed terms, while the original text stays
in `chunks`. The triggers are mandatory: without them, inserts/deletes/updates
will desynchronize the index. Do not also insert into `chunks_fts` manually.

### 4.3 Embedding registry and vectors

```sql
CREATE TABLE embedding_models (
  id TEXT PRIMARY KEY,            -- e.g. gety-embed-v0
  dim INTEGER NOT NULL,
  normalized INTEGER NOT NULL DEFAULT 1,
  query_prefix TEXT,
  passage_prefix TEXT,
  max_tokens INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE chunk_embeddings (
  chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
  model_id TEXT NOT NULL REFERENCES embedding_models(id),
  dim INTEGER NOT NULL,
  dtype TEXT NOT NULL DEFAULT 'f32',   -- f32 | i8
  vector BLOB NOT NULL,
  norm REAL,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_chunk_embeddings_model ON chunk_embeddings(model_id, dim);
```

Why a separate table:

- You can keep old and new model vectors side by side during migration.
- You can drop/re-embed without touching `chunks`.
- The ANN table can reference `chunk_id` without duplicating text.
- The query planner can filter by `model_id` and `dim`.

### 4.4 Tasks and settings

```sql
CREATE TABLE index_tasks (
  id INTEGER PRIMARY KEY,
  doc_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,               -- extract | chunk | embed | delete
  priority INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  run_after TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(doc_id, kind)
);

CREATE INDEX idx_tasks_state ON index_tasks(state, priority, run_after);

CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

### 4.5 Optional ANN table (sqlite-vec)

If you adopt `sqlite-vec`, keep SQLite as the source of truth:

```sql
-- Requires the sqlite-vec extension to be loaded.
CREATE VIRTUAL TABLE chunk_vec USING vec0(
  chunk_id INTEGER PRIMARY KEY,
  embedding FLOAT[384]
);
```

Insert/update from `chunk_embeddings`. Rebuild the ANN table if the model or
dimension changes. For 1024-d Qwen3, use `FLOAT[1024]` or a truncated MRL
dimension (e.g. `FLOAT[512]`) consistently.

> `vec0` syntax varies by sqlite-vec version. Check the installed extension's
> documentation before committing DDL. The SQLite tables above are the stable
> source of truth; the ANN table is disposable.

---

## 5. Query patterns

### 5.1 BM25

```sql
SELECT c.id, c.doc_id, bm25(chunks_fts) AS bm25_score
FROM chunks_fts
JOIN chunks c ON c.id = chunks_fts.rowid
JOIN documents d ON d.id = c.doc_id
WHERE chunks_fts MATCH ?
  AND d.root_id IN (...)
ORDER BY bm25_score
LIMIT ?;
```

- `bm25()` returns a negative score in SQLite; lower is better.
- Quote user input as an FTS5 string; support phrases with `"..."`.
- Avoid `MATCH *` on untrusted input; validate/escape.

### 5.2 Dense (exact, Python/NumPy)

```python
rows = conn.execute("""
  SELECT e.chunk_id, e.vector
  FROM chunk_embeddings e
  JOIN chunks c ON c.id = e.chunk_id
  JOIN documents d ON d.id = c.doc_id
  WHERE e.model_id = ? AND e.dim = ?
    AND d.root_id IN (...)
""", (model_id, dim)).fetchall()

ids = [r[0] for r in rows]
mat = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(-1, dim)
scores = mat @ query_vec
top = np.argpartition(-scores, k)[:k]
```

- This is fast for ≤100k vectors; cache the matrix if the corpus is static.
- For i8, dequantize or use an i8 dot product with scale.
- For 1M+ vectors, use `sqlite-vec`/HNSW.

### 5.3 RRF

```python
def rrf(bm25_ids, dense_ids, k=60):
    scores = {}
    for rank, cid in enumerate(bm25_ids, 1):
        scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank)
    for rank, cid in enumerate(dense_ids, 1):
        scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: -x[1])
```

### 5.4 Filters

Push filters into both retrievers:

- `root_id` / folder path
- extension / MIME / doc_type
- `updated_at` range
- `hidden`/system flags

Do not retrieve globally then filter in Python; you will lose recall and waste
latency.

---

## 6. Storage and scale estimates

Assumptions: 100k documents, 1M chunks, average 700 characters/chunk, 384-d
embeddings.

| Component | Size |
|---|---:|
| Chunk text (UTF-8) | ~700 MB |
| FTS5 index | ~300–500 MB |
| f32 embeddings (1,536 B/chunk) | ~1.5 GB |
| i8 embeddings (384 B/chunk) | ~384 MB |
| Blocks/metadata | ~300–600 MB |
| **Total f32** | **~3–4 GB** |
| **Total i8** | **~2–2.5 GB** |

For Qwen3-Embedding-0.6B at 1024-d:

| Representation | Per chunk | 1M chunks |
|---|---:|---:|
| f32 | 4,096 B | ~4.1 GB |
| i8 | 1,024 B | ~1.0 GB |
| MRL 512-d f32 | 2,048 B | ~2.0 GB |

This is why model dimension and quantization are product decisions, not just
ML details.

---

## 7. Transactions and concurrency

- One writer, many readers: WAL is sufficient.
- Per-document transaction: delete old blocks/chunks/FTS rows, insert new ones,
  update document status. This prevents half-indexed docs.
- Batch embeddings outside the document transaction; commit vectors in batches
  and mark `embedded` atomically per chunk.
- Use `busy_timeout=5000` and retry on `SQLITE_BUSY`.
- Never hold a write transaction while calling a model; compute first, then
  write a short transaction.
- On startup, reset `state='running'` tasks to `pending` (crash recovery).
- Keep `schema_migrations`; apply migrations in order; backup before a
  destructive migration.

---

## 8. Backup, migration, and portability

- The DB is portable at the file level only when the app is stopped and WAL is
  checkpointed. Use `VACUUM INTO` or SQLite's backup API for a consistent copy.
- Paths in `documents` are absolute; moving the data root requires a path
  rewrite or reindex.
- Embeddings are model-specific; store `model_id`/`dim` and never mix models in
  one query.
- For a model change, build a new `chunk_embeddings` set, evaluate, then switch
  the active model in `settings`; keep the old set until rollback is no longer
  needed.

---

## 9. Gety vs minimal schema

| Concern | Gety | Minimal |
|---|---|---|
| Sharding | per-connector physical tables | one table + `root_id` |
| FTS | contentless FTS5 per index | one external-content FTS5 |
| Vectors | `chunks.embedding` BLOB + f32/i8 UDF | `chunk_embeddings` BLOB + NumPy/sqlite-vec |
| Layout | `blocks_*` + spreadsheet anchors | `blocks` + optional cell columns |
| Queues | two task queues | one `index_tasks` |
| Usage/quota | `daily_usage`/`events` | omit or add later |
| Connectors | connector metadata + per-connector tables | `roots` only |

The minimal model keeps the parts that matter for retrieval quality
(blocks, chunks, FTS, vectors) and drops the multi-tenant connector machinery.
