//! SPEC-0003 R25-R28 acceptance tests for `seeky-bench perf`.
//!
//! Hardware-free and hermetic: an injected clock, fake search/embedding
//! targets, a fake RSS sampler and process lister, fixed seeds, and per-test
//! temporary directories. The end-to-end run uses the lexical fixture engine
//! and asserts only the artifact shape, never a timing value.

#![allow(clippy::unwrap_used)]

mod support;

use seeky_bench::corpus::BenchPaths;
use seeky_bench::perf::budget::{
    self, Eligibility, HostFacts, ProcessLister, QuietWindow, Tier, TierDeclaration,
};
use seeky_bench::perf::resources::{self, RssSampler};
use seeky_bench::perf::startup;
use seeky_bench::perf::stats;
use seeky_bench::perf::suites::{self, Clock, EmbeddingTarget, QueryPlan, SearchTarget};
use seeky_bench::{Failure, run_with_paths};
use serde_json::Value;
use std::collections::VecDeque;
use std::io::Cursor;
use std::path::Path;
use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

const MS: u64 = 1_000_000;

/// Clock that only moves when a fake target advances it.
#[derive(Default)]
struct FakeClock {
    now: AtomicU64,
}

impl FakeClock {
    fn advance(&self, ns: u64) {
        self.now.fetch_add(ns, Ordering::SeqCst);
    }
}

impl Clock for FakeClock {
    fn now_ns(&self) -> u64 {
        self.now.load(Ordering::SeqCst)
    }
}

/// Clock that advances by a fixed step on every read.
struct SteppingClock {
    now: AtomicU64,
    step: u64,
}

impl Clock for SteppingClock {
    fn now_ns(&self) -> u64 {
        self.now.fetch_add(self.step, Ordering::SeqCst) + self.step
    }
}

/// Search target whose executions take the scripted durations.
struct ScriptedSearch<'a> {
    clock: &'a FakeClock,
    durations: Mutex<VecDeque<u64>>,
}

impl SearchTarget for ScriptedSearch<'_> {
    fn run_query(&self, _query: &str) -> Result<(), Failure> {
        let duration = self.durations.lock().unwrap().pop_front().unwrap();
        self.clock.advance(duration);
        Ok(())
    }
}

/// Fake embedder probe: scripted durations, or no semantic model.
struct ScriptedEmbedding {
    durations: Mutex<VecDeque<u64>>,
    available: bool,
}

impl EmbeddingTarget for ScriptedEmbedding {
    fn embed_ns(&self, _query: &str) -> Result<Option<u64>, Failure> {
        if !self.available {
            return Ok(None);
        }
        Ok(self.durations.lock().unwrap().pop_front())
    }
}

struct FixedProcesses(Option<Vec<&'static str>>);

impl ProcessLister for FixedProcesses {
    fn process_names(&self) -> Option<Vec<String>> {
        self.0
            .as_ref()
            .map(|names| names.iter().map(|name| (*name).to_string()).collect())
    }
}

struct ScriptedRss(Mutex<VecDeque<Option<u64>>>);

impl RssSampler for ScriptedRss {
    fn rss_bytes(&self) -> Option<u64> {
        self.0.lock().unwrap().pop_front().flatten()
    }
}

fn plan(queries: usize, repetitions: u64) -> QueryPlan {
    QueryPlan {
        queries: (0..queries).map(|index| format!("q{index}")).collect(),
        repetitions,
    }
}

fn close(actual: f64, expected: f64) {
    assert!(
        (actual - expected).abs() < 1e-9,
        "expected {expected}, got {actual}"
    );
}

fn quiet() -> QuietWindow {
    QuietWindow {
        verified: true,
        heavy_processes: Vec::new(),
    }
}

fn host() -> HostFacts {
    HostFacts {
        logical_cores: Some(20),
        memory_bytes: Some(64 * 1024 * 1024 * 1024),
        cpu_features: vec!["avx2".into(), "vnni".into()],
        process_affinity: Some((0..20).collect()),
    }
}

fn emulated(cpus: Vec<u32>, memory: u64) -> TierDeclaration {
    TierDeclaration {
        tier: Tier::T1Emulated,
        cpus: Some(cpus),
        memory_limit_bytes: Some(memory),
    }
}

// --- R25 -------------------------------------------------------------------

/// SPEC-0003-R25: warm-up discarded, one sample per execution, type-7.
#[test]
fn perf_latency_percentiles_match_reference() {
    let clock = FakeClock::default();
    // Warm-up pass: ten slow executions that must be discarded.
    let mut durations: VecDeque<u64> = std::iter::repeat_n(1_000 * MS, 10).collect();
    durations.extend((12..=21).map(|ms| ms * MS));
    let target = ScriptedSearch {
        clock: &clock,
        durations: Mutex::new(durations),
    };
    let samples = suites::measure_search(&clock, &target, &plan(10, 1)).unwrap();
    assert_eq!(samples.queries, 10);
    assert_eq!(samples.repetitions, 1);
    assert!(target.durations.lock().unwrap().is_empty());
    let metrics = stats::latency_metrics(&samples.samples_ms, "seeky-eval-v1", 100).unwrap();
    close(metrics.p50, 16.5);
    close(metrics.p95, 20.55);
    close(metrics.p99, 20.91);
    assert_eq!(
        metrics.ci95.keys().collect::<Vec<_>>(),
        vec!["p50", "p95", "p99"]
    );
}

/// SPEC-0003-R25, section 5.8 D: seed `seeky-eval-reference-v1`, 10,000
/// resamples, purpose `latency-bootstrap` gives a p95 upper CI of 21.0 ms.
#[test]
fn perf_bootstrap_ci_matches_fixed_seed_reference() {
    let samples: Vec<f64> = (12..=21).map(f64::from).collect();
    let metrics =
        stats::latency_metrics(&samples, "seeky-eval-reference-v1", stats::RESAMPLES).unwrap();
    close(metrics.p95, 20.55);
    close(metrics.ci95["p95"][1], 21.0);
    for [low, high] in metrics.ci95.values() {
        assert!(low <= high && *low >= 12.0 && *high <= 21.0);
    }
    let again =
        stats::latency_metrics(&samples, "seeky-eval-reference-v1", stats::RESAMPLES).unwrap();
    assert_eq!(metrics.ci95, again.ci95, "fixed seed must reproduce");
}

/// SPEC-0003-R25, R28: below 1,000 executions and 30 repetitions a value is
/// never budget-eligible.
#[test]
fn undersampled_perf_is_marked_not_budget_eligible() {
    assert!(budget::sample_criteria_met(1_000, 1));
    assert!(budget::sample_criteria_met(10, 30));
    assert!(!budget::sample_criteria_met(999, 29));

    let mut eligibility = Eligibility::new(Tier::T1, &quiet(), false);
    assert!(eligibility.qualifies());
    eligibility.check_samples("search single warm_idle", 20, 2);
    assert!(!eligibility.qualifies());
    assert!(eligibility.reasons()[0].contains("undersampled"));
}

// --- R26 -------------------------------------------------------------------

/// SPEC-0003-R26: batch-1 embedding latency (warm-up discarded) and
/// files/s, MB/s, passages/s are present and computed from one timed run.
#[test]
fn perf_indexing_and_embedding_metrics_are_present() {
    let mut durations: VecDeque<u64> = std::iter::repeat_n(50 * MS, 4).collect();
    durations.extend([2, 4, 6, 8, 10, 12, 14, 16].map(|ms| ms * MS));
    let target = ScriptedEmbedding {
        durations: Mutex::new(durations),
        available: true,
    };
    let samples = suites::measure_embedding(&target, &plan(4, 2))
        .unwrap()
        .expect("embedding available");
    assert_eq!(samples.queries, 8);
    assert_eq!(
        samples.samples_ms,
        vec![2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0]
    );

    let unavailable = ScriptedEmbedding {
        durations: Mutex::new(VecDeque::new()),
        available: false,
    };
    assert!(
        suites::measure_embedding(&unavailable, &plan(4, 2))
            .unwrap()
            .is_none()
    );

    let indexing = suites::indexing_throughput(10, 5_000_000, 100, 2_000 * MS, "cpu").unwrap();
    close(indexing.files_per_s, 5.0);
    close(indexing.extract_mb_per_s, 2.5);
    close(indexing.passages_per_s, 50.0);
    assert_eq!(indexing.provider, "cpu");
    assert_eq!(indexing.samples, 1);
    assert!(suites::indexing_throughput(1, 1, 1, 0, "cpu").is_err());
}

/// SPEC-0003-R26: time-to-searchable stops at the first successful search.
#[test]
fn time_to_searchable_uses_first_matching_result() {
    let clock = SteppingClock {
        now: AtomicU64::new(0),
        step: 5 * MS,
    };
    let mut results = VecDeque::from([false, false, true, true]);
    let mut polls = 0;
    let mut poll = || {
        polls += 1;
        // Each poll costs one clock step before its result is known.
        clock.now_ns();
        Ok(results.pop_front().unwrap())
    };
    let value = suites::time_to_searchable(&clock, 0, 10, &mut poll).unwrap();
    // Three polls (15 ms) plus the final timestamp read (5 ms).
    assert_eq!(value, Some(20.0));
    assert_eq!(polls, 3, "polling must stop at the first match");

    let mut never = || Ok(false);
    assert_eq!(
        suites::time_to_searchable(&clock, 0, 3, &mut never).unwrap(),
        None
    );
    let mut failing = || Err(Failure::engine("search failed"));
    assert!(suites::time_to_searchable(&clock, 0, 3, &mut failing).is_err());
}

/// SPEC-0003-R26, section 5.8 D: idle p95 20 ms and indexing p95 30 ms give
/// S5 = 1.5; an idle p95 of 0 is an error, never a ratio.
#[test]
fn interference_ratio_matches_hand_calculation() {
    let idle = vec![20.0; 40];
    let indexing = vec![30.0; 40];
    let ratio = stats::interference_ratio(&idle, &indexing, "seeky-eval-v1", 200).unwrap();
    close(ratio.value, 1.5);
    close(ratio.idle_p95_ms, 20.0);
    close(ratio.indexing_p95_ms, 30.0);
    close(ratio.ci95[0], 1.5);
    close(ratio.ci95[1], 1.5);
    assert!(stats::interference_ratio(&[0.0; 5], &[1.0; 5], "seeky-eval-v1", 10).is_err());

    // Samples only count while indexing is active.
    let clock = FakeClock::default();
    let target = ScriptedSearch {
        clock: &clock,
        durations: Mutex::new(std::iter::repeat_n(MS, 100).collect()),
    };
    let remaining = AtomicU64::new(7);
    let active = || remaining.fetch_sub(1, Ordering::SeqCst) > 0;
    let samples = suites::measure_search_while(&clock, &target, &plan(4, 10), &active).unwrap();
    assert!(samples.queries <= 4);
    assert!(samples.samples_ms.iter().all(|value| *value == 1.0));
}

// --- R27 -------------------------------------------------------------------

/// SPEC-0003-R27, sections 4.10 and 5.8 D (v0.2): 2.5 GB over 1 M passages is
/// 2,500,000 bytes per 1k passages. RSS peak is the maximum sample and idle the
/// last idle sample.
#[test]
fn perf_resources_match_reference_fixture() {
    close(
        resources::disk_bytes_per_1k_passages(2_500_000_000, 1_000_000).unwrap(),
        2_500_000.0,
    );
    assert!(resources::disk_bytes_per_1k_passages(1, 0).is_err());

    let sampler = ScriptedRss(Mutex::new(VecDeque::from([
        Some(210),
        Some(207),
        Some(205),
    ])));
    let idle = resources::idle_rss(&sampler, 3, Duration::ZERO);
    assert_eq!(idle, Some(205));
    assert_eq!(resources::peak_rss(&[100, 300, 200], idle), Some(300));
    assert_eq!(resources::peak_rss(&[], None), None);
    let none = ScriptedRss(Mutex::new(VecDeque::from([None, None])));
    assert_eq!(resources::idle_rss(&none, 2, Duration::ZERO), None);

    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("seeky.db"), vec![0_u8; 100]).unwrap();
    std::fs::create_dir(dir.path().join("vectors")).unwrap();
    std::fs::write(dir.path().join("vectors").join("v.bin"), vec![0_u8; 200]).unwrap();
    std::fs::write(dir.path().join("index.metadata.json"), vec![0_u8; 50]).unwrap();
    assert_eq!(
        resources::directory_bytes(dir.path(), &["index.metadata.json"]).unwrap(),
        300
    );
}

/// SPEC-0003-R27: startup is a fresh process (`cold`), with an uncontrolled
/// OS cache, timed to the first Instant and semantic capability lines.
#[test]
fn perf_startup_marks_cold_and_scope() {
    let clock = SteppingClock {
        now: AtomicU64::new(0),
        step: 10 * MS,
    };
    let mut lexical = Cursor::new("noise\ninstant-capable\nsemantic-unavailable\n");
    let (instant, semantic) = startup::read_probe_lines(&clock, 0, &mut lexical).unwrap();
    assert_eq!(instant, 20.0);
    assert_eq!(semantic, None);
    let metrics = startup::startup_metrics(instant, semantic);
    assert!(metrics.cold);
    assert_eq!(metrics.os_cache, "uncontrolled");

    let mut both = Cursor::new("instant-capable\nsemantic-capable\n");
    let (instant, semantic) = startup::read_probe_lines(&clock, 0, &mut both).unwrap();
    assert!(semantic.unwrap() > instant);

    let mut broken = Cursor::new("semantic-capable\n");
    assert!(startup::read_probe_lines(&clock, 0, &mut broken).is_err());
    assert_eq!(resources::SCOPE, "engine_headless");
    assert_eq!(resources::SAMPLING_INTERVAL_MS, 50);
}

/// SPEC-0003-R27: a hermetic fixture run reproduces the full artifact shape;
/// unavailable values are null with a warning, never zero.
#[test]
fn unavailable_optional_metrics_are_explicit() {
    let fixture = support::build();
    let output = fixture_perf_run(&fixture, &["--repetitions", "2"]);
    let report = read_json(&output.join("results.json"));
    let performance = &report["performance"];
    let warnings: Vec<&str> = performance["warnings"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| value.as_str().unwrap())
        .collect();
    let warned = |prefix: &str| warnings.iter().any(|warning| warning.starts_with(prefix));

    for field in ["distribution", "ocr", "visual", "energy"] {
        assert!(performance[field].is_null(), "{field}");
        assert!(warned(&format!("{field} unavailable")), "{field}");
    }
    // The fixture engine is lexical-only.
    assert!(performance["query_embedding"].is_null());
    assert!(warned("query_embedding unavailable"));
    assert_eq!(
        performance["time_to_searchable"]["semantic_ms"]["samples"],
        0
    );
    assert!(warned("time_to_searchable.semantic_ms unavailable"));
    assert!(performance["resources"]["page_cache_bytes"].is_null());
    assert!(warned("resources.page_cache_bytes unavailable"));
    if performance["resources"]["idle_rss_bytes"].is_null() {
        assert!(warned("resources.idle_rss_bytes unavailable"));
    } else {
        assert!(performance["resources"]["idle_rss_bytes"].as_u64().unwrap() > 0);
    }

    // Measured sections are present with sample counts.
    let search = performance["search"].as_array().unwrap();
    assert_eq!(search[0]["stage"], "single");
    assert_eq!(search[0]["condition"], "warm_idle");
    assert_eq!(search[0]["repetitions"], 2);
    assert!(search[0]["latency_ms"]["ci95"]["p95"].is_array());
    assert!(performance["indexing"]["files_per_s"].as_f64().unwrap() > 0.0);
    assert_eq!(
        performance["time_to_searchable"]["lexical_ms"]["samples"],
        5
    );
    assert!(performance["resources"]["index_bytes"].as_u64().unwrap() > 0);
    assert_eq!(performance["resources"]["scope"], "engine_headless");
    assert_eq!(performance["resources"]["sampling_interval_ms"], 50);
    assert_eq!(performance["startup"]["cold"], true);
    assert_eq!(performance["startup"]["os_cache"], "uncontrolled");
    assert!(performance["startup"]["semantic_capable_ms"].is_null());
    assert!(
        !performance["interference_ratio"].is_null() || warned("interference_ratio unavailable")
    );

    // Not budget-eligible: T2 and only two repetitions.
    assert_eq!(performance["qualifies_for_budget"], false);
    assert!(warned("not budget-eligible: tier T2"));
    assert!(warned(
        "not budget-eligible: search single warm_idle undersampled"
    ));
    assert_eq!(report["report"]["work_package"], "WP-1.6");

    // Artifacts go through the atomic writer and carry no absolute path.
    for artifact in [
        "results.json",
        "summary.md",
        "environment.json",
        "config.snapshot.json",
        "checksums.sha256",
    ] {
        assert!(output.join(artifact).is_file(), "{artifact}");
    }
    let environment = read_json(&output.join("environment.json"));
    assert_eq!(environment["tier"], "T2");
    assert_eq!(environment["process"]["scope"], "engine_headless");
    assert!(environment["quiet_window"]["verified"].is_boolean());
    let text = std::fs::read_to_string(output.join("results.json")).unwrap();
    assert!(!text.contains(fixture.root.to_str().unwrap()));
    assert!(!text.contains(&fixture.root.to_str().unwrap().replace('\\', "/")));
}

// --- R28 -------------------------------------------------------------------

/// SPEC-0003-R28: a tier/emulation declaration that conflicts with the
/// captured host is rejected with a usage error.
#[test]
fn perf_rejects_tier_emulation_conflict() {
    let gib = 1024 * 1024 * 1024;
    let mut pinned = host();
    pinned.process_affinity = Some((0..8).collect());
    budget::validate_tier(&emulated((0..8).collect(), 16 * gib), &pinned).unwrap();

    let conflicts = [
        // CPU that does not exist.
        (emulated(vec![0, 25], 16 * gib), pinned.clone()),
        // Cap above installed memory.
        (emulated((0..8).collect(), 128 * gib), pinned.clone()),
        // Declared pinning that the process does not have.
        (emulated((0..8).collect(), 16 * gib), host()),
        // Affinity unknown: cannot verify emulation.
        (
            emulated((0..8).collect(), 16 * gib),
            HostFacts {
                process_affinity: None,
                ..host()
            },
        ),
        // Emulation flags on a non-emulated tier.
        (
            TierDeclaration {
                tier: Tier::T2,
                cpus: Some(vec![0]),
                memory_limit_bytes: None,
            },
            host(),
        ),
        // T0 on a host with AVX-512 or too many CPUs.
        (
            TierDeclaration {
                tier: Tier::T0,
                cpus: None,
                memory_limit_bytes: None,
            },
            HostFacts {
                cpu_features: vec!["avx2".into(), "avx512f".into()],
                logical_cores: Some(8),
                ..host()
            },
        ),
        (
            TierDeclaration {
                tier: Tier::T0,
                cpus: None,
                memory_limit_bytes: None,
            },
            host(),
        ),
        // T1 on a host with fewer than 8 logical CPUs.
        (
            TierDeclaration {
                tier: Tier::T1,
                cpus: None,
                memory_limit_bytes: None,
            },
            HostFacts {
                logical_cores: Some(4),
                ..host()
            },
        ),
    ];
    for (declaration, facts) in conflicts {
        let failure = budget::validate_tier(&declaration, &facts).expect_err("conflict");
        assert_eq!(failure.code, 2);
        assert!(
            failure.message.contains("TIER_CONFLICT"),
            "{}",
            failure.message
        );
    }
    let missing = TierDeclaration {
        tier: Tier::T1Emulated,
        cpus: Some(vec![0]),
        memory_limit_bytes: None,
    };
    assert_eq!(
        budget::validate_tier(&missing, &host()).unwrap_err().code,
        2
    );
}

/// SPEC-0003-R28: the environment records the tier, the emulation profile,
/// and an explicit quiet-window result with process classes only.
#[test]
fn perf_records_tier_emulation_and_quiet_window() {
    let noisy = FixedProcesses(Some(vec![
        "explorer.exe",
        "cargo.exe",
        "python3.12.exe",
        "rustc",
        "seeky-bench.exe",
        "seeky-bench.exe",
        "node.exe",
    ]));
    let window = budget::quiet_window(&noisy);
    assert!(!window.verified);
    assert_eq!(
        window.heavy_processes,
        vec!["cargo", "node", "other-benchmark", "python", "rustc"]
    );
    let calm = budget::quiet_window(&FixedProcesses(Some(vec![
        "explorer.exe",
        "seeky-bench.exe",
    ])));
    assert!(calm.verified);
    let unknown = budget::quiet_window(&FixedProcesses(None));
    assert!(!unknown.verified, "an unchecked window is never verified");

    let mut environment = seeky_bench::environment::capture("T2", None, None);
    let declaration = emulated(vec![0, 1, 2, 3], 8 * 1024 * 1024 * 1024);
    seeky_bench::perf::record_environment(&mut environment, &declaration, &host(), &window);
    assert_eq!(environment["tier"], "T1-emulated");
    assert_eq!(
        environment["emulation"]["logical_cpus"],
        serde_json::json!([0, 1, 2, 3])
    );
    assert_eq!(
        environment["emulation"]["memory_limit_bytes"],
        8_u64 * 1024 * 1024 * 1024
    );
    assert_eq!(environment["memory_bytes"], 64_u64 * 1024 * 1024 * 1024);
    assert_eq!(environment["quiet_window"]["verified"], false);
    assert_eq!(
        environment["quiet_window"]["heavy_processes"],
        serde_json::json!(["cargo", "node", "other-benchmark", "python", "rustc"])
    );
    assert_eq!(environment["process"]["scope"], "engine_headless");
    assert_eq!(environment["process"]["sampling_interval_ms"], 50);
    assert!(!environment.to_string().contains("explorer"));
}

/// SPEC-0003-R28: eligibility is explicit, with one reason per failure.
#[test]
fn perf_budget_eligibility_is_explicit() {
    let mut eligible = Eligibility::new(Tier::T1Emulated, &quiet(), false);
    eligible.check_samples("search single warm_idle", 1_000, 1);
    assert!(eligible.qualifies());
    assert!(eligible.reasons().is_empty());

    for (tier, window, synthetic, expected) in [
        (Tier::T2, quiet(), false, "tier T2"),
        (Tier::T0, quiet(), false, "tier T0"),
        (
            Tier::T1,
            QuietWindow {
                verified: false,
                heavy_processes: vec!["cargo".into()],
            },
            false,
            "quiet window",
        ),
        (Tier::T1, quiet(), true, "synthetic"),
    ] {
        let eligibility = Eligibility::new(tier, &window, synthetic);
        assert!(!eligibility.qualifies());
        assert_eq!(eligibility.reasons().len(), 1);
        assert!(eligibility.reasons()[0].contains(expected), "{expected}");
    }
}

// --- flags -----------------------------------------------------------------

/// SPEC-0003-R15, R25, R28: malformed perf flags fail with exit code 2 before
/// any engine work.
#[test]
fn malformed_perf_flags_fail_before_engine_open() {
    let fixture = support::build();
    let paths = BenchPaths::at(fixture.root.clone());
    let data = fixture.work.join("never-created");
    let output = fixture.work.join("never-out");
    let config = fixture.config("default.json");
    for extra in [
        &["--repetitions", "0"][..],
        &["--repetitions", "abc"],
        &["--queries", "0"],
        &["--queries", "1001"],
        &["--stage", "fast"],
        &["--suite", "search,bogus"],
        &["--tier", "T3"],
        &["--tier", "T1-emulated"],
        &[
            "--tier",
            "T1-emulated",
            "--cpus",
            "0,x",
            "--memory-limit",
            "1",
        ],
        &[
            "--tier",
            "T1-emulated",
            "--cpus",
            "0",
            "--memory-limit",
            "-1",
        ],
        &["--cpus", "0,1"],
        &["--memory-limit", "1024"],
    ] {
        let mut args = vec![
            "perf",
            "--corpus",
            "tiny",
            "--config",
            config.to_str().unwrap(),
            "--data-dir",
            data.to_str().unwrap(),
            "--output",
            output.to_str().unwrap(),
        ];
        args.extend_from_slice(extra);
        let failure = run_with_paths(
            &paths,
            args.iter().map(|value| (*value).to_string()).collect(),
        )
        .expect_err("malformed flags");
        assert_eq!(failure.code, 2, "{extra:?}: {}", failure.message);
        assert!(!data.exists(), "{extra:?} started engine work");
        assert!(!output.exists(), "{extra:?} wrote artifacts");
    }
}

// --- helpers ---------------------------------------------------------------

fn read_json(path: &Path) -> Value {
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn fixture_perf_run(fixture: &support::Fixture, extra: &[&str]) -> std::path::PathBuf {
    let paths = BenchPaths::at(fixture.root.clone());
    let data = fixture.data_dir("perf");
    let config = fixture.config("default.json");
    let index_output = fixture.output("perf-index");
    run_with_paths(
        &paths,
        [
            "index",
            "--corpus",
            "tiny",
            "--data-dir",
            data.to_str().unwrap(),
            "--config",
            config.to_str().unwrap(),
            "--output",
            index_output.to_str().unwrap(),
        ]
        .iter()
        .map(|value| (*value).to_string())
        .collect(),
    )
    .expect("index");
    let output = fixture.output("perf");
    let mut args = vec![
        "perf",
        "--corpus",
        "tiny",
        "--config",
        config.to_str().unwrap(),
        "--data-dir",
        data.to_str().unwrap(),
        "--output",
        output.to_str().unwrap(),
    ];
    args.extend_from_slice(extra);
    run_with_paths(
        &paths,
        args.iter().map(|value| (*value).to_string()).collect(),
    )
    .expect("perf");
    output
}
