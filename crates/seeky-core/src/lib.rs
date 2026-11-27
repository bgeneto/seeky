//! Seeky core: domain types and IDs, configuration types, shared error types,
//! and subsystem traits.
//!
//! Responsibilities and allowed dependencies:
//! `docs/specs/SPEC-0001-workspace-and-crate-boundaries.md` (sections 4.2 and 4.4).

use serde::Serialize;
use std::time::{SystemTime, UNIX_EPOCH};

pub type RootId = String;
pub type DocId = String;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("unknown backend: {0}")]
    UnknownBackend(String),
}

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Backend {
    Auto,
    Cpu,
    Cuda,
    Npu,
}

impl Backend {
    pub fn parse(value: &str) -> Result<Self> {
        match value.to_ascii_lowercase().as_str() {
            "auto" => Ok(Self::Auto),
            "cpu" => Ok(Self::Cpu),
            "cuda" | "gpu" => Ok(Self::Cuda),
            "npu" => Ok(Self::Npu),
            other => Err(Error::UnknownBackend(other.to_string())),
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Auto => "Auto",
            Self::Cpu => "CPU",
            Self::Cuda => "CUDA",
            Self::Npu => "NPU",
        }
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct Root {
    pub id: String,
    pub path: String,
    pub documents: i64,
    pub watch_enabled: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct Counts {
    pub documents: i64,
    pub chunks: i64,
    pub roots: i64,
    pub embeddings: i64,
}

#[derive(Clone, Debug, Serialize)]
pub struct DocumentView {
    pub id: String,
    pub title: String,
    pub path: String,
    pub ext: String,
    pub size: i64,
    pub modified: i64,
    pub content: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FileSignature {
    pub size: i64,
    pub modified_ns: i64,
}

impl FileSignature {
    pub fn from_metadata(metadata: &std::fs::Metadata) -> Self {
        let modified_ns = metadata
            .modified()
            .ok()
            .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
            .map(|duration| duration.as_nanos().min(i64::MAX as u128) as i64)
            .unwrap_or(0);
        Self {
            size: metadata.len() as i64,
            modified_ns,
        }
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct SearchHit {
    pub chunk_id: i64,
    pub doc_id: String,
    pub title: String,
    pub path: String,
    pub ext: String,
    pub snippet: String,
    pub score: f64,
    pub page: Option<i64>,
    pub start: i64,
    pub end: i64,
    pub matched: Vec<String>,
}

#[derive(Clone, Debug, Serialize)]
pub struct IndexProgress {
    pub phase: String,
    pub current: usize,
    pub total: usize,
    pub file: String,
    pub message: String,
}

#[derive(Clone, Debug, Serialize, Default)]
pub struct IndexSummary {
    pub scanned: usize,
    pub files: usize,
    pub chunks: usize,
    pub unchanged: usize,
    pub skipped: usize,
    pub errors: usize,
    pub removed: usize,
    pub cancelled: bool,
    pub details: Vec<String>,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct IndexHealth {
    pub indexing: bool,
    pub watching: bool,
    pub watched_roots: usize,
    pub pending: usize,
    pub last_indexed_at: Option<i64>,
    pub last_message: Option<String>,
    pub last_error: Option<String>,
    pub current_file: Option<String>,
    pub skipped: usize,
    pub errors: usize,
    pub details: Vec<String>,
}

#[derive(Clone, Debug, Serialize)]
pub struct EngineInfo {
    pub backend: String,
    pub model: String,
    pub device: String,
    pub detail: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct EngineStatus {
    pub roots: Vec<Root>,
    pub counts: Counts,
    pub backend: String,
    pub backend_label: String,
    pub available_backends: Vec<String>,
    pub engine: Option<EngineInfo>,
    pub model_root: Option<String>,
    pub npu_model: String,
    pub pdfium: String,
    pub db_path: String,
    pub model_ready: bool,
    pub health: IndexHealth,
}

#[derive(Clone, Debug)]
pub struct SearchRequest {
    pub query: String,
    pub limit: Option<usize>,
}

#[derive(Clone, Debug, Serialize)]
pub struct SearchResponse {
    pub hits: Vec<SearchHit>,
    pub backend: String,
    pub semantic_used: bool,
    pub took_ms: u64,
}

pub fn now_secs() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs() as i64)
        .unwrap_or(0)
}
