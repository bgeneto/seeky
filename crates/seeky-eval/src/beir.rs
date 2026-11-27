//! BEIR-layout loader (SPEC-0003 R2).

use std::collections::{BTreeMap, BTreeSet};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::dataset::{
    Dataset, Document, DocumentId, DocumentJudgment, EvaluationConfiguration, LanguageSlice, Query,
    QueryCategory, Split,
};
use crate::error::{EvalError, Result, display_path};
use crate::sdc::{DuplicateCluster, validate_clusters};
use crate::util::{
    join_relative, normalize_relative_path, read_json, read_jsonl, sha256_file, value_sha256,
};

#[derive(Debug, Deserialize, Serialize)]
struct BeirManifest {
    schema_version: u32,
    dataset_id: String,
    layout: String,
    visibility: String,
    license: License,
    source: Source,
    corpus: String,
    #[serde(default)]
    files_root: Option<String>,
    splits: BTreeMap<String, SplitFiles>,
    query_defaults: QueryDefaults,
    transform: Transform,
    local_file_sha256: BTreeMap<String, String>,
    #[serde(default)]
    duplicate_clusters: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
struct License {
    id: String,
    url: String,
    redistribution: String,
    terms_url: String,
}

#[derive(Debug, Deserialize, Serialize)]
struct Source {
    revision: String,
    urls: Vec<String>,
    sha256: Vec<String>,
}

#[derive(Debug, Deserialize, Serialize)]
struct SplitFiles {
    queries: String,
    qrels: String,
}

#[derive(Debug, Deserialize, Serialize)]
struct QueryDefaults {
    language_slice: String,
    category: String,
    configuration: String,
    #[serde(default)]
    language: Option<String>,
    #[serde(default)]
    target_languages: Vec<String>,
}

#[derive(Debug, Deserialize, Serialize)]
struct Transform {
    script: String,
    version: u32,
    seed: String,
}

#[derive(Debug, Deserialize)]
struct BeirDocument {
    #[serde(rename = "_id")]
    id: String,
    title: String,
    text: String,
    #[serde(default)]
    metadata: Option<serde_json::Value>,
}

#[derive(Debug, Deserialize)]
struct BeirQuery {
    #[serde(rename = "_id")]
    id: String,
    text: String,
    #[serde(default)]
    metadata: Option<serde_json::Value>,
}

fn beir_error(location: &str, message: impl Into<String>) -> EvalError {
    EvalError::data("SCHEMA", location, message)
}

/// Load one split from a committed BEIR dataset manifest.
pub fn load_beir(manifest_path: &Path, split: Split) -> Result<Dataset> {
    let manifest: BeirManifest = read_json(manifest_path)?;
    validate_manifest(&manifest)?;
    let root = manifest_path
        .parent()
        .ok_or_else(|| beir_error("manifest", "manifest has no parent directory"))?;
    verify_local_files(root, &manifest)?;

    let corpus_path = join_relative(root, &manifest.corpus)?;
    let corpus_hash = sha256_file(&corpus_path)?;
    let corpus_records = read_jsonl::<BeirDocument>(&corpus_path)?;
    let mut documents = BTreeMap::new();
    for (index, record) in corpus_records.into_iter().enumerate() {
        let location = format!("{}:{}", display_path(&corpus_path), index + 1);
        if record.id.trim().is_empty() || record.text.is_empty() {
            return Err(beir_error(
                &location,
                "document ID and text must be nonempty",
            ));
        }
        let metadata = match record.metadata {
            None => serde_json::json!({}),
            Some(value) if value.is_object() => value,
            Some(_) => {
                return Err(beir_error(
                    &location,
                    "document metadata must be a JSON object",
                ));
            }
        };
        if let Some(file_class) = metadata_string(&metadata, "file_class", &location)?
            && !matches!(file_class, "document")
        {
            return Err(beir_error(
                &location,
                "BEIR datasets cannot declare source-code documents",
            ));
        }
        let relative_path = match metadata.get("relative_path") {
            None => String::new(),
            Some(serde_json::Value::String(path)) => normalize_relative_path(path)?,
            Some(_) => {
                return Err(beir_error(
                    &location,
                    "metadata.relative_path must be a string",
                ));
            }
        };
        if manifest.files_root.is_some() {
            if relative_path.is_empty() {
                return Err(beir_error(
                    &location,
                    "files_root requires metadata.relative_path",
                ));
            }
            let file_path = join_relative(root, &relative_path)?;
            if !manifest.local_file_sha256.contains_key(&relative_path) {
                return Err(EvalError::data(
                    "SCHEMA",
                    &location,
                    "engine file is not listed in local_file_sha256",
                ));
            }
            let bytes =
                std::fs::read(&file_path).map_err(|error| EvalError::io(&file_path, error))?;
            let text = std::str::from_utf8(&bytes)
                .map_err(|error| EvalError::data("UTF8", &location, error.to_string()))?;
            if text != record.text {
                return Err(EvalError::data(
                    "HASH_MISMATCH",
                    &location,
                    "corpus text differs from the engine file",
                ));
            }
        }
        let document = Document {
            id: record.id.clone(),
            title: record.title,
            text: record.text,
            relative_path,
            source_code: false,
            metadata,
        };
        if documents.insert(document.id.clone(), document).is_some() {
            return Err(EvalError::data(
                "DUPLICATE_ID",
                &location,
                "duplicate document ID",
            ));
        }
    }

    let split_name = match split {
        Split::Dev => "dev",
        Split::Test => "test",
    };
    let split_files = manifest.splits.get(split_name).ok_or_else(|| {
        EvalError::data(
            "SCHEMA",
            "manifest.splits",
            format!("missing {split_name} split"),
        )
    })?;
    let query_path = join_relative(root, &split_files.queries)?;
    let qrels_path = join_relative(root, &split_files.qrels)?;
    let judgment_set_hash = sha256_file(&qrels_path)?;
    let query_records = read_jsonl::<BeirQuery>(&query_path)?;
    let default_category = QueryCategory::parse(&manifest.query_defaults.category)?;
    let default_slice = LanguageSlice::parse(&manifest.query_defaults.language_slice)?;
    let default_configuration =
        EvaluationConfiguration::parse(&manifest.query_defaults.configuration)?;
    if default_configuration != EvaluationConfiguration::Default {
        return Err(beir_error(
            "manifest.query_defaults.configuration",
            "BEIR manifests must use the default configuration",
        ));
    }
    let mut queries = Vec::new();
    let mut query_ids = BTreeSet::new();
    for (index, record) in query_records.into_iter().enumerate() {
        let location = format!("{}:{}", display_path(&query_path), index + 1);
        if record.id.trim().is_empty() || record.text.is_empty() {
            return Err(beir_error(&location, "query ID and text must be nonempty"));
        }
        if !query_ids.insert(record.id.clone()) {
            return Err(EvalError::data(
                "DUPLICATE_ID",
                &location,
                "duplicate query ID",
            ));
        }
        let metadata = match record.metadata {
            None => serde_json::json!({}),
            Some(value) if value.is_object() => value,
            Some(_) => {
                return Err(beir_error(
                    &location,
                    "query metadata must be a JSON object",
                ));
            }
        };
        let category = metadata_string(&metadata, "category", &location)?
            .map(QueryCategory::parse)
            .transpose()?
            .unwrap_or(default_category);
        let language_slice = metadata_string(&metadata, "language_slice", &location)?
            .map(LanguageSlice::parse)
            .transpose()?
            .unwrap_or(default_slice);
        let configuration = metadata_string(&metadata, "configuration", &location)?
            .map(EvaluationConfiguration::parse)
            .transpose()?
            .unwrap_or(default_configuration);
        if configuration != EvaluationConfiguration::Default
            || category == QueryCategory::CodeSearch
        {
            return Err(beir_error(
                &location,
                "BEIR datasets only support the default eight categories",
            ));
        }
        let language = metadata_string(&metadata, "language", &location)?
            .map(str::to_owned)
            .or_else(|| manifest.query_defaults.language.clone())
            .unwrap_or_else(|| "und".to_owned());
        let target_languages = match metadata.get("target_languages") {
            None => manifest.query_defaults.target_languages.clone(),
            Some(serde_json::Value::Array(values))
                if values.iter().all(serde_json::Value::is_string) =>
            {
                values
                    .iter()
                    .filter_map(serde_json::Value::as_str)
                    .map(str::to_owned)
                    .collect()
            }
            Some(_) => {
                return Err(beir_error(
                    &location,
                    "target_languages must be an array of strings",
                ));
            }
        };
        queries.push(Query {
            id: record.id,
            text: record.text,
            language,
            target_languages,
            language_slice,
            category,
            configuration,
            split,
            filters: None,
        });
    }

    let document_judgments = read_tsv_qrels(&qrels_path, &documents, &query_ids)?;
    let mut manifest_value = serde_json::to_value(&manifest)
        .map_err(|error| beir_error("manifest", error.to_string()))?;
    if let Some(object) = manifest_value.as_object_mut() {
        object.remove("local_file_sha256");
    }
    let local_files: Vec<_> = manifest
        .local_file_sha256
        .iter()
        .map(|(path, sha256)| serde_json::json!({"path": path, "sha256": sha256}))
        .collect();
    let fingerprint_value = serde_json::json!({
        "manifest": manifest_value,
        "files": local_files,
    });
    let fingerprint = value_sha256(&fingerprint_value)?;

    let duplicate_families = if let Some(relative) = &manifest.duplicate_clusters {
        let path = join_relative(root, relative)?;
        let clusters = read_jsonl::<DuplicateCluster>(&path)?;
        let (families, _) = validate_clusters(&clusters, &documents)?;
        families
    } else {
        BTreeMap::new()
    };
    let duplicate_metrics_available = manifest.duplicate_clusters.is_some();

    Dataset::new(
        manifest.dataset_id.clone(),
        corpus_hash,
        fingerprint,
        format!("{}-{}", manifest.dataset_id, split_name),
        judgment_set_hash,
        split,
        EvaluationConfiguration::Default,
        documents.into_values(),
        Vec::new(),
        queries,
        document_judgments,
        BTreeMap::new(),
        duplicate_families,
        duplicate_metrics_available,
    )
}

fn validate_manifest(manifest: &BeirManifest) -> Result<()> {
    if manifest.schema_version != 1
        || manifest.layout != "beir"
        || manifest.dataset_id.trim().is_empty()
    {
        return Err(beir_error(
            "manifest",
            "invalid schema, layout, or dataset ID",
        ));
    }
    if !matches!(manifest.visibility.as_str(), "public" | "private") {
        return Err(beir_error("manifest.visibility", "unknown visibility"));
    }
    if manifest.license.id.trim().is_empty()
        || manifest.license.url.trim().is_empty()
        || manifest.license.redistribution.trim().is_empty()
        || manifest.license.terms_url.trim().is_empty()
    {
        return Err(beir_error("manifest.license", "incomplete license record"));
    }
    if manifest.source.revision.trim().is_empty()
        || manifest.source.urls.is_empty()
        || manifest.source.urls.len() != manifest.source.sha256.len()
        || manifest.source.sha256.iter().any(|hash| hash.len() != 64)
    {
        return Err(beir_error("manifest.source", "incomplete source record"));
    }
    if manifest.transform.script.trim().is_empty()
        || manifest.transform.version == 0
        || manifest.transform.seed.trim().is_empty()
    {
        return Err(beir_error(
            "manifest.transform",
            "incomplete transformation",
        ));
    }
    normalize_relative_path(&manifest.corpus)?;
    for (name, split) in &manifest.splits {
        if !matches!(name.as_str(), "dev" | "test") {
            return Err(beir_error("manifest.splits", "unknown split name"));
        }
        normalize_relative_path(&split.queries)?;
        normalize_relative_path(&split.qrels)?;
    }
    if !manifest.splits.contains_key("dev") || !manifest.splits.contains_key("test") {
        return Err(beir_error(
            "manifest.splits",
            "both dev and test mappings are required",
        ));
    }
    if let Some(root) = &manifest.files_root {
        normalize_relative_path(root)?;
    }
    if let Some(clusters) = &manifest.duplicate_clusters {
        normalize_relative_path(clusters)?;
    }
    if manifest.local_file_sha256.is_empty() {
        return Err(beir_error(
            "manifest.local_file_sha256",
            "at least one local file hash is required",
        ));
    }
    for path in manifest.local_file_sha256.keys() {
        normalize_relative_path(path)?;
    }
    Ok(())
}

fn verify_local_files(root: &Path, manifest: &BeirManifest) -> Result<()> {
    for (relative, expected) in &manifest.local_file_sha256 {
        let path = join_relative(root, relative)?;
        let actual = sha256_file(&path)?;
        if &actual != expected || expected.len() != 64 {
            return Err(EvalError::data(
                "HASH_MISMATCH",
                relative,
                "local file digest differs",
            ));
        }
    }
    let required = [&manifest.corpus].into_iter().chain(
        manifest
            .splits
            .values()
            .flat_map(|split| [&split.queries, &split.qrels]),
    );
    for relative in required {
        if !manifest.local_file_sha256.contains_key(relative) {
            return Err(EvalError::data(
                "SCHEMA",
                relative,
                "required dataset file has no local hash",
            ));
        }
    }
    if let Some(clusters) = &manifest.duplicate_clusters
        && !manifest.local_file_sha256.contains_key(clusters)
    {
        return Err(EvalError::data(
            "SCHEMA",
            clusters,
            "duplicate cluster file has no local hash",
        ));
    }
    Ok(())
}

fn read_tsv_qrels(
    path: &Path,
    documents: &BTreeMap<DocumentId, Document>,
    query_ids: &BTreeSet<String>,
) -> Result<BTreeMap<String, Vec<DocumentJudgment>>> {
    let file = File::open(path).map_err(|error| EvalError::io(path, error))?;
    let reader = BufReader::new(file);
    let mut by_query: BTreeMap<String, Vec<DocumentJudgment>> = BTreeMap::new();
    let mut seen = BTreeSet::new();
    for (index, line) in reader.lines().enumerate() {
        let line_number = index + 1;
        let line = line.map_err(|error| EvalError::io(path, error))?;
        let line = line.strip_suffix('\r').unwrap_or(&line);
        if line_number == 1 {
            if line != "query-id\tcorpus-id\tscore" {
                return Err(EvalError::data(
                    "TSV",
                    format!("{}:{line_number}", display_path(path)),
                    "expected BEIR qrels header",
                ));
            }
            continue;
        }
        if line.is_empty() {
            return Err(EvalError::data(
                "TSV",
                format!("{}:{line_number}", display_path(path)),
                "blank qrels line",
            ));
        }
        let fields: Vec<_> = line.split('\t').collect();
        if fields.len() != 3 || fields[0].trim().is_empty() || fields[1].trim().is_empty() {
            return Err(EvalError::data(
                "TSV",
                format!("{}:{line_number}", display_path(path)),
                "expected three nonempty TSV columns",
            ));
        }
        let score = fields[2].parse::<u8>().map_err(|_| {
            EvalError::data(
                "TSV",
                format!("{}:{line_number}", display_path(path)),
                "grade must be an integer in 0..=3",
            )
        })?;
        if score > 3 {
            return Err(EvalError::data(
                "TSV",
                format!("{}:{line_number}", display_path(path)),
                "grade must be in 0..=3",
            ));
        }
        if !query_ids.contains(fields[0]) {
            return Err(EvalError::data(
                "DANGLING_REFERENCE",
                format!("{}:{line_number}", display_path(path)),
                "qrel references an unknown query",
            ));
        }
        if !documents.contains_key(fields[1]) {
            return Err(EvalError::data(
                "DANGLING_REFERENCE",
                format!("{}:{line_number}", display_path(path)),
                "qrel references an unknown document",
            ));
        }
        if !seen.insert((fields[0].to_owned(), fields[1].to_owned())) {
            return Err(EvalError::data(
                "DUPLICATE_ID",
                format!("{}:{line_number}", display_path(path)),
                "duplicate qrel",
            ));
        }
        by_query
            .entry(fields[0].to_owned())
            .or_default()
            .push(DocumentJudgment {
                query_id: fields[0].to_owned(),
                document_id: fields[1].to_owned(),
                grade: score,
                evidence_passage_ids: Vec::new(),
                subtopic_labels: Vec::new(),
            });
    }
    for rows in by_query.values_mut() {
        rows.sort_by(|left, right| left.document_id.cmp(&right.document_id));
    }
    Ok(by_query)
}

fn metadata_string<'a>(
    metadata: &'a serde_json::Value,
    key: &str,
    location: &str,
) -> Result<Option<&'a str>> {
    match metadata.get(key) {
        None => Ok(None),
        Some(serde_json::Value::String(value)) => Ok(Some(value)),
        Some(_) => Err(beir_error(location, format!("{key} must be a string"))),
    }
}
