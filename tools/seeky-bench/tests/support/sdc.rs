//! Hermetic, synthetic `sdc-smoke` corpus plus a verified `sdc-smoke-v1`
//! judgment set for the WP-1.8 gate tests (SPEC-0003 R29-R31).
//!
//! Nothing here copies the real drafts: eight one-word documents (one per
//! non-code category), one source-code document in the opt-in code root,
//! five default `dev` queries per non-code category, and five `code_search`
//! queries that only the code-enabled configuration selects. Every record is
//! `verified` by a pseudonymous human reviewer.

use super::{Fixture, sha256_file, sha256_text, write};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::Command;

/// The eight non-code categories and the unique word of their document.
pub const CATEGORIES: [(&str, &str); 8] = [
    ("known_item", "anchor"),
    ("conceptual", "bridge"),
    ("exact_identifier", "copper"),
    ("cross_language", "dolphin"),
    ("needle_in_haystack", "ember"),
    ("exploratory", "falcon"),
    ("mixed_semantic_metadata", "glacier"),
    ("filename_partial", "harbor"),
];
/// The source-code document's word.
pub const CODE_WORD: &str = "lantern";
/// Queries per category.
pub const PER_CATEGORY: usize = 5;

pub fn query_id(category: usize, index: usize) -> String {
    format!("q-{category}-{index}")
}

pub fn document_id(category: usize) -> String {
    format!("doc-{category}")
}

pub const CODE_DOCUMENT: &str = "code-1";

pub fn corpus_dir(fixture: &Fixture) -> PathBuf {
    fixture.root.join("bench/corpora/sdc/sdc-smoke")
}

pub fn qrels_dir(fixture: &Fixture) -> PathBuf {
    fixture.root.join("bench/qrels/sdc/sdc-smoke-v1")
}

fn provenance() -> Value {
    json!({
        "drafted_by": "human:reviewer-a",
        "verified_by": ["human:reviewer-a"],
        "state": "verified",
        "adjudicated_by": null
    })
}

fn jsonl(rows: &[Value]) -> String {
    rows.iter()
        .map(|row| format!("{}\n", serde_json::to_string(row).unwrap()))
        .collect()
}

struct Doc {
    id: String,
    path: String,
    text: String,
    class: &'static str,
}

fn documents() -> Vec<Doc> {
    let mut docs: Vec<Doc> = CATEGORIES
        .iter()
        .enumerate()
        .map(|(index, (_, word))| Doc {
            id: document_id(index),
            path: format!("files/documents/doc-{index}.txt"),
            text: format!("The {word} notes describe the {word} project and its weekly status."),
            class: "document",
        })
        .collect();
    docs.push(Doc {
        id: CODE_DOCUMENT.to_string(),
        path: "files/code/code-1.txt".to_string(),
        text: format!("fn main() {{ let {CODE_WORD} = 1; }} // notes"),
        class: "source_code",
    });
    docs
}

/// Build the fixture repository (committed, clean).
pub fn build() -> Fixture {
    build_with(|_| PER_CATEGORY)
}

/// Build the fixture with `per_category(index)` default queries per category.
pub fn build_with(per_category: impl Fn(usize) -> usize) -> Fixture {
    let dir = tempfile::tempdir().expect("temporary directory");
    let root = dir.path().join("repo");
    let work = dir.path().join("work");
    std::fs::create_dir_all(&root).unwrap();
    std::fs::create_dir_all(&work).unwrap();
    let fixture = Fixture { dir, root, work };

    write_corpus(&corpus_dir(&fixture));
    write_judgments(&fixture, &per_category);
    write(
        &fixture.root.join("bench/configs/default.json"),
        "{\"schema_version\":1,\"name\":\"default\",\"backend\":\"cpu\",\"semantic\":false}\n",
    );
    git(&fixture.root, &["init", "-q"]);
    commit(&fixture, "fixture");
    fixture
}

fn write_corpus(corpus: &Path) {
    let docs = documents();
    let mut files = Vec::new();
    let mut corpus_rows = Vec::new();
    let mut passage_rows = Vec::new();
    let mut truth_rows = Vec::new();
    for (index, doc) in docs.iter().enumerate() {
        let path = corpus.join(&doc.path);
        write(&path, &doc.text);
        let bytes = doc.text.len();
        let sha = sha256_text(&doc.text);
        files.push(json!({"path": doc.path, "byte_count": bytes, "sha256": sha}));
        corpus_rows.push(json!({
            "_id": doc.id,
            "title": doc.id,
            "text": doc.text,
            "metadata": {
                "relative_path": doc.path,
                "media_type": "text/plain",
                "format": "txt",
                "languages": ["en"],
                "file_class": doc.class,
                "source_set_id": "fixture",
                "source_item_id": format!("{}", index + 1),
                "source_sha256": "a".repeat(64),
                "content_sha256": sha,
                "text_sha256": sha,
                "byte_count": bytes,
                "modified_at": "2024-01-01T00:00:00Z",
                "render_recipe_id": "txt-v1",
                "duplicate_cluster_ids": [],
                "version_group_id": null,
                "version_number": null,
                "is_latest": null,
                "boilerplate_family_ids": []
            }
        }));
        passage_rows.push(json!({
            "_id": format!("{}:p:1", doc.id),
            "document_id": doc.id,
            "text": doc.text,
            "start_utf8": 0,
            "end_utf8": bytes,
            "text_sha256": sha,
            "kind": if doc.class == "source_code" { "code" } else { "paragraph" },
            "locator": {"page": 1, "block_id": format!("{}:p:1", doc.id)},
            "boilerplate_family_id": null
        }));
        truth_rows.push(json!({
            "document_id": doc.id,
            "locator": {"page": 1},
            "text": doc.text,
            "text_sha256": sha,
            "truth_origin": "generator-known"
        }));
    }
    write(&corpus.join("corpus.jsonl"), &jsonl(&corpus_rows));
    write(&corpus.join("passages.jsonl"), &jsonl(&passage_rows));
    write(&corpus.join("extraction-truth.jsonl"), &jsonl(&truth_rows));
    write(&corpus.join("duplicate-clusters.jsonl"), "");
    write(&corpus.join("versions.jsonl"), "");

    files.sort_by(|left, right| {
        left["path"]
            .as_str()
            .unwrap_or_default()
            .cmp(right["path"].as_str().unwrap_or_default())
    });
    let sidecars: BTreeMap<String, String> = [
        "corpus.jsonl",
        "passages.jsonl",
        "extraction-truth.jsonl",
        "duplicate-clusters.jsonl",
        "versions.jsonl",
    ]
    .into_iter()
    .map(|name| (name.to_string(), sha256_file(&corpus.join(name))))
    .collect();
    let default_roots = vec!["files/documents".to_string()];
    let code_enabled_roots = vec!["files/documents".to_string(), "files/code".to_string()];
    let corpus_hash = sha256_text(
        &serde_json::to_string(&json!({
            "files": &files,
            "sidecars": &sidecars,
            "default_roots": &default_roots,
            "code_enabled_roots": &code_enabled_roots
        }))
        .unwrap(),
    );
    let manifest = json!({
        "schema_version": 1,
        "corpus_id": "sdc-smoke",
        "profile_sha256": "a".repeat(64),
        "source_set_sha256": "b".repeat(64),
        "seed": "sdc-smoke-v1",
        "generator_version": "0.1.0",
        "renderer_lock_sha256": "c".repeat(64),
        "document_count": docs.len(),
        "passage_count": docs.len(),
        "default_roots": default_roots,
        "code_enabled_roots": code_enabled_roots,
        "files": files,
        "sidecars": sidecars,
        "corpus_hash": corpus_hash
    });
    write(
        &corpus.join("manifest.json"),
        &serde_json::to_string_pretty(&manifest).unwrap(),
    );
}

fn query_row(id: &str, text: &str, category: &str, configuration: &str) -> Value {
    json!({
        "_id": id,
        "text": text,
        "language": "en",
        "target_languages": ["en"],
        "language_slice": "en",
        "category": category,
        "configuration": configuration,
        "split": "dev",
        "filters": null,
        "provenance": provenance()
    })
}

fn write_judgments(fixture: &Fixture, per_category: &dyn Fn(usize) -> usize) {
    let docs = documents();
    let mut queries = Vec::new();
    let mut document_qrels = Vec::new();
    let mut passage_qrels = Vec::new();
    let mut judge = |query: &str, doc: &Doc, labels: Value| {
        document_qrels.push(json!({
            "judgment_set_id": "sdc-smoke-v1", "query_id": query, "document_id": doc.id,
            "document_text_sha256": sha256_text(&doc.text), "grade": 3,
            "evidence_passage_ids": [format!("{}:p:1", doc.id)], "subtopic_labels": labels,
            "provenance": provenance()
        }));
        passage_qrels.push(json!({
            "judgment_set_id": "sdc-smoke-v1", "query_id": query, "document_id": doc.id,
            "passage_id": format!("{}:p:1", doc.id), "passage_text_sha256": sha256_text(&doc.text),
            "grade": 3, "evidence_spans": [], "provenance": provenance()
        }));
    };
    for (category_index, (category, word)) in CATEGORIES.iter().enumerate() {
        for index in 0..per_category(category_index) {
            let id = query_id(category_index, index);
            queries.push(query_row(
                &id,
                &format!("{word} notes"),
                category,
                "default",
            ));
            let labels = if *category == "exploratory" {
                json!(["s1"])
            } else {
                json!([])
            };
            judge(&id, &docs[category_index], labels);
        }
    }
    let code = docs.last().unwrap();
    for index in 0..PER_CATEGORY {
        let id = format!("q-code-{index}");
        queries.push(query_row(&id, CODE_WORD, "code_search", "code_enabled"));
        judge(&id, code, json!([]));
    }
    let qrels = qrels_dir(fixture);
    write(&qrels.join("queries.dev.jsonl"), &jsonl(&queries));
    write(
        &qrels.join("qrels.dev.documents.jsonl"),
        &jsonl(&document_qrels),
    );
    write(
        &qrels.join("qrels.dev.passages.jsonl"),
        &jsonl(&passage_qrels),
    );
    write(
        &qrels.join("reviewers.json"),
        "{\"reviewer-a\":\"verifier\"}\n",
    );
    write_judgment_manifest(fixture, |_| {});
}

/// Rewrite `judgment-set.json` with fresh file hashes, then apply `update`.
pub fn write_judgment_manifest(fixture: &Fixture, update: impl FnOnce(&mut Value)) {
    let qrels = qrels_dir(fixture);
    let mut file_sha256 = BTreeMap::new();
    for name in [
        "queries.dev.jsonl",
        "qrels.dev.documents.jsonl",
        "qrels.dev.passages.jsonl",
    ] {
        file_sha256.insert(name.to_string(), sha256_file(&qrels.join(name)));
    }
    let corpus: Value = serde_json::from_str(
        &std::fs::read_to_string(corpus_dir(fixture).join("manifest.json")).unwrap(),
    )
    .unwrap();
    let queries = std::fs::read_to_string(qrels.join("queries.dev.jsonl"))
        .unwrap()
        .lines()
        .count();
    let mut manifest = json!({
        "schema_version": 1,
        "judgment_set_id": "sdc-smoke-v1",
        "state": "frozen",
        "split_seed": "sdc-smoke-v1",
        "compatible_corpus_hashes": [corpus["corpus_hash"]],
        "query_counts": {"dev": queries, "test": 0},
        "query_file_sha256": {"queries.dev.jsonl": file_sha256["queries.dev.jsonl"]},
        "file_sha256": file_sha256,
        "test_pool_system_ids": [],
        "supersedes": null,
        "test_exposure": "not-applicable"
    });
    update(&mut manifest);
    write(
        &qrels.join("judgment-set.json"),
        &serde_json::to_string_pretty(&manifest).unwrap(),
    );
}

/// Rewrite one line of a judgment-set file (and refresh the hashes).
pub fn edit_jsonl(fixture: &Fixture, name: &str, line: usize, update: impl FnOnce(&mut Value)) {
    let path = qrels_dir(fixture).join(name);
    let text = std::fs::read_to_string(&path).unwrap();
    let mut rows: Vec<Value> = text
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    update(&mut rows[line]);
    write(&path, &jsonl(&rows));
    write_judgment_manifest(fixture, |_| {});
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

/// Commit the whole tree.
pub fn commit(fixture: &Fixture, message: &str) {
    git(&fixture.root, &["add", "."]);
    git(
        &fixture.root,
        &[
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            message,
        ],
    );
}

/// The fixture's `HEAD`.
pub fn head(fixture: &Fixture) -> String {
    let output = Command::new("git")
        .arg("-C")
        .arg(&fixture.root)
        .args(["rev-parse", "HEAD"])
        .output()
        .expect("git");
    String::from_utf8(output.stdout).unwrap().trim().to_string()
}
