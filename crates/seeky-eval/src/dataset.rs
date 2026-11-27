//! Validated dataset model and public accessors (SPEC-0003 R1).

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::error::{EvalError, Result};
use crate::util::{canonical_json, sha256_hex};

/// Dataset split.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Split {
    Dev,
    Test,
}

/// Evaluation configuration; code is measured separately from the default.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvaluationConfiguration {
    Default,
    CodeEnabled,
}

/// The nine accepted SDC query categories.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QueryCategory {
    KnownItem,
    Conceptual,
    ExactIdentifier,
    CrossLanguage,
    NeedleInHaystack,
    Exploratory,
    MixedSemanticMetadata,
    CodeSearch,
    FilenamePartial,
}

impl EvaluationConfiguration {
    pub(crate) fn parse(value: &str) -> Result<Self> {
        match value {
            "default" => Ok(Self::Default),
            "code_enabled" => Ok(Self::CodeEnabled),
            _ => Err(EvalError::data(
                "SCHEMA",
                "configuration",
                format!("unknown evaluation configuration: {value}"),
            )),
        }
    }

    /// Stable wire/report ID.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Default => "default",
            Self::CodeEnabled => "code_enabled",
        }
    }
}

impl QueryCategory {
    /// Stable wire/report ID.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::KnownItem => "known_item",
            Self::Conceptual => "conceptual",
            Self::ExactIdentifier => "exact_identifier",
            Self::CrossLanguage => "cross_language",
            Self::NeedleInHaystack => "needle_in_haystack",
            Self::Exploratory => "exploratory",
            Self::MixedSemanticMetadata => "mixed_semantic_metadata",
            Self::CodeSearch => "code_search",
            Self::FilenamePartial => "filename_partial",
        }
    }

    /// Parse a stable wire/report ID.
    pub(crate) fn parse(value: &str) -> Result<Self> {
        match value {
            "known_item" => Ok(Self::KnownItem),
            "conceptual" => Ok(Self::Conceptual),
            "exact_identifier" => Ok(Self::ExactIdentifier),
            "cross_language" => Ok(Self::CrossLanguage),
            "needle_in_haystack" => Ok(Self::NeedleInHaystack),
            "exploratory" => Ok(Self::Exploratory),
            "mixed_semantic_metadata" => Ok(Self::MixedSemanticMetadata),
            "code_search" => Ok(Self::CodeSearch),
            "filename_partial" => Ok(Self::FilenamePartial),
            _ => Err(EvalError::data(
                "SCHEMA",
                "category",
                format!("unknown query category: {value}"),
            )),
        }
    }
}

/// Reported language slice.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LanguageSlice {
    Pt,
    En,
    CrossLingual,
    Other,
    NonLatinNonRegression,
}

impl LanguageSlice {
    /// Stable wire/report ID.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Pt => "pt",
            Self::En => "en",
            Self::CrossLingual => "cross_lingual",
            Self::Other => "other",
            Self::NonLatinNonRegression => "non_latin_non_regression",
        }
    }

    /// Parse a stable wire/report ID.
    pub(crate) fn parse(value: &str) -> Result<Self> {
        match value {
            "pt" => Ok(Self::Pt),
            "en" => Ok(Self::En),
            "cross_lingual" => Ok(Self::CrossLingual),
            "other" => Ok(Self::Other),
            "non_latin_non_regression" => Ok(Self::NonLatinNonRegression),
            _ => Err(EvalError::data(
                "SCHEMA",
                "language_slice",
                format!("unknown language slice: {value}"),
            )),
        }
    }
}

/// Document identifier (opaque).
pub type DocumentId = String;
/// Passage identifier (opaque).
pub type PassageId = String;
/// Query identifier (opaque).
pub type QueryId = String;

/// A validated corpus document.
#[derive(Clone, Debug)]
pub struct Document {
    /// Stable document ID.
    pub id: DocumentId,
    /// Canonical title.
    pub title: String,
    /// Canonical NFC/LF text.
    pub text: String,
    /// Corpus-relative POSIX path used by the engine.
    pub relative_path: String,
    /// Whether ADR-0024 classifies this as source code.
    pub source_code: bool,
    /// Additional validated metadata used by filters and reports.
    pub metadata: serde_json::Value,
}

/// A canonical gold passage, independent of engine chunking.
#[derive(Clone, Debug)]
pub struct Passage {
    /// Stable passage ID.
    pub id: PassageId,
    /// Owning document.
    pub document_id: DocumentId,
    /// Exact canonical passage text.
    pub text: String,
    /// Zero-based UTF-8 byte start in the document text.
    pub start_utf8: u64,
    /// Exclusive UTF-8 byte end in the document text.
    pub end_utf8: u64,
    /// SPEC-0004 kind (`paragraph`, `context`, …).
    pub kind: String,
    /// Canonical locator object.
    pub locator: serde_json::Value,
    /// Boilerplate family, when applicable.
    pub boilerplate_family_id: Option<String>,
}

/// A selected query.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Query {
    /// Stable query ID.
    pub id: QueryId,
    /// Query text.
    pub text: String,
    /// Query language (BCP-47 when available).
    pub language: String,
    /// Evidence/target languages.
    pub target_languages: Vec<String>,
    /// Reporting language slice.
    pub language_slice: LanguageSlice,
    /// Query category.
    pub category: QueryCategory,
    /// Evaluation configuration.
    pub configuration: EvaluationConfiguration,
    /// Selected split.
    pub split: Split,
    /// Structured metadata filters, if any.
    pub filters: Option<serde_json::Value>,
}

/// A graded document judgment.
#[derive(Clone, Debug)]
pub struct DocumentJudgment {
    /// Query.
    pub query_id: QueryId,
    /// Document.
    pub document_id: DocumentId,
    /// Grade 0–3; an explicit zero is different from absence.
    pub grade: u8,
    /// Canonical evidence passages.
    pub evidence_passage_ids: Vec<PassageId>,
    /// Verified diversity labels.
    pub subtopic_labels: Vec<String>,
}

/// A graded passage judgment.
#[derive(Clone, Debug)]
pub struct PassageJudgment {
    /// Query.
    pub query_id: QueryId,
    /// Document.
    pub document_id: DocumentId,
    /// Canonical passage.
    pub passage_id: PassageId,
    /// Grade 0–3.
    pub grade: u8,
}

/// A validated dataset selected for one split and configuration.
#[derive(Clone, Debug)]
pub struct Dataset {
    /// Dataset identifier.
    pub id: String,
    /// Corpus hash from the manifest or BEIR corpus file.
    pub corpus_hash: String,
    /// Dataset fingerprint used to bind paired evaluations.
    pub fingerprint: String,
    /// Judgment-set identifier.
    pub judgment_set_id: String,
    /// Judgment-set manifest hash.
    pub judgment_set_hash: String,
    /// Selected split.
    pub split: Split,
    /// Selected configuration.
    pub configuration: EvaluationConfiguration,

    documents: BTreeMap<DocumentId, Document>,
    documents_by_path: BTreeMap<String, DocumentId>,
    passages: BTreeMap<PassageId, Passage>,
    passages_by_document: BTreeMap<DocumentId, Vec<PassageId>>,
    queries: Vec<Query>,
    query_ids: BTreeSet<QueryId>,
    document_judgments: BTreeMap<QueryId, Vec<DocumentJudgment>>,
    passage_judgments: BTreeMap<QueryId, Vec<PassageJudgment>>,
    duplicate_families: BTreeMap<DocumentId, String>,
    duplicate_heavy_query_ids: Vec<QueryId>,
    duplicate_metrics_available: bool,
    query_set_sha256: String,
}

impl Dataset {
    /// Construct a dataset from already validated parts.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        id: String,
        corpus_hash: String,
        fingerprint: String,
        judgment_set_id: String,
        judgment_set_hash: String,
        split: Split,
        configuration: EvaluationConfiguration,
        documents: impl IntoIterator<Item = Document>,
        passages: impl IntoIterator<Item = Passage>,
        mut queries: Vec<Query>,
        document_judgments: BTreeMap<QueryId, Vec<DocumentJudgment>>,
        passage_judgments: BTreeMap<QueryId, Vec<PassageJudgment>>,
        duplicate_families: BTreeMap<DocumentId, String>,
        duplicate_metrics_available: bool,
    ) -> Result<Self> {
        let documents: BTreeMap<_, _> = documents
            .into_iter()
            .map(|document| (document.id.clone(), document))
            .collect();
        let mut documents_by_path = BTreeMap::new();
        for document in documents.values() {
            if !document.relative_path.is_empty()
                && documents_by_path
                    .insert(document.relative_path.clone(), document.id.clone())
                    .is_some()
            {
                return Err(EvalError::data(
                    "DUPLICATE_ID",
                    "corpus",
                    "duplicate relative_path",
                ));
            }
        }
        let passages: BTreeMap<_, _> = passages
            .into_iter()
            .map(|passage| (passage.id.clone(), passage))
            .collect();
        let mut passages_by_document: BTreeMap<DocumentId, Vec<PassageId>> = BTreeMap::new();
        for passage in passages.values() {
            passages_by_document
                .entry(passage.document_id.clone())
                .or_default()
                .push(passage.id.clone());
        }
        queries.sort_by(|left, right| left.id.cmp(&right.id));
        let query_ids = queries.iter().map(|query| query.id.clone()).collect();
        let query_set_sha256 = compute_query_set_sha256(&queries)?;
        let duplicate_heavy_query_ids =
            duplicate_heavy_queries(&query_ids, &document_judgments, &duplicate_families);
        Ok(Self {
            id,
            corpus_hash,
            fingerprint,
            judgment_set_id,
            judgment_set_hash,
            split,
            configuration,
            documents,
            documents_by_path,
            passages,
            passages_by_document,
            queries,
            query_ids,
            document_judgments,
            passage_judgments,
            duplicate_families,
            duplicate_heavy_query_ids,
            duplicate_metrics_available,
            query_set_sha256,
        })
    }

    /// Look up a document.
    #[must_use]
    pub fn document(&self, id: &str) -> Option<&Document> {
        self.documents.get(id)
    }

    /// Look up a document by corpus-relative engine path.
    #[must_use]
    pub fn document_by_path(&self, relative_path: &str) -> Option<&Document> {
        self.documents_by_path
            .get(relative_path)
            .and_then(|id| self.documents.get(id))
    }

    /// Look up a passage.
    #[must_use]
    pub fn passage(&self, id: &str) -> Option<&Passage> {
        self.passages.get(id)
    }

    /// All selected queries in deterministic order.
    #[must_use]
    pub fn queries(&self) -> &[Query] {
        &self.queries
    }

    /// Whether a query is in the selected split/configuration.
    #[must_use]
    pub fn contains_query(&self, id: &str) -> bool {
        self.query_ids.contains(id)
    }

    /// Document judgments for one query.
    #[must_use]
    pub fn document_judgments(&self, query_id: &str) -> &[DocumentJudgment] {
        self.document_judgments
            .get(query_id)
            .map_or(&[], Vec::as_slice)
    }

    /// Passage judgments for one query.
    #[must_use]
    pub fn passage_judgments(&self, query_id: &str) -> &[PassageJudgment] {
        self.passage_judgments
            .get(query_id)
            .map_or(&[], Vec::as_slice)
    }

    /// Duplicate-family component for a document.
    #[must_use]
    pub fn duplicate_family(&self, document_id: &str) -> Option<&str> {
        self.duplicate_families.get(document_id).map(String::as_str)
    }

    /// Queries with at least one positive judgment in a nontrivial family.
    #[must_use]
    pub fn duplicate_heavy_query_ids(&self) -> &[QueryId] {
        &self.duplicate_heavy_query_ids
    }

    /// Whether duplicate-cluster labels were supplied for this dataset.
    #[must_use]
    pub const fn duplicate_metrics_available(&self) -> bool {
        self.duplicate_metrics_available
    }

    /// Canonical selected query-set hash.
    #[must_use]
    pub fn query_set_sha256(&self) -> &str {
        &self.query_set_sha256
    }

    /// Passages belonging to a document, ordered by canonical offset.
    #[must_use]
    pub fn passages_for_document(&self, document_id: &str) -> Vec<&Passage> {
        self.passages_by_document
            .get(document_id)
            .map(|ids| {
                let mut passages: Vec<_> =
                    ids.iter().filter_map(|id| self.passages.get(id)).collect();
                passages.sort_by(|left, right| {
                    (left.start_utf8, left.end_utf8, &left.id).cmp(&(
                        right.start_utf8,
                        right.end_utf8,
                        &right.id,
                    ))
                });
                passages
            })
            .unwrap_or_default()
    }

    /// Map an engine chunk's character span to at most one canonical passage.
    ///
    /// The largest byte intersection wins; ties choose the smaller passage ID.
    /// Context passages are never targets. A page filter applies only when both
    /// the chunk and passage have a page.
    pub fn map_chunk_to_passage(
        &self,
        document_id: &str,
        start_char: u64,
        end_char: u64,
        page: Option<u32>,
    ) -> Result<Option<&Passage>> {
        let document = self
            .document(document_id)
            .ok_or_else(|| EvalError::data("DANGLING_REFERENCE", "chunk", "unknown document ID"))?;
        let start = usize::try_from(start_char)
            .ok()
            .and_then(|index| char_index_to_byte(&document.text, index))
            .ok_or_else(|| {
                EvalError::data("SCHEMA", "chunk.start", "character offset out of bounds")
            })? as u64;
        let end = usize::try_from(end_char)
            .ok()
            .and_then(|index| char_index_to_byte(&document.text, index))
            .ok_or_else(|| {
                EvalError::data("SCHEMA", "chunk.end", "character offset out of bounds")
            })? as u64;
        if start >= end {
            return Err(EvalError::data("SCHEMA", "chunk", "start must precede end"));
        }
        let mut best: Option<(u64, &Passage)> = None;
        for passage in self.passages_for_document(document_id) {
            if passage.kind == "context" {
                continue;
            }
            if let (Some(chunk_page), Some(passage_page)) = (
                page,
                passage
                    .locator
                    .get("page")
                    .and_then(serde_json::Value::as_u64),
            ) && u64::from(chunk_page) != passage_page
            {
                continue;
            }
            let intersection = end
                .min(passage.end_utf8)
                .saturating_sub(start.max(passage.start_utf8));
            if intersection == 0 {
                continue;
            }
            if best.is_none_or(|(best_overlap, best_passage)| {
                intersection > best_overlap
                    || (intersection == best_overlap && passage.id < best_passage.id)
            }) {
                best = Some((intersection, passage));
            }
        }
        Ok(best.map(|(_, passage)| passage))
    }
}

fn compute_query_set_sha256(queries: &[Query]) -> Result<String> {
    Ok(sha256_hex(canonical_json(queries)?.as_bytes()))
}

fn duplicate_heavy_queries(
    query_ids: &BTreeSet<QueryId>,
    judgments: &BTreeMap<QueryId, Vec<DocumentJudgment>>,
    families: &BTreeMap<DocumentId, String>,
) -> Vec<QueryId> {
    let mut family_sizes: BTreeMap<&str, usize> = BTreeMap::new();
    for family in families.values() {
        *family_sizes.entry(family.as_str()).or_default() += 1;
    }
    query_ids
        .iter()
        .filter(|query_id| {
            judgments.get(*query_id).is_some_and(|rows| {
                rows.iter().any(|row| {
                    row.grade > 0
                        && families.get(&row.document_id).is_some_and(|family| {
                            family_sizes.get(family.as_str()).copied().unwrap_or(0) > 1
                        })
                })
            })
        })
        .cloned()
        .collect()
}

fn char_index_to_byte(text: &str, char_index: usize) -> Option<usize> {
    if char_index == 0 {
        return Some(0);
    }
    let mut current = 0;
    for (byte, _) in text.char_indices() {
        if current == char_index {
            return Some(byte);
        }
        current += 1;
    }
    (current == char_index).then_some(text.len())
}

#[cfg(test)]
pub(crate) struct DatasetBuilder {
    id: String,
    split: Split,
    configuration: EvaluationConfiguration,
    documents: Vec<Document>,
    passages: Vec<Passage>,
    queries: Vec<Query>,
    document_judgments: BTreeMap<QueryId, Vec<DocumentJudgment>>,
    passage_judgments: BTreeMap<QueryId, Vec<PassageJudgment>>,
    duplicate_families: BTreeMap<DocumentId, String>,
    duplicate_available: bool,
}

#[cfg(test)]
impl DatasetBuilder {
    pub(crate) fn new() -> Self {
        Self {
            id: "fixture".to_owned(),
            split: Split::Dev,
            configuration: EvaluationConfiguration::Default,
            documents: Vec::new(),
            passages: Vec::new(),
            queries: Vec::new(),
            document_judgments: BTreeMap::new(),
            passage_judgments: BTreeMap::new(),
            duplicate_families: BTreeMap::new(),
            duplicate_available: false,
        }
    }

    pub(crate) fn id(mut self, id: &str) -> Self {
        self.id = id.to_owned();
        self
    }

    pub(crate) fn configuration(mut self, configuration: EvaluationConfiguration) -> Self {
        self.configuration = configuration;
        self
    }

    pub(crate) fn document(mut self, id: &str, text: &str, source_code: bool) -> Self {
        let path = format!("files/{id}.txt");
        self.documents.push(Document {
            id: id.to_owned(),
            title: id.to_owned(),
            text: text.to_owned(),
            relative_path: path.clone(),
            source_code,
            metadata: serde_json::json!({"relative_path": path}),
        });
        self
    }

    pub(crate) fn passage(mut self, id: &str, document_id: &str, text: &str, kind: &str) -> Self {
        let document_start = self
            .documents
            .iter()
            .find(|document| document.id == document_id)
            .map(|document| document.text.find(text).unwrap_or(0))
            .unwrap_or(0) as u64;
        self.passages.push(Passage {
            id: id.to_owned(),
            document_id: document_id.to_owned(),
            text: text.to_owned(),
            start_utf8: document_start,
            end_utf8: document_start + text.len() as u64,
            kind: kind.to_owned(),
            locator: serde_json::json!({"page": 1, "block_id": id}),
            boilerplate_family_id: None,
        });
        self
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn query(
        mut self,
        id: &str,
        text: &str,
        category: QueryCategory,
        slice: LanguageSlice,
        split: Split,
        configuration: EvaluationConfiguration,
    ) -> Self {
        self.queries.push(Query {
            id: id.to_owned(),
            text: text.to_owned(),
            language: "en".to_owned(),
            target_languages: vec!["en".to_owned()],
            language_slice: slice,
            category,
            configuration,
            split,
            filters: None,
        });
        self
    }

    pub(crate) fn document_judgment(
        mut self,
        query_id: &str,
        document_id: &str,
        grade: u8,
        evidence: &[&str],
        labels: &[&str],
    ) -> Self {
        self.document_judgments
            .entry(query_id.to_owned())
            .or_default()
            .push(DocumentJudgment {
                query_id: query_id.to_owned(),
                document_id: document_id.to_owned(),
                grade,
                evidence_passage_ids: evidence.iter().map(|id| (*id).to_owned()).collect(),
                subtopic_labels: labels.iter().map(|id| (*id).to_owned()).collect(),
            });
        self
    }

    pub(crate) fn passage_judgment(
        mut self,
        query_id: &str,
        document_id: &str,
        passage_id: &str,
        grade: u8,
    ) -> Self {
        self.passage_judgments
            .entry(query_id.to_owned())
            .or_default()
            .push(PassageJudgment {
                query_id: query_id.to_owned(),
                document_id: document_id.to_owned(),
                passage_id: passage_id.to_owned(),
                grade,
            });
        self
    }

    pub(crate) fn duplicate(mut self, document_id: &str, family: &str) -> Self {
        self.duplicate_available = true;
        self.duplicate_families
            .insert(document_id.to_owned(), family.to_owned());
        self
    }

    pub(crate) fn build(self) -> Dataset {
        Dataset::new(
            self.id,
            "corpus-hash".to_owned(),
            "fingerprint".to_owned(),
            "judgment-set".to_owned(),
            "judgment-set-hash".to_owned(),
            self.split,
            self.configuration,
            self.documents,
            self.passages,
            self.queries,
            self.document_judgments,
            self.passage_judgments,
            self.duplicate_families,
            self.duplicate_available,
        )
        .unwrap()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chunk_overlap_maps_to_one_gold_passage() {
        let dataset = DatasetBuilder::new()
            .document("doc-1", "alpha beta gamma delta", false)
            .document("doc-2", "unmapped text", false)
            .passage("doc-1:p:1", "doc-1", "alpha beta", "paragraph")
            .passage("doc-1:p:2", "doc-1", "gamma delta", "paragraph")
            .query(
                "q1",
                "alpha",
                QueryCategory::Conceptual,
                LanguageSlice::En,
                Split::Dev,
                EvaluationConfiguration::Default,
            )
            .build();
        let passage = dataset
            .map_chunk_to_passage("doc-1", 0, 10, Some(1))
            .unwrap()
            .unwrap();
        assert_eq!(passage.id, "doc-1:p:1");
        let overlap_both = dataset
            .map_chunk_to_passage("doc-1", 5, 16, Some(1))
            .unwrap()
            .unwrap();
        // "beta gamma" intersects both equally; the smaller ID wins.
        assert_eq!(overlap_both.id, "doc-1:p:1");
        assert!(
            dataset
                .map_chunk_to_passage("doc-2", 0, 4, Some(1))
                .unwrap()
                .is_none()
        );
    }

    #[test]
    fn explicit_zero_is_not_missing() {
        let dataset = DatasetBuilder::new()
            .document("doc-1", "alpha", false)
            .query(
                "q1",
                "alpha",
                QueryCategory::Conceptual,
                LanguageSlice::En,
                Split::Dev,
                EvaluationConfiguration::Default,
            )
            .document_judgment("q1", "doc-1", 0, &[], &[])
            .build();
        assert_eq!(dataset.document_judgments("q1").len(), 1);
        assert_eq!(dataset.document_judgments("q1")[0].grade, 0);
        assert!(dataset.document_judgments("q2").is_empty());
    }

    #[test]
    fn duplicate_family_lookup_preserves_component() {
        let dataset = DatasetBuilder::new()
            .document("a", "alpha", false)
            .document("b", "alpha", false)
            .duplicate("a", "a")
            .duplicate("b", "a")
            .build();
        assert_eq!(dataset.duplicate_family("a"), Some("a"));
        assert_eq!(dataset.duplicate_family("b"), Some("a"));
    }
}
