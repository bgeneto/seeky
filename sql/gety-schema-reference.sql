-- Reference: the SQLite schema observed in Gety 0.6.3's live database.
-- This file is for study/comparison only. It is not the minimal app schema.
-- It may not execute on stock SQLite because Gety's build registers a custom
-- FTS5 "simple" tokenizer; use it as documentation, not as a migration.
-- Table names with _folder_2 / _ntfs_1 are per-connector physical tables;
-- Gety creates a new set for each connector/index instance.
--
-- Source: read-only inspection of
--   C:\Users\bernh\AppData\Roaming\ai.gety\data\database\gety_data_v1.db
-- No user rows/content are included.

-- ---------------------------------------------------------------------------
-- Connector registry
-- ---------------------------------------------------------------------------
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
  last_state TEXT NULL,
  last_update_time TEXT NULL,
  description TEXT NULL,
  fs_connector_config TEXT NULL,
  connector_settings TEXT NULL
);

-- ---------------------------------------------------------------------------
-- Per-connector document tables
-- footprint: index_idx_folder_2, index_idx_ntfs_1, ...
-- ---------------------------------------------------------------------------
CREATE TABLE "index_idx_folder_2" (
  iid INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  parent_id TEXT,
  title TEXT NOT NULL,
  metadata TEXT,
  doc_updated_at TEXT NOT NULL,
  hide_from_search BOOLEAN DEFAULT FALSE,
  doc_type TEXT NOT NULL DEFAULT 'other',
  original_file_size INTEGER,
  extraction_status TEXT,
  content_format TEXT NOT NULL DEFAULT 'plaintext',
  content TEXT
);

CREATE INDEX idx_index_idx_folder_2_extraction_pending
  ON index_idx_folder_2(extraction_status)
  WHERE extraction_status IN ('pending', 'awaiting_deep');
CREATE INDEX idx_index_idx_folder_2_hide_from_search
  ON index_idx_folder_2(hide_from_search);
CREATE INDEX idx_index_idx_folder_2_id ON index_idx_folder_2(id);
CREATE INDEX idx_index_idx_folder_2_parent_id ON index_idx_folder_2(parent_id);
CREATE INDEX idx_index_idx_folder_2_title ON index_idx_folder_2(title);

-- ---------------------------------------------------------------------------
-- Per-connector layout blocks
-- footprint: blocks_idx_folder_2, blocks_idx_ntfs_1, ...
-- ---------------------------------------------------------------------------
CREATE TABLE blocks_idx_folder_2 (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_iid INTEGER NOT NULL,
  parent_block_id INTEGER,
  page_num INTEGER,
  block_type TEXT NOT NULL,
  bytes_offset INTEGER NOT NULL,
  bytes_length INTEGER NOT NULL,
  bbox TEXT,
  original_id TEXT,
  text TEXT,
  source TEXT,
  content_hash BLOB,
  FOREIGN KEY (doc_iid) REFERENCES index_idx_folder_2(iid) ON DELETE CASCADE
);

CREATE INDEX idx_blocks_idx_folder_2_content_hash
  ON blocks_idx_folder_2(content_hash)
  WHERE content_hash IS NOT NULL;
CREATE INDEX idx_blocks_idx_folder_2_doc ON blocks_idx_folder_2(doc_iid);
CREATE INDEX idx_blocks_idx_folder_2_page ON blocks_idx_folder_2(doc_iid, page_num);
CREATE INDEX idx_blocks_idx_folder_2_parent ON blocks_idx_folder_2(parent_block_id);

-- ---------------------------------------------------------------------------
-- Per-connector spreadsheet cell anchors
-- footprint: spreadsheet_cell_anchors_idx_folder_2, ...
-- ---------------------------------------------------------------------------
CREATE TABLE spreadsheet_cell_anchors_idx_folder_2 (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_iid INTEGER NOT NULL,
  content_utf16_start INTEGER NOT NULL,
  content_utf16_end INTEGER NOT NULL,
  sheet_index INTEGER NOT NULL,
  row_index INTEGER NOT NULL,
  column_index INTEGER NOT NULL,
  FOREIGN KEY (doc_iid) REFERENCES index_idx_folder_2(iid) ON DELETE CASCADE
);

CREATE INDEX idx_spreadsheet_cell_anchors_idx_folder_2_cell_position
  ON spreadsheet_cell_anchors_idx_folder_2(doc_iid, sheet_index, row_index, column_index);
CREATE INDEX idx_spreadsheet_cell_anchors_idx_folder_2_doc_range
  ON spreadsheet_cell_anchors_idx_folder_2(doc_iid, content_utf16_start, content_utf16_end);

-- ---------------------------------------------------------------------------
-- Semantic chunks (all indexes share this table; index_iid/doc_iid point at
-- the per-connector index table)
-- ---------------------------------------------------------------------------
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

CREATE INDEX idx_chunks_index_doc ON chunks(index_iid, doc_iid);
CREATE INDEX idx_chunks_index_field_doc ON chunks(index_iid, field_iid, doc_iid);
CREATE INDEX idx_chunks_pending_chunks ON chunks(embedding_status, chunk_idx, field_iid);
CREATE INDEX idx_chunks_pending_docs ON chunks(index_iid, doc_iid)
  WHERE embedding_status = 0;

-- ---------------------------------------------------------------------------
-- FTS5 (contentless)
-- footprint: FullTextIndexingStrategy_1, FullTextIndexingStrategy_2, ...
-- ---------------------------------------------------------------------------
CREATE VIRTUAL TABLE "FullTextIndexingStrategy_1" USING fts5(
  "content",
  content='',
  contentless_delete=1,
  tokenize='simple'
);

-- Companion shadow tables created by FTS5:
-- FullTextIndexingStrategy_1_config(k PRIMARY KEY, v) WITHOUT ROWID
-- FullTextIndexingStrategy_1_data(id INTEGER PRIMARY KEY, block BLOB)
-- FullTextIndexingStrategy_1_docsize(id INTEGER PRIMARY KEY, sz BLOB, origin INTEGER)
-- FullTextIndexingStrategy_1_idx(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID

-- ---------------------------------------------------------------------------
-- Durable queues
-- ---------------------------------------------------------------------------
CREATE TABLE task_queue_content (
  task_key TEXT,
  polled INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0,
  deferred INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_task_queue_content_polled ON task_queue_content(polled);
CREATE INDEX idx_task_queue_content_polled_priority ON task_queue_content(polled, priority);
CREATE INDEX idx_content_task_key_polled ON task_queue_content(task_key, polled);

CREATE TABLE task_queue_deep_extraction (
  task_key TEXT,
  polled INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0,
  deferred INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_task_queue_deep_extraction_polled ON task_queue_deep_extraction(polled);
CREATE INDEX idx_task_queue_deep_extraction_polled_priority
  ON task_queue_deep_extraction(polled, priority);
CREATE INDEX idx_deep_extraction_task_key_polled
  ON task_queue_deep_extraction(task_key, polled);

-- ---------------------------------------------------------------------------
-- FTS backfill cursor
-- ---------------------------------------------------------------------------
CREATE TABLE full_text_index_backfills (
  fts_table TEXT PRIMARY KEY,
  target_version INTEGER NOT NULL,
  cursor_iid INTEGER NOT NULL,
  end_iid INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- Pinned folder filters
-- ---------------------------------------------------------------------------
CREATE TABLE pinned_folder_filters (
  connector_id TEXT NOT NULL,
  path TEXT NOT NULL,
  label TEXT NOT NULL,
  position INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (connector_id, path)
);

-- ---------------------------------------------------------------------------
-- Usage, events, migrations
-- ---------------------------------------------------------------------------
CREATE TABLE daily_usage (
  feature_type TEXT NOT NULL,
  usage_date TEXT NOT NULL,
  usage_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (feature_type, usage_date)
) WITHOUT ROWID;

CREATE INDEX idx_usage_date ON daily_usage(usage_date);
CREATE INDEX idx_usage_month ON daily_usage(feature_type, substr(usage_date, 1, 7));

CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  action TEXT NOT NULL,
  actor TEXT,
  payload TEXT DEFAULT '{}',
  duration_ms INTEGER,
  success INTEGER NOT NULL DEFAULT 1,
  error_info TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_events_action_source ON events(action, source);
CREATE INDEX idx_events_created ON events(created_at);
CREATE INDEX idx_events_source ON events(source);

CREATE TABLE migrations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  table_name TEXT NOT NULL UNIQUE,
  version INTEGER NOT NULL,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Notes
-- ---------------------------------------------------------------------------
-- 1. The real database also had index_idx_ntfs_1, blocks_idx_ntfs_1, and
--    spreadsheet_cell_anchors_idx_ntfs_1; they mirror the _folder_2 tables.
-- 2. Gety's FTS tokenizer is 'simple'; custom BM25/pinyin/Unicode logic lives
--    in Rust, not in the DDL.
-- 3. chunks.embedding stores f32 or i8 vectors depending on embedding_version;
--    search uses SQLite scalar functions cosine_sim_f32 / cosine_sim_i8.
-- 4. rarray(?) is an array-expansion helper registered on the connection; it is
--    not a vector index.
