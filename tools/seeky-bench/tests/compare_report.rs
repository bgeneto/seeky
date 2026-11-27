//! SPEC-0003 R19/R20 acceptance tests: compare and report.

#![allow(clippy::unwrap_used)]

mod support;

use seeky_bench::corpus::BenchPaths;
use seeky_bench::{Failure, run_with_paths};
use serde_json::Value;
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

fn write_json(path: &Path, value: &Value) {
    support::write(
        path,
        &format!("{}\n", serde_json::to_string_pretty(value).unwrap()),
    );
}

fn prepare(fixture: &support::Fixture) -> (BenchPaths, PathBuf, PathBuf) {
    let paths = BenchPaths::at(fixture.root.clone());
    let data = fixture.data_dir("compare");
    let index_out = fixture.output("compare-index");
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
            index_out.to_str().unwrap(),
        ],
    )
    .expect("index");
    let baseline = fixture.work.join("baseline");
    run(
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
            baseline.to_str().unwrap(),
        ],
    )
    .expect("eval");
    (paths, data, baseline)
}

fn mutate(input: &Path, output: &Path, update: impl FnOnce(&mut Value)) {
    let mut value = read_json(input);
    update(&mut value);
    write_json(output, &value);
}

/// SPEC-0003-R19
#[test]
fn compare_writes_paired_statistics() {
    let fixture = support::build();
    let (paths, _data, baseline) = prepare(&fixture);
    let candidate = fixture.work.join("candidate");
    mutate(
        &baseline.join("results.json"),
        &candidate.join("results.json"),
        |value| {
            for row in value["quality"]["per_query"].as_array_mut().unwrap() {
                if let Some(metric) = row["metrics"]["ndcg_10"].as_f64() {
                    row["metrics"]["ndcg_10"] = serde_json::json!(metric - 0.1);
                }
            }
            if let Some(metric) = value["quality"]["macro"]["ndcg_10"].as_f64() {
                value["quality"]["macro"]["ndcg_10"] = serde_json::json!(metric - 0.1);
            }
            value["system"]["system_id"] = serde_json::json!("candidate");
        },
    );
    let output = fixture.work.join("compare-out");
    run(
        &paths,
        &[
            "compare",
            "--baseline",
            baseline.join("results.json").to_str().unwrap(),
            "--candidate",
            candidate.join("results.json").to_str().unwrap(),
            "--output",
            output.to_str().unwrap(),
        ],
    )
    .expect("compare");
    let report = read_json(&output.join("results.json"));
    assert_eq!(report["kind"], "comparison");
    let comparisons = report["comparisons"].as_array().unwrap();
    assert_eq!(comparisons.len(), 1);
    let paired = comparisons[0]["metrics"]["ndcg_10"].as_object().unwrap();
    let delta = paired["delta"].as_f64().unwrap();
    assert!((delta + 0.1).abs() < 1e-9, "delta={delta}");
    assert!(paired["p_value"].as_f64().is_some());
    assert_eq!(report["comparisons"][0]["paired_queries"], 4);
    assert!(output.join("summary.md").is_file());
    assert!(output.join("checksums.sha256").is_file());
}

/// SPEC-0003-R19
#[test]
fn compare_requires_compatible_runs() {
    let fixture = support::build();
    let (paths, _data, baseline) = prepare(&fixture);
    let candidate = fixture.work.join("incompatible");
    mutate(
        &baseline.join("results.json"),
        &candidate.join("results.json"),
        |value| {
            value["dataset"]["id"] = serde_json::json!("other");
        },
    );
    let failure = run(
        &paths,
        &[
            "compare",
            "--baseline",
            baseline.join("results.json").to_str().unwrap(),
            "--candidate",
            candidate.join("results.json").to_str().unwrap(),
            "--output",
            fixture.work.join("incompatible-out").to_str().unwrap(),
        ],
    )
    .expect_err("incompatible runs");
    assert_eq!(failure.code, 5);
    assert!(
        failure.message.contains("STATS_INPUT_MISMATCH"),
        "{}",
        failure.message
    );
}

/// SPEC-0003-R19
#[test]
fn compare_never_opens_engine() {
    let fixture = support::build();
    let (paths, data, baseline) = prepare(&fixture);
    std::fs::remove_dir_all(&data).expect("remove index");
    let candidate = fixture.work.join("candidate");
    mutate(
        &baseline.join("results.json"),
        &candidate.join("results.json"),
        |value| {
            value["system"]["system_id"] = serde_json::json!("candidate");
        },
    );
    let output = fixture.work.join("compare-no-engine");
    run(
        &paths,
        &[
            "compare",
            "--baseline",
            baseline.join("results.json").to_str().unwrap(),
            "--candidate",
            candidate.join("results.json").to_str().unwrap(),
            "--output",
            output.to_str().unwrap(),
        ],
    )
    .expect("compare without an engine");
    assert!(output.join("results.json").is_file());
}

/// SPEC-0003-R20
#[test]
fn report_recomputes_nothing() {
    let fixture = support::build();
    let (_paths, _data, baseline) = prepare(&fixture);
    let tampered = fixture.work.join("tampered.json");
    mutate(&baseline.join("results.json"), &tampered, |value| {
        value["quality"]["macro"]["ndcg_10"] = serde_json::json!(0.424242);
    });
    let before = std::fs::read_to_string(&tampered).unwrap();
    let report: seeky_eval::Report = serde_json::from_str(&before).unwrap();
    let expected = seeky_eval::render_markdown(&report);

    let paths = BenchPaths::at(fixture.root.clone());
    let summary = fixture.work.join("recomputed.md");
    run(
        &paths,
        &[
            "report",
            "--results",
            tampered.to_str().unwrap(),
            "--output",
            summary.to_str().unwrap(),
        ],
    )
    .expect("report");
    assert_eq!(std::fs::read_to_string(&summary).unwrap(), expected);
    assert_eq!(std::fs::read_to_string(&tampered).unwrap(), before);
}

/// SPEC-0003-R19
#[test]
fn compare_gate_fails_closed_and_still_writes_the_report() {
    let fixture = support::build();
    let (paths, _data, baseline) = prepare(&fixture);
    let candidate = fixture.work.join("gate-candidate");
    mutate(
        &baseline.join("results.json"),
        &candidate.join("results.json"),
        |value| {
            value["system"]["system_id"] = serde_json::json!("candidate");
        },
    );
    let output = fixture.work.join("gate-out");
    let baseline_commit = "0".repeat(40);
    let failure = run(
        &paths,
        &[
            "compare",
            "--baseline",
            baseline.join("results.json").to_str().unwrap(),
            "--candidate",
            candidate.join("results.json").to_str().unwrap(),
            "--repeat-candidate",
            candidate.join("results.json").to_str().unwrap(),
            "--gate",
            "wp1.8",
            "--baseline-commit",
            baseline_commit.as_str(),
            "--output",
            output.to_str().unwrap(),
        ],
    )
    .expect_err("gate fails closed");
    assert_eq!(failure.code, 6);
    let report = read_json(&output.join("results.json"));
    assert_eq!(report["gates"][0]["id"], "WP-1.8");
    assert_eq!(report["gates"][0]["status"], "fail");
}

/// SPEC-0003-R20
#[test]
fn report_requires_existing_results() {
    let fixture = support::build();
    let paths = BenchPaths::at(fixture.root.clone());
    let failure = run(
        &paths,
        &[
            "report",
            "--results",
            fixture.work.join("missing.json").to_str().unwrap(),
            "--output",
            fixture.work.join("missing.md").to_str().unwrap(),
        ],
    )
    .expect_err("missing results");
    assert_eq!(failure.code, 5);
}

/// SPEC-0003-R20
#[test]
fn report_overwrite_requires_flag() {
    let fixture = support::build();
    let (_paths, _data, baseline) = prepare(&fixture);
    let paths = BenchPaths::at(fixture.root.clone());
    let summary = fixture.work.join("existing.md");
    support::write(&summary, "different content\n");
    let failure = run(
        &paths,
        &[
            "report",
            "--results",
            baseline.join("results.json").to_str().unwrap(),
            "--output",
            summary.to_str().unwrap(),
        ],
    )
    .expect_err("existing differing report");
    assert_eq!(failure.code, 5);
    assert!(
        failure.message.contains("--overwrite"),
        "{}",
        failure.message
    );
    run(
        &paths,
        &[
            "report",
            "--results",
            baseline.join("results.json").to_str().unwrap(),
            "--output",
            summary.to_str().unwrap(),
            "--overwrite",
        ],
    )
    .expect("overwrite");
    assert_ne!(
        std::fs::read_to_string(&summary).unwrap(),
        "different content\n"
    );
}
