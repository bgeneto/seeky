//! Corpus and dataset resolution (SPEC-0003 R15).
//!
//! Corpus IDs resolve only through the built-in SDC mappings or a committed
//! `bench/datasets/<dataset-id>/manifest.json`. Unknown IDs are rejected before
//! the engine is opened.

use crate::{Failure, Result};
use seeky_eval::{Dataset, EvaluationConfiguration, Split, load_beir, load_sdc};
use serde::Deserialize;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// Repository-relative benchmark roots.
#[derive(Clone, Debug)]
pub struct BenchPaths {
    /// Repository root (or the `SEEKY_BENCH_ROOT` override for offline fixtures).
    pub root: PathBuf,
}

impl BenchPaths {
    /// Explicit benchmark root (offline fixtures).
    #[must_use]
    pub fn at(root: PathBuf) -> Self {
        Self { root }
    }

    /// Discover the benchmark root.
    pub fn discover() -> Result<Self> {
        if let Some(root) = std::env::var_os("SEEKY_BENCH_ROOT") {
            let root = PathBuf::from(root);
            if !root.is_dir() {
                return Err(Failure::usage("SEEKY_BENCH_ROOT is not a directory"));
            }
            return Ok(Self { root });
        }
        let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let root = manifest
            .parent()
            .and_then(Path::parent)
            .ok_or_else(|| Failure::usage("cannot locate the repository root"))?;
        Ok(Self {
            root: root.to_path_buf(),
        })
    }

    /// `bench/`.
    pub fn bench(&self) -> PathBuf {
        self.root.join("bench")
    }

    /// `bench/datasets/`.
    pub fn datasets(&self) -> PathBuf {
        self.bench().join("datasets")
    }

    /// `bench/corpora/sdc/`.
    pub fn corpora(&self) -> PathBuf {
        self.bench().join("corpora").join("sdc")
    }

    /// `bench/qrels/sdc/`.
    pub fn qrels(&self) -> PathBuf {
        self.bench().join("qrels").join("sdc")
    }

    /// `bench/exposures/`.
    pub fn exposures(&self) -> PathBuf {
        self.bench().join("exposures")
    }
}

/// Dataset family.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CorpusKind {
    /// Seeky Desktop Corpus (SPEC-0004).
    Sdc,
    /// BEIR-layout dataset.
    Beir,
}

/// Resolved corpus.
#[derive(Clone, Debug)]
pub struct Corpus {
    /// Dataset identifier.
    pub id: String,
    /// Dataset family.
    pub kind: CorpusKind,
    /// Dataset root directory.
    pub root: PathBuf,
    /// Manifest path.
    pub manifest_path: PathBuf,
    /// Absolute roots to index.
    pub roots: Vec<PathBuf>,
    /// Corpus-relative root labels (no absolute paths in artifacts).
    pub root_labels: Vec<String>,
    /// Whether the code-enabled configuration was selected.
    pub code_enabled: bool,
    /// Report visibility.
    pub visibility: String,
    /// Judgment-set directory for SDC datasets.
    pub judgment_dir: Option<PathBuf>,
}

impl Corpus {
    /// Evaluation configuration for this invocation.
    pub fn evaluation_configuration(&self, code_enabled: bool) -> EvaluationConfiguration {
        if code_enabled {
            EvaluationConfiguration::CodeEnabled
        } else {
            EvaluationConfiguration::Default
        }
    }
}

#[derive(Debug, Deserialize)]
struct SdcManifest {
    schema_version: u32,
    corpus_id: String,
    corpus_hash: String,
    default_roots: Vec<String>,
    code_enabled_roots: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct BeirManifest {
    schema_version: u32,
    dataset_id: String,
    layout: String,
    #[serde(default)]
    visibility: Option<String>,
    corpus: String,
    files_root: Option<String>,
    splits: BTreeMap<String, BeirSplit>,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct BeirSplit {
    queries: String,
    qrels: String,
}

/// Resolve a corpus ID.
pub fn resolve(paths: &BenchPaths, id: &str, code_enabled: bool) -> Result<Corpus> {
    match id {
        "sdc-smoke" | "sdc-s" | "sdc-m" => resolve_sdc(paths, id, code_enabled),
        _ => resolve_beir(paths, id, code_enabled),
    }
}

fn resolve_sdc(paths: &BenchPaths, id: &str, code_enabled: bool) -> Result<Corpus> {
    let root = paths.corpora().join(id);
    let manifest_path = root.join("manifest.json");
    let text = std::fs::read_to_string(&manifest_path)
        .map_err(|error| Failure::dataset(format!("cannot read the {id} manifest: {error}")))?;
    let manifest: SdcManifest = serde_json::from_str(&text)
        .map_err(|error| Failure::dataset(format!("invalid {id} manifest: {error}")))?;
    if manifest.schema_version != 1 || manifest.corpus_id != id {
        return Err(Failure::dataset(
            "SDC manifest does not match the corpus ID",
        ));
    }
    let labels = if code_enabled {
        manifest.code_enabled_roots.clone()
    } else {
        manifest.default_roots.clone()
    };
    if labels.is_empty() {
        return Err(Failure::usage("SDC manifest declares no roots"));
    }
    let roots: Vec<PathBuf> = labels.iter().map(|label| root.join(label)).collect();
    for dir in &roots {
        if !dir.is_dir() {
            return Err(Failure::dataset(format!(
                "corpus root {} is missing",
                label_for(dir)
            )));
        }
    }
    let judgment_set = if id == "sdc-smoke" {
        "sdc-smoke-v1"
    } else {
        "sdc-v1"
    };
    Ok(Corpus {
        id: id.to_string(),
        kind: CorpusKind::Sdc,
        root,
        manifest_path,
        roots,
        root_labels: labels,
        code_enabled,
        visibility: "public".to_string(),
        judgment_dir: Some(paths.qrels().join(judgment_set)),
    })
}

fn resolve_beir(paths: &BenchPaths, id: &str, code_enabled: bool) -> Result<Corpus> {
    if id.is_empty() || id.contains(['/', '\\', '.']) {
        return Err(Failure::usage("invalid corpus ID"));
    }
    let root = paths.datasets().join(id);
    let manifest_path = root.join("manifest.json");
    if !manifest_path.is_file() {
        return Err(Failure::usage(format!(
            "unknown corpus {id}: no bench/datasets/{id}/manifest.json"
        )));
    }
    let text = std::fs::read_to_string(&manifest_path)
        .map_err(|error| Failure::dataset(format!("cannot read the {id} manifest: {error}")))?;
    let manifest: BeirManifest = serde_json::from_str(&text)
        .map_err(|error| Failure::dataset(format!("invalid {id} manifest: {error}")))?;
    if manifest.schema_version != 1 || manifest.layout != "beir" || manifest.dataset_id != id {
        return Err(Failure::dataset(
            "BEIR manifest does not match the dataset ID",
        ));
    }
    if code_enabled {
        return Err(Failure::usage(
            "--code-enabled is rejected for BEIR datasets without a code root",
        ));
    }
    let Some(files_root) = manifest.files_root.clone() else {
        return Err(Failure::dataset(
            "dataset has no files_root and cannot be indexed",
        ));
    };
    if manifest.splits.is_empty() {
        return Err(Failure::dataset("dataset declares no splits"));
    }
    if !manifest.corpus.ends_with(".jsonl") {
        return Err(Failure::dataset("dataset corpus must be JSONL"));
    }
    let root_dir = root.join(&files_root);
    if !root_dir.is_dir() {
        return Err(Failure::dataset("dataset files_root is missing"));
    }
    Ok(Corpus {
        id: id.to_string(),
        kind: CorpusKind::Beir,
        root,
        manifest_path,
        roots: vec![root_dir],
        root_labels: vec![files_root],
        code_enabled,
        visibility: manifest.visibility.unwrap_or_else(|| "public".to_string()),
        judgment_dir: None,
    })
}

/// Query filters declared by the raw split file.
///
/// The BEIR loader normalizes query metadata but does not carry filters, so the
/// harness reads the same validated queries file to preserve them (R32). SDC
/// queries already expose filters through `Query::filters`.
pub fn query_filters(corpus: &Corpus, split: Split) -> Result<BTreeMap<String, serde_json::Value>> {
    if corpus.kind == CorpusKind::Sdc {
        return Ok(BTreeMap::new());
    }
    let manifest_text = std::fs::read_to_string(&corpus.manifest_path)
        .map_err(|error| Failure::dataset(format!("cannot read the dataset manifest: {error}")))?;
    let manifest: BeirManifest = serde_json::from_str(&manifest_text)
        .map_err(|error| Failure::dataset(format!("invalid dataset manifest: {error}")))?;
    let name = match split {
        Split::Dev => "dev",
        Split::Test => "test",
    };
    let Some(files) = manifest.splits.get(name) else {
        return Err(Failure::dataset(
            "dataset does not declare the requested split",
        ));
    };
    let path = corpus.root.join(&files.queries);
    let text = std::fs::read_to_string(&path)
        .map_err(|error| Failure::dataset(format!("cannot read the queries file: {error}")))?;
    let mut filters = BTreeMap::new();
    for (index, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            return Err(Failure::dataset(format!(
                "blank queries line {}",
                index + 1
            )));
        }
        let value: serde_json::Value = serde_json::from_str(line).map_err(|error| {
            Failure::dataset(format!("invalid queries line {}: {error}", index + 1))
        })?;
        let Some(id) = value.get("_id").and_then(serde_json::Value::as_str) else {
            return Err(Failure::dataset(format!(
                "queries line {} has no _id",
                index + 1
            )));
        };
        if let Some(filters_value) = value
            .get("metadata")
            .and_then(|metadata| metadata.get("filters"))
        {
            filters.insert(id.to_string(), filters_value.clone());
        }
    }
    Ok(filters)
}

fn label_for(path: &Path) -> String {
    path.file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("root")
        .to_string()
}

/// Load the frozen dataset for a split.
pub fn load_dataset(
    corpus: &Corpus,
    split: Split,
    configuration: EvaluationConfiguration,
    judgment_set: Option<&str>,
) -> Result<Dataset> {
    match corpus.kind {
        CorpusKind::Beir => {
            if configuration == EvaluationConfiguration::CodeEnabled {
                return Err(Failure::dataset(
                    "BEIR datasets support only the default configuration",
                ));
            }
            load_beir(&corpus.manifest_path, split)
                .map_err(|error| Failure::dataset(error.to_string()))
        }
        CorpusKind::Sdc => {
            let dir = match judgment_set {
                Some(id) => corpus
                    .judgment_dir
                    .as_ref()
                    .and_then(|dir| dir.parent())
                    .map(|parent| parent.join(id)),
                None => corpus.judgment_dir.clone(),
            }
            .ok_or_else(|| Failure::dataset("no judgment set for the SDC corpus"))?;
            load_sdc(&corpus.root, &dir, split, configuration)
                .map_err(|error| Failure::dataset(error.to_string()))
        }
    }
}

/// Minimal dataset metadata and fixed dev queries needed by `seeky-bench perf`.
#[derive(Clone, Debug)]
pub struct PerfDataset {
    /// Report dataset metadata.
    pub info: seeky_eval::DatasetInfo,
    /// Fixed dev query texts in deterministic ID order.
    pub queries: Vec<String>,
}

impl PerfDataset {
    /// Construct from a full loaded dataset (requires `Split::Dev`).
    pub fn from_dataset(dataset: &Dataset, visibility: &str) -> Result<Self> {
        if dataset.split != Split::Dev {
            return Err(Failure::dataset("perf only measures the dev split"));
        }
        Ok(Self {
            info: crate::dataset_info(dataset, visibility),
            queries: dataset
                .queries()
                .iter()
                .map(|query| query.text.clone())
                .collect(),
        })
    }
}

#[derive(Debug, Deserialize)]
struct DraftQueryRow {
    #[serde(rename = "_id")]
    id: String,
    text: String,
    split: String,
    configuration: String,
    category: String,
    #[serde(default)]
    language: Option<String>,
    #[serde(default)]
    target_languages: Vec<String>,
    #[serde(default)]
    language_slice: Option<String>,
    #[serde(default)]
    filters: Option<serde_json::Value>,
}

/// Load only `dev` queries from a SPEC-0004 JSONL queries file for `perf`
/// without requiring frozen/verified qrels (SPEC-0003 R21, R25, R28).
///
/// Rejects files that appear to target the `test` split, rejects malformed
/// rows, filters strictly to `split == "dev"` matching `configuration`, and
/// never passes any `test` query to the engine.
pub fn load_perf_queries_file(
    corpus: &Corpus,
    queries_file: &Path,
    configuration: EvaluationConfiguration,
) -> Result<PerfDataset> {
    use crate::environment::sha256_hex;

    if corpus.kind != CorpusKind::Sdc {
        return Err(Failure::usage(
            "--queries-file is supported only for SDC corpora (BEIR corpora load dev directly)",
        ));
    }
    let file_name = queries_file
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if file_name.contains("test") {
        return Err(Failure::usage(
            "TEST_NOT_ALLOWED: perf --queries-file refuses files named for the test split",
        ));
    }
    let manifest_text = std::fs::read_to_string(&corpus.manifest_path)
        .map_err(|error| Failure::dataset(format!("cannot read corpus manifest: {error}")))?;
    let manifest: SdcManifest = serde_json::from_str(&manifest_text)
        .map_err(|error| Failure::dataset(format!("invalid corpus manifest: {error}")))?;
    if manifest.corpus_hash.len() != 64
        || !manifest
            .corpus_hash
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
    {
        return Err(Failure::dataset(
            "SDC manifest corpus_hash must be 64 hex characters",
        ));
    }

    let raw_bytes = std::fs::read(queries_file)
        .map_err(|error| Failure::dataset(format!("cannot read --queries-file: {error}")))?;
    let queries_file_sha256 = sha256_hex(&raw_bytes);
    let raw_text = String::from_utf8(raw_bytes)
        .map_err(|error| Failure::dataset(format!("--queries-file is not UTF-8: {error}")))?;

    let mut seen_ids = std::collections::BTreeSet::new();
    let mut selected: Vec<(String, serde_json::Value, String)> = Vec::new();
    for (index, line) in raw_text.lines().enumerate() {
        let line_no = index + 1;
        if line.trim().is_empty() {
            continue;
        }
        let row: DraftQueryRow = serde_json::from_str(line).map_err(|error| {
            Failure::dataset(format!("invalid --queries-file line {line_no}: {error}"))
        })?;
        if row.id.trim().is_empty() || row.text.trim().is_empty() {
            return Err(Failure::dataset(format!(
                "--queries-file line {line_no} has empty _id or text"
            )));
        }
        if !seen_ids.insert(row.id.clone()) {
            return Err(Failure::dataset(format!(
                "--queries-file line {line_no} duplicates query ID {}",
                row.id
            )));
        }
        match row.split.as_str() {
            "dev" => {}
            "test" => continue,
            other => {
                return Err(Failure::dataset(format!(
                    "--queries-file line {line_no} has unknown split {other:?}"
                )));
            }
        }
        let include = match (configuration, row.configuration.as_str()) {
            (EvaluationConfiguration::Default, "default") => row.category != "code_search",
            (EvaluationConfiguration::Default, "code_enabled") => false,
            (EvaluationConfiguration::CodeEnabled, "default" | "code_enabled") => true,
            (_, other) => {
                return Err(Failure::dataset(format!(
                    "--queries-file line {line_no} has unknown configuration {other:?}"
                )));
            }
        };
        if !include {
            continue;
        }
        let canonical_row = serde_json::json!({
            "id": row.id,
            "text": row.text,
            "language": row.language,
            "target_languages": row.target_languages,
            "language_slice": row.language_slice,
            "category": row.category,
            "configuration": row.configuration,
            "split": "dev",
            "filters": row.filters,
        });
        selected.push((row.id, canonical_row, row.text));
    }

    if selected.is_empty() {
        return Err(Failure::dataset(
            "--queries-file contains no eligible dev queries for this configuration",
        ));
    }
    selected.sort_by(|left, right| left.0.cmp(&right.0));
    let canonical_rows: Vec<serde_json::Value> =
        selected.iter().map(|(_, value, _)| value.clone()).collect();
    let canonical_json = serde_json::to_string(&canonical_rows)
        .map_err(|error| Failure::dataset(format!("cannot serialize query set: {error}")))?;
    let query_set_sha256 = sha256_hex(canonical_json.as_bytes());
    let judgment_set_id = "dev-queries-only".to_string();
    let fingerprint_input = serde_json::json!({
        "corpus_hash": manifest.corpus_hash,
        "judgment_set_id": judgment_set_id,
        "judgment_set_hash": queries_file_sha256,
        "query_set_sha256": query_set_sha256,
    });
    let fingerprint_json = serde_json::to_string(&fingerprint_input)
        .map_err(|error| Failure::dataset(format!("cannot serialize fingerprint: {error}")))?;
    let fingerprint = sha256_hex(fingerprint_json.as_bytes());

    let queries = selected.into_iter().map(|(_, _, text)| text).collect();
    Ok(PerfDataset {
        info: seeky_eval::DatasetInfo {
            id: corpus.id.clone(),
            split: Split::Dev,
            configuration,
            corpus_hash: manifest.corpus_hash,
            fingerprint,
            judgment_set_id,
            judgment_set_hash: queries_file_sha256,
            query_count: canonical_rows.len() as u64,
            query_set_sha256,
            visibility: corpus.visibility.clone(),
        },
        queries,
    })
}
