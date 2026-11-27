//! Test confirmation, append-only exposure, comparison gates, and report
//! rendering (SPEC-0003 R19-R21, R31-compatible gate hooks).

use crate::corpus::{BenchPaths, Corpus};
use crate::environment::{EvaluationSettings, sha256_hex};
use crate::{Failure, Result};
use seeky_eval::{
    Artifacts, CommitInfo, ComparisonReport, Dataset, Decision, DecisionStatus, EvaluationResult,
    GateResult, GateStatus, Report, ReportKind, ReportMetadata, SCHEMA_VERSION, Split,
    StatsOptions, ToolInfo,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::io::Write;
use std::path::{Path, PathBuf};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
#[allow(dead_code)]
struct Confirmation {
    schema_version: u32,
    confirmation_id: String,
    created_at: String,
    selected_on: String,
    dev_comparison_sha256: String,
    dataset: ConfirmationDataset,
    split: String,
    systems: Vec<ConfirmationSystem>,
    gates: Vec<String>,
    evaluation: ConfirmationEvaluation,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ConfirmationDataset {
    id: String,
    corpus_hash: String,
    judgment_set_id: String,
    judgment_set_hash: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ConfirmationSystem {
    system_id: String,
    config_path: String,
    config_hash: String,
    role: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ConfirmationEvaluation {
    limit: usize,
    metrics: Vec<String>,
    seed: String,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct LedgerRow {
    schema_version: u32,
    dataset_id: String,
    confirmation_id: String,
    confirmation_sha256: String,
    system_id: String,
    config_hash: String,
    state: String,
    at: String,
}

#[derive(Debug, Clone)]
pub struct StartedExposure {
    dataset_id: String,
    confirmation_id: String,
    confirmation_sha256: String,
    system_id: String,
    systems: Vec<(String, String)>,
    output: PathBuf,
}

impl StartedExposure {
    /// The system ID declared by the confirmation for this invocation.
    #[must_use]
    pub fn system_id(&self) -> &str {
        &self.system_id
    }
}

fn load_confirmation(path: &Path) -> Result<(Confirmation, String)> {
    let text = std::fs::read_to_string(path)
        .map_err(|error| Failure::usage(format!("cannot read --confirmation: {error}")))?;
    let confirmation: Confirmation = serde_json::from_str(&text)
        .map_err(|error| Failure::usage(format!("invalid confirmation JSON: {error}")))?;
    let sha = sha256_hex(text.as_bytes());
    validate_confirmation_shape(&confirmation)?;
    Ok((confirmation, sha))
}

fn validate_confirmation_shape(confirmation: &Confirmation) -> Result<()> {
    if confirmation.schema_version != 1 {
        return Err(Failure::usage("confirmation schema_version must be 1"));
    }
    if confirmation.confirmation_id.trim().is_empty() {
        return Err(Failure::usage("confirmation_id must be nonempty"));
    }
    if confirmation.split != "test" || confirmation.selected_on != "dev" {
        return Err(Failure::usage(
            "confirmation must select on dev and target the test split",
        ));
    }
    if confirmation.dev_comparison_sha256.len() != 64
        || !confirmation
            .dev_comparison_sha256
            .chars()
            .all(|c| c.is_ascii_hexdigit())
    {
        return Err(Failure::usage(
            "dev_comparison_sha256 must be 64 hexadecimal characters",
        ));
    }
    let mut baseline = 0;
    let mut candidates = 0;
    let mut ids = BTreeSet::new();
    for system in &confirmation.systems {
        if !ids.insert(system.system_id.clone()) {
            return Err(Failure::usage("confirmation system IDs must be unique"));
        }
        match system.role.as_str() {
            "baseline" => baseline += 1,
            "candidate" => candidates += 1,
            other => {
                return Err(Failure::usage(format!("unknown confirmation role {other}")));
            }
        }
        if system.config_hash.len() != 64 {
            return Err(Failure::usage("confirmation config hashes must be SHA-256"));
        }
    }
    if baseline != 1 || candidates > 2 {
        return Err(Failure::usage(
            "confirmation needs exactly one baseline and at most two candidates",
        ));
    }
    if confirmation.evaluation.limit == 0 {
        return Err(Failure::usage("confirmation limit must be positive"));
    }
    Ok(())
}

fn config_relative_path(paths: &BenchPaths, config_path: &Path) -> String {
    let normalized = config_path.to_string_lossy().replace('\\', "/");
    let root = paths.root.to_string_lossy().replace('\\', "/");
    let root = root.trim_end_matches('/');
    if let Some(rest) = normalized.strip_prefix(&format!("{root}/")) {
        return rest.to_string();
    }
    normalized
}

fn validate_confirmation_against(
    paths: &BenchPaths,
    confirmation: &Confirmation,
    dataset: &Dataset,
    config_path: &Path,
    config_hash: &str,
    settings: &EvaluationSettings,
) -> Result<ConfirmationSystem> {
    let expected = &confirmation.dataset;
    if expected.id != dataset.id
        || expected.corpus_hash != dataset.corpus_hash
        || expected.judgment_set_id != dataset.judgment_set_id
        || expected.judgment_set_hash != dataset.judgment_set_hash
    {
        return Err(Failure::dataset(
            "TEST_NOT_ALLOWED: confirmation dataset or judgment hashes do not match",
        ));
    }
    if confirmation.evaluation.limit != settings.limit
        || confirmation.evaluation.seed != settings.seed
        || confirmation.evaluation.metrics != settings.metrics
    {
        return Err(Failure::usage(
            "TEST_NOT_ALLOWED: confirmation evaluation settings differ from the invocation",
        ));
    }
    let relative = config_relative_path(paths, config_path);
    confirmation
        .systems
        .iter()
        .find(|system| system.config_hash == config_hash && system.config_path == relative)
        .cloned()
        .ok_or_else(|| {
            Failure::dataset(
                "TEST_NOT_ALLOWED: this configuration is not declared by the confirmation",
            )
        })
}

/// Dry validation of confirmation metadata (dev `--purpose confirm`).
pub fn dry_validate_confirmation(paths: &BenchPaths, path: Option<&Path>) -> Result<()> {
    let Some(path) = path else {
        return Err(Failure::usage("--purpose confirm requires --confirmation"));
    };
    let (confirmation, _sha) = load_confirmation(path)?;
    let _ = paths;
    println!(
        "confirmation {} is structurally valid ({} systems)",
        confirmation.confirmation_id,
        confirmation.systems.len()
    );
    Ok(())
}

/// Clean-tree precondition for test runs.
pub fn require_clean_tree(root: &Path) -> Result<()> {
    let inside = crate::run_git(root, &["rev-parse", "--is-inside-work-tree"])
        .map_err(|_| Failure::dataset("TEST_NOT_ALLOWED: not inside a git work tree"))?;
    if inside != "true" {
        return Err(Failure::dataset(
            "TEST_NOT_ALLOWED: not inside a git work tree",
        ));
    }
    let status = crate::run_git(root, &["status", "--porcelain"])?;
    if !status.trim().is_empty() {
        return Err(Failure::dataset(
            "TEST_NOT_ALLOWED: the working tree is dirty",
        ));
    }
    Ok(())
}

fn lock_path(paths: &BenchPaths, dataset_id: &str) -> PathBuf {
    paths.exposures().join(format!("{dataset_id}.lock"))
}

fn ledger_path(paths: &BenchPaths, dataset_id: &str) -> PathBuf {
    paths.exposures().join(format!("{dataset_id}.jsonl"))
}

struct LedgerLock {
    path: PathBuf,
}

impl LedgerLock {
    fn acquire(paths: &BenchPaths, dataset_id: &str) -> Result<Self> {
        std::fs::create_dir_all(paths.exposures()).map_err(|error| {
            Failure::dataset(format!(
                "TEST_NOT_ALLOWED: cannot create the exposure ledger: {error}"
            ))
        })?;
        let path = lock_path(paths, dataset_id);
        std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .map_err(|_| {
                Failure::dataset("TEST_NOT_ALLOWED: the exposure ledger is locked by another run")
            })?;
        Ok(Self { path })
    }
}

impl Drop for LedgerLock {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

fn read_ledger(path: &Path) -> Result<Vec<LedgerRow>> {
    let text = match std::fs::read_to_string(path) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => {
            return Err(Failure::dataset(format!(
                "TEST_NOT_ALLOWED: cannot read the exposure ledger: {error}"
            )));
        }
    };
    let mut rows = Vec::new();
    for (index, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            return Err(Failure::dataset(format!(
                "TEST_NOT_ALLOWED: blank exposure ledger line {}",
                index + 1
            )));
        }
        let row: LedgerRow = serde_json::from_str(line).map_err(|error| {
            Failure::dataset(format!(
                "TEST_NOT_ALLOWED: malformed exposure ledger line {}: {error}",
                index + 1
            ))
        })?;
        if row.schema_version != 1 {
            return Err(Failure::dataset(
                "TEST_NOT_ALLOWED: unsupported exposure ledger schema",
            ));
        }
        rows.push(row);
    }
    Ok(rows)
}

fn append_ledger(path: &Path, row: &LedgerRow) -> Result<()> {
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|error| {
            Failure::dataset(format!(
                "TEST_NOT_ALLOWED: cannot append to the exposure ledger: {error}"
            ))
        })?;
    let line = serde_json::to_string(row)
        .map_err(|error| Failure::dataset(format!("cannot serialize the ledger row: {error}")))?;
    writeln!(file, "{line}")
        .map_err(|error| Failure::dataset(format!("cannot append the ledger row: {error}")))?;
    file.sync_all()
        .map_err(|error| Failure::dataset(format!("cannot flush the ledger row: {error}")))
}

fn write_exposure(output: &Path, value: &Value) -> Result<()> {
    std::fs::create_dir_all(output).map_err(|error| {
        Failure::dataset(format!("cannot create the output directory: {error}"))
    })?;
    let mut text = serde_json::to_string_pretty(value)
        .map_err(|error| Failure::dataset(format!("cannot serialize exposure: {error}")))?;
    text.push('\n');
    let temporary = output.join(".exposure.json.tmp");
    std::fs::write(&temporary, text)
        .map_err(|error| Failure::dataset(format!("cannot write exposure metadata: {error}")))?;
    std::fs::rename(&temporary, output.join("exposure.json"))
        .map_err(|error| Failure::dataset(format!("cannot publish exposure metadata: {error}")))
}

fn exposure_value(
    dataset_id: &str,
    confirmation_id: &str,
    confirmation_sha256: &str,
    systems: &[(String, String)],
    state: &str,
) -> Value {
    json!({
        "schema_version": 1,
        "dataset_id": dataset_id,
        "state": state,
        "confirmation_id": confirmation_id,
        "confirmation_sha256": confirmation_sha256,
        "systems": systems
            .iter()
            .map(|(system_id, config_hash)| json!({
                "system_id": system_id,
                "config_hash": config_hash,
            }))
            .collect::<Vec<_>>(),
        "at": crate::environment::rfc3339_now(),
    })
}

/// Validate the confirmation, append the started ledger row, write the started
/// exposure, and update the first-ever `test_exposure` marker.
#[allow(clippy::too_many_arguments)]
pub fn begin_test_run(
    paths: &BenchPaths,
    corpus: &Corpus,
    dataset: &Dataset,
    confirmation_path: &Path,
    config_path: &Path,
    config_hash: &str,
    settings: &EvaluationSettings,
    output: &Path,
) -> Result<StartedExposure> {
    let (confirmation, sha) = load_confirmation(confirmation_path)?;
    let declared = validate_confirmation_against(
        paths,
        &confirmation,
        dataset,
        config_path,
        config_hash,
        settings,
    )?;
    let _lock = LedgerLock::acquire(paths, &dataset.id)?;
    let ledger = ledger_path(paths, &dataset.id);
    let rows = read_ledger(&ledger)?;
    let first_exposure = rows.is_empty();

    if rows
        .iter()
        .any(|row| row.confirmation_id == confirmation.confirmation_id && row.state == "completed")
    {
        return Err(Failure::dataset(
            "TEST_NOT_ALLOWED: a completed confirmation cannot be rerun",
        ));
    }
    if rows.iter().any(|row| {
        row.confirmation_id == confirmation.confirmation_id
            && row.system_id == declared.system_id
            && row.state == "started"
    }) {
        return Err(Failure::dataset(
            "TEST_NOT_ALLOWED: this system already started under the confirmation",
        ));
    }

    append_ledger(
        &ledger,
        &LedgerRow {
            schema_version: 1,
            dataset_id: dataset.id.clone(),
            confirmation_id: confirmation.confirmation_id.clone(),
            confirmation_sha256: sha.clone(),
            system_id: declared.system_id.clone(),
            config_hash: config_hash.to_string(),
            state: "started".to_string(),
            at: crate::environment::rfc3339_now(),
        },
    )?;

    let systems: Vec<(String, String)> = confirmation
        .systems
        .iter()
        .map(|system| (system.system_id.clone(), system.config_hash.clone()))
        .collect();
    write_exposure(
        output,
        &exposure_value(
            &dataset.id,
            &confirmation.confirmation_id,
            &sha,
            &systems,
            "started",
        ),
    )?;

    if first_exposure {
        mark_test_exposure(corpus)?;
    }

    Ok(StartedExposure {
        dataset_id: dataset.id.clone(),
        confirmation_id: confirmation.confirmation_id,
        confirmation_sha256: sha,
        system_id: declared.system_id,
        systems,
        output: output.to_path_buf(),
    })
}

/// Record this system's completion and return the updated exposure record.
pub fn complete_test_run(
    paths: &BenchPaths,
    started: &StartedExposure,
    config_hash: &str,
) -> Result<Value> {
    let _lock = LedgerLock::acquire(paths, &started.dataset_id)?;
    let ledger = ledger_path(paths, &started.dataset_id);
    append_ledger(
        &ledger,
        &LedgerRow {
            schema_version: 1,
            dataset_id: started.dataset_id.clone(),
            confirmation_id: started.confirmation_id.clone(),
            confirmation_sha256: started.confirmation_sha256.clone(),
            system_id: started.system_id.clone(),
            config_hash: config_hash.to_string(),
            state: "completed".to_string(),
            at: crate::environment::rfc3339_now(),
        },
    )?;
    let rows = read_ledger(&ledger)?;
    let completed: BTreeSet<&str> = rows
        .iter()
        .filter(|row| row.confirmation_id == started.confirmation_id && row.state == "completed")
        .map(|row| row.system_id.as_str())
        .collect();
    let all_done = started
        .systems
        .iter()
        .all(|(system, _)| completed.contains(system.as_str()));
    let state = if all_done { "completed" } else { "started" };
    let value = exposure_value(
        &started.dataset_id,
        &started.confirmation_id,
        &started.confirmation_sha256,
        &started.systems,
        state,
    );
    write_exposure(&started.output, &value)?;
    Ok(value)
}

/// Change only the SDC `test_exposure` field, and only on the first exposure.
pub fn mark_test_exposure(corpus: &Corpus) -> Result<()> {
    let Some(dir) = corpus.judgment_dir.as_ref() else {
        return Ok(());
    };
    let path = dir.join("judgment-set.json");
    let text = std::fs::read_to_string(&path).map_err(|error| {
        Failure::dataset(format!(
            "TEST_NOT_ALLOWED: cannot read the judgment set: {error}"
        ))
    })?;
    let mut value: Value = serde_json::from_str(&text).map_err(|error| {
        Failure::dataset(format!("TEST_NOT_ALLOWED: invalid judgment set: {error}"))
    })?;
    let object = value
        .as_object_mut()
        .ok_or_else(|| Failure::dataset("TEST_NOT_ALLOWED: judgment set is not an object"))?;
    if object.get("test_exposure").and_then(Value::as_str) == Some("exposed") {
        return Ok(());
    }
    object.insert("test_exposure".to_string(), json!("exposed"));
    let mut updated = serde_json::to_string_pretty(&value)
        .map_err(|error| Failure::dataset(format!("cannot serialize the judgment set: {error}")))?;
    updated.push('\n');
    let temporary = path.with_extension("json.tmp");
    std::fs::write(&temporary, updated)
        .map_err(|error| Failure::dataset(format!("cannot write the judgment set: {error}")))?;
    std::fs::rename(&temporary, &path)
        .map_err(|error| Failure::dataset(format!("cannot publish the judgment set: {error}")))
}

// ---------------------------------------------------------------------------
// compare
// ---------------------------------------------------------------------------

/// Read and validate a results report.
pub fn read_report(path: &Path) -> Result<Report> {
    let text = std::fs::read_to_string(path)
        .map_err(|error| Failure::report(format!("cannot read results: {error}")))?;
    let report: Report = serde_json::from_str(&text)
        .map_err(|error| Failure::report(format!("invalid results JSON: {error}")))?;
    report
        .validate()
        .map_err(|error| Failure::report(error.to_string()))?;
    Ok(report)
}

/// Reconstruct the evaluator result carried by a quality report.
pub fn result_from_report(report: &Report) -> Result<EvaluationResult> {
    let quality = report
        .quality
        .as_ref()
        .ok_or_else(|| Failure::report("REPORT_INVALID: comparison needs a quality payload"))?;
    let per_query = quality
        .per_query
        .iter()
        .map(|row| (row.query_id.clone(), row.metrics.clone()))
        .collect();
    let query_contexts = quality
        .per_query
        .iter()
        .map(|row| {
            (
                row.query_id.clone(),
                seeky_eval::QueryContext {
                    category: row.category,
                    language_slice: row.language_slice,
                    configuration: report.dataset.configuration,
                },
            )
        })
        .collect();
    let macro_metrics = quality
        .macro_metrics
        .iter()
        .filter_map(|(metric, value)| value.map(|value| (metric.clone(), value)))
        .collect();
    let unavailable_metrics = quality
        .macro_metrics
        .iter()
        .filter(|(_, value)| value.is_none())
        .map(|(metric, _)| metric.clone())
        .collect();
    Ok(EvaluationResult {
        dataset_fingerprint: report.dataset.fingerprint.clone(),
        query_set_sha256: report.dataset.query_set_sha256.clone(),
        split: report.dataset.split,
        configuration: report.dataset.configuration,
        per_query,
        query_contexts,
        macro_metrics,
        category_metrics: BTreeMap::new(),
        language_metrics: BTreeMap::new(),
        weighted_primary: quality.weighted_primary,
        queries_without_positive: quality.queries_without_positive as usize,
        unavailable_metrics,
    })
}

fn compatible(baseline: &Report, candidate: &Report) -> Result<()> {
    if baseline.schema_version != candidate.schema_version {
        return Err(Failure::report(
            "STATS_INPUT_MISMATCH: report schema versions differ",
        ));
    }
    if baseline.kind != ReportKind::Quality || candidate.kind != ReportKind::Quality {
        return Err(Failure::report(
            "STATS_INPUT_MISMATCH: comparisons require quality reports",
        ));
    }
    let left = &baseline.dataset;
    let right = &candidate.dataset;
    if left.id != right.id
        || left.split != right.split
        || left.configuration != right.configuration
        || left.corpus_hash != right.corpus_hash
        || left.fingerprint != right.fingerprint
        || left.judgment_set_id != right.judgment_set_id
        || left.judgment_set_hash != right.judgment_set_hash
        || left.query_set_sha256 != right.query_set_sha256
    {
        return Err(Failure::report(
            "STATS_INPUT_MISMATCH: dataset, split, judgment set, or query membership differs",
        ));
    }
    let left_queries: BTreeSet<&str> = baseline
        .quality
        .as_ref()
        .map(|quality| {
            quality
                .per_query
                .iter()
                .map(|row| row.query_id.as_str())
                .collect()
        })
        .unwrap_or_default();
    let right_queries: BTreeSet<&str> = candidate
        .quality
        .as_ref()
        .map(|quality| {
            quality
                .per_query
                .iter()
                .map(|row| row.query_id.as_str())
                .collect()
        })
        .unwrap_or_default();
    if left_queries != right_queries || left_queries.is_empty() {
        return Err(Failure::report(
            "STATS_INPUT_MISMATCH: paired query membership differs",
        ));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub fn compare(
    paths: &BenchPaths,
    baseline_path: &Path,
    candidate_paths: &[PathBuf],
    repeat: Option<&Path>,
    gate: Option<&str>,
    baseline_commit: Option<&str>,
    output: &Path,
    seed: &str,
    metadata: ReportMetadata,
    command: &[String],
) -> Result<()> {
    let baseline = read_report(baseline_path)?;
    let mut candidates = Vec::with_capacity(candidate_paths.len());
    for path in candidate_paths {
        let report = read_report(path)?;
        compatible(&baseline, &report)?;
        candidates.push(report);
    }
    let baseline_result = result_from_report(&baseline)?;
    let mut candidate_results = Vec::new();
    for report in &candidates {
        candidate_results.push((report.system.system_id.clone(), result_from_report(report)?));
    }
    let pair: Vec<(&str, &EvaluationResult)> = candidate_results
        .iter()
        .map(|(id, result)| (id.as_str(), result))
        .collect();
    let options = StatsOptions {
        seed: seed.to_string(),
        ..StatsOptions::default()
    };
    let comparisons = seeky_eval::compare_many(
        &baseline_result,
        &pair,
        &options,
        &baseline.system.system_id,
    )
    .map_err(|error| Failure::report(error.to_string()))?;
    let comparisons: Vec<ComparisonReport> = comparisons
        .iter()
        .map(ComparisonReport::from_comparison)
        .collect();

    let mut gates = Vec::new();
    let mut gate_failure = None;
    if let Some(gate) = gate {
        if gate != "wp1.8" {
            return Err(Failure::usage(format!("unknown gate {gate}")));
        }
        let result = wp18_gate(&baseline, &candidates, repeat, baseline_commit)?;
        if result.status == GateStatus::Fail {
            gate_failure = Some(result.details.clone());
        }
        gates.push(result);
    }

    let commit = crate::commit_info(&paths.root)?;
    let environment = crate::environment::capture("T2", None, None);
    let report = Report {
        schema_version: SCHEMA_VERSION,
        run_id: crate::run_id("cmp"),
        kind: ReportKind::Comparison,
        generated_at: crate::environment::rfc3339_now(),
        report: metadata,
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
        dataset: baseline.dataset.clone(),
        system: baseline.system.clone(),
        command: {
            let mut rendered = vec!["seeky-bench".to_string()];
            rendered.extend(crate::command_display(
                paths,
                &[(output, "<output>")],
                command,
            ));
            rendered
        },
        quality: None,
        performance: None,
        comparisons,
        gates,
        decision: Decision {
            status: DecisionStatus::NotApplicable,
            text: "Comparison evidence only".to_string(),
        },
        artifacts: Artifacts {
            run: None,
            passage_run: None,
            config_snapshot: None,
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
    artifacts.write_json("environment.json", &report.environment)?;
    artifacts.commit()?;

    println!(
        "compared {} candidate(s) against {}",
        pair.len(),
        baseline.system.system_id
    );
    if let Some(details) = gate_failure {
        return Err(Failure::gate(details));
    }
    Ok(())
}

fn wp18_gate(
    baseline: &Report,
    candidates: &[Report],
    repeat: Option<&Path>,
    baseline_commit: Option<&str>,
) -> Result<GateResult> {
    let fail = |details: &str| GateResult {
        id: "WP-1.8".to_string(),
        status: GateStatus::Fail,
        threshold: "candidate macro nDCG@10 drop <= 1.0 point vs main".to_string(),
        observed: json!(null),
        details: details.to_string(),
    };
    if candidates.len() != 1 {
        return Ok(fail("wp1.8 requires exactly one candidate"));
    }
    let candidate = &candidates[0];
    if repeat.is_none() {
        return Ok(fail("wp1.8 requires --repeat-candidate"));
    }
    let Some(commit) = baseline_commit else {
        return Ok(fail("wp1.8 requires --baseline-commit"));
    };
    if baseline.commit.sha != commit {
        return Ok(fail(
            "wp1.8 requires the baseline to be the supplied main commit",
        ));
    }
    if baseline.dataset.id != "sdc-smoke"
        || baseline.dataset.split != Split::Dev
        || baseline.dataset.judgment_set_id != "sdc-smoke-v1"
        || baseline.dataset.configuration != seeky_eval::EvaluationConfiguration::Default
    {
        return Ok(fail(
            "wp1.8 requires sdc-smoke-v1 dev in the default configuration",
        ));
    }
    if baseline.system.config_hash != candidate.system.config_hash {
        return Ok(fail("wp1.8 requires the same configuration"));
    }
    let baseline_metric = baseline
        .quality
        .as_ref()
        .and_then(|quality| quality.macro_metrics.get("ndcg_10").copied().flatten());
    let candidate_metric = candidate
        .quality
        .as_ref()
        .and_then(|quality| quality.macro_metrics.get("ndcg_10").copied().flatten());
    let (Some(baseline_metric), Some(candidate_metric)) = (baseline_metric, candidate_metric)
    else {
        return Ok(fail(
            "wp1.8 requires a measured macro nDCG@10 for both runs",
        ));
    };
    let drop_points = 100.0 * (baseline_metric - candidate_metric);
    let observe = json!({"drop_points": drop_points, "baseline": baseline_metric, "candidate": candidate_metric});
    if let Some(repeat) = repeat {
        let repeated = read_report(repeat)?;
        compatible(baseline, &repeated)?;
        let left = result_from_report(candidate)?;
        let right = result_from_report(&repeated)?;
        let same = left.per_query.iter().all(|(query_id, metrics)| {
            right.per_query.get(query_id).is_some_and(|other| {
                metrics.len() == other.len()
                    && metrics.iter().all(|(metric, value)| {
                        other
                            .get(metric)
                            .is_some_and(|other| (value - other).abs() <= 1e-9)
                    })
            })
        });
        if !same {
            return Ok(GateResult {
                id: "WP-1.8".to_string(),
                status: GateStatus::Fail,
                threshold: "candidate macro nDCG@10 drop <= 1.0 point vs main".to_string(),
                observed: observe,
                details: "wp1.8 repeat run is not deterministic".to_string(),
            });
        }
    }
    let pass = drop_points <= 1.0 + 1e-12;
    Ok(GateResult {
        id: "WP-1.8".to_string(),
        status: if pass {
            GateStatus::Pass
        } else {
            GateStatus::Fail
        },
        threshold: "candidate macro nDCG@10 drop <= 1.0 point vs main".to_string(),
        observed: observe,
        details: if pass {
            "drop within threshold".to_string()
        } else {
            "drop exceeds 1.0 point".to_string()
        },
    })
}

// ---------------------------------------------------------------------------
// report
// ---------------------------------------------------------------------------

/// Render Markdown from an existing results file without recomputing metrics.
pub fn report(results: &Path, output: &Path, overwrite: bool) -> Result<()> {
    let report = read_report(results)?;
    let markdown = seeky_eval::render_markdown(&report);
    if output.exists() {
        let existing = std::fs::read_to_string(output).map_err(|error| {
            Failure::report(format!("cannot read the existing report: {error}"))
        })?;
        if existing == markdown {
            return Ok(());
        }
        if !overwrite {
            return Err(Failure::report(
                "REPORT_INVALID: report exists with different content; pass --overwrite",
            ));
        }
    }
    if let Some(parent) = output.parent() {
        std::fs::create_dir_all(parent).map_err(|error| {
            Failure::report(format!("cannot create the report directory: {error}"))
        })?;
    }
    let temporary = output.with_extension("md.tmp");
    std::fs::write(&temporary, markdown)
        .map_err(|error| Failure::report(format!("cannot write the report: {error}")))?;
    std::fs::rename(&temporary, output)
        .map_err(|error| Failure::report(format!("cannot publish the report: {error}")))?;
    println!("report written to {}", output.display());
    Ok(())
}
