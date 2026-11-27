//! Seeky evaluation: datasets, relevance judgments, metrics, statistics, and
//! report writing.
//!
//! Responsibilities and allowed dependencies:
//! `docs/specs/SPEC-0001-workspace-and-crate-boundaries.md` sections 4.2 and 4.4.

mod beir;
mod dataset;
mod error;
mod metrics;
mod qrels;
mod report;
mod run;
mod sdc;
mod stats;
mod util;

pub use beir::load_beir;
pub use dataset::{
    Dataset, Document, DocumentId, DocumentJudgment, EvaluationConfiguration, LanguageSlice,
    Passage, PassageId, PassageJudgment, Query, QueryCategory, QueryId, Split,
};
pub use error::{EvalError, Result};
pub use metrics::{
    EvaluationResult, MetricKind, MetricSelection, MetricSpec, QueryContext, evaluate,
    weighted_primary,
};
pub use report::{
    Artifacts, CommitInfo, ComparisonMetric, ComparisonReport, DatasetInfo, Decision,
    DecisionStatus, DiversitySummary, DuplicateSummary, GateResult, GateStatus, IndexingMetrics,
    InterferenceRatio, LatencyMetrics, ModelInfo, PerformanceReport, QualityReport, QueryMetrics,
    Report, ReportKind, ReportMetadata, ResourceMetrics, SCHEMA_VERSION, SearchMeasurement,
    SearchableLatency, SliceGroups, SliceMetrics, StartupMetrics, SystemInfo, TimeToSearchable,
    ToolInfo, render_markdown, write_report_json, write_report_markdown,
};
pub use run::{
    ChunkHit, MappedChunkRun, Run, RunRow, RunTarget, map_chunk_run, read_trec_run, write_trec_run,
};
pub use sdc::load_sdc;
pub use stats::{
    Comparison, PairedStatistic, Significance, StatsOptions, compare, compare_many, holm_adjust,
};

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::{
        Comparison, Dataset, EvaluationConfiguration, EvaluationResult, MetricKind,
        MetricSelection, QueryCategory, Report, Result, Run, RunTarget, Split, StatsOptions,
        compare, evaluate, load_beir, load_sdc,
    };

    #[test]
    fn eval_public_api_exposes_dataset_run_metrics_and_report_types() {
        let _: fn(&Path, Split) -> Result<Dataset> = load_beir;
        let _: fn(&Path, &Path, Split, EvaluationConfiguration) -> Result<Dataset> = load_sdc;
        let _: fn(&Dataset, &Run, &MetricSelection) -> Result<EvaluationResult> = evaluate;
        let _: fn(&EvaluationResult, &EvaluationResult, &StatsOptions) -> Result<Comparison> =
            compare;
        let _ = std::mem::size_of::<Report>();
        let _ = RunTarget::Document(String::new());
        let _ = MetricKind::Ndcg;
        let _ = QueryCategory::KnownItem;
    }

    #[test]
    fn eval_crate_has_no_engine_ui_or_tauri_dependency() {
        let manifest = include_str!("../Cargo.toml");
        for forbidden in [
            "seeky-engine",
            "seeky-store",
            "seeky-search",
            "seeky-infer",
            "tauri",
        ] {
            assert!(
                !manifest.contains(forbidden),
                "seeky-eval must not depend on {forbidden}"
            );
        }
    }
}
