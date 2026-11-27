//! SPEC-0003 R29-R31 acceptance tests: the WP-1.8 smoke gate.
//!
//! The end-to-end tests index and evaluate a synthetic, verified `sdc-smoke`
//! fixture three times (baseline, candidate, repeat) with the real lexical
//! engine, then run `compare --gate wp1.8` on copies with one targeted
//! mutation each. The invariant and property tests call the pure R31 checks.

#![allow(clippy::unwrap_used)]

mod support;

use seeky_bench::corpus::BenchPaths;
use seeky_bench::smoke_gate::{TrecRow, check_ranking, check_repeat, parse_trec};
use seeky_bench::{Failure, run_with_paths};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use support::sdc;

struct Smoke {
    fixture: support::Fixture,
    paths: BenchPaths,
    baseline: PathBuf,
    candidate: PathBuf,
    repeat: PathBuf,
    sha: String,
}

fn args(values: &[&str]) -> Vec<String> {
    values.iter().map(|value| (*value).to_string()).collect()
}

fn read_json(path: &Path) -> Value {
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn smoke() -> Smoke {
    smoke_from(sdc::build())
}

fn smoke_from(fixture: support::Fixture) -> Smoke {
    let paths = BenchPaths::at(fixture.root.clone());
    let config = fixture.root.join("bench/configs/default.json");
    let data = fixture.data_dir("smoke");
    run_with_paths(
        &paths,
        args(&[
            "index",
            "--corpus",
            "sdc-smoke",
            "--data-dir",
            data.to_str().unwrap(),
            "--config",
            config.to_str().unwrap(),
            "--output",
            fixture.output("index").to_str().unwrap(),
        ]),
    )
    .expect("index");
    let eval = |name: &str| {
        let output = fixture.work.join(name);
        run_with_paths(
            &paths,
            args(&[
                "eval",
                "--corpus",
                "sdc-smoke",
                "--split",
                "dev",
                "--config",
                config.to_str().unwrap(),
                "--data-dir",
                data.to_str().unwrap(),
                "--output",
                output.to_str().unwrap(),
            ]),
        )
        .expect("eval");
        output
    };
    let baseline = eval("baseline");
    let candidate = eval("candidate");
    let repeat = eval("repeat");
    let sha = sdc::head(&fixture);
    Smoke {
        fixture,
        paths,
        baseline,
        candidate,
        repeat,
        sha,
    }
}

impl Smoke {
    /// Copy an eval directory, applying `results` and `run` mutations.
    fn variant(
        &self,
        source: &Path,
        name: &str,
        results: impl FnOnce(&mut Value),
        run: impl FnOnce(&mut Vec<String>),
    ) -> PathBuf {
        let target = self.fixture.work.join(name);
        std::fs::create_dir_all(&target).unwrap();
        for entry in std::fs::read_dir(source).unwrap() {
            let entry = entry.unwrap();
            std::fs::copy(entry.path(), target.join(entry.file_name())).unwrap();
        }
        let mut value = read_json(&target.join("results.json"));
        results(&mut value);
        support::write(
            &target.join("results.json"),
            &format!("{}\n", serde_json::to_string_pretty(&value).unwrap()),
        );
        let mut lines: Vec<String> = std::fs::read_to_string(target.join("run.trec"))
            .unwrap()
            .lines()
            .map(str::to_string)
            .collect();
        run(&mut lines);
        let mut text = lines.join("\n");
        if !text.is_empty() {
            text.push('\n');
        }
        support::write(&target.join("run.trec"), &text);
        target
    }

    fn gate_with(
        &self,
        baseline: &Path,
        candidate: &Path,
        repeat: Option<&Path>,
        commit: Option<&str>,
        output: &str,
    ) -> (Result<(), Failure>, Value) {
        let out = self.fixture.work.join(output);
        let baseline = baseline.join("results.json");
        let candidate = candidate.join("results.json");
        let mut values = vec![
            "compare".to_string(),
            "--baseline".to_string(),
            baseline.to_str().unwrap().to_string(),
            "--candidate".to_string(),
            candidate.to_str().unwrap().to_string(),
            "--gate".to_string(),
            "wp1.8".to_string(),
            "--output".to_string(),
            out.to_str().unwrap().to_string(),
        ];
        if let Some(repeat) = repeat {
            values.push("--repeat-candidate".to_string());
            values.push(repeat.join("results.json").to_str().unwrap().to_string());
        }
        if let Some(commit) = commit {
            values.push("--baseline-commit".to_string());
            values.push(commit.to_string());
        }
        let result = run_with_paths(&self.paths, values);
        let report = read_json(&out.join("results.json"));
        assert_eq!(report["kind"], "smoke_gate");
        assert_eq!(report["gates"].as_array().unwrap().len(), 1);
        assert_eq!(report["gates"][0]["id"], "WP-1.8");
        (result, report["gates"][0].clone())
    }

    /// Run the gate on (baseline, candidate, repeat) with the fixture SHA.
    fn gate(&self, candidate: &Path, repeat: &Path, output: &str) -> (Result<(), Failure>, Value) {
        self.gate_with(
            &self.baseline,
            candidate,
            Some(repeat),
            Some(&self.sha),
            output,
        )
    }
}

fn assert_pass(outcome: &(Result<(), Failure>, Value)) {
    let (result, gate) = outcome;
    assert!(result.is_ok(), "gate failed: {}", gate["details"]);
    assert_eq!(gate["status"], "pass");
    assert_eq!(gate["observed"]["reason"], "WITHIN_THRESHOLD");
}

fn assert_fail(outcome: &(Result<(), Failure>, Value), reason: &str) {
    let (result, gate) = outcome;
    let failure = result.as_ref().expect_err("gate must fail");
    assert_eq!(failure.code, 6, "{}", failure.message);
    assert_eq!(gate["status"], "fail");
    assert_eq!(gate["observed"]["reason"], reason, "{}", gate["details"]);
    assert!(
        gate["details"].as_str().unwrap().starts_with(reason),
        "details lead with the reason: {}",
        gate["details"]
    );
}

fn set_ndcg(value: &mut Value, ndcg: f64) {
    for row in value["quality"]["per_query"].as_array_mut().unwrap() {
        row["metrics"]["ndcg_10"] = json!(ndcg);
    }
}

fn first_query_rows(lines: &[String]) -> Vec<usize> {
    let query = lines[0].split(' ').next().unwrap().to_string();
    lines
        .iter()
        .enumerate()
        .filter(|(_, line)| line.split(' ').next() == Some(query.as_str()))
        .map(|(index, _)| index)
        .collect()
}

fn set_field(line: &mut String, field: usize, value: &str) {
    let mut fields: Vec<String> = line.split(' ').map(str::to_string).collect();
    fields[field] = value.to_string();
    *line = fields.join(" ");
}

/// SPEC-0003-R29: two clean identical runs pass with the full report shape.
#[test]
fn wp18_gate_passes_on_identical_clean_runs() {
    let smoke = smoke();
    let outcome = smoke.gate(&smoke.candidate, &smoke.repeat, "gate-pass");
    assert_pass(&outcome);
    let observed = &outcome.1["observed"];
    assert_eq!(observed["queries"], 40);
    assert_eq!(observed["drop_points"], 0.0);
    assert_eq!(observed["categories"].as_object().unwrap().len(), 8);
    assert!(observed["categories"]["code_search"].is_null());
    assert_eq!(observed["language_slices"]["en"]["queries"], 40);
    for label in ["baseline", "candidate", "repeat"] {
        assert_eq!(
            observed["artifacts"][label]["run_sha256"]
                .as_str()
                .unwrap()
                .len(),
            64
        );
    }
    let report = read_json(&smoke.fixture.work.join("gate-pass/results.json"));
    assert!(report["comparisons"].as_array().unwrap().is_empty());
    assert!(smoke.fixture.work.join("gate-pass/run.trec").is_file());
}

/// SPEC-0003-R29
#[test]
fn wp18_gate_passes_at_exactly_one_point_drop() {
    let smoke = smoke();
    let baseline = smoke.variant(&smoke.baseline, "b", |v| set_ndcg(v, 0.5), |_| {});
    let candidate = smoke.variant(&smoke.candidate, "c", |v| set_ndcg(v, 0.49), |_| {});
    let repeat = smoke.variant(&smoke.repeat, "r", |v| set_ndcg(v, 0.49), |_| {});
    let outcome = smoke.gate_with(
        &baseline,
        &candidate,
        Some(&repeat),
        Some(&smoke.sha),
        "gate-exact",
    );
    assert_pass(&outcome);
    let drop = outcome.1["observed"]["drop_points"].as_f64().unwrap();
    assert!((drop - 1.0).abs() < 1e-9, "drop {drop}");
}

/// SPEC-0003-R29
#[test]
fn wp18_gate_fails_above_threshold() {
    let smoke = smoke();
    let baseline = smoke.variant(&smoke.baseline, "b", |v| set_ndcg(v, 0.5), |_| {});
    let candidate = smoke.variant(&smoke.candidate, "c", |v| set_ndcg(v, 0.4899), |_| {});
    let repeat = smoke.variant(&smoke.repeat, "r", |v| set_ndcg(v, 0.4899), |_| {});
    let outcome = smoke.gate_with(
        &baseline,
        &candidate,
        Some(&repeat),
        Some(&smoke.sha),
        "gate-above",
    );
    assert_fail(&outcome, "REGRESSION");
    let drop = outcome.1["observed"]["drop_points"].as_f64().unwrap();
    assert!(drop > 1.0 && drop < 1.02, "drop {drop}");
}

/// SPEC-0003-R29: eight non-code categories with five queries each.
#[test]
fn wp18_requires_eight_non_code_categories_and_same_config() {
    // Four queries in one category: the set cannot support the gate.
    let thin = smoke_from(sdc::build_with(
        |category| if category == 3 { 4 } else { 5 },
    ));
    let outcome = thin.gate(&thin.candidate, &thin.repeat, "gate-thin");
    assert_fail(&outcome, "CATEGORY_COVERAGE");
    assert!(
        outcome.1["details"]
            .as_str()
            .unwrap()
            .contains("cross_language")
    );

    // Same set, different configuration hash.
    let smoke = smoke();
    let other = |value: &mut Value| value["system"]["config_hash"] = json!("f".repeat(64));
    let candidate = smoke.variant(&smoke.candidate, "c", other, |_| {});
    let repeat = smoke.variant(&smoke.repeat, "r", other, |_| {});
    assert_fail(
        &smoke.gate(&candidate, &repeat, "gate-config"),
        "INPUT_MISMATCH",
    );

    // Different query membership hash.
    let members = |value: &mut Value| value["dataset"]["query_set_sha256"] = json!("e".repeat(64));
    let candidate = smoke.variant(&smoke.candidate, "c2", members, |_| {});
    let repeat = smoke.variant(&smoke.repeat, "r2", members, |_| {});
    assert_fail(
        &smoke.gate(&candidate, &repeat, "gate-members"),
        "INPUT_MISMATCH",
    );

    // Code-enabled configuration is never the gate configuration.
    let code = |value: &mut Value| value["dataset"]["configuration"] = json!("code_enabled");
    let candidate = smoke.variant(&smoke.candidate, "c3", code, |_| {});
    let repeat = smoke.variant(&smoke.repeat, "r3", code, |_| {});
    assert_fail(
        &smoke.gate(&candidate, &repeat, "gate-code-config"),
        "WRONG_DATASET",
    );
}

/// SPEC-0003-R29: OS family, architecture, and tier must match.
#[test]
fn wp18_rejects_environment_mismatch() {
    let smoke = smoke();
    for (index, (pointer, value)) in [
        ("/os/arch", "riscv64"),
        ("/os/family", "plan9"),
        ("/tier", "T0"),
    ]
    .into_iter()
    .enumerate()
    {
        let change = |report: &mut Value| {
            *report
                .pointer_mut(&format!("/environment{pointer}"))
                .unwrap() = json!(value);
        };
        let candidate = smoke.variant(&smoke.candidate, &format!("c{index}"), change, |_| {});
        let repeat = smoke.variant(&smoke.repeat, &format!("r{index}"), change, |_| {});
        assert_fail(
            &smoke.gate(&candidate, &repeat, &format!("gate-env-{index}")),
            "ENVIRONMENT_MISMATCH",
        );
    }
}

/// SPEC-0003-R30: draft, unverified, unfrozen, exposed, or absent data fails.
#[test]
fn wp18_rejects_unverified_or_draft_smoke_data() {
    let smoke = smoke();
    let fixture = &smoke.fixture;
    let original_queries =
        std::fs::read_to_string(sdc::qrels_dir(fixture).join("queries.dev.jsonl")).unwrap();
    let original_qrels =
        std::fs::read_to_string(sdc::qrels_dir(fixture).join("qrels.dev.passages.jsonl")).unwrap();
    let restore = || {
        support::write(
            &sdc::qrels_dir(fixture).join("queries.dev.jsonl"),
            &original_queries,
        );
        support::write(
            &sdc::qrels_dir(fixture).join("qrels.dev.passages.jsonl"),
            &original_qrels,
        );
        sdc::write_judgment_manifest(fixture, |_| {});
    };

    sdc::edit_jsonl(fixture, "queries.dev.jsonl", 0, |row| {
        row["provenance"]["state"] = json!("draft");
    });
    assert_fail(
        &smoke.gate(&smoke.candidate, &smoke.repeat, "gate-draft-query"),
        "UNVERIFIED_DATA",
    );
    restore();

    sdc::edit_jsonl(fixture, "queries.dev.jsonl", 3, |row| {
        row["provenance"]["verified_by"] = json!([]);
    });
    assert_fail(
        &smoke.gate(&smoke.candidate, &smoke.repeat, "gate-unverified-query"),
        "UNVERIFIED_DATA",
    );
    restore();

    // A code query is outside the default run but must still be verified.
    sdc::edit_jsonl(fixture, "queries.dev.jsonl", 42, |row| {
        assert_eq!(row["category"], "code_search");
        row["provenance"]["state"] = json!("rejected");
    });
    assert_fail(
        &smoke.gate(&smoke.candidate, &smoke.repeat, "gate-rejected-code-query"),
        "UNVERIFIED_DATA",
    );
    restore();

    sdc::edit_jsonl(fixture, "qrels.dev.passages.jsonl", 7, |row| {
        row["provenance"]["state"] = json!("draft");
    });
    assert_fail(
        &smoke.gate(&smoke.candidate, &smoke.repeat, "gate-draft-qrel"),
        "UNVERIFIED_DATA",
    );
    restore();

    sdc::write_judgment_manifest(fixture, |manifest| manifest["state"] = json!("draft"));
    assert_fail(
        &smoke.gate(&smoke.candidate, &smoke.repeat, "gate-unfrozen"),
        "NOT_FROZEN",
    );
    sdc::write_judgment_manifest(fixture, |manifest| {
        manifest["test_exposure"] = json!("unexposed");
    });
    assert_fail(
        &smoke.gate(&smoke.candidate, &smoke.repeat, "gate-exposure"),
        "NOT_FROZEN",
    );
    restore();

    // The restored set passes again: the checks above were the only change.
    assert_pass(&smoke.gate(&smoke.candidate, &smoke.repeat, "gate-restored"));

    // A changed but still verified set is a different revision than the runs.
    sdc::edit_jsonl(fixture, "queries.dev.jsonl", 0, |row| {
        row["text"] = json!("anchor notes again");
    });
    assert_fail(
        &smoke.gate(&smoke.candidate, &smoke.repeat, "gate-revision"),
        "INPUT_MISMATCH",
    );

    std::fs::remove_dir_all(sdc::qrels_dir(fixture)).unwrap();
    let outcome = smoke.gate(&smoke.candidate, &smoke.repeat, "gate-unpublished");
    assert_fail(&outcome, "SMOKE_SET_UNPUBLISHED");
    assert!(
        outcome.1["details"]
            .as_str()
            .unwrap()
            .contains("sdc-smoke-v1 not published (H6)")
    );
}

/// SPEC-0003-R30: no code_search query and no source-code document.
#[test]
fn wp18_rejects_code_results() {
    let smoke = smoke();
    let code_query = |value: &mut Value| {
        let rows = value["quality"]["per_query"].as_array_mut().unwrap();
        let mut row = rows[0].clone();
        row["query_id"] = json!("q-code-0");
        row["category"] = json!("code_search");
        rows.push(row);
    };
    let candidate = smoke.variant(&smoke.candidate, "c", code_query, |_| {});
    let repeat = smoke.variant(&smoke.repeat, "r", code_query, |_| {});
    assert_fail(
        &smoke.gate(&candidate, &repeat, "gate-code-query"),
        "CODE_RESULTS",
    );

    let code_document = |lines: &mut Vec<String>| {
        let last = first_query_rows(lines).last().copied().unwrap();
        let mut line = lines[last].clone();
        set_field(&mut line, 2, sdc::CODE_DOCUMENT);
        let rank: u32 = line.split(' ').nth(3).unwrap().parse().unwrap();
        set_field(&mut line, 3, &(rank + 1).to_string());
        lines.insert(last + 1, line);
    };
    let candidate = smoke.variant(&smoke.candidate, "c2", |_| {}, code_document);
    let repeat = smoke.variant(&smoke.repeat, "r2", |_| {}, code_document);
    assert_fail(
        &smoke.gate(&candidate, &repeat, "gate-code-document"),
        "CODE_RESULTS",
    );
}

/// SPEC-0003-R30: the baseline is the supplied main SHA; runs are clean.
#[test]
fn wp18_rejects_non_main_baseline() {
    let smoke = smoke();
    let outcome = smoke.gate_with(
        &smoke.baseline,
        &smoke.candidate,
        Some(&smoke.repeat),
        Some(&"0".repeat(40)),
        "gate-not-main",
    );
    assert_fail(&outcome, "NOT_MAIN_BASELINE");

    let outcome = smoke.gate_with(
        &smoke.baseline,
        &smoke.candidate,
        Some(&smoke.repeat),
        None,
        "gate-no-sha",
    );
    assert_fail(&outcome, "MISSING_INPUT");

    let dirty = smoke.variant(
        &smoke.baseline,
        "b-dirty",
        |v| v["commit"]["dirty"] = json!(true),
        |_| {},
    );
    let outcome = smoke.gate_with(
        &dirty,
        &smoke.candidate,
        Some(&smoke.repeat),
        Some(&smoke.sha),
        "gate-dirty",
    );
    assert_fail(&outcome, "DIRTY_COMMIT");

    let other = smoke.variant(
        &smoke.repeat,
        "r-other",
        |v| v["commit"]["sha"] = json!("1".repeat(40)),
        |_| {},
    );
    assert_fail(
        &smoke.gate(&smoke.candidate, &other, "gate-repeat-commit"),
        "DIRTY_COMMIT",
    );
}

/// SPEC-0003-R31: every ranking invariant rejects a broken candidate run.
#[test]
fn wp18_ranking_invariants_reject_bad_runs() {
    let smoke = smoke();
    type Mutation = fn(&mut Vec<String>);
    let cases: [(&str, Mutation); 7] = [
        ("gap", |lines| {
            let rows = first_query_rows(lines);
            set_field(&mut lines[rows[1]], 3, "3");
            set_field(&mut lines[rows[2]], 3, "4");
        }),
        ("duplicate", |lines| {
            let rows = first_query_rows(lines);
            let target = lines[rows[0]].split(' ').nth(2).unwrap().to_string();
            set_field(&mut lines[rows[1]], 2, &target);
        }),
        ("nan", |lines| {
            let rows = first_query_rows(lines);
            set_field(&mut lines[rows[1]], 4, "NaN");
        }),
        ("increasing", |lines| {
            let rows = first_query_rows(lines);
            set_field(&mut lines[rows[1]], 4, "1000");
        }),
        ("unknown-document", |lines| {
            let rows = first_query_rows(lines);
            set_field(&mut lines[rows[1]], 2, "doc-unknown");
        }),
        ("unexpected-query", |lines| {
            let mut line = lines[0].clone();
            set_field(&mut line, 0, "q-not-in-the-set");
            lines.push(line);
        }),
        ("malformed", |lines| lines[0].push_str(" extra")),
    ];
    for (name, mutation) in cases {
        let candidate = smoke.variant(&smoke.candidate, &format!("c-{name}"), |_| {}, mutation);
        assert_fail(
            &smoke.gate(&candidate, &smoke.repeat, &format!("gate-{name}")),
            "RANKING_INVARIANT",
        );
    }

    // Complete expected query coverage.
    let drop_query = |value: &mut Value| {
        value["quality"]["per_query"]
            .as_array_mut()
            .unwrap()
            .remove(0);
    };
    let candidate = smoke.variant(&smoke.candidate, "c-coverage", drop_query, |_| {});
    let repeat = smoke.variant(&smoke.repeat, "r-coverage", drop_query, |_| {});
    assert_fail(
        &smoke.gate(&candidate, &repeat, "gate-coverage"),
        "QUERY_COVERAGE",
    );

    // A missing per-query metric is a failure, never a skip.
    let drop_metric = |value: &mut Value| {
        value["quality"]["per_query"][0]["metrics"]
            .as_object_mut()
            .unwrap()
            .remove("ndcg_10");
    };
    let candidate = smoke.variant(&smoke.candidate, "c-metric", drop_metric, |_| {});
    let repeat = smoke.variant(&smoke.repeat, "r-metric", drop_metric, |_| {});
    assert_fail(
        &smoke.gate(&candidate, &repeat, "gate-metric"),
        "MISSING_METRIC",
    );

    // A missing run artifact is a failure, never a skip.
    let candidate = smoke.variant(&smoke.candidate, "c-no-run", |_| {}, |_| {});
    std::fs::remove_file(candidate.join("run.trec")).unwrap();
    assert_fail(
        &smoke.gate(&candidate, &smoke.repeat, "gate-no-run"),
        "MISSING_INPUT",
    );
}

/// SPEC-0003-R31: the repeat must reproduce target order and scores.
#[test]
fn wp18_requires_identical_repeat_order() {
    let smoke = smoke();
    let swapped = smoke.variant(
        &smoke.repeat,
        "r-swap",
        |_| {},
        |lines| {
            let rows = first_query_rows(lines);
            let first = lines[rows[1]].split(' ').nth(2).unwrap().to_string();
            let second = lines[rows[2]].split(' ').nth(2).unwrap().to_string();
            set_field(&mut lines[rows[1]], 2, &second);
            set_field(&mut lines[rows[2]], 2, &first);
        },
    );
    assert_fail(
        &smoke.gate(&smoke.candidate, &swapped, "gate-swap"),
        "NONDETERMINISTIC_REPEAT",
    );

    let shifted = smoke.variant(
        &smoke.repeat,
        "r-score",
        |_| {},
        |lines| {
            let rows = first_query_rows(lines);
            let score: f64 = lines[rows[0]].split(' ').nth(4).unwrap().parse().unwrap();
            set_field(&mut lines[rows[0]], 4, &format!("{}", score + 1e-6));
        },
    );
    assert_fail(
        &smoke.gate(&smoke.candidate, &shifted, "gate-score"),
        "NONDETERMINISTIC_REPEAT",
    );

    let metric = smoke.variant(
        &smoke.repeat,
        "r-metric",
        |v| {
            v["quality"]["per_query"][0]["metrics"]["ndcg_10"] = json!(0.25);
        },
        |_| {},
    );
    assert_fail(
        &smoke.gate(&smoke.candidate, &metric, "gate-repeat-metric"),
        "NONDETERMINISTIC_REPEAT",
    );

    let outcome = smoke.gate_with(
        &smoke.baseline,
        &smoke.candidate,
        None,
        Some(&smoke.sha),
        "gate-no-repeat",
    );
    assert_fail(&outcome, "MISSING_INPUT");
}

// ---------------------------------------------------------------------------
// R31 boundary and property tests on the pure checks
// ---------------------------------------------------------------------------

fn row(query: &str, target: &str, rank: u32, score: f64) -> TrecRow {
    TrecRow {
        query_id: query.to_string(),
        target: target.to_string(),
        rank,
        score,
    }
}

fn ids(values: &[&str]) -> BTreeSet<String> {
    values.iter().map(|value| (*value).to_string()).collect()
}

fn valid() -> Vec<TrecRow> {
    vec![
        row("q1", "d1", 1, 3.0),
        row("q1", "d2", 2, 2.0),
        row("q1", "d3", 3, 2.0),
        row("q2", "d2", 1, 1.0),
    ]
}

/// SPEC-0003-R31 boundaries: contiguous ranks from 1.
#[test]
fn wp18_ranks_must_start_at_one_and_be_contiguous() {
    let queries = ids(&["q1", "q2"]);
    let documents = ids(&["d1", "d2", "d3"]);
    assert!(check_ranking(&valid(), &queries, &documents).is_ok());
    // File order does not matter; ranks do.
    let mut shuffled = valid();
    shuffled.reverse();
    assert!(check_ranking(&shuffled, &queries, &documents).is_ok());
    let mut zero = valid();
    zero[3].rank = 0;
    assert!(check_ranking(&zero, &queries, &documents).is_err());
    let mut late_start = valid();
    late_start[3].rank = 2;
    assert!(check_ranking(&late_start, &queries, &documents).is_err());
    let mut repeated = valid();
    repeated[2].rank = 2;
    assert!(check_ranking(&repeated, &queries, &documents).is_err());
}

/// SPEC-0003-R31 boundaries: unique targets per query, not across queries.
#[test]
fn wp18_targets_must_be_unique_per_query() {
    let queries = ids(&["q1", "q2"]);
    let documents = ids(&["d1", "d2", "d3"]);
    // d2 appears under q1 and q2: allowed.
    assert!(check_ranking(&valid(), &queries, &documents).is_ok());
    let mut duplicate = valid();
    duplicate[2].target = "d1".to_string();
    assert!(check_ranking(&duplicate, &queries, &documents).is_err());
}

/// SPEC-0003-R31 boundaries: finite, nonincreasing scores (ties allowed).
#[test]
fn wp18_scores_must_be_finite_and_nonincreasing() {
    let queries = ids(&["q1", "q2"]);
    let documents = ids(&["d1", "d2", "d3"]);
    // Equal scores at ranks 2 and 3 pass.
    assert!(check_ranking(&valid(), &queries, &documents).is_ok());
    for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        let mut run = valid();
        run[2].score = bad;
        assert!(check_ranking(&run, &queries, &documents).is_err(), "{bad}");
    }
    let mut rising = valid();
    rising[2].score = 2.0 + f64::EPSILON * 4.0;
    assert!(check_ranking(&rising, &queries, &documents).is_err());
}

/// SPEC-0003-R31 boundaries: expected queries and default documents only.
#[test]
fn wp18_targets_and_queries_must_be_in_the_default_selection() {
    let documents = ids(&["d1", "d2", "d3"]);
    assert!(check_ranking(&valid(), &ids(&["q1", "q2", "q3"]), &documents).is_ok());
    assert!(check_ranking(&valid(), &ids(&["q1"]), &documents).is_err());
    assert!(check_ranking(&valid(), &ids(&["q1", "q2"]), &ids(&["d1", "d2"])).is_err());
}

/// SPEC-0003-R31 boundaries: repeat order and the 1e-9 score tolerance.
#[test]
fn wp18_repeat_tolerance_is_one_e_minus_nine() {
    let base = valid();
    assert!(check_repeat(&base, &base).is_ok());
    let mut within = valid();
    within[0].score += 5e-10;
    assert!(check_repeat(&base, &within).is_ok());
    let mut beyond = valid();
    beyond[0].score += 2e-9;
    assert!(check_repeat(&base, &beyond).is_err());
    let mut shorter = valid();
    shorter.pop();
    assert!(check_repeat(&base, &shorter).is_err());
    let mut reordered = valid();
    reordered[1].target = "d3".to_string();
    reordered[2].target = "d2".to_string();
    assert!(check_repeat(&base, &reordered).is_err());
}

/// SPEC-0003-R31: a parsed run keeps non-finite scores for the invariants.
#[test]
fn wp18_parse_trec_is_strict_about_shape_only() {
    let rows = parse_trec("q1 Q0 d1 1 NaN run\nq1 Q0 d2 2 inf run\n").unwrap();
    assert!(rows[0].score.is_nan());
    assert!(rows[1].score.is_infinite());
    assert!(parse_trec("q1 Q0 d1 1 1.0\n").is_err());
    assert!(parse_trec("q1 X d1 1 1.0 run\n").is_err());
    assert!(parse_trec("q1 Q0 d1 one 1.0 run\n").is_err());
    assert!(parse_trec("").unwrap().is_empty());
}

/// Deterministic generator (no new dependency): SplitMix64.
struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    fn below(&mut self, bound: usize) -> usize {
        usize::try_from(self.next() % bound as u64).unwrap()
    }
}

/// Property (SPEC-0003-R31): a TREC run with gaps, duplicate targets, or
/// non-finite scores never passes a ranking invariant, while the same run
/// before corruption always does.
#[test]
fn wp18_property_corrupted_runs_never_pass() {
    let queries: BTreeSet<String> = (0..6).map(|q| format!("q{q}")).collect();
    let documents: BTreeSet<String> = (0..20).map(|d| format!("d{d}")).collect();
    let mut rng = Rng(0x5EED_0001);
    for case in 0..500 {
        let mut run = Vec::new();
        for query in &queries {
            let depth = 1 + rng.below(10);
            let mut pool: Vec<usize> = (0..20).collect();
            let mut score = 100.0;
            for rank in 1..=depth {
                let pick = pool.remove(rng.below(pool.len()));
                if rng.below(3) > 0 {
                    score -= rng.below(5) as f64 * 0.5;
                }
                run.push(row(
                    query,
                    &format!("d{pick}"),
                    u32::try_from(rank).unwrap(),
                    score,
                ));
            }
        }
        // Shuffle file order: the invariants look at ranks, not lines.
        for index in (1..run.len()).rev() {
            run.swap(index, rng.below(index + 1));
        }
        assert!(
            check_ranking(&run, &queries, &documents).is_ok(),
            "case {case}: a valid run must pass"
        );

        let victim = rng.below(run.len());
        let mut corrupted = run.clone();
        match case % 3 {
            0 => {
                // Gap: push one rank past the end of its query.
                let query = corrupted[victim].query_id.clone();
                let depth = run.iter().filter(|row| row.query_id == query).count();
                corrupted[victim].rank = u32::try_from(depth + 1 + rng.below(3)).unwrap();
            }
            1 => {
                // Duplicate target within the query (or a duplicate row).
                let query = corrupted[victim].query_id.clone();
                let other = run
                    .iter()
                    .find(|row| row.query_id == query && row.rank != corrupted[victim].rank)
                    .cloned();
                match other {
                    Some(other) => corrupted[victim].target = other.target,
                    None => corrupted.push(corrupted[victim].clone()),
                }
            }
            _ => {
                corrupted[victim].score =
                    [f64::NAN, f64::INFINITY, f64::NEG_INFINITY][rng.below(3)];
            }
        }
        assert!(
            check_ranking(&corrupted, &queries, &documents).is_err(),
            "case {case}: corruption {} must fail",
            case % 3
        );
    }
}

/// SPEC-0003-R29: the committed CI configuration is hardware-free.
#[test]
fn wp18_ci_configuration_is_lexical_cpu_only() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("configs/ci-smoke-lexical.json");
    let config = seeky_bench::environment::load_run_config(&path).expect("CI config loads");
    assert!(!config.semantic, "the CI smoke gate never loads a model");
    assert_eq!(config.backend, "cpu");
}
