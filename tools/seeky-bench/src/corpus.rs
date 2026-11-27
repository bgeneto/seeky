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
