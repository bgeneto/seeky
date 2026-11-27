//! `seeky-bench perf`: performance suites (SPEC-0003 R25-R28, sections 4.8,
//! 4.10, and 5.5).
//!
//! Inputs are validated (including the tier declaration against the captured
//! host) before any engine work. Search-only suites run on the existing index;
//! indexing, time-to-searchable, and interference run on a fresh temporary
//! data directory. Every value that was not measured is null with a warning,
//! and `qualifies_for_budget` is false with explicit reasons whenever a sample,
//! tier, quiet-window, or synthetic condition fails. Only the SPEC-0002 v1.1
//! `Engine` API is used.

pub mod budget;
pub mod platform;
pub mod resources;
pub mod startup;
pub mod stats;
pub mod suites;

use crate::corpus::{BenchPaths, Corpus};
use crate::engine::{self, EngineAdapter};
use crate::environment::{self, EvaluationSettings};
use crate::{Failure, Result};
use budget::{Eligibility, HostFacts, QuietWindow, TierDeclaration};
use seeky_engine::{
    Engine, EngineEvents, IndexHealth, IndexProgress, QueryEmbeddingProbe, SearchMode,
    SearchOptions, SearchRequest,
};
use seeky_eval::{
    Artifacts, CommitInfo, Dataset, Decision, DecisionStatus, PerformanceReport,
    QueryEmbeddingMetrics, Report, ReportKind, ReportMetadata, ResourceMetrics, SCHEMA_VERSION,
    SearchMeasurement, SearchableLatency, Split, TimeToSearchable, ToolInfo,
};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::time::Duration;
use suites::{Clock, EmbeddingTarget, MonotonicClock, QueryPlan, SearchTarget};

/// Maximum dev queries in the fixed set (SPEC-0003 section 4.8).
pub const MAX_QUERIES: usize = 1_000;
/// Default fixed-set repetitions (SPEC-0003 section 4.8).
pub const DEFAULT_REPETITIONS: u64 = 30;
/// Time-to-searchable samples per capability.
pub const TTS_SAMPLES: usize = 5;
/// Search polls before a time-to-searchable sample counts as not reached.
pub const TTS_MAX_POLLS: usize = 200;
/// Idle RSS samples after stabilization.
pub const IDLE_SAMPLES: usize = 10;

/// Suite selection (`--suite`).
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
#[allow(clippy::struct_excessive_bools)] // one flag per independently selectable suite
pub struct Suites {
    /// Warm-idle search latency.
    pub search: bool,
    /// Batch-1 query-embedding latency.
    pub embedding: bool,
    /// Bulk indexing throughput and time-to-searchable.
    pub indexing: bool,
    /// S5 interference ratio.
    pub interference: bool,
    /// RSS and index size.
    pub resources: bool,
    /// Cold start.
    pub startup: bool,
}

impl Suites {
    /// Parse a comma-separated `--suite` value.
    pub fn parse(value: &str) -> Result<Self> {
        let mut suites = Self::default();
        for name in value.split(',') {
            match name.trim() {
                "all" => {
                    suites = Self {
                        search: true,
                        embedding: true,
                        indexing: true,
                        interference: true,
                        resources: true,
                        startup: true,
                    };
                }
                "search" => suites.search = true,
                "embedding" => suites.embedding = true,
                "indexing" => suites.indexing = true,
                "interference" => suites.interference = true,
                "resources" => suites.resources = true,
                "startup" => suites.startup = true,
                other => {
                    return Err(Failure::usage(format!(
                        "unknown --suite {other:?}; expected search, embedding, indexing, interference, resources, startup, or all"
                    )));
                }
            }
        }
        Ok(suites)
    }
}

/// Parse `--stage`.
pub fn parse_stage(value: &str) -> Result<String> {
    match value {
        "single" | "instant" | "hybrid" | "refined" => Ok(value.to_string()),
        _ => Err(Failure::usage(
            "--stage must be single, instant, hybrid, or refined",
        )),
    }
}

/// Parse a positive integer flag.
pub fn parse_positive(flag: &str, value: &str, max: u64) -> Result<u64> {
    let parsed: u64 = value
        .parse()
        .map_err(|_| Failure::usage(format!("{flag} must be a positive integer")))?;
    if parsed == 0 || parsed > max {
        return Err(Failure::usage(format!("{flag} must be in 1..={max}")));
    }
    Ok(parsed)
}

/// Host facts captured for the tier check and `environment.json`.
#[must_use]
pub fn capture_host() -> HostFacts {
    HostFacts {
        logical_cores: std::thread::available_parallelism()
            .ok()
            .map(std::num::NonZeroUsize::get),
        memory_bytes: platform::total_memory_bytes(),
        cpu_features: environment::cpu_feature_names(),
        process_affinity: platform::process_affinity(),
    }
}

/// Validated `perf` options.
#[derive(Clone, Debug)]
pub struct PerfOptions {
    /// Selected suites.
    pub suites: Suites,
    /// Requested search stage.
    pub stage: String,
    /// Fixed-set repetitions.
    pub repetitions: u64,
    /// Dev queries in the fixed set.
    pub queries: Option<usize>,
    /// Tier declaration (already validated against the host).
    pub declaration: TierDeclaration,
    /// Host facts.
    pub host: HostFacts,
    /// `--config` path (passed to the startup probe).
    pub config_path: PathBuf,
    /// Bootstrap seed.
    pub seed: String,
    /// Report template metadata.
    pub metadata: ReportMetadata,
}

/// Record the tier, emulation, quiet window, memory, and sampling scope in an
/// environment object produced by [`environment::capture`].
pub fn record_environment(
    environment: &mut Value,
    declaration: &TierDeclaration,
    host: &HostFacts,
    quiet: &QuietWindow,
) {
    environment["tier"] = json!(declaration.tier.as_str());
    environment["emulation"] = if declaration.tier == budget::Tier::T1Emulated {
        json!({
            "logical_cpus": declaration.cpus,
            "memory_limit_bytes": declaration.memory_limit_bytes,
        })
    } else {
        Value::Null
    };
    environment["memory_bytes"] = json!(host.memory_bytes);
    environment["quiet_window"] = json!({
        "verified": quiet.verified,
        "heavy_processes": quiet.heavy_processes,
    });
    environment["process"] = json!({
        "scope": resources::SCOPE,
        "sampling_interval_ms": resources::SAMPLING_INTERVAL_MS,
    });
}

struct EngineTarget<'a>(&'a Engine);

impl SearchTarget for EngineTarget<'_> {
    fn run_query(&self, query: &str) -> Result<()> {
        self.0
            .search(&SearchRequest {
                query: query.to_string(),
                limit: None,
            })
            .map(drop)
            .map_err(|error| Failure::engine(error.to_string()))
    }
}

impl EmbeddingTarget for EngineTarget<'_> {
    fn embed_ns(&self, query: &str) -> Result<Option<u64>> {
        match self
            .0
            .probe_query_embedding(query)
            .map_err(|error| Failure::engine(error.to_string()))?
        {
            QueryEmbeddingProbe::Available { duration_ns, .. } => Ok(Some(duration_ns)),
            QueryEmbeddingProbe::Unavailable => Ok(None),
        }
    }
}

/// Counts extraction progress events so perf can confirm indexing is active.
#[derive(Default)]
struct ProgressCounter {
    events: AtomicUsize,
}

impl EngineEvents for ProgressCounter {
    fn index_progress(&self, progress: &IndexProgress) {
        if progress.phase != "done" {
            self.events.fetch_add(1, Ordering::SeqCst);
        }
    }

    fn index_health(&self, _health: &IndexHealth) {}
}

/// Accumulates report values and warnings.
struct Collected {
    performance: PerformanceReport,
    eligibility: Eligibility,
}

impl Collected {
    fn warn(&mut self, warning: impl Into<String>) {
        self.performance.warnings.push(warning.into());
    }
}

/// Run the requested suites and write the report artifacts.
#[allow(clippy::too_many_arguments, clippy::too_many_lines)]
pub(crate) fn run(
    paths: &BenchPaths,
    corpus: &Corpus,
    dataset: &Dataset,
    config: &environment::RunConfig,
    data_dir: &Path,
    output: &Path,
    options: &PerfOptions,
    command: &[String],
) -> Result<()> {
    let sidecar = engine::sidecar_path(data_dir);
    if !sidecar.is_file() {
        return Err(Failure::engine(
            "INDEX_INCOMPATIBLE: no index metadata; run `seeky-bench index` first",
        ));
    }
    // Validate the tier and quiet window before measurement (section 5.5 step 8).
    budget::validate_tier(&options.declaration, &options.host)?;
    let quiet = budget::quiet_window(&budget::SystemProcesses);
    let mut environment = environment::capture(options.declaration.tier.as_str(), None, None);
    record_environment(
        &mut environment,
        &options.declaration,
        &options.host,
        &quiet,
    );

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
        seed: options.seed.clone(),
    };
    let combined = crate::combined(&snapshot_json, config, &settings)?;
    let config_hash = combined.sha256();
    let system_id: String = config_hash.chars().take(8).collect();
    let commit = crate::commit_info(&paths.root)?;
    let system = crate::system_info(&snapshot_json, &config_hash, &system_id);
    let dataset_info = crate::dataset_info(dataset, &corpus.visibility);

    // Perf only ever reads dev queries (the dataset was loaded with Split::Dev).
    let limit = options.queries.unwrap_or(MAX_QUERIES).min(MAX_QUERIES);
    let plan = QueryPlan {
        queries: dataset
            .queries()
            .iter()
            .take(limit)
            .map(|query| query.text.clone())
            .collect(),
        repetitions: options.repetitions,
    };

    let clock = MonotonicClock::new();
    let sampler: Arc<dyn resources::RssSampler> = Arc::new(resources::ProcessRss);
    let monitor = resources::RssMonitor::start(
        Arc::clone(&sampler),
        Duration::from_millis(resources::SAMPLING_INTERVAL_MS),
    );
    let mut collected = Collected {
        performance: empty_performance(options.declaration.tier.as_str()),
        eligibility: Eligibility::new(options.declaration.tier, &quiet, false),
    };

    // Warm-idle search and query embedding on the existing index.
    let target = EngineTarget(adapter.engine());
    if options.suites.search {
        search_suite(&mut collected, &clock, &target, &plan, options)?;
    } else {
        collected.warn("search not measured: suite not requested");
    }
    if options.suites.embedding {
        embedding_suite(&mut collected, &target, &plan, &options.seed)?;
    } else {
        collected.warn("query_embedding not measured: suite not requested");
    }
    let mut idle_rss = None;
    let mut index_resources = None;
    if options.suites.resources {
        idle_rss = resources::idle_rss(
            sampler.as_ref(),
            IDLE_SAMPLES,
            Duration::from_millis(resources::SAMPLING_INTERVAL_MS),
        );
        let index_bytes = resources::directory_bytes(data_dir, &[engine::SIDECAR_NAME])?;
        let passages = adapter
            .engine()
            .status()
            .map_err(|error| Failure::engine(error.to_string()))?
            .counts
            .chunks;
        let per_1k = resources::disk_bytes_per_1k_passages(
            index_bytes,
            u64::try_from(passages).unwrap_or(0),
        )?;
        index_resources = Some((index_bytes, per_1k));
    }
    adapter.shutdown()?;

    if options.suites.startup {
        startup_suite(&mut collected, &clock, data_dir, &options.config_path);
    } else {
        collected.warn("startup not measured: suite not requested");
    }
    if options.suites.indexing || options.suites.interference {
        fresh_index_suites(
            &mut collected,
            &clock,
            corpus,
            config,
            &plan,
            options,
            &system.provider,
        )?;
    }
    if !options.suites.indexing {
        collected.warn("indexing and time_to_searchable not measured: suite not requested");
    }
    if !options.suites.interference {
        collected.warn("interference_ratio not measured: suite not requested");
    }

    let samples = monitor.finish();
    if let Some((index_bytes, per_1k)) = index_resources {
        let peak = resources::peak_rss(&samples, idle_rss);
        if idle_rss.is_none() {
            collected.warn("resources.idle_rss_bytes unavailable: process RSS cannot be sampled on this platform");
        }
        if peak.is_none() {
            collected.warn("resources.peak_rss_bytes unavailable: process RSS cannot be sampled on this platform");
        }
        collected.warn(
            "resources.page_cache_bytes unavailable: the OS exposes no per-index page-cache figure to the harness",
        );
        collected.performance.resources = Some(ResourceMetrics {
            idle_rss_bytes: idle_rss,
            peak_rss_bytes: peak,
            page_cache_bytes: None,
            index_bytes,
            disk_bytes_per_1k_passages: per_1k,
            scope: resources::SCOPE.to_string(),
            sampling_interval_ms: resources::SAMPLING_INTERVAL_MS,
        });
    } else {
        collected.warn("resources not measured: suite not requested");
    }
    for (field, reason) in [
        ("distribution", "no installer package is part of this run"),
        ("ocr", "no OCR pack is installed"),
        ("visual", "no visual pack is installed"),
        ("energy", "energy is not measurable by the harness"),
    ] {
        collected.warn(format!("{field} unavailable: {reason}"));
    }

    let Collected {
        mut performance,
        eligibility,
    } = collected;
    performance.qualifies_for_budget = eligibility.qualifies();
    performance
        .warnings
        .extend(eligibility.reasons().iter().cloned());
    let decision_text = if performance.qualifies_for_budget {
        "Budget-eligible performance evidence".to_string()
    } else {
        format!(
            "Not budget-eligible: {} reason(s) listed in performance.warnings",
            eligibility.reasons().len()
        )
    };

    let report = Report {
        schema_version: SCHEMA_VERSION,
        run_id: crate::run_id("perf"),
        kind: ReportKind::Performance,
        generated_at: environment::rfc3339_now(),
        report: options.metadata.clone(),
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
        performance: Some(performance),
        comparisons: Vec::new(),
        gates: Vec::new(),
        decision: Decision {
            status: DecisionStatus::NotApplicable,
            text: decision_text,
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

    let qualifies = report
        .performance
        .as_ref()
        .is_some_and(|performance| performance.qualifies_for_budget);
    println!(
        "perf {} at tier {}: {}",
        corpus.id,
        options.declaration.tier.as_str(),
        if qualifies {
            "budget-eligible"
        } else {
            "not budget-eligible (see performance.warnings)"
        }
    );
    Ok(())
}

/// A performance payload with every measurement still null.
#[must_use]
pub fn empty_performance(tier: &str) -> PerformanceReport {
    PerformanceReport {
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
    }
}

fn search_suite(
    collected: &mut Collected,
    clock: &dyn Clock,
    target: &dyn SearchTarget,
    plan: &QueryPlan,
    options: &PerfOptions,
) -> Result<()> {
    if options.stage != "single" {
        collected.warn(format!(
            "search stage {} unavailable: the engine delivers one blocking result list (single)",
            options.stage
        ));
        return Ok(());
    }
    let samples = suites::measure_search(clock, target, plan)?;
    collected.eligibility.check_samples(
        "search single warm_idle",
        samples.queries,
        samples.repetitions,
    );
    collected.performance.search.push(SearchMeasurement {
        stage: "single".to_string(),
        condition: "warm_idle".to_string(),
        queries: samples.queries,
        repetitions: samples.repetitions,
        latency_ms: stats::latency_metrics(&samples.samples_ms, &options.seed, stats::RESAMPLES)?,
    });
    Ok(())
}

fn embedding_suite(
    collected: &mut Collected,
    target: &dyn EmbeddingTarget,
    plan: &QueryPlan,
    seed: &str,
) -> Result<()> {
    match suites::measure_embedding(target, plan)? {
        Some(samples) => {
            collected.eligibility.check_samples(
                "query_embedding",
                samples.queries,
                samples.repetitions,
            );
            collected.performance.query_embedding = Some(QueryEmbeddingMetrics {
                batch: 1,
                samples: samples.queries,
                latency_ms: stats::latency_metrics(&samples.samples_ms, seed, stats::RESAMPLES)?,
            });
        }
        None => collected.warn("query_embedding unavailable: no semantic model is active"),
    }
    Ok(())
}

fn startup_suite(collected: &mut Collected, clock: &dyn Clock, data_dir: &Path, config: &Path) {
    let Some(executable) = startup::bench_executable() else {
        collected.warn("startup unavailable: the seeky-bench executable was not found");
        return;
    };
    match startup::measure_cold_start(clock, &executable, data_dir, config) {
        Ok(metrics) => {
            if metrics.semantic_capable_ms.is_none() {
                collected
                    .warn("startup.semantic_capable_ms unavailable: no semantic model is active");
            }
            collected.warn("startup.os_cache uncontrolled: the OS page cache was not flushed");
            collected.performance.startup = Some(metrics);
        }
        Err(_) => collected.warn("startup unavailable: the startup probe failed"),
    }
}

/// Temporary workspace removed on drop.
struct Workspace(PathBuf);

impl Workspace {
    fn create() -> Result<Self> {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or(0);
        let path =
            std::env::temp_dir().join(format!("seeky-bench-perf-{}-{nanos}", std::process::id()));
        std::fs::create_dir_all(&path)
            .map_err(|error| Failure::engine(format!("cannot create a perf workspace: {error}")))?;
        Ok(Self(path))
    }
}

impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[allow(clippy::needless_pass_by_value)] // used as a `map_err` adapter
fn io_failure(error: std::io::Error) -> Failure {
    Failure::engine(format!("perf workspace I/O failed: {error}"))
}

fn copy_tree(from: &Path, to: &Path) -> Result<()> {
    std::fs::create_dir_all(to).map_err(io_failure)?;
    for entry in std::fs::read_dir(from).map_err(io_failure)? {
        let entry = entry.map_err(io_failure)?;
        let kind = entry.file_type().map_err(io_failure)?;
        let target = to.join(entry.file_name());
        if kind.is_dir() {
            copy_tree(&entry.path(), &target)?;
        } else if kind.is_file() {
            std::fs::copy(entry.path(), &target).map_err(io_failure)?;
        }
    }
    Ok(())
}

#[allow(clippy::needless_pass_by_value)] // used as a `map_err` adapter
fn engine_failure(error: seeky_engine::EngineError) -> Failure {
    Failure::engine(error.to_string())
}

fn add_unwatched_root(engine: &Engine, path: &Path) -> Result<()> {
    let root = engine.add_root(path).map_err(engine_failure)?;
    engine
        .set_root_watching(&root.id, false)
        .map_err(engine_failure)?;
    Ok(())
}

/// Bulk indexing, time-to-searchable, and interference on a fresh data dir.
#[allow(clippy::too_many_lines)]
fn fresh_index_suites(
    collected: &mut Collected,
    clock: &dyn Clock,
    corpus: &Corpus,
    config: &environment::RunConfig,
    plan: &QueryPlan,
    options: &PerfOptions,
    provider: &str,
) -> Result<()> {
    let workspace = Workspace::create()?;
    let progress = Arc::new(ProgressCounter::default());
    let events: Arc<dyn EngineEvents> = progress.clone();
    let adapter = EngineAdapter::open_with_events(&workspace.0.join("data"), config, events)?;
    let engine = adapter.engine();

    // Bulk indexing throughput over the corpus roots.
    let mut source_bytes = 0_u64;
    for root in &corpus.roots {
        add_unwatched_root(engine, root)?;
        source_bytes = source_bytes.saturating_add(resources::directory_bytes(root, &[])?);
    }
    let started = clock.now_ns();
    let (mut files, mut passages) = (0_u64, 0_u64);
    for root in &corpus.roots {
        let summary = engine.index_path(root).map_err(engine_failure)?;
        files += summary.files as u64;
        passages += summary.chunks as u64;
    }
    let elapsed = clock.now_ns().saturating_sub(started);
    if options.suites.indexing {
        collected.performance.indexing = Some(suites::indexing_throughput(
            files,
            source_bytes,
            passages,
            elapsed,
            provider,
        )?);
        collected.warn(
            "indexing.samples is 1: one bulk run; extraction and embedding share one timed pass",
        );
        time_to_searchable_suite(collected, clock, engine, &workspace.0, config.semantic)?;
    }

    if options.suites.interference {
        interference_suite(
            collected,
            clock,
            engine,
            corpus,
            plan,
            &options.seed,
            &progress,
            &workspace.0,
        )?;
    }
    adapter.shutdown()?;
    drop(workspace);
    Ok(())
}

fn probe_matches(engine: &Engine, token: &str, file_name: &str, channel: &str) -> Result<bool> {
    let outcome = engine
        .search_with(
            &SearchRequest {
                query: token.to_string(),
                limit: Some(100),
            },
            &SearchOptions {
                mode: SearchMode::Evaluation,
                filters: None,
                telemetry: false,
            },
        )
        .map_err(engine_failure)?;
    Ok(outcome.response.hits.iter().any(|hit| {
        hit.path
            .replace('\\', "/")
            .ends_with(&format!("/{file_name}"))
            && hit.matched.iter().any(|matched| matched == channel)
    }))
}

fn searchable_latency(values: &mut [f64]) -> SearchableLatency {
    values.sort_by(f64::total_cmp);
    if values.is_empty() {
        return SearchableLatency {
            samples: 0,
            p50: 0.0,
            p95: 0.0,
        };
    }
    SearchableLatency {
        samples: values.len() as u64,
        p50: stats::percentile_type7(values, 0.50),
        p95: stats::percentile_type7(values, 0.95),
    }
}

/// Unique search token of time-to-searchable probe `sample`.
#[must_use]
pub fn tts_probe_token(sample: usize) -> String {
    format!("seekyperfprobe{sample:04}")
}

/// Contents of time-to-searchable probe `sample`.
///
/// The engine treats a file whose size and modification time are unchanged
/// as unchanged. Within the filesystem timestamp resolution (notably on
/// Windows) consecutive rewrites can keep the same mtime, so every sample has
/// a distinct byte length: the rewrite is always detected as a change.
#[must_use]
pub fn tts_probe_contents(sample: usize) -> String {
    format!(
        "{}\nSynthetic time-to-searchable probe document number {sample}.\n{}\n",
        tts_probe_token(sample),
        "x".repeat(sample + 1)
    )
}

fn time_to_searchable_suite(
    collected: &mut Collected,
    clock: &dyn Clock,
    engine: &Engine,
    workspace: &Path,
    semantic: bool,
) -> Result<()> {
    let probe_root = workspace.join("tts");
    std::fs::create_dir_all(&probe_root).map_err(io_failure)?;
    add_unwatched_root(engine, &probe_root)?;
    let file_name = "seeky-perf-probe.txt";
    let (mut lexical, mut dense) = (Vec::new(), Vec::new());
    for sample in 0..TTS_SAMPLES {
        let token = tts_probe_token(sample);
        let start = clock.now_ns();
        std::fs::write(probe_root.join(file_name), tts_probe_contents(sample))
            .map_err(io_failure)?;
        engine.index_path(&probe_root).map_err(engine_failure)?;
        let mut poll = || probe_matches(engine, &token, file_name, "bm25");
        if let Some(value) = suites::time_to_searchable(clock, start, TTS_MAX_POLLS, &mut poll)? {
            lexical.push(value);
        }
        if semantic {
            let mut poll = || probe_matches(engine, &token, file_name, "semantic");
            if let Some(value) = suites::time_to_searchable(clock, start, TTS_MAX_POLLS, &mut poll)?
            {
                dense.push(value);
            }
        }
    }
    if lexical.len() < TTS_SAMPLES {
        collected.warn("time_to_searchable.lexical_ms: some probes were never found");
    }
    if dense.is_empty() {
        collected.warn(if semantic {
            "time_to_searchable.semantic_ms unavailable: the semantic channel never returned the probe"
        } else {
            "time_to_searchable.semantic_ms unavailable: no semantic model is active"
        });
    }
    collected.warn(
        "time_to_searchable measures a single changed file indexed explicitly (watching off, no debounce)",
    );
    collected.performance.time_to_searchable = Some(TimeToSearchable {
        lexical_ms: searchable_latency(&mut lexical),
        semantic_ms: searchable_latency(&mut dense),
    });
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn interference_suite(
    collected: &mut Collected,
    clock: &dyn Clock,
    engine: &Engine,
    corpus: &Corpus,
    plan: &QueryPlan,
    seed: &str,
    progress: &ProgressCounter,
    workspace: &Path,
) -> Result<()> {
    let target = EngineTarget(engine);
    let idle = suites::measure_search(clock, &target, plan)?;
    // Copies of the corpus roots are new files to the engine: real bulk work.
    let mut copies = Vec::with_capacity(corpus.roots.len());
    for (index, root) in corpus.roots.iter().enumerate() {
        let copy = workspace.join(format!("interference-{index}"));
        copy_tree(root, &copy)?;
        add_unwatched_root(engine, &copy)?;
        copies.push(copy);
    }
    let before = progress.events.load(Ordering::SeqCst);
    let done = AtomicBool::new(false);
    let indexing = std::thread::scope(|scope| -> Result<suites::SearchSamples> {
        let worker = scope.spawn(|| {
            let result = copies
                .iter()
                .try_for_each(|copy| engine.index_path(copy).map(drop));
            done.store(true, Ordering::SeqCst);
            result
        });
        // Confirm that bulk indexing is active before timing any query.
        while progress.events.load(Ordering::SeqCst) == before && !done.load(Ordering::SeqCst) {
            std::thread::yield_now();
        }
        let active = || !done.load(Ordering::SeqCst);
        let samples = suites::measure_search_while(clock, &target, plan, &active);
        engine.cancel_indexing();
        let joined = worker
            .join()
            .map_err(|_| Failure::engine("interference indexing thread panicked"))?;
        joined.map_err(engine_failure)?;
        samples
    })?;
    if indexing.samples_ms.is_empty() {
        collected.warn(
            "interference_ratio unavailable: bulk indexing finished before any query completed",
        );
        return Ok(());
    }
    collected.eligibility.check_samples(
        "search single warm_indexing",
        indexing.queries,
        indexing.repetitions,
    );
    collected.performance.search.push(SearchMeasurement {
        stage: "single".to_string(),
        condition: "warm_indexing".to_string(),
        queries: indexing.queries,
        repetitions: indexing.repetitions,
        latency_ms: stats::latency_metrics(&indexing.samples_ms, seed, stats::RESAMPLES)?,
    });
    match stats::interference_ratio(
        &idle.samples_ms,
        &indexing.samples_ms,
        seed,
        stats::RESAMPLES,
    ) {
        Ok(ratio) => collected.performance.interference_ratio = Some(ratio),
        Err(_) => collected.warn("interference_ratio unavailable: idle p95 is 0"),
    }
    Ok(())
}
