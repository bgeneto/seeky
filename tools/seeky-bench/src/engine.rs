//! Engine adapter, index lifecycle, query execution helpers, and the index
//! metadata sidecar (SPEC-0003 R17).

use crate::corpus::Corpus;
use crate::environment::RunConfig;
use crate::{Failure, Result};
use seeky_engine::{
    Backend, DepthReport, Engine, EngineConfig, EngineEvents, FilterReport, FolderFilter,
    IndexHealth, IndexProgress, MetadataFilter,
};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// Sidecar filename inside the data directory.
pub const SIDECAR_NAME: &str = "index.metadata.json";

/// Sidecar path for a data directory.
pub fn sidecar_path(data_dir: &Path) -> PathBuf {
    data_dir.join(SIDECAR_NAME)
}

/// Index counts bound into the sidecar.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct IndexCounts {
    /// Indexed documents.
    pub documents: i64,
    /// Indexed chunks.
    pub chunks: i64,
}

/// Index timings bound into the sidecar.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct IndexTimings {
    /// Wall-clock indexing duration.
    pub elapsed_ms: u64,
}

/// Index metadata sidecar (never contains paths).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct IndexMetadata {
    /// Schema version.
    pub schema_version: u32,
    /// Dataset ID.
    pub corpus_id: String,
    /// Dataset corpus hash.
    pub corpus_hash: String,
    /// Code configuration.
    pub code_enabled: bool,
    /// Engine config snapshot SHA-256.
    pub config_hash: String,
    /// Active model hashes.
    pub models: Vec<crate::environment::SnapshotModel>,
    /// Counts.
    pub counts: IndexCounts,
    /// Timings.
    pub timings: IndexTimings,
    /// Corpus-relative root labels.
    pub roots: Vec<String>,
}

struct NoopEvents;

impl EngineEvents for NoopEvents {
    fn index_progress(&self, _progress: &IndexProgress) {}

    fn index_health(&self, _health: &IndexHealth) {}
}

/// Engine facade used by the harness.
pub struct EngineAdapter {
    engine: Engine,
}

impl EngineAdapter {
    /// Open the engine for the configured capabilities.
    pub fn open(data_dir: &Path, config: &RunConfig) -> Result<Self> {
        Self::open_with_events(data_dir, config, Arc::new(NoopEvents))
    }

    /// Open the engine and forward its index events to `events` (perf uses
    /// progress events to confirm that bulk indexing is active).
    pub fn open_with_events(
        data_dir: &Path,
        config: &RunConfig,
        events: Arc<dyn EngineEvents>,
    ) -> Result<Self> {
        let engine_config = EngineConfig {
            data_dir: data_dir.to_path_buf(),
            resource_dir: None,
        };
        let engine = if config.semantic {
            Engine::open(engine_config, events)
        } else {
            Engine::open_lexical(engine_config, events)
        }
        .map_err(|error| Failure::engine(error.to_string()))?;
        if config.backend != "auto" {
            let backend = Backend::parse(&config.backend)
                .map_err(|error| Failure::usage(error.to_string()))?;
            engine
                .set_backend(backend)
                .map_err(|error| Failure::engine(error.to_string()))?;
        }
        Ok(Self { engine })
    }

    /// The underlying engine.
    pub fn engine(&self) -> &Engine {
        &self.engine
    }

    /// Add every corpus root with watching disabled, then index it.
    pub fn index_roots(&self, corpus: &Corpus) -> Result<Vec<String>> {
        let mut labels = Vec::with_capacity(corpus.roots.len());
        for (root, label) in corpus.roots.iter().zip(&corpus.root_labels) {
            let added = self
                .engine
                .add_root(root)
                .map_err(|error| Failure::engine(error.to_string()))?;
            // Deterministic benchmark indexing never watches the filesystem.
            self.engine
                .set_root_watching(&added.id, false)
                .map_err(|error| Failure::engine(error.to_string()))?;
            labels.push(label.clone());
        }
        for root in &corpus.roots {
            self.engine
                .index_path(root)
                .map_err(|error| Failure::engine(error.to_string()))?;
        }
        Ok(labels)
    }

    /// Shut the engine down.
    pub fn shutdown(self) -> Result<()> {
        self.engine
            .shutdown()
            .map_err(|error| Failure::engine(error.to_string()))
    }
}

/// True when the directory exists and contains at least one entry.
pub fn is_nonempty(data_dir: &Path) -> Result<bool> {
    match std::fs::read_dir(data_dir) {
        Ok(mut entries) => Ok(entries.next().is_some()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(Failure::engine(format!(
            "cannot inspect the data directory: {error}"
        ))),
    }
}

/// Read the sidecar.
pub fn read_sidecar(path: &Path) -> Result<IndexMetadata> {
    let text = std::fs::read_to_string(path).map_err(|error| {
        Failure::engine(format!(
            "INDEX_INCOMPATIBLE: cannot read index metadata: {error}"
        ))
    })?;
    let metadata: IndexMetadata = serde_json::from_str(&text).map_err(|error| {
        Failure::engine(format!(
            "INDEX_INCOMPATIBLE: invalid index metadata: {error}"
        ))
    })?;
    if metadata.schema_version != 1 {
        return Err(Failure::engine(
            "INDEX_INCOMPATIBLE: unsupported index metadata schema",
        ));
    }
    Ok(metadata)
}

/// Write the sidecar atomically.
pub fn write_sidecar(path: &Path, metadata: &IndexMetadata) -> Result<()> {
    let text = serde_json::to_string_pretty(metadata)
        .map_err(|error| Failure::engine(format!("cannot serialize index metadata: {error}")))?;
    let temporary = path.with_extension("json.tmp");
    std::fs::write(&temporary, format!("{text}\n"))
        .map_err(|error| Failure::engine(format!("cannot write index metadata: {error}")))?;
    std::fs::rename(&temporary, path)
        .map_err(|error| Failure::engine(format!("cannot publish index metadata: {error}")))
}

/// Verify that the sidecar matches this corpus, code configuration, config
/// hash, and engine snapshot.
pub fn verify_index(
    engine: &Engine,
    path: &Path,
    corpus: &Corpus,
    corpus_hash: &str,
    code_enabled: bool,
) -> Result<IndexMetadata> {
    let metadata = read_sidecar(path)?;
    let snapshot = engine
        .config_snapshot()
        .map_err(|error| Failure::engine(error.to_string()))?;
    if metadata.corpus_id != corpus.id {
        return Err(Failure::engine(
            "INDEX_INCOMPATIBLE: index metadata names a different corpus",
        ));
    }
    if metadata.corpus_hash != corpus_hash {
        return Err(Failure::engine(
            "INDEX_INCOMPATIBLE: corpus hash differs from the index",
        ));
    }
    if metadata.code_enabled != code_enabled {
        return Err(Failure::engine(
            "INDEX_INCOMPATIBLE: code configuration differs from the index",
        ));
    }
    if metadata.config_hash != snapshot.sha256() {
        return Err(Failure::engine(
            "INDEX_INCOMPATIBLE: semantic configuration differs from the index",
        ));
    }
    Ok(metadata)
}

/// Parse a SPEC-0004 query filter object into an engine filter.
///
/// `root_label` is the corpus-relative label of the engine root used for folder
/// filters; the dataset-relative prefix is converted to be root-relative.
pub fn parse_query_filter(
    value: &serde_json::Value,
    root_id: &str,
    root_label: &str,
) -> Result<MetadataFilter> {
    let object = value
        .as_object()
        .ok_or_else(|| filter_error("filter must be an object"))?;
    let mut filter = MetadataFilter::default();
    for (key, value) in object {
        match key.as_str() {
            "extensions" => {
                let items = value
                    .as_array()
                    .ok_or_else(|| filter_error("filters.extensions must be an array"))?;
                for item in items {
                    let extension = item.as_str().ok_or_else(|| {
                        filter_error("filters.extensions entries must be strings")
                    })?;
                    filter.extensions.push(extension.to_string());
                }
            }
            "modified_after" => {
                let text = value
                    .as_str()
                    .ok_or_else(|| filter_error("filters.modified_after must be a string"))?;
                filter.modified_after_ns = Some(
                    crate::environment::parse_rfc3339_ns(text)
                        .ok_or_else(|| filter_error("filters.modified_after must be RFC 3339"))?,
                );
            }
            "modified_before" => {
                let text = value
                    .as_str()
                    .ok_or_else(|| filter_error("filters.modified_before must be a string"))?;
                filter.modified_before_ns = Some(
                    crate::environment::parse_rfc3339_ns(text)
                        .ok_or_else(|| filter_error("filters.modified_before must be RFC 3339"))?,
                );
            }
            "folder_prefix" => {
                let text = value
                    .as_str()
                    .ok_or_else(|| filter_error("filters.folder_prefix must be a string"))?;
                let mut prefix = text.replace('\\', "/").trim_start_matches('/').to_string();
                if !prefix.ends_with('/') {
                    prefix.push('/');
                }
                let label = root_label.trim_end_matches('/');
                let label_prefix = format!("{label}/");
                let relative = if let Some(rest) = prefix.strip_prefix(&label_prefix) {
                    rest.to_string()
                } else if prefix.trim_end_matches('/') == label {
                    String::new()
                } else {
                    return Err(filter_error(
                        "filters.folder_prefix is outside the configured corpus root",
                    ));
                };
                if relative.is_empty() {
                    return Err(filter_error(
                        "filters.folder_prefix cannot be the root itself",
                    ));
                }
                filter.folder = Some(FolderFilter {
                    root_id: root_id.to_string(),
                    relative_prefix: relative,
                });
            }
            "min_bytes" => {
                filter.min_bytes = Some(
                    value
                        .as_u64()
                        .ok_or_else(|| filter_error("filters.min_bytes must be an integer"))?,
                );
            }
            "max_bytes" => {
                filter.max_bytes = Some(
                    value
                        .as_u64()
                        .ok_or_else(|| filter_error("filters.max_bytes must be an integer"))?,
                );
            }
            other => {
                return Err(filter_error(format!("unsupported filter key {other}")));
            }
        }
    }
    Ok(filter)
}

fn filter_error(message: impl Into<String>) -> Failure {
    Failure::dataset(format!("SCHEMA: {}", message.into()))
}

/// Map an engine hit path to a dataset-relative POSIX path.
///
/// `prefixes` pairs each absolute engine root with its corpus-relative label.
pub fn relative_path(hit_path: &str, prefixes: &[(String, String)]) -> Option<String> {
    let normalized = hit_path.replace('\\', "/");
    for (root, label) in prefixes {
        if let Some(rest) = normalized.strip_prefix(root.as_str())
            && let Some(rest) = rest.strip_prefix('/')
            && !rest.is_empty()
        {
            let label = label.trim_end_matches('/');
            return Some(if label.is_empty() {
                rest.to_string()
            } else {
                format!("{label}/{rest}")
            });
        }
    }
    None
}

/// Resolve an engine hit to a dataset document ID.
pub fn hit_document(
    dataset: &seeky_eval::Dataset,
    hit: &seeky_engine::SearchHit,
    prefixes: &[(String, String)],
) -> Result<String> {
    let relative = relative_path(&hit.path, prefixes).ok_or_else(|| {
        Failure::dataset("DANGLING_REFERENCE: result path is outside the corpus root")
    })?;
    let document = dataset.document_by_path(&relative).ok_or_else(|| {
        Failure::dataset("DANGLING_REFERENCE: result path does not map to a dataset document")
    })?;
    Ok(document.id.clone())
}

/// The harness fails closed when a capped or post-filtered list is too short.
#[must_use]
pub fn depth_is_insufficient(
    depth: &DepthReport,
    filter: Option<&FilterReport>,
    cutoff: usize,
) -> bool {
    if depth.returned_hits >= cutoff {
        return false;
    }
    match filter {
        Some(report) => report.possibly_incomplete,
        None => depth.candidate_cap_reached,
    }
}

/// Aggregate filter mode over the run.
#[must_use]
pub fn aggregate_filter_mode(saw_filter: bool, saw_post: bool) -> &'static str {
    if !saw_filter {
        "none"
    } else if saw_post {
        "post"
    } else {
        "pushdown"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn relative_path_strips_the_root_prefix() {
        // SPEC-0003-R18
        let prefixes = vec![(
            "//?/C:/corpus/data/files".to_string(),
            "data/files".to_string(),
        )];
        assert_eq!(
            relative_path(r"\\?\C:\corpus\data\files\sub\a.txt", &prefixes).as_deref(),
            Some("data/files/sub/a.txt")
        );
        assert_eq!(relative_path("//?/C:/other/a.txt", &prefixes), None);
        assert_eq!(relative_path("//?/C:/corpus/data/files", &prefixes), None);
    }

    #[test]
    fn depth_is_insufficient_fails_closed() {
        // SPEC-0003-R18, R32
        let mut depth = DepthReport {
            requested_hits: 100,
            returned_hits: 20,
            distinct_documents: 20,
            candidate_depths: seeky_engine::CandidateDepths::default(),
            candidate_cap_reached: false,
        };
        assert!(!depth_is_insufficient(&depth, None, 100));
        depth.candidate_cap_reached = true;
        assert!(depth_is_insufficient(&depth, None, 100));
        let post = FilterReport {
            mode: seeky_engine::FilterMode::Post,
            applications: Vec::new(),
            examined: 20,
            matched: 5,
            returned: 5,
            possibly_incomplete: true,
        };
        assert!(depth_is_insufficient(&depth, Some(&post), 100));
        depth.returned_hits = 100;
        assert!(!depth_is_insufficient(&depth, Some(&post), 100));
    }

    #[test]
    fn query_filter_parser_rejects_unknown_keys() {
        // SPEC-0003-R32
        let value = serde_json::json!({"min_size": 10});
        assert!(parse_query_filter(&value, "root", "data/files").is_err());
        let value = serde_json::json!({"modified_after": "not-a-date"});
        assert!(parse_query_filter(&value, "root", "data/files").is_err());
        let value = serde_json::json!({"folder_prefix": "data/files/sub"});
        let filter = parse_query_filter(&value, "root", "data/files").expect("valid filter");
        assert_eq!(filter.folder.expect("folder").relative_prefix, "sub/");
    }
}
