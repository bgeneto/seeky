//! Versioned report object and Markdown writer (SPEC-0003 R12/R13).

use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::dataset::{Dataset, EvaluationConfiguration, LanguageSlice, QueryCategory, Split};
use crate::error::{EvalError, Result};
use crate::metrics::EvaluationResult;
use crate::stats::Comparison;

/// Report schema version.
pub const SCHEMA_VERSION: u32 = 1;

/// Report payload kind.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReportKind {
    /// Quality evaluation.
    Quality,
    /// Performance measurement.
    Performance,
    /// Baseline/candidate comparison.
    Comparison,
    /// WP-1.8 smoke gate.
    SmokeGate,
}

/// Template metadata.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ReportMetadata {
    /// Implementing work package.
    pub work_package: String,
    /// Spec identifier.
    pub spec: String,
    /// Area/title prefix.
    pub area: String,
    /// Short title.
    pub title: String,
    /// Tested hypothesis.
    pub hypothesis: String,
    /// Gate IDs.
    pub gate_ids: Vec<String>,
}

/// Tool identity.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ToolInfo {
    /// Tool name.
    pub name: String,
    /// Tool version.
    pub version: String,
    /// Evaluator version.
    pub eval_version: String,
}

/// Git state recorded by the run.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CommitInfo {
    /// Commit SHA.
    pub sha: String,
    /// Whether the tree was dirty.
    pub dirty: bool,
}

/// Dataset identity and hashes.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DatasetInfo {
    /// Dataset ID.
    pub id: String,
    /// Split.
    pub split: Split,
    /// Evaluation configuration.
    pub configuration: EvaluationConfiguration,
    /// Corpus hash.
    pub corpus_hash: String,
    /// Dataset fingerprint.
    pub fingerprint: String,
    /// Judgment-set ID.
    pub judgment_set_id: String,
    /// Judgment-set hash.
    pub judgment_set_hash: String,
    /// Selected query count.
    pub query_count: u64,
    /// Query set hash.
    pub query_set_sha256: String,
    /// Public/private visibility.
    pub visibility: String,
}

/// Model variant identity.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ModelInfo {
    /// Model ID.
    pub id: String,
    /// Role.
    pub task: String,
    /// Variant.
    pub variant: String,
    /// File hash.
    pub sha256: String,
    /// Execution provider.
    pub provider: String,
}

/// System and config identity.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SystemInfo {
    /// System ID.
    pub system_id: String,
    /// Configuration hash.
    pub config_hash: String,
    /// Ordered model variants.
    pub models: Vec<ModelInfo>,
    /// Execution provider.
    pub provider: String,
}

/// One query's metrics.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct QueryMetrics {
    /// Query ID.
    pub query_id: String,
    /// Category.
    pub category: QueryCategory,
    /// Language slice.
    pub language_slice: LanguageSlice,
    /// Metric ratios.
    pub metrics: BTreeMap<String, f64>,
}

/// Metrics for one category/language slice.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SliceMetrics {
    /// Query count in the slice.
    pub query_count: u64,
    /// Metric values.
    pub metrics: BTreeMap<String, Option<f64>>,
}

/// Language/category groups.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SliceGroups {
    /// Group name → metrics.
    pub groups: BTreeMap<String, SliceMetrics>,
}

/// Duplicate summary.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DuplicateSummary {
    /// Duplicate-rate@10 when available.
    pub duplicate_rate_10: Option<f64>,
    /// Number of queries in the duplicate-heavy slice.
    pub query_count: u64,
}

/// Diversity summary.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DiversitySummary {
    /// α-nDCG@10 when available.
    pub alpha_ndcg_10: Option<f64>,
    /// Number of eligible exploratory queries.
    pub query_count: u64,
}

/// Quality payload.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct QualityReport {
    /// Filter application mode.
    pub filter_mode: String,
    /// Macro metrics; `None` means explicitly unavailable.
    #[serde(rename = "macro")]
    pub macro_metrics: BTreeMap<String, Option<f64>>,
    /// Weighted primary over the eight default categories.
    pub weighted_primary: Option<f64>,
    /// Language and category groups.
    pub slices: BTreeMap<String, SliceGroups>,
    /// Category summary.
    pub categories: BTreeMap<String, SliceMetrics>,
    /// Duplicate summary.
    pub duplicate: Option<DuplicateSummary>,
    /// Diversity summary.
    pub diversity: Option<DiversitySummary>,
    /// Queries with no positive judgment.
    pub queries_without_positive: u64,
    /// Chunks that mapped to no gold passage.
    pub unmapped_chunks: u64,
    /// Per-query rows; omitted for private data.
    pub per_query: Vec<QueryMetrics>,
    /// Nonfatal warnings.
    pub warnings: Vec<String>,
}

impl QualityReport {
    /// Convert a validated evaluation into the report payload.
    #[must_use]
    pub fn from_evaluation(
        dataset: &Dataset,
        result: &EvaluationResult,
        filter_mode: &str,
        unmapped_chunks: u64,
    ) -> Self {
        let mut macro_metrics: BTreeMap<String, Option<f64>> = result
            .macro_metrics
            .iter()
            .map(|(id, value)| (id.clone(), Some(*value)))
            .collect();
        for metric in &result.unavailable_metrics {
            macro_metrics.insert(metric.clone(), None);
        }
        for required in ["ndcg_10", "mrr_10", "recall_100", "success_1"] {
            macro_metrics.entry(required.to_owned()).or_insert(None);
        }
        let mut language_groups = BTreeMap::new();
        for (name, values) in &result.language_metrics {
            let query_count = result
                .query_contexts
                .values()
                .filter(|context| context.language_slice.as_str() == name)
                .count();
            language_groups.insert(
                name.clone(),
                SliceMetrics {
                    query_count: u64::try_from(query_count).unwrap_or(u64::MAX),
                    metrics: values
                        .iter()
                        .map(|(id, value)| (id.clone(), Some(*value)))
                        .collect(),
                },
            );
        }
        let mut slices = BTreeMap::new();
        slices.insert(
            "language".to_owned(),
            SliceGroups {
                groups: language_groups,
            },
        );
        let mut categories = BTreeMap::new();
        for (name, values) in &result.category_metrics {
            let query_count = dataset
                .queries()
                .iter()
                .filter(|query| query.category.as_str() == name)
                .count();
            categories.insert(
                name.clone(),
                SliceMetrics {
                    query_count: u64::try_from(query_count).unwrap_or(u64::MAX),
                    metrics: values
                        .iter()
                        .map(|(id, value)| (id.clone(), Some(*value)))
                        .collect(),
                },
            );
        }
        slices.insert(
            "category".to_owned(),
            SliceGroups {
                groups: categories.clone(),
            },
        );
        let per_query = result
            .per_query
            .iter()
            .filter_map(|(query_id, metrics)| {
                result
                    .query_contexts
                    .get(query_id)
                    .map(|context| QueryMetrics {
                        query_id: query_id.clone(),
                        category: context.category,
                        language_slice: context.language_slice,
                        metrics: metrics.clone(),
                    })
            })
            .collect();
        let duplicate = if dataset.duplicate_metrics_available() {
            Some(DuplicateSummary {
                duplicate_rate_10: result.macro_metrics.get("duplicate_rate_10").copied(),
                query_count: u64::try_from(dataset.duplicate_heavy_query_ids().len())
                    .unwrap_or(u64::MAX),
            })
        } else {
            None
        };
        let diversity = if result.macro_metrics.contains_key("alpha_ndcg_10") {
            Some(DiversitySummary {
                alpha_ndcg_10: result.macro_metrics.get("alpha_ndcg_10").copied(),
                query_count: u64::try_from(
                    dataset
                        .queries()
                        .iter()
                        .filter(|query| query.category == QueryCategory::Exploratory)
                        .count(),
                )
                .unwrap_or(u64::MAX),
            })
        } else {
            None
        };
        Self {
            filter_mode: filter_mode.to_owned(),
            macro_metrics,
            weighted_primary: result.weighted_primary,
            slices,
            categories,
            duplicate,
            diversity,
            queries_without_positive: u64::try_from(result.queries_without_positive)
                .unwrap_or(u64::MAX),
            unmapped_chunks,
            per_query,
            warnings: result
                .unavailable_metrics
                .iter()
                .map(|metric| format!("metric unavailable: {metric}"))
                .collect(),
        }
    }
}

/// Latency percentile set.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LatencyMetrics {
    /// Median.
    pub p50: f64,
    /// 95th percentile.
    pub p95: f64,
    /// 99th percentile.
    pub p99: f64,
    /// Confidence intervals by percentile.
    pub ci95: BTreeMap<String, [f64; 2]>,
}

/// One search measurement.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SearchMeasurement {
    /// Stage.
    pub stage: String,
    /// Warm/cold and idle/indexing condition.
    pub condition: String,
    /// Query executions.
    pub queries: u64,
    /// Fixed-set repetitions.
    pub repetitions: u64,
    /// Latency values.
    pub latency_ms: LatencyMetrics,
}

/// Batch-1 query-embedding latency (SPEC-0003 section 4.10).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct QueryEmbeddingMetrics {
    /// Embedding batch size; always 1.
    pub batch: u64,
    /// Measured embedding calls after warm-up.
    pub samples: u64,
    /// Latency values.
    pub latency_ms: LatencyMetrics,
}

/// Indexing throughput.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct IndexingMetrics {
    /// Files per second.
    pub files_per_s: f64,
    /// Extraction MB/s.
    pub extract_mb_per_s: f64,
    /// Passages per second.
    pub passages_per_s: f64,
    /// Provider.
    pub provider: String,
    /// Samples.
    pub samples: u64,
}

/// Time-to-searchable pair.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SearchableLatency {
    /// Samples.
    pub samples: u64,
    /// Median milliseconds.
    pub p50: f64,
    /// 95th percentile milliseconds.
    pub p95: f64,
}

/// Time-to-searchable metrics.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TimeToSearchable {
    /// Lexical availability.
    pub lexical_ms: SearchableLatency,
    /// Semantic availability.
    pub semantic_ms: SearchableLatency,
}

/// Interference ratio.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct InterferenceRatio {
    /// Ratio.
    pub value: f64,
    /// Idle p95.
    pub idle_p95_ms: f64,
    /// Indexing p95.
    pub indexing_p95_ms: f64,
    /// Confidence interval.
    pub ci95: [f64; 2],
}

/// Resource metrics.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ResourceMetrics {
    /// Idle RSS; null when the platform cannot sample process memory.
    pub idle_rss_bytes: Option<u64>,
    /// Peak RSS; null when the platform cannot sample process memory.
    pub peak_rss_bytes: Option<u64>,
    /// Page-cache bytes when measurable.
    pub page_cache_bytes: Option<u64>,
    /// Index bytes.
    pub index_bytes: u64,
    /// Disk per 1k passages.
    pub disk_bytes_per_1k_passages: f64,
    /// Measurement scope.
    pub scope: String,
    /// Sampling interval.
    pub sampling_interval_ms: u64,
}

/// Startup metrics.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StartupMetrics {
    /// Whether this was a fresh process.
    pub cold: bool,
    /// OS cache status.
    pub os_cache: String,
    /// Time to Instant capability.
    pub instant_capable_ms: f64,
    /// Time to semantic capability.
    pub semantic_capable_ms: Option<f64>,
}

/// Performance payload.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PerformanceReport {
    /// Hardware tier.
    pub tier: String,
    /// Whether all sampling/tier conditions were met.
    pub qualifies_for_budget: bool,
    /// Search measurements.
    pub search: Vec<SearchMeasurement>,
    /// Query-embedding latency.
    pub query_embedding: Option<QueryEmbeddingMetrics>,
    /// Indexing throughput.
    pub indexing: Option<IndexingMetrics>,
    /// Time to searchable.
    pub time_to_searchable: Option<TimeToSearchable>,
    /// Interference ratio.
    pub interference_ratio: Option<InterferenceRatio>,
    /// Resource metrics.
    pub resources: Option<ResourceMetrics>,
    /// Startup metrics.
    pub startup: Option<StartupMetrics>,
    /// Distribution measurements.
    pub distribution: Option<serde_json::Value>,
    /// OCR metrics.
    pub ocr: Option<serde_json::Value>,
    /// Visual metrics.
    pub visual: Option<serde_json::Value>,
    /// Energy metrics.
    pub energy: Option<serde_json::Value>,
    /// One entry per unavailable, undersampled, or not-budget-eligible value.
    #[serde(default)]
    pub warnings: Vec<String>,
}

/// One paired comparison report row.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ComparisonMetric {
    /// Delta.
    pub delta: f64,
    /// Delta in points.
    pub delta_points: f64,
    /// CI low.
    pub ci95_low: f64,
    /// CI high.
    pub ci95_high: f64,
    /// Randomization p.
    pub p_value: f64,
    /// Holm-adjusted p.
    pub holm_p: Option<f64>,
    /// Significance.
    pub significance: String,
}

/// Paired comparison payload.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ComparisonReport {
    /// Baseline system.
    pub baseline_system_id: String,
    /// Candidate systems.
    pub candidate_system_ids: Vec<String>,
    /// Paired query count.
    pub paired_queries: u64,
    /// Seed.
    pub seed: String,
    /// Metrics.
    pub metrics: BTreeMap<String, ComparisonMetric>,
}

impl ComparisonReport {
    /// Convert from statistics output.
    #[must_use]
    pub fn from_comparison(comparison: &Comparison) -> Self {
        let metrics = comparison
            .metrics
            .iter()
            .map(|(id, statistic)| {
                (
                    id.clone(),
                    ComparisonMetric {
                        delta: statistic.delta,
                        delta_points: statistic.delta_points,
                        ci95_low: statistic.ci95_low,
                        ci95_high: statistic.ci95_high,
                        p_value: statistic.p_value,
                        holm_p: statistic.holm_p,
                        significance: format!("{:?}", statistic.significance).to_lowercase(),
                    },
                )
            })
            .collect();
        Self {
            baseline_system_id: comparison.baseline_system_id.clone(),
            candidate_system_ids: comparison.candidate_system_ids.clone(),
            paired_queries: u64::try_from(comparison.paired_queries).unwrap_or(u64::MAX),
            seed: comparison.seed.clone(),
            metrics,
        }
    }
}

/// Gate status.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GateStatus {
    /// Gate passed.
    Pass,
    /// Gate failed.
    Fail,
    /// Gate did not apply.
    NotApplicable,
}

/// One gate result.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GateResult {
    /// Gate ID.
    pub id: String,
    /// Status.
    pub status: GateStatus,
    /// Threshold text.
    pub threshold: String,
    /// Observed value.
    pub observed: serde_json::Value,
    /// Additional bounded details.
    pub details: String,
}

/// Decision status.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DecisionStatus {
    /// Candidate adopted.
    Adopt,
    /// Candidate rejected.
    Reject,
    /// Inconclusive.
    Inconclusive,
    /// Evidence-only report.
    NotApplicable,
}

/// Report decision.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Decision {
    /// Status.
    pub status: DecisionStatus,
    /// Bounded explanation.
    pub text: String,
}

/// Relative artifact names.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Artifacts {
    /// Document run.
    pub run: Option<String>,
    /// Passage run.
    pub passage_run: Option<String>,
    /// Config snapshot.
    pub config_snapshot: Option<String>,
    /// Environment capture.
    pub environment: Option<String>,
    /// Checksums.
    pub checksums: Option<String>,
    /// Index sidecar.
    pub index: Option<String>,
    /// Exposure record.
    pub exposure: Option<String>,
    /// Pareto plot.
    pub pareto: Option<String>,
}

/// Complete report object.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Report {
    /// Schema version.
    pub schema_version: u32,
    /// Unique run ID.
    pub run_id: String,
    /// Payload kind.
    pub kind: ReportKind,
    /// Generation timestamp.
    pub generated_at: String,
    /// Template metadata.
    pub report: ReportMetadata,
    /// Tool identity.
    pub tool: ToolInfo,
    /// Git state.
    pub commit: CommitInfo,
    /// Privacy-safe environment object.
    pub environment: serde_json::Value,
    /// Dataset identity.
    pub dataset: DatasetInfo,
    /// System identity.
    pub system: SystemInfo,
    /// Reproduction command.
    pub command: Vec<String>,
    /// Quality payload.
    pub quality: Option<QualityReport>,
    /// Performance payload.
    pub performance: Option<PerformanceReport>,
    /// Paired comparisons.
    pub comparisons: Vec<ComparisonReport>,
    /// Gate results.
    pub gates: Vec<GateResult>,
    /// Decision.
    pub decision: Decision,
    /// Artifact names.
    pub artifacts: Artifacts,
}

impl Report {
    /// Validate required schema semantics before writing.
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != SCHEMA_VERSION {
            return Err(report_error("schema_version", "unsupported report schema"));
        }
        for (field, value) in [
            ("run_id", self.run_id.as_str()),
            ("generated_at", self.generated_at.as_str()),
            ("report.work_package", self.report.work_package.as_str()),
            ("report.spec", self.report.spec.as_str()),
            ("report.area", self.report.area.as_str()),
            ("report.title", self.report.title.as_str()),
            ("tool.name", self.tool.name.as_str()),
            ("tool.version", self.tool.version.as_str()),
            ("tool.eval_version", self.tool.eval_version.as_str()),
            ("commit.sha", self.commit.sha.as_str()),
            ("dataset.id", self.dataset.id.as_str()),
            ("dataset.corpus_hash", self.dataset.corpus_hash.as_str()),
            ("dataset.fingerprint", self.dataset.fingerprint.as_str()),
            (
                "dataset.judgment_set_hash",
                self.dataset.judgment_set_hash.as_str(),
            ),
            (
                "dataset.query_set_sha256",
                self.dataset.query_set_sha256.as_str(),
            ),
            ("system.system_id", self.system.system_id.as_str()),
            ("system.config_hash", self.system.config_hash.as_str()),
            ("decision.text", self.decision.text.as_str()),
        ] {
            if value.trim().is_empty() {
                return Err(report_error(field, "required value is empty"));
            }
        }
        if self.command.is_empty() || self.command.iter().any(|value| value.trim().is_empty()) {
            return Err(report_error("command", "reproduction command is empty"));
        }
        if !self.environment.is_object() {
            return Err(report_error("environment", "environment must be an object"));
        }
        if !matches!(self.dataset.visibility.as_str(), "public" | "private") {
            return Err(report_error("dataset.visibility", "unknown visibility"));
        }
        match self.kind {
            ReportKind::Quality | ReportKind::SmokeGate => {
                if self.quality.is_none() {
                    return Err(report_error("quality", "quality payload is required"));
                }
            }
            ReportKind::Performance => {
                if self.performance.is_none() {
                    return Err(report_error(
                        "performance",
                        "performance payload is required",
                    ));
                }
            }
            ReportKind::Comparison => {
                if self.comparisons.is_empty() {
                    return Err(report_error(
                        "comparisons",
                        "comparison payload is required",
                    ));
                }
            }
        }
        for artifact in [
            self.artifacts.run.as_deref(),
            self.artifacts.passage_run.as_deref(),
            self.artifacts.config_snapshot.as_deref(),
            self.artifacts.environment.as_deref(),
            self.artifacts.checksums.as_deref(),
            self.artifacts.index.as_deref(),
            self.artifacts.exposure.as_deref(),
            self.artifacts.pareto.as_deref(),
        ]
        .into_iter()
        .flatten()
        {
            if Path::new(artifact).is_absolute() {
                return Err(report_error("artifacts", "artifact names must be relative"));
            }
        }
        if self.kind != ReportKind::Comparison {
            for (name, value) in [
                ("checksums", self.artifacts.checksums.as_deref()),
                ("environment", self.artifacts.environment.as_deref()),
                ("config_snapshot", self.artifacts.config_snapshot.as_deref()),
            ] {
                if value.is_none_or(str::is_empty) {
                    return Err(report_error(
                        "artifacts",
                        format!("missing required artifact: {name}"),
                    ));
                }
            }
            if matches!(self.kind, ReportKind::Quality | ReportKind::SmokeGate)
                && self.dataset.visibility == "public"
                && self.artifacts.run.is_none()
            {
                return Err(report_error("artifacts", "missing required run artifact"));
            }
        }
        if let Some(quality) = &self.quality {
            if !matches!(quality.filter_mode.as_str(), "none" | "pushdown" | "post") {
                return Err(report_error(
                    "quality.filter_mode",
                    "unknown filter application mode",
                ));
            }
            for required in ["ndcg_10", "mrr_10", "recall_100", "success_1"] {
                if !quality.macro_metrics.contains_key(required) {
                    return Err(report_error(
                        "quality.macro_metrics",
                        format!("missing required metric: {required}"),
                    ));
                }
            }
            if self.dataset.visibility == "private"
                && (!quality.per_query.is_empty()
                    || self.artifacts.run.is_some()
                    || self.artifacts.passage_run.is_some()
                    || self.artifacts.index.is_some()
                    || self.artifacts.exposure.is_some())
            {
                return Err(report_error(
                    "privacy",
                    "private report must omit per-query rows and local target artifacts",
                ));
            }
            for value in quality
                .macro_metrics
                .values()
                .filter_map(|value| *value)
                .chain(quality.weighted_primary)
            {
                if !value.is_finite() {
                    return Err(report_error("quality", "metric is not finite"));
                }
            }
        }
        if self.kind != ReportKind::Comparison && !self.comparisons.is_empty() {
            // A quality run may include `--baseline` paired evidence, so this
            // is intentionally allowed.
        }
        Ok(())
    }
}

/// Write the deterministic JSON representation.
pub fn write_report_json(report: &Report, path: &Path) -> Result<()> {
    report.validate()?;
    let mut json = serde_json::to_string_pretty(report)
        .map_err(|error| report_error("results.json", error.to_string()))?;
    json.push('\n');
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| EvalError::io(parent, error))?;
    }
    std::fs::write(path, json).map_err(|error| EvalError::io(path, error))
}

/// Render the report template.
pub fn write_report_markdown(report: &Report, path: &Path) -> Result<()> {
    report.validate()?;
    let markdown = render_markdown(report);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| EvalError::io(parent, error))?;
    }
    std::fs::write(path, markdown).map_err(|error| EvalError::io(path, error))
}

/// Render Markdown without writing.
#[must_use]
pub fn render_markdown(report: &Report) -> String {
    let date = report.generated_at.get(..10).unwrap_or("unknown-date");
    let mut out = String::new();
    let _ = writeln!(
        out,
        "# {date} — {}: {}\n\n| Field | Value |\n|---|---|\n| Work package / spec | {} / {} |\n| Hypothesis | {} |\n| Gate(s) | {} |\n| Decision | {:?} |\n| Commit | `{}` |\n| Config hash | `{}` |\n| Hardware tier | {} |\n",
        escape(&report.report.area),
        escape(&report.report.title),
        escape(&report.report.work_package),
        escape(&report.report.spec),
        escape(&report.report.hypothesis),
        escape(&report.report.gate_ids.join(", ")),
        report.decision.status,
        escape(&report.commit.sha),
        escape(&report.system.config_hash),
        escape(
            report
                .performance
                .as_ref()
                .map_or("not measured", |performance| performance.tier.as_str())
        ),
    );
    let _ = writeln!(
        out,
        "## 1. Setup\n\n- Dataset: `{}`; split `{}`; configuration `{}`.\n- Corpus hash: `{}`; judgment set: `{}`; fingerprint: `{}`.\n- System: `{}`; provider: `{}`.\n- Command: `{}`.\n",
        escape(&report.dataset.id),
        match report.dataset.split {
            Split::Dev => "dev",
            Split::Test => "test",
        },
        report.dataset.configuration.as_str(),
        escape(&report.dataset.corpus_hash),
        escape(&report.dataset.judgment_set_id),
        escape(&report.dataset.fingerprint),
        escape(&report.system.system_id),
        escape(&report.system.provider),
        escape(&report.command.join(" ")),
    );
    let _ = writeln!(out, "## 2. Results\n");
    if let Some(quality) = &report.quality {
        let _ = writeln!(out, "### Quality\n");
        let _ = writeln!(
            out,
            "| System | Weighted nDCG@10 | pt | en | cross-lingual | other | Recall@100 | MRR@10 |\n|---|---:|---:|---:|---:|---:|---:|---:|\n| {} | {} | {} | {} | {} | {} | {} | {} |\n",
            escape(&report.system.system_id),
            format_metric(quality.weighted_primary),
            language_metric(quality, "pt", "ndcg_10"),
            language_metric(quality, "en", "ndcg_10"),
            language_metric(quality, "cross_lingual", "ndcg_10"),
            language_metric(quality, "other", "ndcg_10"),
            format_metric(quality.macro_metrics.get("recall_100").copied().flatten()),
            format_metric(quality.macro_metrics.get("mrr_10").copied().flatten()),
        );
        let _ = writeln!(out, "| Category | nDCG@10 |\n|---|---:|");
        for (category, values) in &quality.categories {
            let _ = writeln!(
                out,
                "| {} | {} |",
                escape(category),
                format_metric(values.metrics.get("ndcg_10").copied().flatten())
            );
        }
        if !report.comparisons.is_empty() {
            let _ = writeln!(
                out,
                "\nPaired differences:\n\n| Metric | Delta (points) | 95% CI | p | Holm |\n|---|---:|---:|---:|---:|"
            );
            for comparison in &report.comparisons {
                for (metric, statistic) in &comparison.metrics {
                    let _ = writeln!(
                        out,
                        "| {} | {:.3} | [{:.3}, {:.3}] | {:.6} | {} |",
                        escape(metric),
                        statistic.delta_points,
                        statistic.ci95_low * 100.0,
                        statistic.ci95_high * 100.0,
                        statistic.p_value,
                        statistic
                            .holm_p
                            .map_or_else(|| "—".to_owned(), |value| format!("{value:.6}"))
                    );
                }
            }
        }
        let _ = writeln!(out);
    } else {
        let _ = writeln!(out, "### Quality\n\nNot measured in this run.\n");
    }
    if let Some(performance) = &report.performance {
        let _ = writeln!(
            out,
            "### Performance\n\n| System | S1 p95 | S2 p95 | S3 p95 | passages/s | RSS idle | RSS peak | disk/1M | download |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|"
        );
        let _ = writeln!(
            out,
            "| {} | {} | {} | {} | {} | {} | {} | {} | — |",
            escape(&report.system.system_id),
            stage_p95(performance, "instant"),
            stage_p95(performance, "hybrid"),
            stage_p95(performance, "refined"),
            format_metric(
                performance
                    .indexing
                    .as_ref()
                    .map(|value| value.passages_per_s)
            ),
            format_metric(
                performance
                    .resources
                    .as_ref()
                    .and_then(|value| value.idle_rss_bytes)
                    .map(|value| value as f64)
            ),
            format_metric(
                performance
                    .resources
                    .as_ref()
                    .and_then(|value| value.peak_rss_bytes)
                    .map(|value| value as f64)
            ),
            format_metric(
                performance
                    .resources
                    .as_ref()
                    .map(|value| value.disk_bytes_per_1k_passages * 1000.0)
            )
        );
        let _ = writeln!(out);
        for warning in &performance.warnings {
            let _ = writeln!(out, "- Warning: {}", escape(warning));
        }
        if !performance.warnings.is_empty() {
            let _ = writeln!(out);
        }
    } else {
        let _ = writeln!(out, "### Performance\n\nNot measured in this run.\n");
    }
    let _ = writeln!(
        out,
        "### Pareto view\n\n{}\n",
        report.artifacts.pareto.as_ref().map_or_else(
            || "Not generated".to_owned(),
            |path| format!("Plot: `{path}`")
        )
    );
    let _ = writeln!(out, "## 3. Analysis\n");
    if let Some(quality) = &report.quality {
        for warning in &quality.warnings {
            let _ = writeln!(out, "- {}", escape(warning));
        }
        if quality.queries_without_positive > 0 {
            let _ = writeln!(
                out,
                "- {} queries have no positive judgment.",
                quality.queries_without_positive
            );
        }
        if quality.unmapped_chunks > 0 {
            let _ = writeln!(
                out,
                "- {} engine chunks mapped to no canonical passage.",
                quality.unmapped_chunks
            );
        }
    }
    let _ = writeln!(
        out,
        "\n## 4. Decision and follow-ups\n\n- Status: `{:?}`.\n- {}",
        report.decision.status,
        escape(&report.decision.text)
    );
    if !report.gates.is_empty() {
        let _ = writeln!(
            out,
            "\n| Gate | Status | Threshold | Observed |\n|---|---|---|---|"
        );
        for gate in &report.gates {
            let _ = writeln!(
                out,
                "| {} | {:?} | {} | {} |",
                escape(&gate.id),
                gate.status,
                escape(&gate.threshold),
                escape(&gate.observed.to_string())
            );
        }
    }
    let _ = writeln!(
        out,
        "\n## 5. Reproduction\n\n- Run: `{}`.\n- Commit: `{}`.\n- Config hash: `{}`.\n- Artifacts: {}.\n",
        escape(&report.command.join(" ")),
        escape(&report.commit.sha),
        escape(&report.system.config_hash),
        artifact_list(&report.artifacts)
    );
    out
}

fn language_metric(quality: &QualityReport, language: &str, metric: &str) -> String {
    quality
        .slices
        .get("language")
        .and_then(|groups| groups.groups.get(language))
        .and_then(|values| values.metrics.get(metric))
        .copied()
        .flatten()
        .map_or_else(|| "—".to_owned(), |value| format!("{value:.6}"))
}

fn format_metric(value: Option<f64>) -> String {
    value.map_or_else(|| "—".to_owned(), |value| format!("{value:.6}"))
}

fn stage_p95(performance: &PerformanceReport, stage: &str) -> String {
    performance
        .search
        .iter()
        .find(|measurement| measurement.stage == stage)
        .map_or_else(
            || "—".to_owned(),
            |measurement| format!("{:.6}", measurement.latency_ms.p95),
        )
}

fn artifact_list(artifacts: &Artifacts) -> String {
    let mut items = Vec::new();
    for (name, value) in [
        ("run", &artifacts.run),
        ("passage_run", &artifacts.passage_run),
        ("config_snapshot", &artifacts.config_snapshot),
        ("environment", &artifacts.environment),
        ("checksums", &artifacts.checksums),
        ("index", &artifacts.index),
        ("exposure", &artifacts.exposure),
        ("pareto", &artifacts.pareto),
    ] {
        if let Some(path) = value {
            items.push(format!("{name}=`{path}`"));
        }
    }
    if items.is_empty() {
        "—".to_owned()
    } else {
        items.join(", ")
    }
}

fn escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('|', "\\|")
        .replace(['\n', '\r'], " ")
}

fn report_error(location: &str, message: impl Into<String>) -> EvalError {
    EvalError::data("REPORT_INVALID", location, message)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dataset::{
        DatasetBuilder, EvaluationConfiguration, LanguageSlice, QueryCategory, Split,
    };
    use crate::metrics::{MetricSelection, evaluate};
    use crate::run::{Run, RunRow, RunTarget};

    fn quality_report() -> Report {
        let dataset = DatasetBuilder::new()
            .document("d1", "d1", false)
            .document("d2", "d2", false)
            .query(
                "q1",
                "q",
                QueryCategory::Conceptual,
                LanguageSlice::Pt,
                Split::Dev,
                EvaluationConfiguration::Default,
            )
            .query(
                "q2",
                "q",
                QueryCategory::Conceptual,
                LanguageSlice::En,
                Split::Dev,
                EvaluationConfiguration::Default,
            )
            .document_judgment("q1", "d1", 1, &[], &[])
            .document_judgment("q2", "d2", 1, &[], &[])
            .build();
        let run = Run {
            run_id: "r".to_owned(),
            system_id: "s".to_owned(),
            rows: vec![
                RunRow {
                    query_id: "q1".to_owned(),
                    target: RunTarget::Document("d1".to_owned()),
                    rank: 1,
                    score: 1.0,
                },
                RunRow {
                    query_id: "q2".to_owned(),
                    target: RunTarget::Document("d2".to_owned()),
                    rank: 1,
                    score: 1.0,
                },
            ],
        };
        let selection =
            MetricSelection::from_ids(&["ndcg_10", "mrr_10", "recall_100", "success_1"]).unwrap();
        let evaluation = evaluate(&dataset, &run, &selection).unwrap();
        let quality = QualityReport::from_evaluation(&dataset, &evaluation, "none", 0);
        Report {
            schema_version: SCHEMA_VERSION,
            run_id: "run-1".to_owned(),
            kind: ReportKind::Quality,
            generated_at: "2026-11-27T12:00:00Z".to_owned(),
            report: ReportMetadata {
                work_package: "WP-1.1".to_owned(),
                spec: "SPEC-0003".to_owned(),
                area: "quality".to_owned(),
                title: "Fixture".to_owned(),
                hypothesis: "Metrics render".to_owned(),
                gate_ids: vec!["Q1".to_owned()],
            },
            tool: ToolInfo {
                name: "seeky-eval".to_owned(),
                version: "0.1.0".to_owned(),
                eval_version: "0.1.0".to_owned(),
            },
            commit: CommitInfo {
                sha: "0123456789abcdef0123456789abcdef01234567".to_owned(),
                dirty: false,
            },
            environment: serde_json::json!({"tier": "T2"}),
            dataset: DatasetInfo {
                id: dataset.id.clone(),
                split: Split::Dev,
                configuration: EvaluationConfiguration::Default,
                corpus_hash: dataset.corpus_hash.clone(),
                fingerprint: dataset.fingerprint.clone(),
                judgment_set_id: dataset.judgment_set_id.clone(),
                judgment_set_hash: dataset.judgment_set_hash.clone(),
                query_count: 2,
                query_set_sha256: dataset.query_set_sha256().to_owned(),
                visibility: "public".to_owned(),
            },
            system: SystemInfo {
                system_id: "system".to_owned(),
                config_hash: "a".repeat(64),
                models: Vec::new(),
                provider: "cpu".to_owned(),
            },
            command: vec!["seeky-eval".to_owned()],
            quality: Some(quality),
            performance: None,
            comparisons: Vec::new(),
            gates: Vec::new(),
            decision: Decision {
                status: DecisionStatus::NotApplicable,
                text: "Evidence only".to_owned(),
            },
            artifacts: Artifacts {
                run: Some("run.trec".to_owned()),
                config_snapshot: Some("config.snapshot.json".to_owned()),
                environment: Some("environment.json".to_owned()),
                checksums: Some("checksums.sha256".to_owned()),
                ..Artifacts::default()
            },
        }
    }

    #[test]
    fn report_json_round_trip_and_schema_validation() {
        let report = quality_report();
        report.validate().unwrap();
        let text = serde_json::to_string(&report).unwrap();
        let parsed: Report = serde_json::from_str(&text).unwrap();
        parsed.validate().unwrap();
    }

    #[test]
    fn malformed_report_is_rejected() {
        let mut report = quality_report();
        report
            .quality
            .as_mut()
            .unwrap()
            .macro_metrics
            .remove("ndcg_10");
        assert_eq!(report.validate().unwrap_err().code(), "REPORT_INVALID");
    }

    #[test]
    fn report_json_is_deterministic() {
        let report = quality_report();
        let first = serde_json::to_string_pretty(&report).unwrap();
        let second = serde_json::to_string_pretty(&report).unwrap();
        assert_eq!(first, second);
    }

    #[test]
    fn markdown_report_matches_golden() {
        let report = quality_report();
        let markdown = render_markdown(&report);
        let expected = include_str!("../tests/fixtures/report-v1/expected.md");
        assert_eq!(markdown, expected);
    }

    #[test]
    fn missing_measurements_are_not_invented() {
        let mut report = quality_report();
        report
            .quality
            .as_mut()
            .unwrap()
            .macro_metrics
            .insert("recall_100".to_owned(), None);
        assert!(render_markdown(&report).contains("| system |"));
        assert!(render_markdown(&report).contains("—"));
    }

    #[test]
    fn performance_payload_keeps_unavailable_values_null_with_warnings() {
        // SPEC-0003-R27: unavailable values are null with a warning, never zero.
        let performance = PerformanceReport {
            tier: "T2".to_owned(),
            qualifies_for_budget: false,
            search: Vec::new(),
            query_embedding: Some(QueryEmbeddingMetrics {
                batch: 1,
                samples: 10,
                latency_ms: LatencyMetrics {
                    p50: 1.0,
                    p95: 2.0,
                    p99: 3.0,
                    ci95: BTreeMap::new(),
                },
            }),
            indexing: None,
            time_to_searchable: None,
            interference_ratio: None,
            resources: Some(ResourceMetrics {
                idle_rss_bytes: None,
                peak_rss_bytes: None,
                page_cache_bytes: None,
                index_bytes: 2_500,
                disk_bytes_per_1k_passages: 2_500.0,
                scope: "engine_headless".to_owned(),
                sampling_interval_ms: 50,
            }),
            startup: None,
            distribution: None,
            ocr: None,
            visual: None,
            energy: None,
            warnings: vec!["resources.idle_rss_bytes unavailable".to_owned()],
        };
        let value = serde_json::to_value(&performance).unwrap();
        assert_eq!(value["query_embedding"]["batch"], 1);
        assert_eq!(value["query_embedding"]["samples"], 10);
        assert!(value["resources"]["idle_rss_bytes"].is_null());
        assert!(value["resources"]["page_cache_bytes"].is_null());
        let mut legacy = value.clone();
        legacy.as_object_mut().unwrap().remove("warnings");
        let parsed: PerformanceReport = serde_json::from_value(legacy).unwrap();
        assert!(parsed.warnings.is_empty());

        let mut report = quality_report();
        report.performance = Some(performance);
        let markdown = render_markdown(&report);
        assert!(markdown.contains("- Warning: resources.idle_rss_bytes unavailable"));
    }

    #[test]
    fn report_writers_write_valid_deterministic_artifacts() {
        let report = quality_report();
        let dir = tempfile::TempDir::new().unwrap();
        let json_path = dir.path().join("results.json");
        let markdown_path = dir.path().join("summary.md");
        write_report_json(&report, &json_path).unwrap();
        write_report_markdown(&report, &markdown_path).unwrap();
        let parsed: Report = serde_json::from_slice(&std::fs::read(&json_path).unwrap()).unwrap();
        parsed.validate().unwrap();
        assert_eq!(
            std::fs::read_to_string(&markdown_path).unwrap(),
            render_markdown(&report)
        );
    }

    #[test]
    fn report_reader_never_panics_on_arbitrary_bytes() {
        let mut state = 0xabcd_1234_u64;
        for index in 0..64 {
            let mut bytes = vec![0x7b];
            for _ in 0..(index * 5) {
                state = state
                    .wrapping_mul(6_364_136_223_846_793_005)
                    .wrapping_add(1);
                bytes.push((state >> 24) as u8);
            }
            assert!(serde_json::from_slice::<Report>(&bytes).is_err());
        }
    }

    #[test]
    fn private_report_omits_per_query_and_paths() {
        let mut report = quality_report();
        report.dataset.visibility = "private".to_owned();
        report.artifacts.run = None;
        report.quality.as_mut().unwrap().per_query.clear();
        report.validate().unwrap();
        report
            .quality
            .as_mut()
            .unwrap()
            .per_query
            .push(QueryMetrics {
                query_id: "private-query".to_owned(),
                category: QueryCategory::Conceptual,
                language_slice: LanguageSlice::En,
                metrics: BTreeMap::new(),
            });
        assert_eq!(report.validate().unwrap_err().code(), "REPORT_INVALID");
    }
}
