export type Root = {
  id: string;
  path: string;
  documents: number;
  watch_enabled: boolean;
};

export type Counts = {
  documents: number;
  chunks: number;
  roots: number;
  embeddings: number;
};

export type EngineInfo = {
  backend: string;
  model: string;
  device: string;
  detail: string;
};

export type IndexHealth = {
  indexing: boolean;
  watching: boolean;
  watched_roots: number;
  pending: number;
  last_indexed_at: number | null;
  last_message: string | null;
  last_error: string | null;
  current_file: string | null;
  skipped: number;
  errors: number;
  details: string[];
};

export type Status = {
  roots: Root[];
  counts: Counts;
  backend: string;
  backend_label: string;
  available_backends: string[];
  engine: EngineInfo | null;
  model_root: string | null;
  npu_model: string;
  pdfium: string;
  db_path: string;
  model_ready: boolean;
  health: IndexHealth;
};

export type SearchHit = {
  chunk_id: number;
  doc_id: string;
  title: string;
  path: string;
  ext: string;
  snippet: string;
  score: number;
  page: number | null;
  start: number;
  end: number;
  matched: string[];
};

export type SearchResponse = {
  hits: SearchHit[];
  backend: string;
  semantic_used: boolean;
  took_ms: number;
};

export type DocumentView = {
  id: string;
  title: string;
  path: string;
  ext: string;
  size: number;
  modified: number;
  content: string;
};

export type IndexProgress = {
  phase: string;
  current: number;
  total: number;
  file: string;
  message: string;
};

export type IndexSummary = {
  details?: string[];
  removed?: number;
  scanned?: number;
  unchanged?: number;
  cancelled?: boolean;
  files: number;
  chunks: number;
  skipped: number;
  errors: number;
};
