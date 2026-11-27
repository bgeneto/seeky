//! SPEC-0003 R21 acceptance tests: test confirmation and exposure.

#![allow(clippy::unwrap_used)]

mod support;

use seeky_bench::corpus::{self, BenchPaths, CorpusKind};
use seeky_bench::engine::EngineAdapter;
use seeky_bench::environment::{self, EvaluationSettings};
use seeky_bench::gate;
use seeky_bench::{DEFAULT_LIMIT, DEFAULT_METRICS, DEFAULT_SEED, Failure, run_with_paths};
use seeky_eval::{EvaluationConfiguration, Split};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};

fn args(values: &[&str]) -> Vec<String> {
    values.iter().map(|value| (*value).to_string()).collect()
}

fn run(paths: &BenchPaths, values: &[&str]) -> Result<(), Failure> {
    run_with_paths(paths, args(values))
}

fn read_json(path: &Path) -> Value {
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

struct Prepared {
    paths: BenchPaths,
    data: PathBuf,
    config_path: PathBuf,
    config_hash: String,
    confirmation: PathBuf,
    output: PathBuf,
}

fn settings() -> EvaluationSettings {
    EvaluationSettings {
        split: Split::Test,
        configuration: EvaluationConfiguration::Default,
        limit: DEFAULT_LIMIT,
        metrics: DEFAULT_METRICS.iter().map(|id| (*id).to_string()).collect(),
        seed: DEFAULT_SEED.to_string(),
    }
}

fn prepare(fixture: &support::Fixture) -> Prepared {
    let paths = BenchPaths::at(fixture.root.clone());
    let data = fixture.data_dir("test");
    run(
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
            fixture.output("test-index").to_str().unwrap(),
        ],
    )
    .expect("index");

    let corpus = corpus::resolve(&paths, "tiny", false).unwrap();
    let dataset =
        corpus::load_dataset(&corpus, Split::Test, EvaluationConfiguration::Default, None).unwrap();
    let config_path = fixture.config("default.json");
    let config = environment::load_run_config(&config_path).unwrap();
    let adapter = EngineAdapter::open(&data, &config).expect("open");
    let snapshot = adapter.engine().config_snapshot().unwrap().canonical_json();
    adapter.shutdown().unwrap();
    let config_hash = environment::combined_config(&snapshot, &config, &settings())
        .unwrap()
        .sha256();

    let confirmation = fixture.work.join("confirmation.json");
    support::write(
        &confirmation,
        &format!(
            "{}\n",
            serde_json::to_string_pretty(&json!({
                "schema_version": 1,
                "confirmation_id": "confirmation-1",
                "created_at": "2026-11-27T12:00:00Z",
                "selected_on": "dev",
                "dev_comparison_sha256": "a".repeat(64),
                "dataset": {
                    "id": dataset.id,
                    "corpus_hash": dataset.corpus_hash,
                    "judgment_set_id": dataset.judgment_set_id,
                    "judgment_set_hash": dataset.judgment_set_hash,
                },
                "split": "test",
                "systems": [{
                    "system_id": "baseline",
                    "config_path": "bench/configs/default.json",
                    "config_hash": config_hash,
                    "role": "baseline",
                }],
                "gates": ["Q1", "Q2"],
                "evaluation": {
                    "limit": DEFAULT_LIMIT,
                    "metrics": DEFAULT_METRICS,
                    "seed": DEFAULT_SEED,
                },
            }))
            .unwrap()
        ),
    );

    Prepared {
        paths,
        data,
        config_path,
        config_hash,
        confirmation,
        output: fixture.work.join("test-out"),
    }
}

fn test_eval(
    fixture: &support::Fixture,
    prepared: &Prepared,
    confirmation: &Path,
) -> Result<(), Failure> {
    run(
        &prepared.paths,
        &[
            "eval",
            "--corpus",
            "tiny",
            "--split",
            "test",
            "--purpose",
            "confirm",
            "--config",
            fixture.config("default.json").to_str().unwrap(),
            "--data-dir",
            prepared.data.to_str().unwrap(),
            "--output",
            prepared.output.to_str().unwrap(),
            "--confirmation",
            confirmation.to_str().unwrap(),
        ],
    )
}

/// SPEC-0003-R21
#[test]
fn test_eval_requires_confirmation_and_clean_tree() {
    let fixture = support::build();
    let prepared = prepare(&fixture);
    let failure = run(
        &prepared.paths,
        &[
            "eval",
            "--corpus",
            "tiny",
            "--split",
            "test",
            "--purpose",
            "confirm",
            "--config",
            fixture.config("default.json").to_str().unwrap(),
            "--data-dir",
            prepared.data.to_str().unwrap(),
            "--output",
            prepared.output.to_str().unwrap(),
        ],
    )
    .expect_err("missing confirmation");
    assert_eq!(failure.code, 2);

    // A dirty tree fails before any engine work.
    support::write(&fixture.root.join("untracked.txt"), "dirty\n");
    let failure = test_eval(&fixture, &prepared, &prepared.confirmation).expect_err("dirty tree");
    assert_eq!(failure.code, 3);
    assert!(
        failure.message.contains("working tree is dirty"),
        "{}",
        failure.message
    );
}

/// SPEC-0003-R21
#[test]
fn test_exposure_is_written_before_first_query() {
    let fixture = support::build();
    let prepared = prepare(&fixture);
    let paths = prepared.paths.clone();
    let corpus = corpus::resolve(&paths, "tiny", false).unwrap();
    let dataset =
        corpus::load_dataset(&corpus, Split::Test, EvaluationConfiguration::Default, None).unwrap();
    let started = gate::begin_test_run(
        &paths,
        &corpus,
        &dataset,
        &prepared.confirmation,
        &prepared.config_path,
        &prepared.config_hash,
        &settings(),
        &prepared.output,
    )
    .expect("begin exposure");
    let exposure = read_json(&prepared.output.join("exposure.json"));
    assert_eq!(exposure["state"], "started");
    assert_eq!(exposure["confirmation_id"], "confirmation-1");
    let ledger = std::fs::read_to_string(fixture.root.join("bench/exposures/tiny.jsonl")).unwrap();
    assert_eq!(ledger.lines().count(), 1);
    assert!(ledger.contains("\"state\":\"started\""));

    let completed = gate::complete_test_run(&paths, &started, &prepared.config_hash)
        .expect("complete exposure");
    assert_eq!(completed["state"], "completed");
    let exposure = read_json(&prepared.output.join("exposure.json"));
    assert_eq!(exposure["state"], "completed");
    let ledger = std::fs::read_to_string(fixture.root.join("bench/exposures/tiny.jsonl")).unwrap();
    assert_eq!(ledger.lines().count(), 2);
}

/// SPEC-0003-R21
#[test]
fn test_rejects_new_or_modified_configs() {
    let fixture = support::build();
    let prepared = prepare(&fixture);
    let mut confirmation = read_json(&prepared.confirmation);
    confirmation["systems"][0]["config_hash"] = json!("b".repeat(64));
    let modified = fixture.work.join("modified-confirmation.json");
    support::write(
        &modified,
        &format!("{}\n", serde_json::to_string_pretty(&confirmation).unwrap()),
    );
    let failure = test_eval(&fixture, &prepared, &modified).expect_err("modified config");
    assert_eq!(failure.code, 3);
    assert!(
        failure.message.contains("not declared"),
        "{}",
        failure.message
    );
}

/// SPEC-0003-R21
#[test]
fn completed_confirmation_cannot_rerun() {
    let fixture = support::build();
    let prepared = prepare(&fixture);
    test_eval(&fixture, &prepared, &prepared.confirmation).expect("first test eval");
    let exposure = read_json(&prepared.output.join("exposure.json"));
    assert_eq!(exposure["state"], "completed");
    // The exposure ledger is committed by the operator before the next run.
    support::commit_all(&fixture, "exposure");
    let failure = test_eval(&fixture, &prepared, &prepared.confirmation).expect_err("rerun");
    assert_eq!(failure.code, 3);
    assert!(
        failure.message.contains("completed confirmation"),
        "{}",
        failure.message
    );
}

/// SPEC-0003-R21
#[test]
fn test_resume_requires_same_confirmation_and_configs() {
    let fixture = support::build();
    let prepared = prepare(&fixture);
    let corpus = corpus::resolve(&prepared.paths, "tiny", false).unwrap();
    let dataset =
        corpus::load_dataset(&corpus, Split::Test, EvaluationConfiguration::Default, None).unwrap();
    let _started = gate::begin_test_run(
        &prepared.paths,
        &corpus,
        &dataset,
        &prepared.confirmation,
        &prepared.config_path,
        &prepared.config_hash,
        &settings(),
        &prepared.output,
    )
    .expect("begin");
    let failure = gate::begin_test_run(
        &prepared.paths,
        &corpus,
        &dataset,
        &prepared.confirmation,
        &prepared.config_path,
        &prepared.config_hash,
        &settings(),
        &prepared.output,
    )
    .expect_err("already started");
    assert_eq!(failure.code, 3);
    assert!(
        failure.message.contains("already started"),
        "{}",
        failure.message
    );
}

/// SPEC-0003-R21
#[test]
fn later_confirmation_does_not_rewrite_test_exposure() {
    let fixture = support::build();
    let judgment_dir = fixture.work.join("judgment");
    support::write(
        &judgment_dir.join("judgment-set.json"),
        "{\"judgment_set_id\":\"tiny-test\",\"test_exposure\":\"not-applicable\"}\n",
    );
    let corpus = seeky_bench::corpus::Corpus {
        id: "tiny".to_string(),
        kind: CorpusKind::Beir,
        root: fixture.root.clone(),
        manifest_path: fixture.root.join("bench/datasets/tiny/manifest.json"),
        roots: Vec::new(),
        root_labels: Vec::new(),
        code_enabled: false,
        visibility: "public".to_string(),
        judgment_dir: Some(judgment_dir.clone()),
    };
    gate::mark_test_exposure(&corpus).expect("first exposure");
    let first = std::fs::read_to_string(judgment_dir.join("judgment-set.json")).unwrap();
    assert!(first.contains("\"exposed\""));
    assert!(first.contains("\"judgment_set_id\""));
    gate::mark_test_exposure(&corpus).expect("later exposure");
    let second = std::fs::read_to_string(judgment_dir.join("judgment-set.json")).unwrap();
    assert_eq!(first, second);
}

/// SPEC-0003-R21
#[test]
fn malformed_confirmation_is_rejected() {
    let fixture = support::build();
    let prepared = prepare(&fixture);
    let malformed = fixture.work.join("malformed-confirmation.json");
    support::write(&malformed, "{\"schema_version\": 1}\n");
    let failure = test_eval(&fixture, &prepared, &malformed).expect_err("malformed");
    assert_eq!(failure.code, 2);
    assert!(
        failure.message.contains("invalid confirmation"),
        "{}",
        failure.message
    );
}

/// SPEC-0003-R21 (dry validation never touches test)
#[test]
fn dev_confirmation_purpose_is_a_dry_validation() {
    let fixture = support::build();
    let prepared = prepare(&fixture);
    run(
        &prepared.paths,
        &[
            "eval",
            "--corpus",
            "tiny",
            "--split",
            "dev",
            "--purpose",
            "confirm",
            "--config",
            fixture.config("default.json").to_str().unwrap(),
            "--data-dir",
            prepared.data.to_str().unwrap(),
            "--output",
            prepared.output.to_str().unwrap(),
            "--confirmation",
            prepared.confirmation.to_str().unwrap(),
        ],
    )
    .expect("dry validation");
    assert!(!prepared.output.exists());
    assert!(!fixture.root.join("bench/exposures/tiny.jsonl").exists());
}
