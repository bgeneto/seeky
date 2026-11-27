//! `seeky-bench`: the internal headless benchmark harness (SPEC-0003).
//!
//! This tool never ships (ADR-0008). It is the only bridge between
//! `seeky-engine` and `seeky-eval`; it contains no second metric
//! implementation. All input validation happens before the engine is opened.

#![allow(clippy::print_stdout)]

pub mod artifact;
pub mod corpus;
pub mod engine;
pub mod environment;
pub mod gate;
pub mod perf;
pub mod smoke_gate;

use artifact::ArtifactDir;
use corpus::BenchPaths;
use environment::{CombinedConfig, EvaluationSettings, RunConfig};
use seeky_eval::{Dataset, MetricSelection, Split, StatsOptions, SystemInfo};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::path::{Path, PathBuf};

/// Default statistics seed (SPEC-0003 section 5.3).
pub const DEFAULT_SEED: &str = "seeky-eval-v1";
/// Default evaluation depth.
pub const DEFAULT_LIMIT: usize = 100;
/// Required macro metrics.
pub const DEFAULT_METRICS: [&str; 4] = ["ndcg_10", "mrr_10", "recall_100", "success_1"];

/// A typed failure carrying the SPEC-0003 exit code.
#[derive(Debug)]
pub struct Failure {
    /// Process exit code.
    pub code: i32,
    /// Human-readable message (never query text, content, or user paths).
    pub message: String,
}

impl Failure {
    /// Usage or configuration error (exit 2).
    pub fn usage(message: impl Into<String>) -> Self {
        Self {
            code: 2,
            message: message.into(),
        }
    }

    /// Dataset or judgment validation error (exit 3).
    pub fn dataset(message: impl Into<String>) -> Self {
        Self {
            code: 3,
            message: message.into(),
        }
    }

    /// Engine or index unavailability (exit 4).
    pub fn engine(message: impl Into<String>) -> Self {
        Self {
            code: 4,
            message: message.into(),
        }
    }

    /// Statistics or report validation error (exit 5).
    pub fn report(message: impl Into<String>) -> Self {
        Self {
            code: 5,
            message: message.into(),
        }
    }

    /// Gate failure (exit 6).
    pub fn gate(message: impl Into<String>) -> Self {
        Self {
            code: 6,
            message: message.into(),
        }
    }
}

impl fmt::Display for Failure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for Failure {}

/// Result alias for the harness.
pub type Result<T> = std::result::Result<T, Failure>;

/// Parsed command line.
#[derive(Debug, Default)]
pub struct Parsed {
    values: BTreeMap<String, Vec<String>>,
    flags: BTreeSet<String>,
}

impl Parsed {
    fn value(&self, name: &str) -> Option<&str> {
        self.values
            .get(name)
            .and_then(|values| values.first())
            .map(String::as_str)
    }

    fn values(&self, name: &str) -> &[String] {
        self.values.get(name).map(Vec::as_slice).unwrap_or_default()
    }

    fn flag(&self, name: &str) -> bool {
        self.flags.contains(name)
    }

    fn required(&self, name: &str) -> Result<&str> {
        self.value(name)
            .ok_or_else(|| Failure::usage(format!("missing required flag {name}")))
    }
}

const BOOL_FLAGS: [&str; 5] = [
    "--help",
    "--code-enabled",
    "--fresh",
    "--require-clean",
    "--overwrite",
];

const REPEATABLE: [&str; 2] = ["--candidate", "--gate-id"];

fn parse_flags(args: &[String], allowed: &[&str]) -> Result<Parsed> {
    let mut parsed = Parsed::default();
    let mut index = 0;
    while index < args.len() {
        let token = &args[index];
        if token == "--" {
            index += 1;
            continue;
        }
        if !allowed.contains(&token.as_str()) {
            return Err(Failure::usage(format!("unknown flag {token}")));
        }
        if BOOL_FLAGS.contains(&token.as_str()) {
            parsed.flags.insert(token.clone());
            index += 1;
            continue;
        }
        let value = args
            .get(index + 1)
            .ok_or_else(|| Failure::usage(format!("{token} requires a value")))?;
        if value.starts_with("--") {
            return Err(Failure::usage(format!("{token} requires a value")));
        }
        if parsed.values.contains_key(token) && !REPEATABLE.contains(&token.as_str()) {
            return Err(Failure::usage(format!("duplicate flag {token}")));
        }
        parsed
            .values
            .entry(token.clone())
            .or_default()
            .push(value.clone());
        index += 2;
    }
    Ok(parsed)
}

/// Run one command. Returns `Ok(())` on success.
pub fn run(args: Vec<String>) -> Result<()> {
    let paths = BenchPaths::discover()?;
    run_with_paths(&paths, args)
}

/// Run one command against explicit benchmark roots (used by offline fixtures).
#[allow(clippy::needless_pass_by_value)] // the binary edge owns its argv
pub fn run_with_paths(paths: &BenchPaths, args: Vec<String>) -> Result<()> {
    let Some(command) = args.first().cloned() else {
        print_usage();
        return Err(Failure::usage("missing subcommand"));
    };
    if command == "--help" || command == "-h" || command == "help" {
        print_usage();
        return Ok(());
    }
    let rest = &args[1..];
    if rest.iter().any(|token| token == "--help") {
        print_usage();
        return Ok(());
    }
    match command.as_str() {
        "index" => command_index(paths, rest),
        "eval" => command_eval(paths, rest),
        "perf" => command_perf(paths, rest),
        "compare" => command_compare(paths, rest),
        "report" => command_report(rest),
        perf::startup::PROBE_COMMAND => command_startup_probe(rest),
        other => Err(Failure::usage(format!("unknown subcommand {other}"))),
    }
}

fn print_usage() {
    println!(
        "seeky-bench (internal, never shipped)\n\n\
         Usage:\n\
           seeky-bench index   --corpus <id> --data-dir <dir> --config <path> --output <dir> [--code-enabled] [--fresh]\n\
           seeky-bench eval    --corpus <id> --split <dev|test> --config <path> --data-dir <dir> --output <dir> [--judgment-set <id>] [--system-id <id>] [--limit <1..=1000>] [--code-enabled] [--purpose <screen|deploy|confirm>] [--confirmation <path>] [--baseline <results.json>] [--require-clean] [--seed <seed>]\n\
           seeky-bench perf    --corpus <id> --config <path> --data-dir <dir> --output <dir> [--suite <s>] [--stage <s>] [--repetitions <n>] [--queries <n>] [--tier <T0|T1|T1-emulated|T2>] [--cpus <list>] [--memory-limit <bytes>] [--code-enabled]\n\
           seeky-bench compare --baseline <results.json> --candidate <results.json> [--candidate <results.json> ...] [--repeat-candidate <results.json>] [--gate <wp1.8>] [--baseline-commit <sha>] --output <dir> [--seed <seed>]\n\
           seeky-bench report  --results <results.json> --output <summary.md> [--overwrite]\n\n\
         All commands emit exit code 0 only on success."
    );
}

fn parse_split(value: &str) -> Result<Split> {
    match value {
        "dev" => Ok(Split::Dev),
        "test" => Ok(Split::Test),
        other => Err(Failure::usage(format!("unknown split {other}"))),
    }
}

fn parse_limit(value: &str) -> Result<usize> {
    let limit: usize = value
        .parse()
        .map_err(|_| Failure::usage("--limit must be an integer"))?;
    if !(1..=1000).contains(&limit) {
        return Err(Failure::usage("--limit must be in 1..=1000"));
    }
    Ok(limit)
}

fn seed_of(parsed: &Parsed) -> String {
    parsed.value("--seed").unwrap_or(DEFAULT_SEED).to_string()
}

fn metric_ids() -> Vec<String> {
    DEFAULT_METRICS.iter().map(|id| (*id).to_string()).collect()
}

fn selection() -> Result<MetricSelection> {
    MetricSelection::from_ids(&DEFAULT_METRICS).map_err(|error| Failure::report(error.to_string()))
}

fn report_metadata(
    parsed: &Parsed,
    area: &str,
    title: &str,
    work_package: &str,
    spec: &str,
) -> seeky_eval::ReportMetadata {
    seeky_eval::ReportMetadata {
        work_package: parsed
            .value("--work-package")
            .unwrap_or(work_package)
            .to_string(),
        spec: parsed.value("--spec").unwrap_or(spec).to_string(),
        area: parsed.value("--area").unwrap_or(area).to_string(),
        title: parsed.value("--title").unwrap_or(title).to_string(),
        hypothesis: parsed.value("--hypothesis").unwrap_or_default().to_string(),
        gate_ids: parsed.values("--gate-id").to_vec(),
    }
}

fn now_rfc3339() -> String {
    environment::rfc3339_now()
}

fn run_id(prefix: &str) -> String {
    let stamp = now_rfc3339()
        .replace(['-', ':'], "")
        .replace(['T', 'Z'], "");
    let stamp = stamp.split('.').next().unwrap_or(&stamp).to_string();
    format!("{stamp}-{prefix}")
}

const METADATA_FLAGS: [&str; 6] = [
    "--work-package",
    "--spec",
    "--area",
    "--title",
    "--hypothesis",
    "--gate-id",
];

fn common_metadata_allowed(allowed: &mut Vec<&str>) {
    for flag in METADATA_FLAGS {
        allowed.push(flag);
    }
    allowed.push("--seed");
}

// ---------------------------------------------------------------------------
// index
// ---------------------------------------------------------------------------

fn command_index(paths: &BenchPaths, args: &[String]) -> Result<()> {
    let mut allowed = vec![
        "--corpus",
        "--data-dir",
        "--config",
        "--output",
        "--fresh",
        "--code-enabled",
    ];
    common_metadata_allowed(&mut allowed);
    let parsed = parse_flags(args, &allowed)?;
    let corpus_id = parsed.required("--corpus")?.to_string();
    let data_dir = PathBuf::from(parsed.required("--data-dir")?);
    let config_path = PathBuf::from(parsed.required("--config")?);
    let output = PathBuf::from(parsed.required("--output")?);
    let code_enabled = parsed.flag("--code-enabled");
    let fresh = parsed.flag("--fresh");

    let config = environment::load_run_config(&config_path)?;
    let corpus = corpus::resolve(paths, &corpus_id, code_enabled)?;

    // The corpus must validate before the engine is opened.
    let corpus_hash = corpus::corpus_hash_for_index(&corpus)?;

    // Refuse to reuse an incompatible data directory before creating anything.
    let sidecar_path = engine::sidecar_path(&data_dir);
    let nonempty = engine::is_nonempty(&data_dir)?;
    if nonempty && !fresh {
        return Err(Failure::usage(
            "--fresh is required to reuse a nonempty data directory",
        ));
    }
    if nonempty && !sidecar_path.is_file() {
        return Err(Failure::engine(
            "INDEX_INCOMPATIBLE: the data directory has no index metadata",
        ));
    }

    let started = std::time::Instant::now();
    let adapter = engine::EngineAdapter::open(&data_dir, &config)?;
    let snapshot = adapter
        .engine()
        .config_snapshot()
        .map_err(|error| Failure::engine(error.to_string()))?;
    if nonempty {
        engine::verify_index(
            adapter.engine(),
            &sidecar_path,
            &corpus,
            &corpus_hash,
            code_enabled,
        )?;
    }
    let root_labels = adapter.index_roots(&corpus)?;
    let status = adapter
        .engine()
        .status()
        .map_err(|error| Failure::engine(error.to_string()))?;
    let snapshot_json = snapshot.canonical_json();
    let elapsed_ms = started.elapsed().as_millis() as u64;
    adapter
        .shutdown()
        .map_err(|error| Failure::engine(error.to_string()))?;

    let metadata = engine::IndexMetadata {
        schema_version: 1,
        corpus_id: corpus.id.clone(),
        corpus_hash: corpus_hash.clone(),
        code_enabled,
        config_hash: snapshot.sha256(),
        models: environment::snapshot_models(&snapshot_json),
        counts: engine::IndexCounts {
            documents: status.counts.documents,
            chunks: status.counts.chunks,
        },
        timings: engine::IndexTimings { elapsed_ms },
        roots: root_labels,
    };
    engine::write_sidecar(&sidecar_path, &metadata)?;

    let artifacts = ArtifactDir::new(&output)?;
    artifacts.write_json("index.json", &metadata)?;
    artifacts.commit()?;

    println!(
        "indexed {} documents / {} chunks into <data-dir> ({} ms)",
        metadata.counts.documents, metadata.counts.chunks, elapsed_ms
    );
    Ok(())
}

// ---------------------------------------------------------------------------
// eval
// ---------------------------------------------------------------------------

struct EvalInput {
    split: Split,
    config_path: PathBuf,
    data_dir: PathBuf,
    output: PathBuf,
    system_id: String,
    limit: usize,
    code_enabled: bool,
    confirmation: Option<PathBuf>,
    baseline: Option<PathBuf>,
    seed: String,
    metadata: seeky_eval::ReportMetadata,
    command: Vec<String>,
}

fn command_eval(paths: &BenchPaths, args: &[String]) -> Result<()> {
    let mut allowed = vec![
        "--corpus",
        "--split",
        "--config",
        "--data-dir",
        "--output",
        "--judgment-set",
        "--system-id",
        "--limit",
        "--purpose",
        "--confirmation",
        "--baseline",
        "--candidate",
        "--repeat-candidate",
        "--gate",
        "--baseline-commit",
        "--tier",
        "--cpus",
        "--memory-limit",
        "--suite",
        "--stage",
        "--repetitions",
        "--queries",
        "--code-enabled",
        "--require-clean",
    ];
    common_metadata_allowed(&mut allowed);
    let parsed = parse_flags(args, &allowed)?;

    let split = parse_split(parsed.required("--split")?)?;
    let corpus_id = parsed.required("--corpus")?.to_string();
    let config_path = PathBuf::from(parsed.required("--config")?);
    let data_dir = PathBuf::from(parsed.required("--data-dir")?);
    let output = PathBuf::from(parsed.required("--output")?);
    let limit = match parsed.value("--limit") {
        Some(value) => parse_limit(value)?,
        None => DEFAULT_LIMIT,
    };
    let code_enabled = parsed.flag("--code-enabled");
    let purpose = parsed
        .value("--purpose")
        .unwrap_or(if split == Split::Test {
            "confirm"
        } else {
            "screen"
        })
        .to_string();
    let confirmation = parsed.value("--confirmation").map(PathBuf::from);
    let baseline = parsed.value("--baseline").map(PathBuf::from);
    let require_clean = parsed.flag("--require-clean");
    let judgment_set = parsed.value("--judgment-set").map(str::to_string);
    let system_id = parsed.value("--system-id").map(str::to_string);
    let seed = seed_of(&parsed);

    if selection()?.max_cutoff() as usize > limit {
        return Err(Failure::report(format!(
            "INSUFFICIENT_DEPTH: --limit {limit} is below the largest metric cutoff"
        )));
    }
    match (split, purpose.as_str()) {
        (Split::Dev, "screen" | "deploy" | "confirm") => {}
        (Split::Test, "confirm") => {}
        (Split::Test, other) => {
            return Err(Failure::usage(format!(
                "test split requires --purpose confirm (got {other})"
            )));
        }
        (Split::Dev, other) => {
            return Err(Failure::usage(format!("unknown --purpose {other}")));
        }
    }
    if split == Split::Test {
        if confirmation.is_none() {
            return Err(Failure::usage("test split requires --confirmation"));
        }
        if baseline.is_some() {
            return Err(Failure::usage("--baseline is rejected for test runs"));
        }
        if judgment_set.is_some() {
            return Err(Failure::usage("--judgment-set is rejected for test runs"));
        }
        if code_enabled {
            return Err(Failure::usage("--code-enabled is rejected for test runs"));
        }
    }
    if split == Split::Dev && purpose == "confirm" {
        // Dry validation of confirmation metadata only; never touches test.
        return gate::dry_validate_confirmation(paths, confirmation.as_deref());
    }

    let config = environment::load_run_config(&config_path)?;
    let corpus = corpus::resolve(paths, &corpus_id, code_enabled)?;
    let evaluation_configuration = corpus.evaluation_configuration(code_enabled);
    let dataset = corpus::load_dataset(
        &corpus,
        split,
        evaluation_configuration,
        judgment_set.as_deref(),
    )
    .map_err(|error| Failure::dataset(error.to_string()))?;
    if dataset.split != split {
        return Err(Failure::dataset("dataset split does not match the request"));
    }

    let input = EvalInput {
        split,
        config_path,
        data_dir,
        output,
        system_id: system_id.unwrap_or_default(),
        limit,
        code_enabled,
        confirmation,
        baseline,
        seed,
        metadata: report_metadata(
            &parsed,
            &corpus.id,
            &format!("eval {} {:?}", corpus.id, split),
            "WP-1.2",
            "SPEC-0003",
        ),
        command: args.to_vec(),
    };

    if split == Split::Test || require_clean {
        gate::require_clean_tree(&paths.root)?;
    }

    eval::execute(paths, &corpus, &dataset, &config, &input)
}

mod eval;

// ---------------------------------------------------------------------------
// perf
// ---------------------------------------------------------------------------

fn command_perf(paths: &BenchPaths, args: &[String]) -> Result<()> {
    let mut allowed = vec![
        "--corpus",
        "--config",
        "--data-dir",
        "--output",
        "--suite",
        "--stage",
        "--repetitions",
        "--queries",
        "--queries-file",
        "--tier",
        "--cpus",
        "--memory-limit",
        "--code-enabled",
    ];
    common_metadata_allowed(&mut allowed);
    let parsed = parse_flags(args, &allowed)?;
    // `--split` is not an allowed value flag for perf, so parsing rejects it
    // before any engine work; keep an explicit conflict check for clarity.
    if parsed.value("--split").is_some() {
        return Err(Failure::usage("perf never runs the test split"));
    }
    let corpus_id = parsed.required("--corpus")?.to_string();
    let config_path = PathBuf::from(parsed.required("--config")?);
    let data_dir = PathBuf::from(parsed.required("--data-dir")?);
    let output = PathBuf::from(parsed.required("--output")?);
    let code_enabled = parsed.flag("--code-enabled");
    let queries_file = parsed.value("--queries-file").map(PathBuf::from);

    // Every flag is validated before any dataset or engine work.
    let suites = perf::Suites::parse(parsed.value("--suite").unwrap_or("all"))?;
    let stage = perf::parse_stage(parsed.value("--stage").unwrap_or("single"))?;
    let repetitions = match parsed.value("--repetitions") {
        Some(value) => perf::parse_positive("--repetitions", value, 1_000_000)?,
        None => perf::DEFAULT_REPETITIONS,
    };
    let queries = parsed
        .value("--queries")
        .map(|value| perf::parse_positive("--queries", value, perf::MAX_QUERIES as u64))
        .transpose()?
        .map(|value| value as usize);
    let tier = perf::budget::Tier::parse(parsed.value("--tier").unwrap_or("T2"))?;
    let cpus = parsed
        .value("--cpus")
        .map(|value| {
            perf::platform::parse_cpu_list(value)
                .map_err(|error| Failure::usage(format!("--cpus: {error}")))
        })
        .transpose()?;
    let memory_limit_bytes = parsed
        .value("--memory-limit")
        .map(|value| perf::parse_positive("--memory-limit", value, u64::MAX))
        .transpose()?;
    let declaration = perf::budget::TierDeclaration {
        tier,
        cpus,
        memory_limit_bytes,
    };
    let host = perf::capture_host();
    perf::budget::validate_tier(&declaration, &host)?;

    let config = environment::load_run_config(&config_path)?;
    let corpus = corpus::resolve(paths, &corpus_id, code_enabled)?;
    let evaluation_configuration = corpus.evaluation_configuration(code_enabled);
    let dataset = match queries_file.as_deref() {
        Some(path) => corpus::load_perf_queries_file(&corpus, path, evaluation_configuration)?,
        None => {
            let loaded = corpus::load_dataset(&corpus, Split::Dev, evaluation_configuration, None)
                .map_err(|error| Failure::dataset(error.to_string()))?;
            corpus::PerfDataset::from_dataset(&loaded, &corpus.visibility)?
        }
    };
    let options = perf::PerfOptions {
        suites,
        stage,
        repetitions,
        queries,
        declaration,
        host,
        config_path,
        seed: seed_of(&parsed),
        metadata: report_metadata(
            &parsed,
            &corpus.id,
            &format!("perf {} {}", corpus.id, tier.as_str()),
            "WP-1.6",
            "SPEC-0003",
        ),
    };
    perf::run(
        paths, &corpus, &dataset, &config, &data_dir, &output, &options, args,
    )
}

/// Hidden child process for the cold-start suite (never documented).
fn command_startup_probe(args: &[String]) -> Result<()> {
    let parsed = parse_flags(args, &["--data-dir", "--config"])?;
    let data_dir = PathBuf::from(parsed.required("--data-dir")?);
    let config = environment::load_run_config(Path::new(parsed.required("--config")?))?;
    perf::startup::run_probe(&data_dir, &config)
}

// ---------------------------------------------------------------------------
// compare
// ---------------------------------------------------------------------------

fn command_compare(paths: &BenchPaths, args: &[String]) -> Result<()> {
    let mut allowed = vec![
        "--baseline",
        "--candidate",
        "--repeat-candidate",
        "--gate",
        "--baseline-commit",
        "--allow-config-change",
        "--output",
    ];
    common_metadata_allowed(&mut allowed);
    let parsed = parse_flags(args, &allowed)?;
    let baseline_path = PathBuf::from(parsed.required("--baseline")?);
    let candidates: Vec<PathBuf> = parsed
        .values("--candidate")
        .iter()
        .map(PathBuf::from)
        .collect();
    if candidates.is_empty() {
        return Err(Failure::usage("compare requires at least one --candidate"));
    }
    let repeat = parsed.value("--repeat-candidate").map(PathBuf::from);
    let gate = parsed.value("--gate").map(str::to_string);
    let baseline_commit = parsed.value("--baseline-commit").map(str::to_string);
    let allow_config_change = parsed.value("--allow-config-change").map(str::to_string);
    if let Some(adr) = allow_config_change.as_deref() {
        if gate.as_deref() != Some("wp1.8") {
            return Err(Failure::usage(
                "--allow-config-change is valid only with --gate wp1.8",
            ));
        }
        if !smoke_gate::is_valid_adr_id(adr) {
            return Err(Failure::usage(
                "--allow-config-change must name an ADR identifier (for example ADR-0027)",
            ));
        }
    }
    let output = PathBuf::from(parsed.required("--output")?);
    let seed = seed_of(&parsed);
    gate::compare(
        paths,
        &baseline_path,
        &candidates,
        repeat.as_deref(),
        gate.as_deref(),
        baseline_commit.as_deref(),
        allow_config_change.as_deref(),
        &output,
        &seed,
        report_metadata(
            &parsed,
            "comparison",
            "paired comparison",
            "WP-1.2",
            "SPEC-0003",
        ),
        args,
    )
}

// ---------------------------------------------------------------------------
// report
// ---------------------------------------------------------------------------

fn command_report(args: &[String]) -> Result<()> {
    let parsed = parse_flags(args, &["--results", "--output", "--overwrite"])?;
    let results_path = PathBuf::from(parsed.required("--results")?);
    let output = PathBuf::from(parsed.required("--output")?);
    let overwrite = parsed.flag("--overwrite");
    gate::report(&results_path, &output, overwrite)
}

// ---------------------------------------------------------------------------
// shared helpers used by eval and perf
// ---------------------------------------------------------------------------

pub(crate) fn commit_info(root: &Path) -> Result<CommitInfo> {
    if !root.join(".git").exists() {
        return Err(Failure::dataset(
            "repository state unavailable: no .git directory under the bench root",
        ));
    }
    let sha = run_git(root, &["rev-parse", "HEAD"])?;
    let status = run_git(root, &["status", "--porcelain"])?;
    Ok(CommitInfo {
        sha,
        dirty: !status.trim().is_empty(),
    })
}

pub(crate) fn run_git(root: &Path, args: &[&str]) -> Result<String> {
    let output = std::process::Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()
        .map_err(|error| Failure::dataset(format!("git unavailable: {error}")))?;
    if !output.status.success() {
        return Err(Failure::dataset("git command failed"));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

pub(crate) struct CommitInfo {
    pub sha: String,
    pub dirty: bool,
}

pub(crate) fn command_display(
    paths: &BenchPaths,
    substitutions: &[(&Path, &str)],
    args: &[String],
) -> Vec<String> {
    let repo = paths.root.to_string_lossy().replace('\\', "/");
    let repo = repo.trim_end_matches('/').to_string();
    let mut command = vec!["seeky-bench".to_string()];
    for argument in args {
        let normalized = argument.replace('\\', "/");
        if let Some(rest) = normalized.strip_prefix(&format!("{repo}/")) {
            command.push(rest.to_string());
            continue;
        }
        let mut replaced = None;
        for (path, token) in substitutions {
            let path = path.to_string_lossy().replace('\\', "/");
            let path = path.trim_end_matches('/');
            if normalized == path {
                replaced = Some((*token).to_string());
                break;
            }
            if let Some(rest) = normalized.strip_prefix(&format!("{path}/")) {
                replaced = Some(format!("{token}/{rest}"));
                break;
            }
        }
        if let Some(replaced) = replaced {
            command.push(replaced);
        } else if Path::new(argument).is_absolute() {
            command.push("<path>".to_string());
        } else {
            command.push(argument.clone());
        }
    }
    command
}

pub(crate) fn system_info(snapshot_json: &str, config_hash: &str, system_id: &str) -> SystemInfo {
    let value: serde_json::Value =
        serde_json::from_str(snapshot_json).unwrap_or(serde_json::Value::Null);
    let provider = value
        .get("execution")
        .and_then(|execution| execution.get("provider"))
        .and_then(|provider| provider.as_str())
        .unwrap_or("cpu")
        .to_string();
    let models = environment::snapshot_models(snapshot_json)
        .into_iter()
        .map(|model| seeky_eval::ModelInfo {
            id: model.id,
            task: model.task,
            variant: model.variant,
            sha256: model.sha256,
            provider: model.provider,
        })
        .collect();
    SystemInfo {
        system_id: system_id.to_string(),
        config_hash: config_hash.to_string(),
        models,
        provider,
    }
}

pub(crate) fn combined(
    snapshot_json: &str,
    config: &RunConfig,
    settings: &EvaluationSettings,
) -> Result<CombinedConfig> {
    environment::combined_config(snapshot_json, config, settings)
}

pub(crate) fn dataset_info(dataset: &Dataset, visibility: &str) -> seeky_eval::DatasetInfo {
    seeky_eval::DatasetInfo {
        id: dataset.id.clone(),
        split: dataset.split,
        configuration: dataset.configuration,
        corpus_hash: dataset.corpus_hash.clone(),
        fingerprint: dataset.fingerprint.clone(),
        judgment_set_id: dataset.judgment_set_id.clone(),
        judgment_set_hash: dataset.judgment_set_hash.clone(),
        query_count: dataset.queries().len() as u64,
        query_set_sha256: dataset.query_set_sha256().to_string(),
        visibility: visibility.to_string(),
    }
}

pub(crate) fn stats_options(seed: &str) -> StatsOptions {
    StatsOptions {
        seed: seed.to_string(),
        ..StatsOptions::default()
    }
}
