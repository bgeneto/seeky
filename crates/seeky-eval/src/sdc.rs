//! Loader for the accepted Seeky Desktop Corpus format (SPEC-0003 R3/R4).

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use serde::Deserialize;

use crate::dataset::{
    Dataset, Document, DocumentId, DocumentJudgment, EvaluationConfiguration, LanguageSlice,
    Passage, PassageId, PassageJudgment, Query, QueryCategory, QueryId, Split,
};
use crate::error::{EvalError, Result, display_path};
use crate::qrels::{DocumentQrel, EvidenceSpan, PassageQrel, Provenance, validate_grade};
use crate::util::{
    canonical_json, is_regular_file, join_relative, normalize_relative_path, read_json, read_jsonl,
    sha256_file, sha256_hex, value_sha256,
};

const SIDECARS: [&str; 5] = [
    "corpus.jsonl",
    "passages.jsonl",
    "extraction-truth.jsonl",
    "duplicate-clusters.jsonl",
    "versions.jsonl",
];

#[derive(Debug, Deserialize)]
struct SdcManifest {
    schema_version: u32,
    corpus_id: String,
    profile_sha256: String,
    source_set_sha256: String,
    seed: String,
    generator_version: String,
    renderer_lock_sha256: String,
    document_count: usize,
    passage_count: usize,
    default_roots: Vec<String>,
    code_enabled_roots: Vec<String>,
    files: Vec<FileEntry>,
    sidecars: BTreeMap<String, String>,
    corpus_hash: String,
}

#[derive(Debug, Deserialize, serde::Serialize)]
struct FileEntry {
    path: String,
    byte_count: u64,
    sha256: String,
}

#[derive(Debug, Deserialize)]
struct DocumentRecord {
    #[serde(rename = "_id")]
    id: String,
    title: String,
    text: String,
    metadata: DocumentMetadata,
}

#[derive(Debug, Deserialize, serde::Serialize)]
struct DocumentMetadata {
    relative_path: String,
    media_type: String,
    format: String,
    languages: Vec<String>,
    file_class: String,
    source_set_id: String,
    source_item_id: String,
    source_sha256: String,
    content_sha256: String,
    text_sha256: String,
    byte_count: u64,
    modified_at: String,
    render_recipe_id: String,
    duplicate_cluster_ids: Vec<String>,
    version_group_id: Option<String>,
    version_number: Option<u32>,
    is_latest: Option<bool>,
    boilerplate_family_ids: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct PassageRecord {
    #[serde(rename = "_id")]
    id: String,
    document_id: String,
    text: String,
    start_utf8: u64,
    end_utf8: u64,
    text_sha256: String,
    kind: String,
    locator: serde_json::Value,
    boilerplate_family_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ExtractionTruthRecord {
    document_id: String,
    locator: serde_json::Value,
    text: String,
    text_sha256: String,
    truth_origin: String,
}

#[derive(Debug, Deserialize)]
pub(crate) struct DuplicateCluster {
    pub(crate) cluster_id: String,
    pub(crate) kind: String,
    pub(crate) canonical_document_id: String,
    pub(crate) member_document_ids: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct VersionGroup {
    version_group_id: String,
    members: Vec<VersionMember>,
}

#[derive(Debug, Deserialize)]
struct VersionMember {
    document_id: String,
    version_number: u32,
    is_latest: bool,
    changed_passages: Vec<VersionChange>,
}

#[derive(Debug, Deserialize)]
struct VersionChange {
    change: String,
    from_passage_id: Option<String>,
    to_passage_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct JudgmentSetManifest {
    schema_version: u32,
    judgment_set_id: String,
    state: String,
    split_seed: String,
    compatible_corpus_hashes: Vec<String>,
    query_counts: BTreeMap<String, u64>,
    #[serde(default)]
    query_file_sha256: BTreeMap<String, String>,
    file_sha256: BTreeMap<String, String>,
    #[serde(default)]
    test_pool_system_ids: Vec<String>,
    supersedes: Option<String>,
    test_exposure: String,
}

#[derive(Debug, Deserialize)]
struct QueryRecord {
    #[serde(rename = "_id")]
    id: String,
    text: String,
    language: String,
    target_languages: Vec<String>,
    language_slice: String,
    category: String,
    configuration: String,
    split: String,
    filters: Option<serde_json::Value>,
    provenance: Provenance,
}

fn manifest_error(location: &str, message: impl Into<String>) -> EvalError {
    EvalError::data("SCHEMA", location, message)
}

/// Load and validate an SDC corpus plus one frozen judgment set.
pub fn load_sdc(
    corpus_dir: &Path,
    judgment_set_dir: &Path,
    split: Split,
    configuration: EvaluationConfiguration,
) -> Result<Dataset> {
    let manifest_path = corpus_dir.join("manifest.json");
    let manifest: SdcManifest = read_json(&manifest_path)?;
    validate_manifest_shape(&manifest)?;
    validate_corpus_files(corpus_dir, &manifest)?;

    let documents = read_jsonl::<DocumentRecord>(&corpus_dir.join("corpus.jsonl"))?;
    let mut all_documents = BTreeMap::new();
    for (index, record) in documents.into_iter().enumerate() {
        let location = format!("corpus.jsonl:{}", index + 1);
        validate_document(&record, &location, &manifest)?;
        let metadata = serde_json::to_value(&record.metadata)
            .map_err(|error| EvalError::data("SCHEMA", &location, error.to_string()))?;
        let document = Document {
            id: record.id.clone(),
            title: record.title,
            text: record.text,
            relative_path: record.metadata.relative_path,
            source_code: record.metadata.file_class == "source_code",
            metadata,
        };
        if all_documents
            .insert(document.id.clone(), document)
            .is_some()
        {
            return Err(EvalError::data(
                "DUPLICATE_ID",
                location,
                "duplicate document ID",
            ));
        }
    }
    if all_documents.len() != manifest.document_count {
        return Err(manifest_error(
            "manifest.document_count",
            "document count does not match corpus.jsonl",
        ));
    }

    let passage_records = read_jsonl::<PassageRecord>(&corpus_dir.join("passages.jsonl"))?;
    let mut all_passages = BTreeMap::new();
    for (index, record) in passage_records.into_iter().enumerate() {
        let location = format!("passages.jsonl:{}", index + 1);
        validate_passage(&record, &location, &all_documents)?;
        let passage = Passage {
            id: record.id,
            document_id: record.document_id,
            text: record.text,
            start_utf8: record.start_utf8,
            end_utf8: record.end_utf8,
            kind: record.kind,
            locator: record.locator,
            boilerplate_family_id: record.boilerplate_family_id,
        };
        if all_passages.insert(passage.id.clone(), passage).is_some() {
            return Err(EvalError::data(
                "DUPLICATE_ID",
                location,
                "duplicate passage ID",
            ));
        }
    }
    if all_passages.len() != manifest.passage_count {
        return Err(manifest_error(
            "manifest.passage_count",
            "passage count does not match passages.jsonl",
        ));
    }

    let truth = read_jsonl::<ExtractionTruthRecord>(&corpus_dir.join("extraction-truth.jsonl"))?;
    for (index, record) in truth.iter().enumerate() {
        validate_extraction_truth(record, index + 1, &all_documents)?;
    }

    let clusters = read_jsonl::<DuplicateCluster>(&corpus_dir.join("duplicate-clusters.jsonl"))?;
    let (duplicate_families, cluster_kinds) = validate_clusters(&clusters, &all_documents)?;
    let versions = read_jsonl::<VersionGroup>(&corpus_dir.join("versions.jsonl"))?;
    validate_versions(&versions, &all_documents, &all_passages, &cluster_kinds)?;

    let judgment_manifest_path = judgment_set_dir.join("judgment-set.json");
    let judgment_manifest: JudgmentSetManifest = read_json(&judgment_manifest_path)?;
    validate_judgment_manifest(&judgment_manifest, &manifest, split)?;
    let judgment_set_hash = sha256_file(&judgment_manifest_path)?;

    let split_name = match split {
        Split::Dev => "dev",
        Split::Test => "test",
    };
    let queries_name = format!("queries.{split_name}.jsonl");
    let documents_qrels_name = format!("qrels.{split_name}.documents.jsonl");
    let passages_qrels_name = format!("qrels.{split_name}.passages.jsonl");
    for name in [&queries_name, &documents_qrels_name, &passages_qrels_name] {
        let expected = judgment_manifest.file_sha256.get(name).ok_or_else(|| {
            EvalError::data(
                "FROZEN_REQUIRED",
                format!("judgment-set.json:{name}"),
                "selected split file has no published hash",
            )
        })?;
        let path = judgment_set_dir.join(name);
        let actual = sha256_file(&path)?;
        if &actual != expected {
            return Err(EvalError::data(
                "HASH_MISMATCH",
                format!("judgment-set.json:{name}"),
                "published file digest differs",
            ));
        }
    }
    let query_hash = judgment_manifest
        .query_file_sha256
        .get(&queries_name)
        .ok_or_else(|| {
            EvalError::data(
                "FROZEN_REQUIRED",
                "judgment-set.json:query_file_sha256",
                "frozen judgment set does not pin the query file",
            )
        })?;
    if Some(query_hash) != judgment_manifest.file_sha256.get(&queries_name) {
        return Err(EvalError::data(
            "HASH_MISMATCH",
            "judgment-set.json:query_file_sha256",
            "query freeze hash differs from published hash",
        ));
    }

    let query_records = read_jsonl::<QueryRecord>(&judgment_set_dir.join(&queries_name))?;
    let mut published_query_ids = BTreeSet::new();
    let mut selected_queries = Vec::new();
    let mut selected_query_ids = BTreeSet::new();
    let published_count = query_records.len();
    for (index, record) in query_records.into_iter().enumerate() {
        let location = format!("{queries_name}:{}", index + 1);
        let query = validate_query(&record, &location, split)?;
        if !published_query_ids.insert(query.id.clone()) {
            return Err(EvalError::data(
                "DUPLICATE_ID",
                location,
                "duplicate query ID",
            ));
        }
        if configuration == EvaluationConfiguration::Default
            && query.configuration != EvaluationConfiguration::Default
        {
            continue;
        }
        selected_query_ids.insert(query.id.clone());
        selected_queries.push(query);
    }
    let expected_count = judgment_manifest
        .query_counts
        .get(split_name)
        .copied()
        .unwrap_or(0);
    if u64::try_from(published_count).unwrap_or(u64::MAX) != expected_count {
        return Err(EvalError::data(
            "SCHEMA",
            format!("judgment-set.json:query_counts.{split_name}"),
            "query count differs from the published split",
        ));
    }

    let document_qrels = read_jsonl::<DocumentQrel>(&judgment_set_dir.join(&documents_qrels_name))?;
    let passage_qrels = read_jsonl::<PassageQrel>(&judgment_set_dir.join(&passages_qrels_name))?;

    let selected_documents: BTreeMap<_, _> = all_documents
        .iter()
        .filter(|(_, document)| {
            configuration == EvaluationConfiguration::CodeEnabled || !document.source_code
        })
        .map(|(id, document)| (id.clone(), document.clone()))
        .collect();
    let selected_passages: BTreeMap<_, _> = all_passages
        .iter()
        .filter(|(_, passage)| selected_documents.contains_key(&passage.document_id))
        .map(|(id, passage)| (id.clone(), passage.clone()))
        .collect();

    let document_judgments = validate_document_qrels(
        &document_qrels,
        &documents_qrels_name,
        &judgment_manifest.judgment_set_id,
        &published_query_ids,
        &selected_queries,
        &all_documents,
        &selected_documents,
        &selected_passages,
    )?;
    let passage_judgments = validate_passage_qrels(
        &passage_qrels,
        &passages_qrels_name,
        &judgment_manifest.judgment_set_id,
        &published_query_ids,
        &selected_queries,
        &all_documents,
        &all_passages,
        &selected_documents,
        &selected_passages,
    )?;
    validate_evidence_targets(&document_judgments, &passage_judgments)?;

    let query_set_sha256 = sha256_hex(canonical_json(selected_queries.as_slice())?.as_bytes());
    let fingerprint_value = serde_json::json!({
        "corpus_hash": &manifest.corpus_hash,
        "judgment_set_id": &judgment_manifest.judgment_set_id,
        "judgment_set_hash": &judgment_set_hash,
        "query_set_sha256": &query_set_sha256,
    });
    let fingerprint = value_sha256(&fingerprint_value)?;

    Dataset::new(
        manifest.corpus_id,
        manifest.corpus_hash,
        fingerprint,
        judgment_manifest.judgment_set_id,
        judgment_set_hash,
        split,
        configuration,
        selected_documents.into_values(),
        selected_passages.into_values(),
        selected_queries,
        document_judgments,
        passage_judgments,
        duplicate_families,
        true,
    )
}

fn validate_manifest_shape(manifest: &SdcManifest) -> Result<()> {
    if manifest.schema_version != 1 {
        return Err(manifest_error(
            "manifest.schema_version",
            "unsupported schema version",
        ));
    }
    if manifest.corpus_id.trim().is_empty()
        || manifest.seed.trim().is_empty()
        || manifest.generator_version.trim().is_empty()
        || manifest.profile_sha256.len() != 64
        || manifest.source_set_sha256.len() != 64
        || manifest.renderer_lock_sha256.len() != 64
    {
        return Err(manifest_error(
            "manifest",
            "required identifiers or hashes are empty or malformed",
        ));
    }
    if manifest.default_roots != ["files/documents"]
        || manifest.code_enabled_roots != ["files/documents", "files/code"]
    {
        return Err(manifest_error(
            "manifest.roots",
            "unexpected default or code-enabled roots",
        ));
    }
    for name in SIDECARS {
        if !manifest.sidecars.contains_key(name) {
            return Err(manifest_error(
                "manifest.sidecars",
                format!("missing sidecar hash: {name}"),
            ));
        }
    }
    if manifest
        .sidecars
        .keys()
        .any(|name| !SIDECARS.contains(&name.as_str()))
    {
        return Err(manifest_error(
            "manifest.sidecars",
            "unexpected sidecar name",
        ));
    }
    if !manifest
        .files
        .windows(2)
        .all(|pair| pair[0].path <= pair[1].path)
    {
        return Err(manifest_error(
            "manifest.files",
            "corpus files are not path-sorted",
        ));
    }
    let expected_hash = value_sha256(&serde_json::json!({
        "files": &manifest.files,
        "sidecars": &manifest.sidecars,
        "default_roots": &manifest.default_roots,
        "code_enabled_roots": &manifest.code_enabled_roots,
    }))?;
    if expected_hash != manifest.corpus_hash {
        return Err(EvalError::data(
            "HASH_MISMATCH",
            "manifest.corpus_hash",
            "canonical corpus hash differs",
        ));
    }
    Ok(())
}

fn validate_corpus_files(corpus_dir: &Path, manifest: &SdcManifest) -> Result<()> {
    let mut expected = BTreeMap::new();
    for file in &manifest.files {
        let relative = normalize_relative_path(&file.path)?;
        if expected.insert(relative.clone(), file).is_some() {
            return Err(EvalError::data(
                "DUPLICATE_ID",
                relative,
                "duplicate corpus file entry",
            ));
        }
    }
    for name in SIDECARS {
        let expected_hash = manifest.sidecars.get(name).ok_or_else(|| {
            manifest_error("manifest.sidecars", format!("missing sidecar: {name}"))
        })?;
        let actual = sha256_file(&corpus_dir.join(name))?;
        if &actual != expected_hash {
            return Err(EvalError::data(
                "HASH_MISMATCH",
                name,
                "sidecar digest differs",
            ));
        }
    }
    for (relative, entry) in &expected {
        let path = join_relative(corpus_dir, relative)?;
        if !is_regular_file(&path) {
            return Err(EvalError::data(
                "SCHEMA",
                relative,
                "declared corpus file is missing",
            ));
        }
        let actual = sha256_file(&path)?;
        if actual != entry.sha256 {
            return Err(EvalError::data(
                "HASH_MISMATCH",
                relative,
                "corpus file digest differs",
            ));
        }
        if path.metadata().map(|meta| meta.len()).unwrap_or_default() != entry.byte_count {
            return Err(EvalError::data(
                "HASH_MISMATCH",
                relative,
                "corpus file byte count differs",
            ));
        }
    }
    let mut actual_files = BTreeSet::new();
    collect_files(corpus_dir, corpus_dir, &mut actual_files)?;
    for relative in actual_files {
        if relative == "manifest.json" || SIDECARS.contains(&relative.as_str()) {
            continue;
        }
        if !expected.contains_key(&relative) {
            return Err(EvalError::data(
                "SCHEMA",
                relative,
                "unexpected corpus output file",
            ));
        }
    }
    Ok(())
}

fn collect_files(root: &Path, current: &Path, files: &mut BTreeSet<String>) -> Result<()> {
    let entries = std::fs::read_dir(current).map_err(|error| EvalError::io(current, error))?;
    for entry in entries {
        let entry = entry.map_err(|error| EvalError::io(current, error))?;
        let path = entry.path();
        if path.is_dir() {
            collect_files(root, &path, files)?;
        } else if path.is_file() {
            let relative = path.strip_prefix(root).map_err(|_| {
                EvalError::data("SCHEMA", display_path(&path), "file outside corpus root")
            })?;
            files.insert(relative.to_string_lossy().replace('\\', "/"));
        }
    }
    Ok(())
}

fn validate_document(
    record: &DocumentRecord,
    location: &str,
    manifest: &SdcManifest,
) -> Result<()> {
    if record.id.trim().is_empty() || record.text.is_empty() {
        return Err(EvalError::data(
            "SCHEMA",
            location,
            "document ID and text must be nonempty",
        ));
    }
    let metadata = &record.metadata;
    let relative = normalize_relative_path(&metadata.relative_path)?;
    let file = manifest
        .files
        .iter()
        .find(|file| file.path == relative)
        .ok_or_else(|| {
            EvalError::data(
                "DANGLING_REFERENCE",
                location,
                "document path is not listed in the manifest",
            )
        })?;
    if metadata.content_sha256 != file.sha256 || metadata.byte_count != file.byte_count {
        return Err(EvalError::data(
            "HASH_MISMATCH",
            location,
            "document content hash or byte count differs from manifest",
        ));
    }
    if sha256_hex(record.text.as_bytes()) != metadata.text_sha256 {
        return Err(EvalError::data(
            "HASH_MISMATCH",
            location,
            "document text hash differs",
        ));
    }
    if metadata.file_class != "document" && metadata.file_class != "source_code" {
        return Err(EvalError::data("SCHEMA", location, "unknown file_class"));
    }
    for value in [
        &metadata.media_type,
        &metadata.format,
        &metadata.source_set_id,
        &metadata.source_item_id,
        &metadata.source_sha256,
        &metadata.modified_at,
        &metadata.render_recipe_id,
    ] {
        if value.trim().is_empty() {
            return Err(EvalError::data(
                "SCHEMA",
                location,
                "empty required document metadata",
            ));
        }
    }
    if metadata.languages.is_empty() {
        return Err(EvalError::data(
            "SCHEMA",
            location,
            "document languages are empty",
        ));
    }
    Ok(())
}

fn validate_passage(
    record: &PassageRecord,
    location: &str,
    documents: &BTreeMap<DocumentId, Document>,
) -> Result<()> {
    let document = documents.get(&record.document_id).ok_or_else(|| {
        EvalError::data("DANGLING_REFERENCE", location, "unknown passage document")
    })?;
    if record.start_utf8 >= record.end_utf8
        || record.end_utf8 > document.text.len() as u64
        || !document.text.is_char_boundary(record.start_utf8 as usize)
        || !document.text.is_char_boundary(record.end_utf8 as usize)
    {
        return Err(EvalError::data(
            "SCHEMA",
            location,
            "invalid canonical UTF-8 passage offsets",
        ));
    }
    let actual = &document.text[record.start_utf8 as usize..record.end_utf8 as usize];
    if actual != record.text || sha256_hex(record.text.as_bytes()) != record.text_sha256 {
        return Err(EvalError::data(
            "HASH_MISMATCH",
            location,
            "passage text does not match its document span and hash",
        ));
    }
    if !matches!(
        record.kind.as_str(),
        "heading" | "paragraph" | "list_item" | "table_cell" | "code" | "page" | "context"
    ) {
        return Err(EvalError::data("SCHEMA", location, "unknown passage kind"));
    }
    Ok(())
}

fn validate_extraction_truth(
    record: &ExtractionTruthRecord,
    line: usize,
    documents: &BTreeMap<DocumentId, Document>,
) -> Result<()> {
    let location = format!("extraction-truth.jsonl:{line}");
    if !documents.contains_key(&record.document_id) {
        return Err(EvalError::data(
            "DANGLING_REFERENCE",
            location,
            "unknown truth document",
        ));
    }
    if sha256_hex(record.text.as_bytes()) != record.text_sha256 {
        return Err(EvalError::data(
            "HASH_MISMATCH",
            location,
            "truth text hash differs",
        ));
    }
    if !record.locator.is_object() {
        return Err(EvalError::data(
            "SCHEMA",
            location,
            "truth locator must be an object",
        ));
    }
    if !matches!(
        record.truth_origin.as_str(),
        "generator-known" | "human-verified"
    ) {
        return Err(EvalError::data("SCHEMA", location, "unknown truth origin"));
    }
    Ok(())
}

pub(crate) fn validate_clusters(
    clusters: &[DuplicateCluster],
    documents: &BTreeMap<DocumentId, Document>,
) -> Result<(BTreeMap<DocumentId, String>, BTreeMap<String, String>)> {
    let mut adjacency: BTreeMap<DocumentId, BTreeSet<DocumentId>> = BTreeMap::new();
    let mut cluster_kinds = BTreeMap::new();
    for (index, cluster) in clusters.iter().enumerate() {
        let location = format!("duplicate-clusters.jsonl:{}", index + 1);
        if cluster.cluster_id.trim().is_empty()
            || !matches!(
                cluster.kind.as_str(),
                "exact_byte" | "exact_text" | "near_duplicate" | "version" | "scanned_variant"
            )
        {
            return Err(EvalError::data(
                "SCHEMA",
                location,
                "invalid duplicate cluster ID or kind",
            ));
        }
        if !cluster
            .member_document_ids
            .contains(&cluster.canonical_document_id)
        {
            return Err(EvalError::data(
                "DANGLING_REFERENCE",
                location,
                "canonical document is not a cluster member",
            ));
        }
        for member in &cluster.member_document_ids {
            let document = documents.get(member).ok_or_else(|| {
                EvalError::data(
                    "DANGLING_REFERENCE",
                    location.clone(),
                    "unknown cluster member",
                )
            })?;
            let listed = document
                .metadata
                .get("duplicate_cluster_ids")
                .and_then(serde_json::Value::as_array);
            if !listed.is_some_and(|ids| {
                ids.iter()
                    .any(|id| id.as_str() == Some(cluster.cluster_id.as_str()))
            }) {
                return Err(EvalError::data(
                    "SCHEMA",
                    &location,
                    "cluster member metadata does not list the cluster ID",
                ));
            }
            adjacency
                .entry(member.clone())
                .or_default()
                .extend(cluster.member_document_ids.iter().cloned());
        }
        if cluster_kinds
            .insert(cluster.cluster_id.clone(), cluster.kind.clone())
            .is_some()
        {
            return Err(EvalError::data(
                "DUPLICATE_ID",
                &location,
                "duplicate cluster ID",
            ));
        }
    }
    for document in documents.values() {
        if let Some(ids) = document
            .metadata
            .get("duplicate_cluster_ids")
            .and_then(serde_json::Value::as_array)
        {
            for id in ids {
                if id.as_str().is_none_or(|id| !cluster_kinds.contains_key(id)) {
                    return Err(EvalError::data(
                        "DANGLING_REFERENCE",
                        "duplicate-clusters.jsonl",
                        "document metadata lists an unknown cluster ID",
                    ));
                }
            }
        }
    }
    let mut families = BTreeMap::new();
    let mut visited = BTreeSet::new();
    for document_id in adjacency.keys() {
        if visited.contains(document_id) {
            continue;
        }
        let mut component = BTreeSet::new();
        let mut queue = vec![document_id.clone()];
        while let Some(current) = queue.pop() {
            if !component.insert(current.clone()) {
                continue;
            }
            if let Some(neighbors) = adjacency.get(&current) {
                queue.extend(neighbors.iter().cloned());
            }
        }
        visited.extend(component.iter().cloned());
        let key = component.iter().next().cloned().ok_or_else(|| {
            EvalError::data("SCHEMA", "duplicate-clusters.jsonl", "empty component")
        })?;
        for member in component {
            families.insert(member, key.clone());
        }
    }
    Ok((families, cluster_kinds))
}

fn validate_versions(
    groups: &[VersionGroup],
    documents: &BTreeMap<DocumentId, Document>,
    passages: &BTreeMap<PassageId, Passage>,
    cluster_kinds: &BTreeMap<String, String>,
) -> Result<()> {
    for (index, group) in groups.iter().enumerate() {
        let location = format!("versions.jsonl:{}", index + 1);
        if cluster_kinds
            .get(&group.version_group_id)
            .map(String::as_str)
            != Some("version")
        {
            return Err(EvalError::data(
                "DANGLING_REFERENCE",
                &location,
                "version group has no matching version cluster",
            ));
        }
        let mut seen_versions = BTreeSet::new();
        let mut latest = 0;
        for member in &group.members {
            let document = documents.get(&member.document_id).ok_or_else(|| {
                EvalError::data("DANGLING_REFERENCE", &location, "unknown version document")
            })?;
            if member.version_number == 0 || !seen_versions.insert(member.version_number) {
                return Err(EvalError::data(
                    "SCHEMA",
                    &location,
                    "version numbers must be unique positive integers",
                ));
            }
            if member.is_latest {
                latest += 1;
            }
            for (change_index, change) in member.changed_passages.iter().enumerate() {
                let change_location = format!("{location}.changed_passages[{change_index}]");
                if !matches!(change.change.as_str(), "added" | "removed" | "modified") {
                    return Err(EvalError::data(
                        "SCHEMA",
                        change_location,
                        "unknown version change kind",
                    ));
                }
                if let Some(id) = &change.from_passage_id {
                    let passage = passages.get(id).ok_or_else(|| {
                        EvalError::data(
                            "DANGLING_REFERENCE",
                            &change_location,
                            "unknown previous passage",
                        )
                    })?;
                    if !documents.contains_key(&passage.document_id) {
                        return Err(EvalError::data(
                            "DANGLING_REFERENCE",
                            &change_location,
                            "previous passage document is missing",
                        ));
                    }
                }
                if let Some(id) = &change.to_passage_id {
                    let passage = passages.get(id).ok_or_else(|| {
                        EvalError::data(
                            "DANGLING_REFERENCE",
                            &change_location,
                            "unknown next passage",
                        )
                    })?;
                    if !documents.contains_key(&passage.document_id) {
                        return Err(EvalError::data(
                            "DANGLING_REFERENCE",
                            &change_location,
                            "next passage document is missing",
                        ));
                    }
                }
                if change.change == "modified"
                    && (change.from_passage_id.is_none() || change.to_passage_id.is_none())
                {
                    return Err(EvalError::data(
                        "SCHEMA",
                        change_location,
                        "modified change requires both passage IDs",
                    ));
                }
            }
            let group_metadata = document
                .metadata
                .get("version_group_id")
                .and_then(serde_json::Value::as_str);
            if group_metadata != Some(group.version_group_id.as_str()) {
                return Err(EvalError::data(
                    "SCHEMA",
                    &location,
                    "document metadata version group differs",
                ));
            }
        }
        if latest != 1
            || seen_versions.is_empty()
            || *seen_versions.iter().next().unwrap_or(&0) != 1
            || seen_versions.len()
                != usize::try_from(*seen_versions.iter().next_back().unwrap_or(&0))
                    .unwrap_or(usize::MAX)
        {
            return Err(EvalError::data(
                "SCHEMA",
                &location,
                "versions must be consecutive and have exactly one latest member",
            ));
        }
    }
    Ok(())
}

fn validate_judgment_manifest(
    manifest: &JudgmentSetManifest,
    corpus: &SdcManifest,
    split: Split,
) -> Result<()> {
    if manifest.schema_version != 1
        || manifest.judgment_set_id.trim().is_empty()
        || manifest.split_seed.trim().is_empty()
        || !matches!(manifest.state.as_str(), "frozen")
    {
        return Err(EvalError::data(
            "FROZEN_REQUIRED",
            "judgment-set.json",
            "judgment set is not a valid frozen schema-v1 set",
        ));
    }
    if !manifest
        .compatible_corpus_hashes
        .iter()
        .any(|hash| hash == &corpus.corpus_hash)
    {
        return Err(EvalError::data(
            "HASH_MISMATCH",
            "judgment-set.json:compatible_corpus_hashes",
            "corpus hash is not compatible with this judgment set",
        ));
    }
    if !matches!(
        manifest.test_exposure.as_str(),
        "unexposed" | "exposed" | "not-applicable"
    ) {
        return Err(EvalError::data(
            "SCHEMA",
            "judgment-set.json:test_exposure",
            "unknown exposure state",
        ));
    }
    if split == Split::Test && manifest.test_exposure == "not-applicable" {
        return Err(EvalError::data(
            "FROZEN_REQUIRED",
            "judgment-set.json:test_exposure",
            "test is not applicable for this judgment set",
        ));
    }
    if manifest.supersedes.as_deref().is_some_and(str::is_empty) {
        return Err(EvalError::data(
            "SCHEMA",
            "judgment-set.json:supersedes",
            "supersedes must be null or nonempty",
        ));
    }
    let _ = manifest.test_pool_system_ids.len();
    Ok(())
}

fn validate_query(record: &QueryRecord, location: &str, split: Split) -> Result<Query> {
    if record.id.trim().is_empty() || record.text.is_empty() {
        return Err(EvalError::data(
            "SCHEMA",
            location,
            "query ID and text must be nonempty",
        ));
    }
    if record.language.trim().is_empty() {
        return Err(EvalError::data(
            "SCHEMA",
            location,
            "query language is empty",
        ));
    }
    let query_split = match record.split.as_str() {
        "dev" => Split::Dev,
        "test" => Split::Test,
        _ => {
            return Err(EvalError::data("SCHEMA", location, "unknown query split"));
        }
    };
    if query_split != split {
        return Err(EvalError::data(
            "SCHEMA",
            location,
            "query split differs from requested split",
        ));
    }
    let query_configuration = EvaluationConfiguration::parse(&record.configuration)
        .map_err(|_| EvalError::data("SCHEMA", location, "unknown evaluation configuration"))?;
    let category = QueryCategory::parse(&record.category)?;
    if category == QueryCategory::CodeSearch
        && query_configuration != EvaluationConfiguration::CodeEnabled
    {
        return Err(EvalError::data(
            "SCHEMA",
            location,
            "code_search queries must use code_enabled",
        ));
    }
    let language_slice = LanguageSlice::parse(&record.language_slice)?;
    if record.filters.is_some() && category != QueryCategory::MixedSemanticMetadata {
        return Err(EvalError::data(
            "SCHEMA",
            location,
            "filters are only valid on mixed_semantic_metadata",
        ));
    }
    if let Some(filters) = &record.filters {
        validate_filters(filters, location)?;
    }
    record.provenance.validate_gate_eligible(location)?;
    Ok(Query {
        id: record.id.clone(),
        text: record.text.clone(),
        language: record.language.clone(),
        target_languages: record.target_languages.clone(),
        language_slice,
        category,
        configuration: query_configuration,
        split: query_split,
        filters: record.filters.clone(),
    })
}

fn validate_filters(filters: &serde_json::Value, location: &str) -> Result<()> {
    let object = filters
        .as_object()
        .ok_or_else(|| EvalError::data("SCHEMA", location, "filters must be a JSON object"))?;
    let allowed = [
        "extensions",
        "modified_after",
        "modified_before",
        "folder_prefix",
        "min_bytes",
        "max_bytes",
    ];
    if object.is_empty() || object.keys().any(|key| !allowed.contains(&key.as_str())) {
        return Err(EvalError::data(
            "SCHEMA",
            location,
            "filter object is empty or has an unknown key",
        ));
    }
    if let Some(folder) = object
        .get("folder_prefix")
        .and_then(serde_json::Value::as_str)
    {
        normalize_relative_path(folder)?;
    }
    for key in ["modified_after", "modified_before"] {
        if let Some(value) = object.get(key)
            && !value.is_string()
        {
            return Err(EvalError::data(
                "SCHEMA",
                location,
                format!("{key} must be a timestamp string"),
            ));
        }
    }
    for key in ["min_bytes", "max_bytes"] {
        if let Some(value) = object.get(key)
            && !value.is_u64()
        {
            return Err(EvalError::data(
                "SCHEMA",
                location,
                format!("{key} must be a nonnegative integer"),
            ));
        }
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn validate_document_qrels(
    records: &[DocumentQrel],
    source: &str,
    judgment_set_id: &str,
    published_query_ids: &BTreeSet<QueryId>,
    queries: &[Query],
    all_documents: &BTreeMap<DocumentId, Document>,
    documents: &BTreeMap<DocumentId, Document>,
    passages: &BTreeMap<PassageId, Passage>,
) -> Result<BTreeMap<QueryId, Vec<DocumentJudgment>>> {
    let query_map: BTreeMap<_, _> = queries.iter().map(|query| (&query.id, query)).collect();
    let mut by_query: BTreeMap<QueryId, Vec<DocumentJudgment>> = BTreeMap::new();
    let mut seen = BTreeSet::new();
    for (index, record) in records.iter().enumerate() {
        let location = format!("{source}:{}", index + 1);
        if record.judgment_set_id != judgment_set_id {
            return Err(EvalError::data(
                "SCHEMA",
                &location,
                "qrel judgment_set_id differs from manifest",
            ));
        }
        if !published_query_ids.contains(&record.query_id) {
            return Err(EvalError::data(
                "DANGLING_REFERENCE",
                &location,
                "qrel references a query outside the published split",
            ));
        }
        validate_grade(record.grade, &location)?;
        record.provenance.validate_gate_eligible(&location)?;
        let all_document = all_documents.get(&record.document_id).ok_or_else(|| {
            EvalError::data(
                "DANGLING_REFERENCE",
                &location,
                "qrel references an unknown document",
            )
        })?;
        let text_hash = all_document
            .metadata
            .get("text_sha256")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default();
        if text_hash != record.document_text_sha256 {
            return Err(EvalError::data(
                "HASH_MISMATCH",
                &location,
                "document qrel text hash is stale",
            ));
        }
        let Some(query) = query_map.get(&record.query_id) else {
            // A code-enabled query is omitted from the default configuration.
            continue;
        };
        let Some(_document) = documents.get(&record.document_id) else {
            // A source-code document is omitted from the default configuration.
            continue;
        };
        if !seen.insert((record.query_id.clone(), record.document_id.clone())) {
            return Err(EvalError::data(
                "DUPLICATE_ID",
                &location,
                "duplicate document judgment",
            ));
        }
        if record.grade == 0 && !record.evidence_passage_ids.is_empty() {
            return Err(EvalError::data(
                "SCHEMA",
                &location,
                "grade 0 must not carry evidence passages",
            ));
        }
        if record.grade >= 2 && record.evidence_passage_ids.is_empty() {
            return Err(EvalError::data(
                "SCHEMA",
                &location,
                "grades 2 and 3 require evidence passages",
            ));
        }
        let mut labels = BTreeSet::new();
        for label in &record.subtopic_labels {
            if !is_snake_label(label) {
                return Err(EvalError::data(
                    "SCHEMA",
                    &location,
                    "subtopic labels must be ASCII snake_case",
                ));
            }
            if !labels.insert(label) {
                return Err(EvalError::data(
                    "SCHEMA",
                    &location,
                    "duplicate subtopic label",
                ));
            }
        }
        if query.category != QueryCategory::Exploratory && !labels.is_empty() {
            return Err(EvalError::data(
                "SCHEMA",
                &location,
                "subtopic labels are only valid for exploratory queries",
            ));
        }
        if query.category == QueryCategory::Exploratory && record.grade >= 2 && labels.is_empty() {
            return Err(EvalError::data(
                "SCHEMA",
                &location,
                "exploratory relevant judgments require subtopic labels",
            ));
        }
        for evidence_id in &record.evidence_passage_ids {
            let passage = passages.get(evidence_id).ok_or_else(|| {
                EvalError::data(
                    "DANGLING_REFERENCE",
                    &location,
                    "qrel evidence passage is missing",
                )
            })?;
            if passage.document_id != record.document_id {
                return Err(EvalError::data(
                    "DANGLING_REFERENCE",
                    &location,
                    "evidence passage belongs to another document",
                ));
            }
        }
        by_query
            .entry(record.query_id.clone())
            .or_default()
            .push(DocumentJudgment {
                query_id: record.query_id.clone(),
                document_id: record.document_id.clone(),
                grade: record.grade,
                evidence_passage_ids: record.evidence_passage_ids.clone(),
                subtopic_labels: record.subtopic_labels.clone(),
            });
    }
    for rows in by_query.values_mut() {
        rows.sort_by(|left, right| left.document_id.cmp(&right.document_id));
    }
    Ok(by_query)
}

#[allow(clippy::too_many_arguments)]
fn validate_passage_qrels(
    records: &[PassageQrel],
    source: &str,
    judgment_set_id: &str,
    published_query_ids: &BTreeSet<QueryId>,
    queries: &[Query],
    all_documents: &BTreeMap<DocumentId, Document>,
    all_passages: &BTreeMap<PassageId, Passage>,
    documents: &BTreeMap<DocumentId, Document>,
    passages: &BTreeMap<PassageId, Passage>,
) -> Result<BTreeMap<QueryId, Vec<PassageJudgment>>> {
    let query_ids: BTreeSet<_> = queries.iter().map(|query| &query.id).collect();
    let mut by_query: BTreeMap<QueryId, Vec<PassageJudgment>> = BTreeMap::new();
    let mut seen = BTreeSet::new();
    for (index, record) in records.iter().enumerate() {
        let location = format!("{source}:{}", index + 1);
        if record.judgment_set_id != judgment_set_id {
            return Err(EvalError::data(
                "SCHEMA",
                &location,
                "qrel judgment_set_id differs from manifest",
            ));
        }
        if !published_query_ids.contains(&record.query_id) {
            return Err(EvalError::data(
                "DANGLING_REFERENCE",
                &location,
                "passage qrel references a query outside the published split",
            ));
        }
        validate_grade(record.grade, &location)?;
        record.provenance.validate_gate_eligible(&location)?;
        if !all_documents.contains_key(&record.document_id) {
            return Err(EvalError::data(
                "DANGLING_REFERENCE",
                &location,
                "passage qrel references an unknown document",
            ));
        }
        let all_passage = all_passages.get(&record.passage_id).ok_or_else(|| {
            EvalError::data(
                "DANGLING_REFERENCE",
                &location,
                "passage qrel references an unknown passage",
            )
        })?;
        if all_passage.document_id != record.document_id {
            return Err(EvalError::data(
                "DANGLING_REFERENCE",
                &location,
                "passage qrel document differs from passage owner",
            ));
        }
        if sha256_hex(all_passage.text.as_bytes()) != record.passage_text_sha256 {
            return Err(EvalError::data(
                "HASH_MISMATCH",
                &location,
                "passage qrel text hash is stale",
            ));
        }
        validate_spans(
            &record.evidence_spans,
            all_passage.text.len() as u64,
            &location,
        )?;
        if !query_ids.contains(&record.query_id) {
            // A code-enabled query is omitted from the default configuration.
            continue;
        }
        if !documents.contains_key(&record.document_id)
            || !passages.contains_key(&record.passage_id)
        {
            // The target belongs to a file excluded by the configuration.
            continue;
        }
        if !seen.insert((record.query_id.clone(), record.passage_id.clone())) {
            return Err(EvalError::data(
                "DUPLICATE_ID",
                &location,
                "duplicate passage judgment",
            ));
        }
        by_query
            .entry(record.query_id.clone())
            .or_default()
            .push(PassageJudgment {
                query_id: record.query_id.clone(),
                document_id: record.document_id.clone(),
                passage_id: record.passage_id.clone(),
                grade: record.grade,
            });
    }
    for rows in by_query.values_mut() {
        rows.sort_by(|left, right| left.passage_id.cmp(&right.passage_id));
    }
    Ok(by_query)
}

fn validate_spans(spans: &[EvidenceSpan], text_len: u64, location: &str) -> Result<()> {
    let mut previous_end = 0;
    for span in spans {
        if span.start_utf8 >= span.end_utf8
            || span.end_utf8 > text_len
            || span.start_utf8 < previous_end
        {
            return Err(EvalError::data(
                "SCHEMA",
                location,
                "evidence spans must be ordered, nonoverlapping, in-bounds, and nonempty",
            ));
        }
        previous_end = span.end_utf8;
    }
    Ok(())
}

fn validate_evidence_targets(
    documents: &BTreeMap<QueryId, Vec<DocumentJudgment>>,
    passages: &BTreeMap<QueryId, Vec<PassageJudgment>>,
) -> Result<()> {
    for (query_id, rows) in documents {
        let positive_passages: BTreeSet<_> = passages
            .get(query_id)
            .into_iter()
            .flatten()
            .filter(|judgment| judgment.grade > 0)
            .map(|judgment| judgment.passage_id.as_str())
            .collect();
        for row in rows {
            for evidence in &row.evidence_passage_ids {
                if !positive_passages.contains(evidence.as_str()) {
                    return Err(EvalError::data(
                        "DANGLING_REFERENCE",
                        "qrels",
                        "document evidence has no matching positive passage judgment",
                    ));
                }
            }
        }
    }
    Ok(())
}

fn is_snake_label(label: &str) -> bool {
    !label.is_empty()
        && label
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
        && !label.starts_with('_')
        && !label.ends_with('_')
        && !label.contains("__")
}

#[cfg(test)]
mod tests {
    // Integration-level fixture construction lives in `tests/sdc_loader.rs`.
    use super::*;

    #[test]
    fn snake_labels_are_strict() {
        assert!(is_snake_label("topic_1"));
        assert!(!is_snake_label("Topic"));
        assert!(!is_snake_label("_topic"));
        assert!(!is_snake_label("a__b"));
    }

    #[test]
    fn unsupported_sdc_schema_is_rejected() {
        let mut manifest = SdcManifest {
            schema_version: 2,
            corpus_id: "x".to_owned(),
            profile_sha256: "0".repeat(64),
            source_set_sha256: "0".repeat(64),
            seed: "seed".to_owned(),
            generator_version: "1".to_owned(),
            renderer_lock_sha256: "0".repeat(64),
            document_count: 0,
            passage_count: 0,
            default_roots: vec!["files/documents".to_owned()],
            code_enabled_roots: vec!["files/documents".to_owned(), "files/code".to_owned()],
            files: Vec::new(),
            sidecars: BTreeMap::new(),
            corpus_hash: "0".repeat(64),
        };
        assert_eq!(
            validate_manifest_shape(&manifest).unwrap_err().code(),
            "SCHEMA"
        );
        manifest.schema_version = 1;
        assert!(validate_manifest_shape(&manifest).is_err());
    }
}
