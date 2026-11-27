//! Seeky engine: the `Engine` facade over roots, scanning, watching, indexing
//! orchestration, health, and status.
//!
//! Responsibilities and allowed dependencies:
//! `docs/specs/SPEC-0001-workspace-and-crate-boundaries.md` (sections 4.2 and 4.4).

mod config_snapshot;
mod engine;
mod indexer;

pub use config_snapshot::EngineConfigSnapshot;
pub use engine::{Engine, EngineConfig, EngineError, EngineEvents, ResolvedEngineConfig};
pub use seeky_core::{
    Backend, CandidateDepths, Counts, DeliveryStage, DepthReport, DocId, DocumentView, EngineInfo,
    EngineStatus, FileSignature, FilterApplication, FilterKind, FilterMode, FilterReport,
    FilterSupport, FolderFilter, IndexHealth, IndexProgress, IndexSummary, MetadataFilter,
    ModelIdentity, QueryEmbeddingProbe, QueryEmbeddingTiming, Root, RootId, SearchHit, SearchMode,
    SearchOptions, SearchOutcome, SearchRequest, SearchResponse, SearchStage, SearchTelemetry,
    StageTiming,
};
pub use seeky_infer::{find_gety_model_root, resolve_npu_dir};

pub type Error = EngineError;
pub type Result<T> = std::result::Result<T, EngineError>;
