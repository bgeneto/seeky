-- Minimal local RAG schema for SQLite 3.40+ (FTS5 required).
-- This is the recommended schema, not a copy of Gety's multi-connector schema.
-- Run with: sqlite3 data/index/app.db < sql/minimal_rag_schema.sql

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- ---------------------------------------------------------------------------
-- Schema version
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
  version    INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Indexed roots (folders or drive roots)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS roots (
  id           TEXT PRIMARY KEY,
  path         TEXT NOT NULL UNIQUE,
  display_name TEXT,
  enabled      INTEGER NOT NULL DEFAULT 1,
  created_at   TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Documents
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
  id            TEXT PRIMARY KEY,
  root_id       TEXT NOT NULL REFERENCES roots(id) ON DELETE CASCADE,
  rel_path      TEXT NOT NULL,
  abs_path      TEXT NOT NULL,
  title         TEXT NOT NULL,
  ext           TEXT,
  mime          TEXT,
  doc_type      TEXT,
  size_bytes    INTEGER,
  mtime_ns      INTEGER,
  content_hash  BLOB,
  status        TEXT NOT NULL DEFAULT 'pending',  -- pending|extracting|extracted|embedded|failed
  error         TEXT,
  page_count    INTEGER,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  indexed_at    TEXT,
  UNIQUE(root_id, rel_path)
);

CREATE INDEX IF NOT EXISTS idx_documents_root    ON documents(root_id);
CREATE INDEX IF NOT EXISTS idx_documents_status  ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_ext     ON documents(ext);
CREATE INDEX IF NOT EXISTS idx_documents_updated ON documents(updated_at);

-- ---------------------------------------------------------------------------
-- Layout blocks (pages, text regions, table cells)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS blocks (
  id         INTEGER PRIMARY KEY,
  doc_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  ordinal    INTEGER NOT NULL,
  kind       TEXT NOT NULL,               -- paragraph|heading|table|cell|image|page
  page       INTEGER,
  bbox       TEXT,                        -- JSON [x0,y0,x1,y1]
  text       TEXT,
  byte_start INTEGER,
  byte_end   INTEGER,
  sheet      INTEGER,
  row        INTEGER,
  col        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_blocks_doc_page ON blocks(doc_id, page, ordinal);

-- ---------------------------------------------------------------------------
-- Retrieval chunks
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
  id           INTEGER PRIMARY KEY,
  doc_id       TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  ordinal      INTEGER NOT NULL,
  text         TEXT NOT NULL,
  token_count  INTEGER NOT NULL,
  page_start   INTEGER,
  page_end     INTEGER,
  block_start  INTEGER,
  block_end    INTEGER,
  byte_start   INTEGER,
  byte_end     INTEGER,
  content_hash BLOB,
  created_at   TEXT NOT NULL,
  UNIQUE(doc_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

-- External-content FTS5: text is stored once in chunks; the FTS table indexes it.
-- The triggers keep FTS in sync with chunks.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text,
  content='chunks',
  content_rowid='id',
  tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE OF text ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;

-- ---------------------------------------------------------------------------
-- Embedding model registry
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS embedding_models (
  id             TEXT PRIMARY KEY,       -- e.g. gety-embed-v0, qwen3-embedding-0.6b
  dim            INTEGER NOT NULL,
  normalized     INTEGER NOT NULL DEFAULT 1,
  query_prefix   TEXT,
  passage_prefix TEXT,
  max_tokens     INTEGER,
  created_at     TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Vectors (source of truth; ANN tables are disposable)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunk_embeddings (
  chunk_id   INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
  model_id   TEXT NOT NULL REFERENCES embedding_models(id),
  dim        INTEGER NOT NULL,
  dtype      TEXT NOT NULL DEFAULT 'f32',  -- f32 | i8
  vector     BLOB NOT NULL,
  norm       REAL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_model
  ON chunk_embeddings(model_id, dim);

-- ---------------------------------------------------------------------------
-- Durable indexing tasks
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS index_tasks (
  id         INTEGER PRIMARY KEY,
  doc_id     TEXT REFERENCES documents(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL,               -- extract|chunk|embed|delete
  priority   INTEGER NOT NULL DEFAULT 0,
  state      TEXT NOT NULL DEFAULT 'pending', -- pending|running|done|failed
  attempts   INTEGER NOT NULL DEFAULT 0,
  run_after  TEXT,
  error      TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(doc_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_tasks_state
  ON index_tasks(state, priority, run_after);

-- ---------------------------------------------------------------------------
-- Settings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT OR IGNORE INTO settings(key, value) VALUES
  ('schema_version', '1'),
  ('active_embedding_model', 'gety-embed-v0');

INSERT OR IGNORE INTO embedding_models
  (id, dim, normalized, query_prefix, passage_prefix, max_tokens, created_at)
VALUES
  ('gety-embed-v0', 384, 1, '', '', 512, datetime('now'));

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES (1, datetime('now'));
