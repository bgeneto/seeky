#![allow(clippy::unwrap_used)]
#![allow(dead_code)]

//! Hermetic BEIR fixture used by the `seeky-bench` acceptance tests.
//!
//! Everything is synthetic and created in a temporary directory; a tiny git
//! repository supplies commit and clean-tree evidence.

use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::process::Command;

pub struct Fixture {
    pub dir: tempfile::TempDir,
    pub root: PathBuf,
    pub work: PathBuf,
}

pub const DOCS: [(&str, &str, &str, &str); 5] = [
    (
        "d1",
        "data/files/d1.txt",
        "Doc one",
        "The quick brown fox jumps over the lazy dog. Needle alpha content about contracts and renewal.",
    ),
    (
        "d2",
        "data/files/d2.txt",
        "Doc two",
        "A second document about budgets and invoices. Needle beta content about the annual budget.",
    ),
    (
        "d3",
        "data/files/d3.txt",
        "Doc three",
        "Third document about satellites and orbits. Needle gamma content about orbit mechanics.",
    ),
    (
        "d4",
        "data/files/d4.md",
        "Doc four",
        "Markdown notes about the weekly meeting. Needle delta content about minutes.",
    ),
    (
        "d5",
        "data/files/d5.md",
        "Doc five",
        "Markdown recipe page with unrelated cooking text for the corpus.",
    ),
];

pub const DEV_QUERIES: [(&str, &str); 4] = [
    ("q3", "needle gamma"),
    ("q1", "needle alpha"),
    ("q4", "needle delta"),
    ("q2", "needle beta"),
];

pub const QRELS_DEV: [(&str, &str); 4] = [("q1", "d1"), ("q2", "d2"), ("q3", "d3"), ("q4", "d4")];
pub const TEST_QUERIES: [(&str, &str); 2] = [("t1", "needle alpha"), ("t2", "needle beta")];
pub const QRELS_TEST: [(&str, &str); 2] = [("t1", "d1"), ("t2", "d2")];

pub fn build() -> Fixture {
    let dir = tempfile::tempdir().expect("temporary directory");
    let root = dir.path().join("repo");
    let work = dir.path().join("work");
    std::fs::create_dir_all(&root).unwrap();
    std::fs::create_dir_all(&work).unwrap();

    let dataset = root.join("bench/datasets/tiny");
    std::fs::create_dir_all(dataset.join("data/files")).unwrap();
    let mut files = Vec::new();
    for (_, relative, _, text) in DOCS {
        let path = dataset.join(relative);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, text).unwrap();
        files.push(relative.to_string());
    }

    let mut corpus = String::new();
    for (id, relative, title, text) in DOCS {
        corpus.push_str(&format!(
            "{}\n",
            serde_json::json!({
                "_id": id,
                "title": title,
                "text": text,
                "metadata": {"relative_path": relative},
            })
        ));
    }
    write(&dataset.join("data/corpus.jsonl"), &corpus);

    let mut dev_queries = String::new();
    for (id, text) in DEV_QUERIES {
        let row = if id == "q4" {
            serde_json::json!({
                "_id": id,
                "text": text,
                "metadata": {"filters": {"extensions": ["md"]}},
            })
        } else {
            serde_json::json!({"_id": id, "text": text})
        };
        dev_queries.push_str(&format!("{row}\n"));
    }
    write(&dataset.join("data/queries.dev.jsonl"), &dev_queries);

    let mut test_queries = String::new();
    for (id, text) in TEST_QUERIES {
        test_queries.push_str(&format!(
            "{}\n",
            serde_json::json!({"_id": id, "text": text})
        ));
    }
    write(&dataset.join("data/queries.test.jsonl"), &test_queries);

    write_qrels(&dataset.join("data/qrels.dev.tsv"), &QRELS_DEV);
    write_qrels(&dataset.join("data/qrels.test.tsv"), &QRELS_TEST);

    let mut local = serde_json::Map::new();
    for relative in [
        "data/corpus.jsonl",
        "data/queries.dev.jsonl",
        "data/queries.test.jsonl",
        "data/qrels.dev.tsv",
        "data/qrels.test.tsv",
    ] {
        local.insert(
            relative.to_string(),
            serde_json::json!(sha256_file(&dataset.join(relative))),
        );
    }
    for relative in &files {
        local.insert(
            relative.clone(),
            serde_json::json!(sha256_file(&dataset.join(relative))),
        );
    }

    let manifest = serde_json::json!({
        "schema_version": 1,
        "dataset_id": "tiny",
        "layout": "beir",
        "visibility": "public",
        "license": {
            "id": "CC0-1.0",
            "url": "https://example.invalid/license",
            "redistribution": "download-only",
            "terms_url": "https://example.invalid/terms",
        },
        "source": {
            "revision": "fixture",
            "urls": ["https://example.invalid/fixture"],
            "sha256": ["0".repeat(64)],
        },
        "corpus": "data/corpus.jsonl",
        "files_root": "data/files",
        "splits": {
            "dev": {"queries": "data/queries.dev.jsonl", "qrels": "data/qrels.dev.tsv"},
            "test": {"queries": "data/queries.test.jsonl", "qrels": "data/qrels.test.tsv"},
        },
        "query_defaults": {
            "language_slice": "en",
            "category": "conceptual",
            "configuration": "default",
        },
        "transform": {
            "script": "tools/seeky-bench/tests/support",
            "version": 1,
            "seed": "fixture-v1",
        },
        "local_file_sha256": local,
    });
    write(
        &dataset.join("manifest.json"),
        &format!("{}\n", serde_json::to_string_pretty(&manifest).unwrap()),
    );

    let configs = root.join("bench/configs");
    std::fs::create_dir_all(&configs).unwrap();
    write(
        &configs.join("default.json"),
        "{\"schema_version\":1,\"name\":\"default\",\"backend\":\"cpu\",\"semantic\":false}\n",
    );
    write(
        &configs.join("other.json"),
        "{\"schema_version\":1,\"name\":\"other\",\"backend\":\"cpu\",\"semantic\":false}\n",
    );
    write(
        &configs.join("npu.json"),
        "{\"schema_version\":1,\"name\":\"default\",\"backend\":\"npu\",\"semantic\":false}\n",
    );

    git(&root, &["init", "-q"]);
    git(&root, &["add", "."]);
    let status = Command::new("git")
        .arg("-C")
        .arg(&root)
        .args([
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ])
        .status()
        .expect("git commit");
    assert!(status.success(), "git commit failed");

    Fixture { dir, root, work }
}

impl Fixture {
    pub fn config(&self, name: &str) -> PathBuf {
        self.root.join("bench/configs").join(name)
    }

    pub fn data_dir(&self, name: &str) -> PathBuf {
        self.work.join(name).join("data")
    }

    pub fn output(&self, name: &str) -> PathBuf {
        self.work.join(name).join("out")
    }

    pub fn dataset_dir(&self) -> PathBuf {
        self.root.join("bench/datasets/tiny")
    }
}

pub fn write(path: &Path, text: &str) {
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, text).unwrap();
}

fn write_qrels(path: &Path, rows: &[(&str, &str)]) {
    let mut text = String::from("query-id\tcorpus-id\tscore\n");
    for (query, document) in rows {
        text.push_str(&format!("{query}\t{document}\t3\n"));
    }
    write(path, &text);
}

pub fn sha256_file(path: &Path) -> String {
    let bytes = std::fs::read(path).unwrap();
    let digest = Sha256::digest(&bytes);
    format!("{digest:x}")
}

pub fn sha256_text(text: &str) -> String {
    let digest = Sha256::digest(text.as_bytes());
    format!("{digest:x}")
}

fn git(root: &Path, args: &[&str]) {
    let status = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .status()
        .expect("git");
    assert!(status.success(), "git {args:?} failed");
}

/// Commit the current tree (the operator commits the exposure ledger).
pub fn commit_all(fixture: &Fixture, message: &str) {
    git(&fixture.root, &["add", "."]);
    let status = Command::new("git")
        .arg("-C")
        .arg(&fixture.root)
        .args([
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            message,
        ])
        .status()
        .expect("git commit");
    assert!(status.success(), "git commit failed");
}

/// Rewrite the dev queries with an extra malformed filter and refresh hashes.
#[allow(clippy::needless_pass_by_value)]
pub fn add_dev_query(fixture: &Fixture, id: &str, text: &str, filters: serde_json::Value) {
    let dataset = fixture.dataset_dir();
    let mut dev_queries = String::new();
    for (query, text) in DEV_QUERIES {
        let row = if query == "q4" {
            serde_json::json!({
                "_id": query,
                "text": text,
                "metadata": {"filters": {"extensions": ["md"]}},
            })
        } else {
            serde_json::json!({"_id": query, "text": text})
        };
        dev_queries.push_str(&format!("{row}\n"));
    }
    dev_queries.push_str(&format!(
        "{}\n",
        serde_json::json!({"_id": id, "text": text, "metadata": {"filters": filters}})
    ));
    write(&dataset.join("data/queries.dev.jsonl"), &dev_queries);

    let manifest_path = dataset.join("manifest.json");
    let mut manifest: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&manifest_path).unwrap()).unwrap();
    manifest["local_file_sha256"]["data/queries.dev.jsonl"] =
        serde_json::json!(sha256_text(&dev_queries));
    write(
        &manifest_path,
        &format!("{}\n", serde_json::to_string_pretty(&manifest).unwrap()),
    );
    git(&fixture.root, &["add", "."]);
    let status = Command::new("git")
        .arg("-C")
        .arg(&fixture.root)
        .args([
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture query",
        ])
        .status()
        .expect("git commit");
    assert!(status.success());
}
