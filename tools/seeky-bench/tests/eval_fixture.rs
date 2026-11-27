//! SPEC-0003 acceptance tests for `index`, `eval`, and R16/R17/R18/R32.

#![allow(clippy::unwrap_used)]

mod support;

use seeky_bench::corpus::BenchPaths;
use seeky_bench::engine::EngineAdapter;
use seeky_bench::environment::{self, EvaluationSettings, RunConfig};
use seeky_bench::{DEFAULT_LIMIT, DEFAULT_METRICS, DEFAULT_SEED, Failure, run_with_paths};
use serde_json::Value;
use std::path::Path;

fn args(values: &[&str]) -> Vec<String> {
    values.iter().map(|value| (*value).to_string()).collect()
}

fn run(paths: &BenchPaths, values: &[&str]) -> Result<(), Failure> {
    run_with_paths(paths, args(values))
}

fn index(fixture: &support::Fixture, data_dir: &Path, config: &Path, output: &Path) {
    let paths = BenchPaths::at(fixture.root.clone());
    run(
        &paths,
        &[
            "index",
            "--corpus",
            "tiny",
            "--data-dir",
            data_dir.to_str().unwrap(),
            "--config",
            config.to_str().unwrap(),
            "--output",
            output.to_str().unwrap(),
        ],
    )
    .expect("index");
}

fn eval(
    fixture: &support::Fixture,
    data_dir: &Path,
    config: &Path,
    output: &Path,
    limit: Option<usize>,
) {
    let paths = BenchPaths::at(fixture.root.clone());
    let limit = limit.map(|value| value.to_string());
    let mut values = vec![
        "eval",
        "--corpus",
        "tiny",
        "--split",
        "dev",
        "--config",
        config.to_str().unwrap(),
        "--data-dir",
        data_dir.to_str().unwrap(),
        "--output",
        output.to_str().unwrap(),
    ];
    if let Some(limit) = limit.as_deref() {
        values.push("--limit");
        values.push(limit);
    }
    run(&paths, &values).expect("eval");
}

fn read_json(path: &Path) -> Value {
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

/// SPEC-0003-R17
#[test]
fn index_writes_metadata_and_disables_watching() {
    let fixture = support::build();
    let data = fixture.data_dir("index");
    let output = fixture.output("index");
    index(&fixture, &data, &fixture.config("default.json"), &output);

    let sidecar = read_json(&data.join("index.metadata.json"));
    assert_eq!(sidecar["schema_version"], 1);
    assert_eq!(sidecar["corpus_id"], "tiny");
    assert_eq!(sidecar["code_enabled"], false);
    assert_eq!(sidecar["roots"], serde_json::json!(["data/files"]));
    assert!(
        sidecar["corpus_hash"].as_str().unwrap().len() == 64,
        "{sidecar}"
    );
    assert!(sidecar["config_hash"].as_str().unwrap().len() == 64);
    assert!(sidecar["counts"]["documents"].as_i64().unwrap() >= 5);
    assert!(output.join("index.json").is_file());

    let config = environment::load_run_config(&fixture.config("default.json")).unwrap();
    let adapter = EngineAdapter::open(&data, &config).expect("open");
    let roots = adapter.engine().list_roots().unwrap();
    assert!(!roots.is_empty());
    assert!(roots.iter().all(|root| !root.watch_enabled));
    adapter.shutdown().unwrap();
}

/// SPEC-0003-R17
#[test]
fn index_reuses_only_compatible_data_directory() {
    let fixture = support::build();
    let data = fixture.data_dir("reuse");
    let output = fixture.output("reuse");
    index(&fixture, &data, &fixture.config("default.json"), &output);

    let paths = BenchPaths::at(fixture.root.clone());
    // Without --fresh a nonempty data directory is refused.
    let failure = run(
        &paths,
        &[
            "index",
            "--corpus",
            "tiny",
            "--data-dir",
            data.to_str().unwrap(),
            "--config",
            fixture.config("default.json").to_str().unwrap(),
            "--output",
            output.to_str().unwrap(),
        ],
    )
    .expect_err("reuse without --fresh");
    assert_eq!(failure.code, 2);
    assert!(failure.message.contains("--fresh"), "{}", failure.message);

    // With --fresh but incompatible metadata the reuse is refused.
    let sidecar_path = data.join("index.metadata.json");
    let mut sidecar = read_json(&sidecar_path);
    sidecar["config_hash"] = serde_json::json!("0".repeat(64));
    std::fs::write(&sidecar_path, serde_json::to_string(&sidecar).unwrap()).unwrap();
    let failure = run(
        &paths,
        &[
            "index",
            "--corpus",
            "tiny",
            "--data-dir",
            data.to_str().unwrap(),
            "--config",
            fixture.config("default.json").to_str().unwrap(),
            "--output",
            output.to_str().unwrap(),
            "--fresh",
        ],
    )
    .expect_err("incompatible reuse");
    assert_eq!(failure.code, 4);
    assert!(
        failure.message.contains("INDEX_INCOMPATIBLE"),
        "{}",
        failure.message
    );
}

/// SPEC-0003-R17
#[test]
fn eval_rejects_mismatched_index_metadata() {
    let fixture = support::build();
    let data = fixture.data_dir("mismatch");
    let output = fixture.output("mismatch-index");
    index(&fixture, &data, &fixture.config("default.json"), &output);

    let paths = BenchPaths::at(fixture.root.clone());
    let failure = run(
        &paths,
        &[
            "eval",
            "--corpus",
            "tiny",
            "--split",
            "dev",
            "--config",
            fixture.config("npu.json").to_str().unwrap(),
            "--data-dir",
            data.to_str().unwrap(),
            "--output",
            fixture.output("mismatch-eval").to_str().unwrap(),
        ],
    )
    .expect_err("mismatched config");
    assert_eq!(failure.code, 4);
    assert!(
        failure.message.contains("INDEX_INCOMPATIBLE"),
        "{}",
        failure.message
    );
}

/// SPEC-0003-R18
#[test]
fn eval_writes_complete_reproducible_artifact_set() {
    let fixture = support::build();
    let data = fixture.data_dir("repro");
    index(
        &fixture,
        &data,
        &fixture.config("default.json"),
        &fixture.output("repro-index"),
    );
    let first = fixture.output("repro-a");
    let second = fixture.output("repro-b");
    eval(
        &fixture,
        &data,
        &fixture.config("default.json"),
        &first,
        None,
    );
    eval(
        &fixture,
        &data,
        &fixture.config("default.json"),
        &second,
        None,
    );

    for name in [
        "run.trec",
        "results.json",
        "summary.md",
        "environment.json",
        "config.snapshot.json",
        "checksums.sha256",
    ] {
        assert!(first.join(name).is_file(), "missing {name}");
        assert!(second.join(name).is_file(), "missing {name}");
    }
    assert_eq!(
        std::fs::read_to_string(first.join("run.trec")).unwrap(),
        std::fs::read_to_string(second.join("run.trec")).unwrap()
    );
    assert_eq!(
        std::fs::read_to_string(first.join("config.snapshot.json")).unwrap(),
        std::fs::read_to_string(second.join("config.snapshot.json")).unwrap()
    );
    let mut left = read_json(&first.join("results.json"));
    let mut right = read_json(&second.join("results.json"));
    for value in [&mut left, &mut right] {
        let object = value.as_object_mut().unwrap();
        object.remove("run_id");
        object.remove("generated_at");
        if let Some(environment) = object.get_mut("environment") {
            environment.as_object_mut().unwrap().remove("captured_at");
        }
    }
    assert_eq!(left, right);
    let checksums = std::fs::read_to_string(first.join("checksums.sha256")).unwrap();
    assert!(checksums.contains("  run.trec\n"));
    assert!(checksums.contains("  results.json\n"));
}

/// SPEC-0003-R18
#[test]
fn eval_query_order_is_deterministic() {
    let fixture = support::build();
    let data = fixture.data_dir("order");
    index(
        &fixture,
        &data,
        &fixture.config("default.json"),
        &fixture.output("order-index"),
    );
    let output = fixture.output("order");
    eval(
        &fixture,
        &data,
        &fixture.config("default.json"),
        &output,
        None,
    );
    let trec = std::fs::read_to_string(output.join("run.trec")).unwrap();
    let queries: Vec<&str> = trec
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| line.split(' ').next().unwrap())
        .collect();
    let mut sorted = queries.clone();
    sorted.sort_unstable();
    assert_eq!(queries, sorted, "run.trec must follow query-ID order");
    assert!(queries.iter().all(|query| !query.is_empty()));
}

/// SPEC-0003-R18, R29
#[test]
fn eval_rejects_insufficient_result_depth() {
    let fixture = support::build();
    let data = fixture.data_dir("depth");
    index(
        &fixture,
        &data,
        &fixture.config("default.json"),
        &fixture.output("depth-index"),
    );
    let paths = BenchPaths::at(fixture.root.clone());
    let failure = run(
        &paths,
        &[
            "eval",
            "--corpus",
            "tiny",
            "--split",
            "dev",
            "--config",
            fixture.config("default.json").to_str().unwrap(),
            "--data-dir",
            data.to_str().unwrap(),
            "--output",
            fixture.output("depth").to_str().unwrap(),
            "--limit",
            "10",
        ],
    )
    .expect_err("insufficient depth");
    assert_eq!(failure.code, 5);
    assert!(
        failure.message.contains("INSUFFICIENT_DEPTH"),
        "{}",
        failure.message
    );
}

/// SPEC-0003-R16
#[test]
fn environment_capture_contains_no_user_or_private_path() {
    let fixture = support::build();
    let data = fixture.data_dir("env");
    index(
        &fixture,
        &data,
        &fixture.config("default.json"),
        &fixture.output("env-index"),
    );
    let output = fixture.output("env");
    eval(
        &fixture,
        &data,
        &fixture.config("default.json"),
        &output,
        None,
    );
    let environment = std::fs::read_to_string(output.join("environment.json")).unwrap();
    assert!(!environment.contains(&fixture.root.to_string_lossy().to_string()));
    assert!(!environment.contains(&fixture.work.to_string_lossy().to_string()));
    for name in ["d1.txt", "needle alpha", "tiny"] {
        assert!(!environment.contains(name), "environment contains {name}");
    }
    let value: Value = serde_json::from_str(&environment).unwrap();
    assert_eq!(value["schema_version"], 1);
    assert_eq!(value["process"]["scope"], "engine_headless");
    assert_eq!(value["devices"]["npu"], Value::Null);
}

/// SPEC-0003-R16
#[test]
fn semantic_changes_change_config_hash() {
    let fixture = support::build();
    let data = fixture.data_dir("config-hash");
    index(
        &fixture,
        &data,
        &fixture.config("default.json"),
        &fixture.output("config-hash-index"),
    );
    let config = environment::load_run_config(&fixture.config("default.json")).unwrap();
    let adapter = EngineAdapter::open(&data, &config).expect("open");
    let snapshot = adapter.engine().config_snapshot().unwrap().canonical_json();
    adapter.shutdown().unwrap();
    let settings = EvaluationSettings {
        split: seeky_eval::Split::Dev,
        configuration: seeky_eval::EvaluationConfiguration::Default,
        limit: DEFAULT_LIMIT,
        metrics: DEFAULT_METRICS.iter().map(|id| (*id).to_string()).collect(),
        seed: DEFAULT_SEED.to_string(),
    };
    let first = environment::combined_config(&snapshot, &config, &settings)
        .unwrap()
        .sha256();
    let changed = environment::combined_config(
        &snapshot,
        &RunConfig {
            name: "other".into(),
            backend: "cpu".into(),
            semantic: false,
        },
        &settings,
    )
    .unwrap()
    .sha256();
    assert_ne!(first, changed);
}

/// SPEC-0003-R32
#[test]
fn filters_are_applied_exactly_and_reported() {
    let fixture = support::build();
    let data = fixture.data_dir("filter");
    index(
        &fixture,
        &data,
        &fixture.config("default.json"),
        &fixture.output("filter-index"),
    );
    let output = fixture.output("filter");
    eval(
        &fixture,
        &data,
        &fixture.config("default.json"),
        &output,
        None,
    );
    let results = read_json(&output.join("results.json"));
    assert_eq!(results["quality"]["filter_mode"], "pushdown");
    let trec = std::fs::read_to_string(output.join("run.trec")).unwrap();
    let filtered: Vec<&str> = trec
        .lines()
        .filter(|line| line.starts_with("q4 "))
        .collect();
    assert!(!filtered.is_empty(), "q4 has no rows");
    for line in filtered {
        assert_eq!(line.split(' ').nth(2).unwrap(), "d4", "{line}");
    }
}

/// SPEC-0003-R32
#[test]
fn unsupported_filter_metadata_is_an_error() {
    let fixture = support::build();
    let data = fixture.data_dir("bad-filter");
    index(
        &fixture,
        &data,
        &fixture.config("default.json"),
        &fixture.output("bad-filter-index"),
    );
    support::add_dev_query(
        &fixture,
        "q5",
        "needle alpha",
        serde_json::json!({"min_size": 10}),
    );
    let paths = BenchPaths::at(fixture.root.clone());
    let failure = run(
        &paths,
        &[
            "eval",
            "--corpus",
            "tiny",
            "--split",
            "dev",
            "--config",
            fixture.config("default.json").to_str().unwrap(),
            "--data-dir",
            data.to_str().unwrap(),
            "--output",
            fixture.output("bad-filter").to_str().unwrap(),
        ],
    )
    .expect_err("unsupported filter");
    assert_eq!(failure.code, 3);
    assert!(failure.message.contains("SCHEMA"), "{}", failure.message);
    assert!(
        !failure.message.contains(fixture.root.to_str().unwrap()),
        "{}",
        failure.message
    );
}

/// SPEC-0003-R15
#[test]
fn perf_writes_a_not_budget_eligible_report() {
    let fixture = support::build();
    let data = fixture.data_dir("perf");
    index(
        &fixture,
        &data,
        &fixture.config("default.json"),
        &fixture.output("perf-index"),
    );
    let paths = BenchPaths::at(fixture.root.clone());
    let output = fixture.output("perf");
    run(
        &paths,
        &[
            "perf",
            "--corpus",
            "tiny",
            "--config",
            fixture.config("default.json").to_str().unwrap(),
            "--data-dir",
            data.to_str().unwrap(),
            "--output",
            output.to_str().unwrap(),
            "--suite",
            "resources",
        ],
    )
    .expect("perf resources suite");
    let report = read_json(&output.join("results.json"));
    assert_eq!(report["kind"], "performance");
    assert_eq!(report["performance"]["qualifies_for_budget"], false);
    assert_eq!(report["performance"]["search"], serde_json::json!([]));
    assert!(output.join("config.snapshot.json").is_file());
    assert!(output.join("checksums.sha256").is_file());
}
