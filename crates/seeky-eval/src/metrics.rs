//! Metric definitions, nominal aggregates, and document/passage evaluation
//! (SPEC-0003 R6–R10).

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::dataset::{
    Dataset, EvaluationConfiguration, LanguageSlice, QueryCategory, QueryId, Split,
};
use crate::error::{EvalError, Result};
use crate::run::{Run, RunRow, RunTarget};

/// One metric requested by a caller.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum MetricKind {
    /// Document nDCG.
    Ndcg,
    /// Document MRR.
    Mrr,
    /// Document recall.
    Recall,
    /// Document success.
    Success,
    /// Passage nDCG.
    PassageNdcg,
    /// Passage MRR.
    PassageMrr,
    /// Passage recall.
    PassageRecall,
    /// Passage success.
    PassageSuccess,
    /// Document duplicate rate.
    DuplicateRate,
    /// Distinct positive subtopics.
    DistinctRelevant,
    /// Fraction of positive subtopics covered.
    SubtopicRecall,
    /// Binary-subtopic α-nDCG.
    AlphaNdcg,
}

/// Metric plus cutoff.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct MetricSpec {
    /// Metric family.
    pub kind: MetricKind,
    /// Cutoff in 1..=1000.
    pub cutoff: u32,
}

impl MetricSpec {
    /// Construct a validated metric.
    pub fn new(kind: MetricKind, cutoff: u32) -> Result<Self> {
        if !(1..=1000).contains(&cutoff) {
            return Err(EvalError::data(
                "SCHEMA",
                "metric.cutoff",
                "metric cutoff must be in 1..=1000",
            ));
        }
        Ok(Self { kind, cutoff })
    }

    /// Stable report identifier (`ndcg_10`, `passage_ndcg_10`, …).
    #[must_use]
    pub fn id(self) -> String {
        let prefix = match self.kind {
            MetricKind::Ndcg => "ndcg",
            MetricKind::Mrr => "mrr",
            MetricKind::Recall => "recall",
            MetricKind::Success => "success",
            MetricKind::PassageNdcg => "passage_ndcg",
            MetricKind::PassageMrr => "passage_mrr",
            MetricKind::PassageRecall => "passage_recall",
            MetricKind::PassageSuccess => "passage_success",
            MetricKind::DuplicateRate => "duplicate_rate",
            MetricKind::DistinctRelevant => "distinct_relevant",
            MetricKind::SubtopicRecall => "subtopic_recall",
            MetricKind::AlphaNdcg => "alpha_ndcg",
        };
        format!("{prefix}_{}", self.cutoff)
    }

    /// Whether the metric operates on canonical passages.
    #[must_use]
    pub const fn is_passage(self) -> bool {
        matches!(
            self.kind,
            MetricKind::PassageNdcg
                | MetricKind::PassageMrr
                | MetricKind::PassageRecall
                | MetricKind::PassageSuccess
        )
    }
}

/// Default and custom metric selection.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MetricSelection {
    /// Ordered unique metrics.
    pub metrics: Vec<MetricSpec>,
}

impl Default for MetricSelection {
    fn default() -> Self {
        Self {
            metrics: vec![
                MetricSpec {
                    kind: MetricKind::Ndcg,
                    cutoff: 10,
                },
                MetricSpec {
                    kind: MetricKind::Mrr,
                    cutoff: 10,
                },
                MetricSpec {
                    kind: MetricKind::Success,
                    cutoff: 1,
                },
                MetricSpec {
                    kind: MetricKind::Recall,
                    cutoff: 100,
                },
                MetricSpec {
                    kind: MetricKind::PassageNdcg,
                    cutoff: 10,
                },
                MetricSpec {
                    kind: MetricKind::DuplicateRate,
                    cutoff: 10,
                },
                MetricSpec {
                    kind: MetricKind::DistinctRelevant,
                    cutoff: 10,
                },
                MetricSpec {
                    kind: MetricKind::SubtopicRecall,
                    cutoff: 10,
                },
                MetricSpec {
                    kind: MetricKind::AlphaNdcg,
                    cutoff: 10,
                },
            ],
        }
    }
}

impl MetricSelection {
    /// Parse report IDs such as `ndcg_10` and `passage_recall_100`.
    pub fn from_ids(ids: &[&str]) -> Result<Self> {
        let mut metrics = Vec::new();
        for id in ids {
            metrics.push(MetricSpec::from_id(id)?);
        }
        metrics.sort_unstable();
        metrics.dedup();
        Ok(Self { metrics })
    }

    /// Maximum cutoff requested.
    #[must_use]
    pub fn max_cutoff(&self) -> u32 {
        self.metrics
            .iter()
            .map(|metric| metric.cutoff)
            .max()
            .unwrap_or(1)
    }

    /// Metric IDs in deterministic order.
    #[must_use]
    pub fn ids(&self) -> Vec<String> {
        self.metrics.iter().map(|metric| metric.id()).collect()
    }
}

impl MetricSpec {
    fn from_id(id: &str) -> Result<Self> {
        let (kind, cutoff) = if let Some(value) = id.strip_prefix("passage_") {
            let (name, cutoff) = split_metric_id(value)?;
            let kind = match name {
                "ndcg" => MetricKind::PassageNdcg,
                "mrr" => MetricKind::PassageMrr,
                "recall" => MetricKind::PassageRecall,
                "success" => MetricKind::PassageSuccess,
                _ => {
                    return Err(EvalError::data(
                        "SCHEMA",
                        "metric",
                        format!("unknown passage metric: {id}"),
                    ));
                }
            };
            (kind, cutoff)
        } else {
            let (name, cutoff) = split_metric_id(id)?;
            let kind = match name {
                "ndcg" => MetricKind::Ndcg,
                "mrr" => MetricKind::Mrr,
                "recall" => MetricKind::Recall,
                "success" => MetricKind::Success,
                "duplicate_rate" => MetricKind::DuplicateRate,
                "distinct_relevant" => MetricKind::DistinctRelevant,
                "subtopic_recall" => MetricKind::SubtopicRecall,
                "alpha_ndcg" => MetricKind::AlphaNdcg,
                _ => {
                    return Err(EvalError::data(
                        "SCHEMA",
                        "metric",
                        format!("unknown metric: {id}"),
                    ));
                }
            };
            (kind, cutoff)
        };
        MetricSpec::new(kind, cutoff)
    }
}

fn split_metric_id(id: &str) -> Result<(&str, u32)> {
    let (name, cutoff) = id.rsplit_once('_').ok_or_else(|| {
        EvalError::data("SCHEMA", "metric", format!("metric has no cutoff: {id}"))
    })?;
    let cutoff = cutoff
        .parse::<u32>()
        .map_err(|_| EvalError::data("SCHEMA", "metric", format!("invalid metric cutoff: {id}")))?;
    Ok((name, cutoff))
}

/// Query reporting context retained for weighted and grouped statistics.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct QueryContext {
    /// Category.
    pub category: QueryCategory,
    /// Language slice.
    pub language_slice: LanguageSlice,
    /// Evaluation configuration.
    pub configuration: EvaluationConfiguration,
}

/// Per-query and aggregate metrics for one dataset/run.
#[derive(Clone, Debug)]
pub struct EvaluationResult {
    /// Dataset fingerprint.
    pub dataset_fingerprint: String,
    /// Selected query-set hash.
    pub query_set_sha256: String,
    /// Split.
    pub split: Split,
    /// Configuration.
    pub configuration: EvaluationConfiguration,
    /// Query ID → metric ID → ratio.
    pub per_query: BTreeMap<QueryId, BTreeMap<String, f64>>,
    /// Query ID → category/language/configuration.
    pub query_contexts: BTreeMap<QueryId, QueryContext>,
    /// Macro metric values.
    pub macro_metrics: BTreeMap<String, f64>,
    /// Category → metric values.
    pub category_metrics: BTreeMap<String, BTreeMap<String, f64>>,
    /// Language slice → metric values.
    pub language_metrics: BTreeMap<String, BTreeMap<String, f64>>,
    /// Weighted primary nDCG@10 when all four slices exist.
    pub weighted_primary: Option<f64>,
    /// Queries with no positive target-level judgment.
    pub queries_without_positive: usize,
    /// Requested metrics that could not be computed for this dataset/run.
    pub unavailable_metrics: BTreeSet<String>,
}

/// Evaluate one document or passage run.
pub fn evaluate(
    dataset: &Dataset,
    run: &Run,
    selection: &MetricSelection,
) -> Result<EvaluationResult> {
    validate_run_for_dataset(dataset, run)?;
    let is_passage = run.rows.first().is_some_and(|row| row.target.is_passage());
    let mut per_query: BTreeMap<QueryId, BTreeMap<String, f64>> = BTreeMap::new();
    let mut query_contexts = BTreeMap::new();
    let mut requested = BTreeSet::new();
    for metric in &selection.metrics {
        requested.insert(metric.id());
    }

    let mut has_exploratory = false;
    let mut exploratory_missing_labels = false;
    for query in dataset.queries() {
        query_contexts.insert(
            query.id.clone(),
            QueryContext {
                category: query.category,
                language_slice: query.language_slice,
                configuration: query.configuration,
            },
        );
        if query.category == QueryCategory::Exploratory {
            has_exploratory = true;
            let positive_labels = dataset
                .document_judgments(&query.id)
                .iter()
                .filter(|judgment| judgment.grade > 0)
                .flat_map(|judgment| judgment.subtopic_labels.iter())
                .collect::<BTreeSet<_>>();
            if positive_labels.is_empty() {
                exploratory_missing_labels = true;
            }
        }
    }
    let has_diversity = has_exploratory && !exploratory_missing_labels;
    if has_exploratory && exploratory_missing_labels {
        let wants_diversity = selection.metrics.iter().any(|metric| {
            matches!(
                metric.kind,
                MetricKind::DistinctRelevant | MetricKind::SubtopicRecall | MetricKind::AlphaNdcg
            )
        });
        if wants_diversity {
            return Err(EvalError::data(
                "UNSUPPORTED_METRIC",
                "metrics",
                "exploratory queries must have positive subtopic labels",
            ));
        }
    }

    let mut rows_by_query: BTreeMap<&str, Vec<&RunRow>> = BTreeMap::new();
    for row in &run.rows {
        rows_by_query
            .entry(row.query_id.as_str())
            .or_default()
            .push(row);
    }

    let mut queries_without_positive = 0;
    for query in dataset.queries() {
        let rows = rows_by_query
            .get(query.id.as_str())
            .map_or(&[][..], Vec::as_slice);
        let concepts = if is_passage {
            TargetConcepts::from_passages(dataset, &query.id)
        } else {
            TargetConcepts::from_documents(dataset, &query.id)
        };
        if concepts.positive_count == 0 {
            queries_without_positive += 1;
        }
        let mut metrics = BTreeMap::new();
        for spec in &selection.metrics {
            if spec.is_passage() != is_passage {
                continue;
            }
            if let Some(value) = compute_metric(spec, &concepts, rows, dataset)? {
                metrics.insert(spec.id(), value);
            }
        }
        if !is_passage && has_diversity && query.category == QueryCategory::Exploratory {
            for spec in &selection.metrics {
                if matches!(
                    spec.kind,
                    MetricKind::DistinctRelevant
                        | MetricKind::SubtopicRecall
                        | MetricKind::AlphaNdcg
                ) && let Some(value) =
                    compute_diversity_metric(spec, dataset, &query.id, rows, &concepts)?
                {
                    metrics.insert(spec.id(), value);
                }
            }
        }
        per_query.insert(query.id.clone(), metrics);
    }

    let mut macro_metrics = aggregate_queries(&per_query, dataset.queries().iter(), None);
    let mut unavailable_metrics = BTreeSet::new();
    for metric in &requested {
        if !macro_metrics.contains_key(metric) {
            unavailable_metrics.insert(metric.clone());
        }
    }
    let mut category_metrics = BTreeMap::new();
    for category in all_categories() {
        let values = aggregate_queries(
            &per_query,
            dataset
                .queries()
                .iter()
                .filter(|query| query.category == category),
            None,
        );
        if !values.is_empty() {
            category_metrics.insert(category.as_str().to_owned(), values);
        }
    }
    let mut language_metrics = BTreeMap::new();
    for slice in all_language_slices() {
        let values = aggregate_queries(
            &per_query,
            dataset
                .queries()
                .iter()
                .filter(|query| query.language_slice == slice),
            None,
        );
        if !values.is_empty() {
            language_metrics.insert(slice.as_str().to_owned(), values);
        }
    }
    if !is_passage
        && !macro_metrics.contains_key("ndcg_10")
        && selection
            .metrics
            .iter()
            .any(|metric| metric.id() == "ndcg_10")
    {
        unavailable_metrics.insert("ndcg_10".to_owned());
    }

    let weighted_primary = if is_passage {
        None
    } else {
        let default_queries: Vec<_> = dataset
            .queries()
            .iter()
            .filter(|query| query.configuration == EvaluationConfiguration::Default)
            .collect();
        let mut slice_values = BTreeMap::new();
        for slice in all_language_slices() {
            let values: Vec<f64> = default_queries
                .iter()
                .filter(|query| query.language_slice == slice)
                .filter_map(|query| {
                    per_query
                        .get(&query.id)
                        .and_then(|metrics| metrics.get("ndcg_10").copied())
                })
                .collect();
            if !values.is_empty() {
                slice_values.insert(slice, values.iter().sum::<f64>() / values.len() as f64);
            }
        }
        weighted_primary(&slice_values).ok()
    };

    macro_metrics.retain(|metric, _| !unavailable_metrics.contains(metric));
    Ok(EvaluationResult {
        dataset_fingerprint: dataset.fingerprint.clone(),
        query_set_sha256: dataset.query_set_sha256().to_owned(),
        split: dataset.split,
        configuration: dataset.configuration,
        per_query,
        query_contexts,
        macro_metrics,
        category_metrics,
        language_metrics,
        weighted_primary,
        queries_without_positive,
        unavailable_metrics,
    })
}

/// Compute the fixed-weight primary score. Every language slice is required.
pub fn weighted_primary(slice_means: &BTreeMap<LanguageSlice, f64>) -> Result<f64> {
    let mut total = 0.0;
    for (slice, weight) in [
        (LanguageSlice::Pt, 0.35),
        (LanguageSlice::En, 0.35),
        (LanguageSlice::CrossLingual, 0.15),
        (LanguageSlice::Other, 0.15),
    ] {
        let value = slice_means.get(&slice).ok_or_else(|| {
            EvalError::data(
                "UNSUPPORTED_METRIC",
                "weighted_primary",
                format!("missing language slice: {}", slice.as_str()),
            )
        })?;
        total += weight * value;
    }
    Ok(total)
}

fn aggregate_queries<'a>(
    per_query: &BTreeMap<QueryId, BTreeMap<String, f64>>,
    queries: impl Iterator<Item = &'a crate::dataset::Query>,
    metric_filter: Option<&BTreeSet<String>>,
) -> BTreeMap<String, f64> {
    let mut sums: BTreeMap<String, (f64, usize)> = BTreeMap::new();
    for query in queries {
        if let Some(metrics) = per_query.get(&query.id) {
            for (metric, value) in metrics {
                if metric_filter.is_some_and(|filter| !filter.contains(metric)) {
                    continue;
                }
                let entry = sums.entry(metric.clone()).or_insert((0.0, 0));
                entry.0 += value;
                entry.1 += 1;
            }
        }
    }
    sums.into_iter()
        .filter(|(_, (_, count))| *count > 0)
        .map(|(metric, (sum, count))| (metric, sum / count as f64))
        .collect()
}

fn compute_metric(
    spec: &MetricSpec,
    concepts: &TargetConcepts,
    rows: &[&RunRow],
    dataset: &Dataset,
) -> Result<Option<f64>> {
    let cutoff = usize::try_from(spec.cutoff).unwrap_or(usize::MAX);
    let returned: Vec<&str> = rows
        .iter()
        .take(cutoff)
        .map(|row| row.target.id())
        .collect();
    let value = match spec.kind {
        MetricKind::Ndcg | MetricKind::PassageNdcg => {
            Some(ndcg(&returned, &concepts.grades, cutoff))
        }
        MetricKind::Mrr | MetricKind::PassageMrr => Some(mrr(&returned, &concepts.grades, cutoff)),
        MetricKind::Recall | MetricKind::PassageRecall => {
            Some(recall(&returned, &concepts.positive, cutoff))
        }
        MetricKind::Success | MetricKind::PassageSuccess => {
            Some(success(&returned, &concepts.grades, cutoff))
        }
        MetricKind::DuplicateRate => {
            if spec.is_passage() || !dataset.duplicate_metrics_available() {
                None
            } else {
                Some(duplicate_rate(dataset, &returned))
            }
        }
        MetricKind::DistinctRelevant | MetricKind::SubtopicRecall | MetricKind::AlphaNdcg => None,
    };
    Ok(value)
}

fn compute_diversity_metric(
    spec: &MetricSpec,
    dataset: &Dataset,
    query_id: &str,
    rows: &[&RunRow],
    concepts: &TargetConcepts,
) -> Result<Option<f64>> {
    let cutoff = usize::try_from(spec.cutoff).unwrap_or(usize::MAX);
    let returned: Vec<&str> = rows
        .iter()
        .take(cutoff)
        .map(|row| row.target.id())
        .collect();
    let total_labels = concepts.all_labels.len();
    if total_labels == 0 {
        return Ok(None);
    }
    let value = match spec.kind {
        MetricKind::DistinctRelevant => {
            let covered = covered_labels(dataset, query_id, &returned);
            Some(covered.len() as f64)
        }
        MetricKind::SubtopicRecall => {
            let covered = covered_labels(dataset, query_id, &returned);
            Some(covered.len() as f64 / total_labels as f64)
        }
        MetricKind::AlphaNdcg => Some(alpha_ndcg(dataset, query_id, &returned, cutoff)),
        _ => None,
    };
    Ok(value)
}

fn ndcg(returned: &[&str], grades: &BTreeMap<&str, u8>, cutoff: usize) -> f64 {
    let actual: f64 = returned
        .iter()
        .take(cutoff)
        .enumerate()
        .map(|(index, id)| f64::from(grades.get(id).copied().unwrap_or(0)) / discount(index + 1))
        .sum();
    let mut ideal_grades: Vec<u8> = grades
        .values()
        .copied()
        .filter(|grade| *grade > 0)
        .collect();
    ideal_grades.sort_unstable_by(|left, right| right.cmp(left));
    let ideal: f64 = ideal_grades
        .iter()
        .take(cutoff)
        .enumerate()
        .map(|(index, grade)| f64::from(*grade) / discount(index + 1))
        .sum();
    if ideal == 0.0 { 0.0 } else { actual / ideal }
}

fn mrr(returned: &[&str], grades: &BTreeMap<&str, u8>, cutoff: usize) -> f64 {
    returned
        .iter()
        .take(cutoff)
        .enumerate()
        .find(|(_, id)| grades.get(*id).copied().unwrap_or(0) > 0)
        .map_or(0.0, |(index, _)| 1.0 / (index + 1) as f64)
}

fn recall(returned: &[&str], positive: &BTreeSet<&str>, cutoff: usize) -> f64 {
    if positive.is_empty() {
        return 0.0;
    }
    let retrieved = returned
        .iter()
        .take(cutoff)
        .filter(|id| positive.contains(**id))
        .count();
    retrieved as f64 / positive.len() as f64
}

fn success(returned: &[&str], grades: &BTreeMap<&str, u8>, cutoff: usize) -> f64 {
    if returned
        .iter()
        .take(cutoff)
        .any(|id| grades.get(*id).copied().unwrap_or(0) > 0)
    {
        1.0
    } else {
        0.0
    }
}

fn duplicate_rate(dataset: &Dataset, returned: &[&str]) -> f64 {
    if returned.is_empty() {
        return 0.0;
    }
    let mut seen_families = BTreeSet::new();
    let mut redundant = 0;
    for document_id in returned {
        if let Some(family) = dataset.duplicate_family(document_id)
            && !seen_families.insert(family)
        {
            redundant += 1;
        }
    }
    redundant as f64 / returned.len() as f64
}

fn covered_labels(dataset: &Dataset, query_id: &str, returned: &[&str]) -> BTreeSet<String> {
    dataset
        .document_judgments(query_id)
        .iter()
        .filter(|judgment| judgment.grade > 0 && returned.contains(&judgment.document_id.as_str()))
        .flat_map(|judgment| judgment.subtopic_labels.iter().cloned())
        .collect()
}

fn alpha_ndcg(dataset: &Dataset, query_id: &str, returned: &[&str], cutoff: usize) -> f64 {
    let labels: BTreeMap<&str, &[String]> = dataset
        .document_judgments(query_id)
        .iter()
        .filter(|judgment| judgment.grade > 0)
        .map(|judgment| {
            (
                judgment.document_id.as_str(),
                judgment.subtopic_labels.as_slice(),
            )
        })
        .collect();
    let mut counts: BTreeMap<&str, usize> = BTreeMap::new();
    let actual: f64 = returned
        .iter()
        .take(cutoff)
        .enumerate()
        .map(|(index, document_id)| {
            let gain = labels.get(document_id).map_or(0.0, |topics| {
                topics
                    .iter()
                    .map(|topic| {
                        let count = counts.get(topic.as_str()).copied().unwrap_or(0);
                        novelty(count)
                    })
                    .sum()
            });
            if let Some(topics) = labels.get(document_id) {
                for topic in *topics {
                    *counts.entry(topic.as_str()).or_default() += 1;
                }
            }
            gain / discount(index + 1)
        })
        .sum();

    let mut remaining: Vec<(&str, u8, &[String])> = dataset
        .document_judgments(query_id)
        .iter()
        .filter(|judgment| judgment.grade > 0)
        .map(|judgment| {
            (
                judgment.document_id.as_str(),
                judgment.grade,
                judgment.subtopic_labels.as_slice(),
            )
        })
        .collect();
    let mut ideal_counts: BTreeMap<&str, usize> = BTreeMap::new();
    let mut ideal = 0.0;
    for index in 0..cutoff.min(remaining.len()) {
        let mut best_position = 0;
        let mut best_gain = -1.0;
        let mut best_grade = 0;
        for (position, (document_id, grade, topics)) in remaining.iter().enumerate() {
            let gain: f64 = topics
                .iter()
                .map(|topic| {
                    let count = ideal_counts.get(topic.as_str()).copied().unwrap_or(0);
                    novelty(count)
                })
                .sum();
            let better = gain > best_gain
                || (gain == best_gain && *grade > best_grade)
                || (gain == best_gain
                    && *grade == best_grade
                    && *document_id < remaining[best_position].0);
            if position == 0 || better {
                best_position = position;
                best_gain = gain;
                best_grade = *grade;
            }
        }
        ideal += best_gain / discount(index + 1);
        let (_, _, topics) = remaining.remove(best_position);
        for topic in topics {
            *ideal_counts.entry(topic.as_str()).or_default() += 1;
        }
    }
    if ideal == 0.0 { 0.0 } else { actual / ideal }
}

fn discount(rank: usize) -> f64 {
    ((rank + 1) as f64).log2()
}

fn novelty(count: usize) -> f64 {
    (1.0 - 0.5_f64).powi(i32::try_from(count).unwrap_or(i32::MAX))
}

struct TargetConcepts<'a> {
    grades: BTreeMap<&'a str, u8>,
    positive: BTreeSet<&'a str>,
    all_labels: BTreeSet<String>,
    positive_count: usize,
}

impl<'a> TargetConcepts<'a> {
    fn from_documents(dataset: &'a Dataset, query_id: &str) -> Self {
        let judgments = dataset.document_judgments(query_id);
        let grades = judgments
            .iter()
            .map(|judgment| (judgment.document_id.as_str(), judgment.grade))
            .collect();
        let positive = judgments
            .iter()
            .filter(|judgment| judgment.grade > 0)
            .map(|judgment| judgment.document_id.as_str())
            .collect();
        let all_labels = judgments
            .iter()
            .filter(|judgment| judgment.grade > 0)
            .flat_map(|judgment| judgment.subtopic_labels.iter().cloned())
            .collect();
        Self {
            grades,
            positive,
            all_labels,
            positive_count: judgments
                .iter()
                .filter(|judgment| judgment.grade > 0)
                .count(),
        }
    }

    fn from_passages(dataset: &'a Dataset, query_id: &str) -> Self {
        let judgments = dataset.passage_judgments(query_id);
        let grades = judgments
            .iter()
            .map(|judgment| (judgment.passage_id.as_str(), judgment.grade))
            .collect();
        let positive = judgments
            .iter()
            .filter(|judgment| judgment.grade > 0)
            .map(|judgment| judgment.passage_id.as_str())
            .collect();
        Self {
            grades,
            positive,
            all_labels: BTreeSet::new(),
            positive_count: judgments
                .iter()
                .filter(|judgment| judgment.grade > 0)
                .count(),
        }
    }
}

fn validate_run_for_dataset(dataset: &Dataset, run: &Run) -> Result<()> {
    let mut by_query: BTreeMap<&str, Vec<&RunRow>> = BTreeMap::new();
    let mut target_type = None;
    for row in &run.rows {
        if !dataset.contains_query(&row.query_id) {
            return Err(EvalError::data(
                "DANGLING_REFERENCE",
                "run",
                "row references a query outside the selected split",
            ));
        }
        if !row.score.is_finite() || !(1..=1000).contains(&row.rank) {
            return Err(EvalError::data("SCHEMA", "run", "invalid rank or score"));
        }
        let is_passage = row.target.is_passage();
        if let Some(existing) = target_type
            && existing != is_passage
        {
            return Err(EvalError::data("SCHEMA", "run", "mixed run target types"));
        }
        target_type = Some(is_passage);
        match &row.target {
            RunTarget::Document(id) => {
                if dataset.document(id).is_none() {
                    return Err(EvalError::data(
                        "DANGLING_REFERENCE",
                        "run",
                        "unknown document target",
                    ));
                }
            }
            RunTarget::Passage(id) => {
                if dataset.passage(id).is_none() {
                    return Err(EvalError::data(
                        "DANGLING_REFERENCE",
                        "run",
                        "unknown passage target",
                    ));
                }
            }
        }
        by_query.entry(row.query_id.as_str()).or_default().push(row);
    }
    for rows in by_query.values_mut() {
        rows.sort_by_key(|row| row.rank);
        let mut targets = BTreeSet::new();
        for (index, row) in rows.iter().enumerate() {
            if row.rank != u32::try_from(index + 1).unwrap_or(u32::MAX) {
                return Err(EvalError::data("SCHEMA", "run", "non-contiguous ranks"));
            }
            if !targets.insert(row.target.clone()) {
                return Err(EvalError::data(
                    "DUPLICATE_ID",
                    "run",
                    "duplicate target for query",
                ));
            }
        }
    }
    Ok(())
}

fn all_categories() -> [QueryCategory; 9] {
    [
        QueryCategory::KnownItem,
        QueryCategory::Conceptual,
        QueryCategory::ExactIdentifier,
        QueryCategory::CrossLanguage,
        QueryCategory::NeedleInHaystack,
        QueryCategory::Exploratory,
        QueryCategory::MixedSemanticMetadata,
        QueryCategory::CodeSearch,
        QueryCategory::FilenamePartial,
    ]
}

fn all_language_slices() -> [LanguageSlice; 5] {
    [
        LanguageSlice::Pt,
        LanguageSlice::En,
        LanguageSlice::CrossLingual,
        LanguageSlice::Other,
        LanguageSlice::NonLatinNonRegression,
    ]
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dataset::{
        DatasetBuilder, EvaluationConfiguration as Config, LanguageSlice as Slice,
        QueryCategory as Cat, Split,
    };

    fn fixture() -> Dataset {
        DatasetBuilder::new()
            .document("d1", "d1", false)
            .document("d2", "d2", false)
            .document("d3", "d3", false)
            .document("d4", "d4", false)
            .document("d5", "d5", false)
            .document("d6", "d6", false)
            .document("d7", "d7", false)
            .document("d8", "d8", false)
            .document("d9", "d9", false)
            .query(
                "q1",
                "a",
                Cat::Conceptual,
                Slice::En,
                Split::Dev,
                Config::Default,
            )
            .query(
                "q2",
                "b",
                Cat::Conceptual,
                Slice::En,
                Split::Dev,
                Config::Default,
            )
            .query(
                "q3",
                "c",
                Cat::Conceptual,
                Slice::En,
                Split::Dev,
                Config::Default,
            )
            .document_judgment("q1", "d1", 3, &[], &[])
            .document_judgment("q1", "d2", 1, &[], &[])
            .document_judgment("q1", "d3", 2, &[], &[])
            .document_judgment("q1", "d4", 0, &[], &[])
            .document_judgment("q1", "d5", 3, &[], &[])
            .document_judgment("q2", "d6", 0, &[], &[])
            .document_judgment("q2", "d7", 0, &[], &[])
            .document_judgment("q2", "d8", 2, &[], &[])
            .document_judgment("q3", "d9", 0, &[], &[])
            .build()
    }

    fn run() -> Run {
        Run {
            run_id: "r".to_owned(),
            system_id: "s".to_owned(),
            rows: vec![
                row("q1", "d2", 1),
                row("q1", "d1", 2),
                row("q1", "d3", 3),
                row("q1", "d4", 4),
                row("q2", "d6", 1),
                row("q2", "d7", 2),
                row("q3", "d9", 1),
            ],
        }
    }

    fn row(query: &str, document: &str, rank: u32) -> RunRow {
        RunRow {
            query_id: query.to_owned(),
            target: RunTarget::Document(document.to_owned()),
            rank,
            score: 10.0 - f64::from(rank),
        }
    }

    #[test]
    fn ndcg_matches_reference_values() {
        let selection = MetricSelection::from_ids(&["ndcg_10"]).unwrap();
        let result = evaluate(&fixture(), &run(), &selection).unwrap();
        assert!((result.per_query["q1"]["ndcg_10"] - 0.615_610_074_011_697).abs() < 1e-12);
        assert!((result.macro_metrics["ndcg_10"] - 0.205_203_358_003_899).abs() < 1e-12);
    }

    #[test]
    fn mrr_recall_success_match_reference_values() {
        let selection = MetricSelection::from_ids(&["mrr_10", "recall_10", "success_1"]).unwrap();
        let result = evaluate(&fixture(), &run(), &selection).unwrap();
        assert!((result.per_query["q1"]["mrr_10"] - 1.0).abs() < 1e-12);
        assert!((result.per_query["q1"]["recall_10"] - 0.75).abs() < 1e-12);
        assert!((result.per_query["q1"]["success_1"] - 1.0).abs() < 1e-12);
        assert!((result.macro_metrics["recall_10"] - 0.25).abs() < 1e-12);
        assert!((result.macro_metrics["success_1"] - 1.0 / 3.0).abs() < 1e-12);
    }

    #[test]
    fn document_metrics_match_reference_values() {
        let selection = MetricSelection::from_ids(&["ndcg_10", "mrr_10"]).unwrap();
        let result = evaluate(&fixture(), &run(), &selection).unwrap();
        assert!((result.per_query["q2"]["ndcg_10"]).abs() < 1e-12);
        assert!((result.per_query["q2"]["mrr_10"]).abs() < 1e-12);
        assert_eq!(result.queries_without_positive, 1);
    }

    #[test]
    fn queries_without_positive_judgments_are_retained() {
        let selection = MetricSelection::from_ids(&["ndcg_10"]).unwrap();
        let result = evaluate(&fixture(), &run(), &selection).unwrap();
        assert!(result.per_query.contains_key("q3"));
        assert_eq!(result.per_query["q3"]["ndcg_10"], 0.0);
        assert_eq!(result.queries_without_positive, 1);
    }

    #[test]
    fn property_metric_domains_and_unretrieved_positive_rules() {
        let selection = MetricSelection::from_ids(&["ndcg_10", "recall_10", "success_1"]).unwrap();
        let result = evaluate(&fixture(), &run(), &selection).unwrap();
        for metrics in result.per_query.values() {
            for (id, value) in metrics {
                if id == "success_1" {
                    assert!(*value == 0.0 || *value == 1.0);
                } else {
                    assert!((0.0..=1.0).contains(value));
                }
            }
        }
        let ideal_run = Run {
            run_id: "ideal".to_owned(),
            system_id: "s".to_owned(),
            rows: vec![
                row("q1", "d1", 1),
                row("q1", "d5", 2),
                row("q1", "d3", 3),
                row("q1", "d2", 4),
            ],
        };
        let ideal_result = evaluate(&fixture(), &ideal_run, &selection).unwrap();
        assert!((ideal_result.per_query["q1"]["ndcg_10"] - 1.0).abs() < 1e-12);
        let with_unretrieved = DatasetBuilder::new()
            .document("d1", "d1", false)
            .document("d5", "d5", false)
            .document("d3", "d3", false)
            .document("d2", "d2", false)
            .document("dX", "dX", false)
            .query(
                "q1",
                "a",
                Cat::Conceptual,
                Slice::En,
                Split::Dev,
                Config::Default,
            )
            .document_judgment("q1", "d1", 3, &[], &[])
            .document_judgment("q1", "d5", 3, &[], &[])
            .document_judgment("q1", "d3", 2, &[], &[])
            .document_judgment("q1", "d2", 1, &[], &[])
            .document_judgment("q1", "dX", 3, &[], &[])
            .build();
        let smaller = evaluate(&with_unretrieved, &ideal_run, &selection).unwrap();
        assert!(smaller.per_query["q1"]["ndcg_10"] < 1.0);
    }

    #[test]
    fn passage_metrics_use_canonical_passage_judgments() {
        let dataset = DatasetBuilder::new()
            .id("passage-fixture")
            .document("d1", "alpha beta gamma", false)
            .passage("d1:p:1", "d1", "alpha beta", "paragraph")
            .passage("d1:p:2", "d1", "gamma", "paragraph")
            .query(
                "q1",
                "alpha",
                Cat::Conceptual,
                Slice::En,
                Split::Dev,
                Config::Default,
            )
            .passage_judgment("q1", "d1", "d1:p:1", 3)
            .build();
        assert_eq!(dataset.id, "passage-fixture");
        let run = Run {
            run_id: "r".to_owned(),
            system_id: "s".to_owned(),
            rows: vec![
                RunRow {
                    query_id: "q1".to_owned(),
                    target: RunTarget::Passage("d1:p:1".to_owned()),
                    rank: 1,
                    score: 1.0,
                },
                RunRow {
                    query_id: "q1".to_owned(),
                    target: RunTarget::Passage("d1:p:2".to_owned()),
                    rank: 2,
                    score: 0.5,
                },
            ],
        };
        let selection = MetricSelection::from_ids(&["passage_ndcg_10"]).unwrap();
        let result = evaluate(&dataset, &run, &selection).unwrap();
        assert!((result.per_query["q1"]["passage_ndcg_10"] - 1.0).abs() < 1e-12);
    }

    fn duplicate_fixture() -> (Dataset, Run) {
        let mut builder = DatasetBuilder::new()
            .document("a", "a", false)
            .document("b", "b", false)
            .document("c", "c", false)
            .document("d", "d", false)
            .document("e", "e", false)
            .document("f", "f", false)
            .document("g", "g", false)
            .query(
                "qdup",
                "a",
                Cat::Conceptual,
                Slice::En,
                Split::Dev,
                Config::Default,
            )
            .query(
                "qclean",
                "f",
                Cat::Conceptual,
                Slice::En,
                Split::Dev,
                Config::Default,
            )
            .duplicate("a", "a")
            .duplicate("b", "a")
            .duplicate("c", "a")
            .duplicate("d", "d")
            .duplicate("e", "d");
        for doc in ["a", "b", "c", "d", "e"] {
            builder =
                builder.document_judgment("qdup", doc, if doc == "a" { 1 } else { 0 }, &[], &[]);
        }
        let dataset = builder.build();
        let ranking = Run {
            run_id: "d".to_owned(),
            system_id: "d".to_owned(),
            rows: vec![
                row("qdup", "a", 1),
                row("qdup", "b", 2),
                row("qdup", "c", 3),
                row("qdup", "d", 4),
                row("qdup", "e", 5),
                row("qclean", "f", 1),
                row("qclean", "g", 2),
            ],
        };
        (dataset, ranking)
    }

    #[test]
    fn duplicate_rate_matches_reference_value() {
        let (dataset, ranking) = duplicate_fixture();
        let selection = MetricSelection::from_ids(&["duplicate_rate_5"]).unwrap();
        let result = evaluate(&dataset, &ranking, &selection).unwrap();
        assert!((result.per_query["qdup"]["duplicate_rate_5"] - 0.6).abs() < 1e-12);
        assert!((result.macro_metrics["duplicate_rate_5"] - 0.3).abs() < 1e-12);
        assert_eq!(dataset.duplicate_heavy_query_ids(), ["qdup"]);
    }

    #[test]
    fn duplicate_slice_is_derived_from_judged_clusters() {
        let mut builder = DatasetBuilder::new()
            .document("a", "a", false)
            .document("b", "b", false)
            .document("clean", "clean", false)
            .query(
                "qdup",
                "a",
                Cat::Conceptual,
                Slice::En,
                Split::Dev,
                Config::Default,
            )
            .query(
                "qclean",
                "clean",
                Cat::Conceptual,
                Slice::En,
                Split::Dev,
                Config::Default,
            )
            .document_judgment("qdup", "a", 1, &[], &[])
            .document_judgment("qclean", "clean", 1, &[], &[])
            .duplicate("a", "a")
            .duplicate("b", "a");
        builder = builder.document_judgment("qdup", "b", 0, &[], &[]);
        let dataset = builder.build();
        assert_eq!(dataset.duplicate_heavy_query_ids(), ["qdup"]);
    }

    #[test]
    fn missing_clusters_report_metric_unavailable() {
        let dataset = DatasetBuilder::new()
            .document("d1", "d1", false)
            .query(
                "q1",
                "q",
                Cat::Conceptual,
                Slice::En,
                Split::Dev,
                Config::Default,
            )
            .document_judgment("q1", "d1", 1, &[], &[])
            .build();
        let run = Run {
            run_id: "r".to_owned(),
            system_id: "s".to_owned(),
            rows: vec![row("q1", "d1", 1)],
        };
        let selection = MetricSelection::from_ids(&["duplicate_rate_10"]).unwrap();
        let result = evaluate(&dataset, &run, &selection).unwrap();
        assert!(result.unavailable_metrics.contains("duplicate_rate_10"));
    }

    fn diversity_fixture() -> (Dataset, Run) {
        let dataset = DatasetBuilder::new()
            .document("dA", "dA", false)
            .document("dB", "dB", false)
            .document("dC", "dC", false)
            .document("dD", "dD", false)
            .document("dE", "dE", false)
            .query(
                "qexp",
                "q",
                Cat::Exploratory,
                Slice::En,
                Split::Dev,
                Config::Default,
            )
            .document_judgment("qexp", "dA", 3, &[], &["x"])
            .document_judgment("qexp", "dB", 2, &[], &["x"])
            .document_judgment("qexp", "dC", 2, &[], &["y"])
            .document_judgment("qexp", "dD", 1, &[], &["z"])
            .document_judgment("qexp", "dE", 3, &[], &["y", "z"])
            .build();
        let run = Run {
            run_id: "r".to_owned(),
            system_id: "s".to_owned(),
            rows: vec![
                row("qexp", "dA", 1),
                row("qexp", "dB", 2),
                row("qexp", "dC", 3),
                row("qexp", "dD", 4),
            ],
        };
        (dataset, run)
    }

    #[test]
    fn alpha_ndcg_matches_reference_value() {
        let (dataset, run) = diversity_fixture();
        let selection =
            MetricSelection::from_ids(&["alpha_ndcg_10", "distinct_relevant_4"]).unwrap();
        let result = evaluate(&dataset, &run, &selection).unwrap();
        assert!(
            (result.per_query["qexp"]["alpha_ndcg_10"] - 0.682_781_175_699_810_9).abs() < 1e-12
        );
        assert!((result.per_query["qexp"]["distinct_relevant_4"] - 3.0).abs() < 1e-12);
    }

    #[test]
    fn distinct_and_subtopic_recall_match_reference_values() {
        let (dataset, run) = diversity_fixture();
        let selection = MetricSelection::from_ids(&[
            "distinct_relevant_2",
            "subtopic_recall_2",
            "subtopic_recall_4",
        ])
        .unwrap();
        let result = evaluate(&dataset, &run, &selection).unwrap();
        assert!((result.per_query["qexp"]["distinct_relevant_2"] - 1.0).abs() < 1e-12);
        assert!((result.per_query["qexp"]["subtopic_recall_2"] - 1.0 / 3.0).abs() < 1e-12);
        assert!((result.per_query["qexp"]["subtopic_recall_4"] - 1.0).abs() < 1e-12);
    }

    #[test]
    fn missing_subtopic_labels_are_typed_errors() {
        let dataset = DatasetBuilder::new()
            .document("d1", "d1", false)
            .query(
                "qexp",
                "q",
                Cat::Exploratory,
                Slice::En,
                Split::Dev,
                Config::Default,
            )
            .document_judgment("qexp", "d1", 2, &[], &[])
            .build();
        let run = Run {
            run_id: "r".to_owned(),
            system_id: "s".to_owned(),
            rows: vec![row("qexp", "d1", 1)],
        };
        let selection = MetricSelection::from_ids(&["alpha_ndcg_10"]).unwrap();
        let error = evaluate(&dataset, &run, &selection).unwrap_err();
        assert_eq!(error.code(), "UNSUPPORTED_METRIC");
    }

    #[test]
    fn weighted_primary_matches_hand_calculation() {
        let slices = BTreeMap::from([
            (Slice::Pt, 0.8),
            (Slice::En, 0.6),
            (Slice::CrossLingual, 0.4),
            (Slice::Other, 0.2),
        ]);
        assert!((weighted_primary(&slices).unwrap() - 0.58).abs() < 1e-12);
    }

    #[test]
    fn missing_language_slice_is_not_silently_reweighted() {
        let slices = BTreeMap::from([(Slice::Pt, 0.8)]);
        assert_eq!(
            weighted_primary(&slices).unwrap_err().code(),
            "UNSUPPORTED_METRIC"
        );
    }

    #[test]
    fn default_aggregate_excludes_code_search() {
        let dataset = DatasetBuilder::new()
            .configuration(Config::CodeEnabled)
            .document("d1", "d1", false)
            .document("d2", "d2", false)
            .query(
                "qd",
                "d1",
                Cat::Conceptual,
                Slice::Pt,
                Split::Dev,
                Config::Default,
            )
            .query(
                "qc",
                "d2",
                Cat::CodeSearch,
                Slice::En,
                Split::Dev,
                Config::CodeEnabled,
            )
            .document_judgment("qd", "d1", 1, &[], &[])
            .document_judgment("qc", "d2", 1, &[], &[])
            .build();
        let run = Run {
            run_id: "r".to_owned(),
            system_id: "s".to_owned(),
            rows: vec![row("qd", "d1", 1), row("qc", "d2", 1)],
        };
        let selection = MetricSelection::from_ids(&["ndcg_10"]).unwrap();
        let result = evaluate(&dataset, &run, &selection).unwrap();
        assert_eq!(result.category_metrics["code_search"]["ndcg_10"], 1.0);
        assert!(result.weighted_primary.is_none());
    }

    #[test]
    fn code_enabled_aggregate_is_separate() {
        let dataset = DatasetBuilder::new()
            .configuration(Config::CodeEnabled)
            .document("dpt", "dpt", false)
            .document("den", "den", false)
            .document("dx", "dx", false)
            .document("dother", "dother", false)
            .document("dcode", "dcode", false)
            .query(
                "qpt",
                "dpt",
                Cat::Conceptual,
                Slice::Pt,
                Split::Dev,
                Config::Default,
            )
            .query(
                "qen",
                "den",
                Cat::Conceptual,
                Slice::En,
                Split::Dev,
                Config::Default,
            )
            .query(
                "qx",
                "dx",
                Cat::CrossLanguage,
                Slice::CrossLingual,
                Split::Dev,
                Config::Default,
            )
            .query(
                "qother",
                "dother",
                Cat::Conceptual,
                Slice::Other,
                Split::Dev,
                Config::Default,
            )
            .query(
                "qcode",
                "dcode",
                Cat::CodeSearch,
                Slice::En,
                Split::Dev,
                Config::CodeEnabled,
            )
            .document_judgment("qpt", "dpt", 1, &[], &[])
            .document_judgment("qen", "den", 1, &[], &[])
            .document_judgment("qx", "dx", 1, &[], &[])
            .document_judgment("qother", "dother", 1, &[], &[])
            .document_judgment("qcode", "dcode", 1, &[], &[])
            .build();
        let run = Run {
            run_id: "r".to_owned(),
            system_id: "s".to_owned(),
            rows: vec![
                row("qpt", "dpt", 1),
                row("qen", "den", 1),
                row("qx", "dx", 1),
                row("qother", "dother", 1),
            ],
        };
        let selection = MetricSelection::from_ids(&["ndcg_10"]).unwrap();
        let result = evaluate(&dataset, &run, &selection).unwrap();
        assert!((result.macro_metrics["ndcg_10"] - 0.8).abs() < 1e-12);
        assert_eq!(result.category_metrics["code_search"]["ndcg_10"], 0.0);
        assert!((result.weighted_primary.unwrap() - 1.0).abs() < 1e-12);
    }

    fn reference_expected() -> serde_json::Value {
        serde_json::from_str(include_str!("../tests/fixtures/reference-v1/expected.json"))
            .expect("committed reference fixture must parse")
    }

    fn committed_metrics_dataset() -> Dataset {
        let qrels = include_str!("../tests/fixtures/reference-v1/qrels.tsv");
        let mut builder = DatasetBuilder::new();
        for document in ["d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8", "d9"] {
            builder = builder.document(document, document, false);
        }
        for (query, text) in [("q1", "a"), ("q2", "b"), ("q3", "c")] {
            builder = builder.query(
                query,
                text,
                Cat::Conceptual,
                Slice::En,
                Split::Dev,
                Config::Default,
            );
        }
        let mut lines = qrels.lines();
        assert_eq!(
            lines.next(),
            Some("query-id\tcorpus-id\tscore"),
            "committed qrels header changed"
        );
        for (index, line) in lines.enumerate() {
            let fields: Vec<&str> = line.split('\t').collect();
            assert_eq!(
                fields.len(),
                3,
                "malformed committed qrels line {index}: {line}"
            );
            let grade: u8 = fields[2]
                .parse()
                .unwrap_or_else(|_| panic!("noninteger grade on committed line {index}: {line}"));
            builder = builder.document_judgment(fields[0], fields[1], grade, &[], &[]);
        }
        builder.build()
    }

    fn assert_close(got: f64, want: f64, label: &str) {
        assert!((got - want).abs() < 1e-12, "{label}: {got} != {want}");
    }

    #[test]
    fn committed_reference_fixtures_match_expected_json() {
        let expected = reference_expected();

        // SPEC-0003-R6: the committed qrels.tsv and run.trec produce §5.8 A.
        let dataset = committed_metrics_dataset();
        let run_path = std::path::Path::new(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/tests/fixtures/reference-v1/run.trec"
        ));
        let run = crate::run::read_trec_run(run_path, &dataset)
            .expect("committed run.trec must load through the TREC reader");
        let selection =
            MetricSelection::from_ids(&["ndcg_10", "mrr_10", "recall_10", "success_1"]).unwrap();
        let result = evaluate(&dataset, &run, &selection).unwrap();
        let metrics = &expected["metrics-v1"];
        for metric in ["ndcg_10", "mrr_10", "recall_10", "success_1"] {
            for query in ["q1", "q2", "q3"] {
                assert_close(
                    result.per_query[query][metric],
                    metrics[metric][query].as_f64().unwrap(),
                    &format!("metrics-v1 {metric}/{query}"),
                );
            }
            assert_close(
                result.macro_metrics[metric],
                metrics[metric]["macro"].as_f64().unwrap(),
                &format!("metrics-v1 {metric}/macro"),
            );
        }

        // SPEC-0003-R8: §5.8 B.
        let (duplicate_dataset, duplicate_run) = duplicate_fixture();
        let duplicate_selection = MetricSelection::from_ids(&["duplicate_rate_5"]).unwrap();
        let duplicate_result =
            evaluate(&duplicate_dataset, &duplicate_run, &duplicate_selection).unwrap();
        let duplicates = &expected["duplicates-v1"];
        assert_close(
            duplicate_result.per_query["qdup"]["duplicate_rate_5"],
            duplicates["duplicate_rate_5_qdup"].as_f64().unwrap(),
            "duplicates-v1 qdup",
        );
        assert_close(
            duplicate_result.per_query["qclean"]["duplicate_rate_5"],
            duplicates["duplicate_rate_5_qclean"].as_f64().unwrap(),
            "duplicates-v1 qclean",
        );
        assert_close(
            duplicate_result.macro_metrics["duplicate_rate_5"],
            duplicates["macro"].as_f64().unwrap(),
            "duplicates-v1 macro",
        );

        // SPEC-0003-R9: §5.8 C.
        let (diversity_dataset, diversity_run) = diversity_fixture();
        let diversity_selection = MetricSelection::from_ids(&[
            "alpha_ndcg_10",
            "distinct_relevant_2",
            "distinct_relevant_4",
            "subtopic_recall_2",
            "subtopic_recall_4",
        ])
        .unwrap();
        let diversity_result =
            evaluate(&diversity_dataset, &diversity_run, &diversity_selection).unwrap();
        let diversity = &expected["diversity-v1"];
        for metric in [
            "alpha_ndcg_10",
            "distinct_relevant_2",
            "distinct_relevant_4",
            "subtopic_recall_2",
            "subtopic_recall_4",
        ] {
            assert_close(
                diversity_result.per_query["qexp"][metric],
                diversity[metric].as_f64().unwrap(),
                &format!("diversity-v1 {metric}"),
            );
        }
        let positives: std::collections::BTreeSet<&str> = diversity_dataset
            .document_judgments("qexp")
            .iter()
            .filter(|judgment| judgment.grade > 0)
            .flat_map(|judgment| judgment.subtopic_labels.iter().map(String::as_str))
            .collect();
        assert_eq!(
            positives.len() as u64,
            diversity["total_positive_subtopics"].as_u64().unwrap()
        );
    }
}
