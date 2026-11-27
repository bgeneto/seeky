//! SPEC-0003 R15 acceptance tests: CLI surface and corpus resolution.

#![allow(clippy::unwrap_used)]

mod support;

use seeky_bench::corpus::{self, BenchPaths};
use seeky_bench::run_with_paths;
use std::process::Command;

fn args(values: &[&str]) -> Vec<String> {
    values.iter().map(|value| (*value).to_string()).collect()
}

fn binary() -> Command {
    Command::new(env!("CARGO_BIN_EXE_seeky-bench"))
}

/// SPEC-0003-R15
#[test]
fn cli_exposes_all_five_subcommands_and_flags() {
    let output = binary().arg("--help").output().expect("run help");
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    for command in ["index", "eval", "perf", "compare", "report"] {
        assert!(stdout.contains(command), "help lacks {command}");
    }
    for flag in [
        "--corpus",
        "--split",
        "--limit",
        "--confirmation",
        "--gate",
        "--overwrite",
        "--data-dir",
        "--config",
        "--output",
    ] {
        assert!(stdout.contains(flag), "help lacks {flag}");
    }
}

/// SPEC-0003-R15
#[test]
fn unknown_or_conflicting_flags_fail_before_engine_open() {
    let fixture = support::build();
    let data = fixture.work.join("never-created");
    let output = binary()
        .env("SEEKY_BENCH_ROOT", &fixture.root)
        .args(args(&[
            "index",
            "--corpus",
            "tiny",
            "--data-dir",
            data.to_str().unwrap(),
            "--config",
            fixture.config("default.json").to_str().unwrap(),
            "--output",
            fixture.work.join("never-out").to_str().unwrap(),
            "--bogus",
        ]))
        .output()
        .expect("run");
    assert_eq!(output.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&output.stderr).contains("unknown flag"));
    assert!(!data.exists(), "engine work started before validation");

    // Conflicting combination: perf never accepts the test split.
    let output = binary()
        .env("SEEKY_BENCH_ROOT", &fixture.root)
        .args(args(&[
            "perf",
            "--corpus",
            "tiny",
            "--config",
            fixture.config("default.json").to_str().unwrap(),
            "--data-dir",
            data.to_str().unwrap(),
            "--output",
            fixture.work.join("never-out").to_str().unwrap(),
            "--split",
            "test",
        ]))
        .output()
        .expect("run");
    assert_eq!(output.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&output.stderr).contains("unknown flag"));
    assert!(!data.exists());
}

/// SPEC-0003-R15
#[test]
fn corpus_unknown_id_is_rejected() {
    let fixture = support::build();
    let paths = BenchPaths::at(fixture.root.clone());
    let failure = corpus::resolve(&paths, "does-not-exist", false).expect_err("unknown corpus");
    assert_eq!(failure.code, 2);
    assert!(failure.message.contains("unknown corpus"));
}

/// SPEC-0003-R15
#[test]
fn corpus_resolves_only_the_builtin_or_manifest_layout() {
    let fixture = support::build();
    let paths = BenchPaths::at(fixture.root.clone());
    let resolved = corpus::resolve(&paths, "tiny", false).expect("resolve");
    assert_eq!(resolved.root_labels, vec!["data/files".to_string()]);
    assert_eq!(resolved.visibility, "public");
    assert_eq!(resolved.roots.len(), 1);

    let failure = corpus::resolve(&paths, "tiny", true).expect_err("code config");
    assert_eq!(failure.code, 2);
    assert!(failure.message.contains("--code-enabled"));
}

/// SPEC-0003-R15
#[test]
fn index_requires_fresh_for_a_nonempty_data_directory() {
    let fixture = support::build();
    let paths = BenchPaths::at(fixture.root.clone());
    let data = fixture.data_dir("fresh");
    support::write(&data.join("stray.txt"), "occupied\n");
    let failure = run_with_paths(
        &paths,
        args(&[
            "index",
            "--corpus",
            "tiny",
            "--data-dir",
            data.to_str().unwrap(),
            "--config",
            fixture.config("default.json").to_str().unwrap(),
            "--output",
            fixture.output("fresh").to_str().unwrap(),
        ]),
    )
    .expect_err("nonempty without --fresh");
    assert_eq!(failure.code, 2);
}
