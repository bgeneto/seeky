//! `perf` skeleton (SPEC-0003 R25-R28 are owned by WP-1.6).
//!
//! This command validates its inputs, verifies the index, captures the
//! environment and configuration, and writes an explicitly not-budget-eligible
//! performance report. Measurement suites land with WP-1.6.

use crate::corpus::{BenchPaths, Corpus};
use crate::engine::{self, EngineAdapter};
use crate::environment::{self, EvaluationSettings};
use crate::{Failure, Result};
use seeky_eval::{
    Artifacts, CommitInfo, Dataset, Decision, DecisionStatus, PerformanceReport, Report,
    ReportKind, SCHEMA_VERSION, Split, ToolInfo,
};
use std::path::Path;

#[allow(clippy::too_many_arguments)]
pub(crate) fn run(
    paths: &BenchPaths,
    corpus: &Corpus,
    dataset: &Dataset,
    config: &environment::RunConfig,
    data_dir: &Path,
    output: &Path,
    tier: &str,
    command: &[String],
) -> Result<()> {
    let sidecar = engine::sidecar_path(data_dir);
    if !sidecar.is_file() {
        return Err(Failure::engine(
            "INDEX_INCOMPATIBLE: no index metadata; run `seeky-bench index` first",
        ));
    }
    let adapter = EngineAdapter::open(data_dir, config)?;
    engine::verify_index(
        adapter.engine(),
        &sidecar,
        corpus,
        &dataset.corpus_hash,
        corpus.code_enabled,
    )?;
    let snapshot_json = adapter
        .engine()
        .config_snapshot()
        .map_err(|error| Failure::engine(error.to_string()))?
        .canonical_json();
    let settings = EvaluationSettings {
        split: Split::Dev,
        configuration: dataset.configuration,
        limit: crate::DEFAULT_LIMIT,
        metrics: crate::metric_ids(),
        seed: crate::DEFAULT_SEED.to_string(),
    };
    let combined = crate::combined(&snapshot_json, config, &settings)?;
    let config_hash = combined.sha256();
    let system_id: String = config_hash.chars().take(8).collect();
    let commit = crate::commit_info(&paths.root)?;
    let environment = environment::capture(tier, None, None);
    let system = crate::system_info(&snapshot_json, &config_hash, &system_id);
    let dataset_info = crate::dataset_info(dataset, &corpus.visibility);

    let report = Report {
        schema_version: SCHEMA_VERSION,
        run_id: crate::run_id("perf"),
        kind: ReportKind::Performance,
        generated_at: environment::rfc3339_now(),
        report: seeky_eval::ReportMetadata {
            work_package: "WP-1.2".to_string(),
            spec: "SPEC-0003".to_string(),
            area: corpus.id.clone(),
            title: format!("perf skeleton {}", corpus.id),
            hypothesis: String::new(),
            gate_ids: Vec::new(),
        },
        tool: ToolInfo {
            name: "seeky-bench".to_string(),
            version: env!("CARGO_PKG_VERSION").to_string(),
            eval_version: env!("CARGO_PKG_VERSION").to_string(),
        },
        commit: CommitInfo {
            sha: commit.sha,
            dirty: commit.dirty,
        },
        environment,
        dataset: dataset_info,
        system,
        command: crate::command_display(
            paths,
            &[(data_dir, "<data-dir>"), (output, "<output>")],
            command,
        ),
        quality: None,
        performance: Some(PerformanceReport {
            tier: tier.to_string(),
            qualifies_for_budget: false,
            search: Vec::new(),
            query_embedding: None,
            indexing: None,
            time_to_searchable: None,
            interference_ratio: None,
            resources: None,
            startup: None,
            distribution: None,
            ocr: None,
            visual: None,
            energy: None,
            warnings: Vec::new(),
        }),
        comparisons: Vec::new(),
        gates: Vec::new(),
        decision: Decision {
            status: DecisionStatus::NotApplicable,
            text: "Performance measurement is implemented by WP-1.6".to_string(),
        },
        artifacts: Artifacts {
            run: None,
            passage_run: None,
            config_snapshot: Some("config.snapshot.json".to_string()),
            environment: Some("environment.json".to_string()),
            checksums: Some("checksums.sha256".to_string()),
            index: None,
            exposure: None,
            pareto: None,
        },
    };
    report
        .validate()
        .map_err(|error| Failure::report(error.to_string()))?;

    let artifacts = crate::artifact::ArtifactDir::new(output)?;
    artifacts.write_report("results.json", &report)?;
    artifacts.write_text("summary.md", &seeky_eval::render_markdown(&report))?;
    artifacts.write_text("config.snapshot.json", &snapshot_json)?;
    artifacts.write_json("environment.json", &report.environment)?;
    artifacts.commit()?;
    adapter.shutdown()?;

    println!(
        "perf skeleton for {} at tier {tier}: not budget-eligible (WP-1.6)",
        corpus.id
    );
    Ok(())
}
