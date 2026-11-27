//! `eval` execution (SPEC-0003 R18, R32).

use crate::corpus::{self, BenchPaths, Corpus};
use crate::engine::{self, EngineAdapter};
use crate::environment::{self, EvaluationSettings};
use crate::{EvalInput, Failure, Result};
use seeky_engine::{SearchMode, SearchOptions, SearchRequest};
use seeky_eval::{
    Artifacts, ChunkHit, CommitInfo, Dataset, Decision, DecisionStatus, EvaluationResult,
    MetricSelection, QualityReport, Report, ReportKind, Run, RunRow, RunTarget, SCHEMA_VERSION,
    Split, ToolInfo,
};
use std::collections::{BTreeMap, BTreeSet};

pub(crate) fn execute(
    paths: &BenchPaths,
    corpus: &Corpus,
    dataset: &Dataset,
    config: &environment::RunConfig,
    input: &EvalInput,
) -> Result<()> {
    let sidecar = engine::sidecar_path(&input.data_dir);
    if !sidecar.is_file() {
        return Err(Failure::engine(
            "INDEX_INCOMPATIBLE: no index metadata; run `seeky-bench index` first",
        ));
    }
    let adapter = EngineAdapter::open(&input.data_dir, config)?;
    engine::verify_index(
        adapter.engine(),
        &sidecar,
        corpus,
        &dataset.corpus_hash,
        input.code_enabled,
    )?;

    let snapshot_json = adapter
        .engine()
        .config_snapshot()
        .map_err(|error| Failure::engine(error.to_string()))?
        .canonical_json();
    let settings = EvaluationSettings {
        split: input.split,
        configuration: dataset.configuration,
        limit: input.limit,
        metrics: crate::metric_ids(),
        seed: input.seed.clone(),
    };
    let combined = crate::combined(&snapshot_json, config, &settings)?;
    let config_hash = combined.sha256();
    let system_id = if input.system_id.trim().is_empty() {
        config_hash.chars().take(8).collect::<String>()
    } else {
        input.system_id.clone()
    };

    let mut exposure_started = None;
    let mut system_id = system_id;
    if input.split == Split::Test {
        let started = crate::gate::begin_test_run(
            paths,
            corpus,
            dataset,
            input
                .confirmation
                .as_deref()
                .ok_or_else(|| Failure::usage("test split requires --confirmation"))?,
            &input.config_path,
            &config_hash,
            &settings,
            &input.output,
        )?;
        system_id = started.system_id().to_string();
        exposure_started = Some(started);
    }

    let roots: Vec<(String, String)> = {
        let mut prefixes: Vec<(String, String)> = corpus
            .roots
            .iter()
            .zip(&corpus.root_labels)
            .map(|(root, label)| {
                let canonical = std::fs::canonicalize(root).unwrap_or_else(|_| root.clone());
                let prefix = canonical
                    .to_string_lossy()
                    .replace('\\', "/")
                    .trim_end_matches('/')
                    .to_string();
                (prefix, label.clone())
            })
            .collect();
        prefixes.sort_by_key(|(prefix, _)| std::cmp::Reverse(prefix.len()));
        prefixes
    };
    let root_id = adapter
        .engine()
        .list_roots()
        .map_err(|error| Failure::engine(error.to_string()))?
        .first()
        .map(|root| root.id.clone())
        .ok_or_else(|| Failure::engine("the data directory has no indexed root"))?;
    let root_label = corpus
        .root_labels
        .first()
        .cloned()
        .ok_or_else(|| Failure::engine("the corpus declares no indexed root"))?;

    let selection = crate::selection()?;
    let max_cutoff = selection.max_cutoff() as usize;
    let query_filters = corpus::query_filters(corpus, input.split)?;
    let mut queries = dataset.queries().to_vec();
    queries.sort_by(|left, right| left.id.cmp(&right.id));

    let mut document_rows: BTreeMap<String, Vec<(String, f64)>> = BTreeMap::new();
    let mut chunk_hits: Vec<ChunkHit> = Vec::new();
    let mut mapped_documents: BTreeSet<String> = BTreeSet::new();
    let mut saw_filter = false;
    let mut saw_post = false;

    for query in &queries {
        if query.split != input.split || query.configuration != dataset.configuration {
            continue;
        }
        let filter = match query
            .filters
            .as_ref()
            .or_else(|| query_filters.get(&query.id))
        {
            Some(value) => Some(
                engine::parse_query_filter(value, &root_id, &root_label)
                    .map_err(|error| Failure::dataset(error.to_string()))?,
            ),
            None => None,
        };
        let outcome = adapter
            .engine()
            .search_with(
                &SearchRequest {
                    query: query.text.clone(),
                    limit: Some(input.limit),
                },
                &SearchOptions {
                    mode: SearchMode::Evaluation,
                    filters: filter,
                    telemetry: false,
                },
            )
            .map_err(|error| Failure::engine(error.to_string()))?;
        if let Some(report) = &outcome.filter {
            saw_filter = true;
            if report.mode == seeky_engine::FilterMode::Post {
                saw_post = true;
            }
        }
        if engine::depth_is_insufficient(&outcome.depth, outcome.filter.as_ref(), max_cutoff) {
            return Err(Failure::report(format!(
                "INSUFFICIENT_DEPTH: query {} returned {} hits below the {max_cutoff} cutoff",
                query.id, outcome.depth.returned_hits
            )));
        }

        let mut seen = BTreeSet::new();
        for (index, hit) in outcome.response.hits.iter().enumerate() {
            let document_id = engine::hit_document(dataset, hit, &roots)
                .map_err(|error| Failure::dataset(error.to_string()))?;
            let rank = u32::try_from(index + 1).unwrap_or(u32::MAX);
            let start = u64::try_from(hit.start)
                .map_err(|_| Failure::dataset("engine contract: negative chunk offset"))?;
            let end = u64::try_from(hit.end)
                .map_err(|_| Failure::dataset("engine contract: negative chunk offset"))?;
            if start >= end {
                return Err(Failure::dataset(
                    "engine contract: chunk start must precede end",
                ));
            }
            let page = match hit.page {
                Some(page) => Some(u32::try_from(page).map_err(|_| {
                    Failure::dataset("engine contract: chunk page is out of range")
                })?),
                None => None,
            };
            if seen.insert(document_id.clone()) {
                document_rows
                    .entry(query.id.clone())
                    .or_default()
                    .push((document_id.clone(), hit.score));
            }
            mapped_documents.insert(document_id.clone());
            chunk_hits.push(ChunkHit {
                query_id: query.id.clone(),
                document_id,
                start_char: start,
                end_char: end,
                page,
                rank,
                score: hit.score,
            });
        }
    }

    // Deterministic so a repeated eval produces a byte-identical TREC run.
    let run_id = format!("seekybench{}", &config_hash[..12]);
    let mut rows = Vec::new();
    for (query_id, documents) in &document_rows {
        for (index, (document_id, score)) in documents.iter().enumerate() {
            rows.push(RunRow {
                query_id: query_id.clone(),
                target: RunTarget::Document(document_id.clone()),
                rank: u32::try_from(index + 1).unwrap_or(u32::MAX),
                score: *score,
            });
        }
    }
    let document_run = Run {
        run_id: run_id.clone(),
        system_id: system_id.clone(),
        rows,
    };

    let mut result = seeky_eval::evaluate(dataset, &document_run, &selection)
        .map_err(|error| Failure::report(error.to_string()))?;

    let passage_supported = mapped_documents
        .iter()
        .any(|document| !dataset.passages_for_document(document).is_empty());
    let mut passage_run = None;
    let mut unmapped_chunks = 0_usize;
    if passage_supported {
        let mapped = seeky_eval::map_chunk_run(
            dataset,
            &run_id,
            &system_id,
            &chunk_hits,
            input.limit as u32,
        )
        .map_err(|error| Failure::report(error.to_string()))?;
        unmapped_chunks = mapped.unmapped_chunks;
        let passage_metrics = MetricSelection::from_ids(&[
            "passage_ndcg_10",
            "passage_mrr_10",
            "passage_recall_100",
            "passage_success_1",
        ])
        .map_err(|error| Failure::report(error.to_string()))?;
        let passage_result = seeky_eval::evaluate(dataset, &mapped.run, &passage_metrics)
            .map_err(|error| Failure::report(error.to_string()))?;
        merge_results(&mut result, passage_result);
        passage_run = Some(mapped.run);
    }

    let filter_mode = engine::aggregate_filter_mode(saw_filter, saw_post);
    let quality =
        QualityReport::from_evaluation(dataset, &result, filter_mode, unmapped_chunks as u64);

    let commit = crate::commit_info(&paths.root)?;
    let environment = environment::capture("T2", None, None);
    let dataset_info = crate::dataset_info(dataset, &corpus.visibility);
    let system = crate::system_info(&snapshot_json, &config_hash, &system_id);
    let mut comparisons = Vec::new();
    if let Some(baseline_path) = &input.baseline {
        let baseline = crate::gate::read_report(baseline_path)?;
        let baseline_result = crate::gate::result_from_report(&baseline)?;
        let comparison = seeky_eval::compare(
            &baseline_result,
            &result,
            &crate::stats_options(&input.seed),
        )
        .map_err(|error| Failure::report(error.to_string()))?;
        comparisons.push(seeky_eval::ComparisonReport::from_comparison(&comparison));
        let _ = &comparison.baseline_system_id;
    }

    let exposure_completed = match exposure_started.as_ref() {
        Some(started) => Some(crate::gate::complete_test_run(
            paths,
            started,
            &config_hash,
        )?),
        None => None,
    };

    let artifacts = Artifacts {
        run: Some("run.trec".to_string()),
        passage_run: passage_run
            .as_ref()
            .map(|_| "run.passages.trec".to_string()),
        config_snapshot: Some("config.snapshot.json".to_string()),
        environment: Some("environment.json".to_string()),
        checksums: Some("checksums.sha256".to_string()),
        index: None,
        exposure: exposure_completed
            .as_ref()
            .map(|_| "exposure.json".to_string()),
        pareto: None,
    };
    let report = Report {
        schema_version: SCHEMA_VERSION,
        run_id: run_id.clone(),
        kind: ReportKind::Quality,
        generated_at: environment::rfc3339_now(),
        report: input.metadata.clone(),
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
            &[(&input.data_dir, "<data-dir>"), (&input.output, "<output>")],
            &input.command,
        ),
        quality: Some(quality),
        performance: None,
        comparisons,
        gates: Vec::new(),
        decision: Decision {
            status: DecisionStatus::NotApplicable,
            text: "Benchmark evidence only".to_string(),
        },
        artifacts,
    };
    report
        .validate()
        .map_err(|error| Failure::report(error.to_string()))?;

    let artifact_dir = crate::artifact::ArtifactDir::new(&input.output)?;
    artifact_dir.write_run("run.trec", &document_run)?;
    if let Some(run) = &passage_run {
        artifact_dir.write_run("run.passages.trec", run)?;
    }
    artifact_dir.write_report("results.json", &report)?;
    artifact_dir.write_text("summary.md", &seeky_eval::render_markdown(&report))?;
    artifact_dir.write_text("config.snapshot.json", &snapshot_json)?;
    artifact_dir.write_json("environment.json", &report.environment)?;
    if let Some(exposure) = &exposure_completed {
        artifact_dir.write_json("exposure.json", exposure)?;
    }
    artifact_dir.commit()?;

    adapter.shutdown()?;
    println!(
        "eval {} {:?}: {} queries, {} hits (filter mode {})",
        corpus.id,
        input.split,
        queries.len(),
        document_run.rows.len(),
        filter_mode
    );
    Ok(())
}

fn merge_results(base: &mut EvaluationResult, extra: EvaluationResult) {
    for (metric, value) in extra.macro_metrics {
        base.macro_metrics.insert(metric.clone(), value);
        base.unavailable_metrics.remove(&metric);
    }
    for metric in extra.unavailable_metrics {
        if !base.macro_metrics.contains_key(&metric) {
            base.unavailable_metrics.insert(metric);
        }
    }
    for (query_id, metrics) in extra.per_query {
        base.per_query.entry(query_id).or_default().extend(metrics);
    }
    if base.weighted_primary.is_none() {
        base.weighted_primary = extra.weighted_primary;
    }
}
