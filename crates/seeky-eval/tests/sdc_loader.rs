//! SDC loader acceptance tests (SPEC-0003 R3/R4).

#![allow(clippy::unwrap_used)] // Test helpers are outside #[test] functions.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use seeky_eval::{EvaluationConfiguration, Split, load_sdc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use tempfile::TempDir;

struct SdcFixture {
    _dir: TempDir,
    corpus: PathBuf,
    qrels: PathBuf,
}

fn sha256(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn write(path: &Path, content: &str) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, content).unwrap();
}

fn json_line(value: &Value) -> String {
    format!("{}\n", serde_json::to_string(value).unwrap())
}

fn provenance() -> Value {
    json!({
        "drafted_by": "human:reviewer-a",
        "verified_by": ["human:reviewer-a"],
        "state": "verified",
        "adjudicated_by": null
    })
}

#[allow(clippy::too_many_lines)]
fn make_fixture() -> SdcFixture {
    let dir = TempDir::new().unwrap();
    let corpus = dir.path().join("corpus");
    let qrels = dir.path().join("qrels");
    let d1_text = "alpha beta gamma";
    let d2_text = "alpha beta";
    let d3_text = "fn main";
    let docs = [
        (
            "doc-1",
            "files/documents/doc-1.txt",
            d1_text,
            "document",
            "1",
            "false",
            Some(("ver-1", 1, false)),
        ),
        (
            "doc-2",
            "files/documents/doc-2.txt",
            d2_text,
            "document",
            "2",
            "true",
            Some(("ver-1", 2, true)),
        ),
        (
            "doc-3",
            "files/code/code-1.txt",
            d3_text,
            "source_code",
            "3",
            "false",
            None,
        ),
    ];
    let mut file_entries = Vec::new();
    let mut corpus_rows = Vec::new();
    for (id, path, text, class, source, _is_latest_str, version) in &docs {
        write(&corpus.join(*path), text);
        let content = fs::read(corpus.join(*path)).unwrap();
        file_entries.push(json!({
            "path": path,
            "byte_count": content.len(),
            "sha256": sha256(&content)
        }));
        let (version_group_id, version_number, is_latest) = (*version)
            .map_or((None, None, None), |(group, number, latest)| {
                (Some(group), Some(number), Some(latest))
            });
        corpus_rows.push(json!({
            "_id": id,
            "title": id,
            "text": text,
            "metadata": {
                "relative_path": path,
                "media_type": "text/plain",
                "format": "txt",
                "languages": ["en"],
                "file_class": class,
                "source_set_id": "fixture",
                "source_item_id": source,
                "source_sha256": "a".repeat(64),
                "content_sha256": sha256(&content),
                "text_sha256": sha256(text.as_bytes()),
                "byte_count": content.len(),
                "modified_at": "2024-01-01T00:00:00Z",
                "render_recipe_id": "txt-v1",
                "duplicate_cluster_ids": if *id == "doc-3" { json!([]) } else { json!(["ver-1"]) },
                "version_group_id": version_group_id,
                "version_number": version_number,
                "is_latest": is_latest,
                "boilerplate_family_ids": []
            }
        }));
    }
    let passages = [
        ("doc-1:p:1", "doc-1", "alpha beta", 0, 10, "paragraph"),
        ("doc-2:p:1", "doc-2", "alpha beta", 0, 10, "paragraph"),
        ("doc-3:p:1", "doc-3", "fn main", 0, 7, "code"),
    ];
    let mut passage_rows = Vec::new();
    for (id, document_id, text, start, end, kind) in passages {
        passage_rows.push(json!({
            "_id": id,
            "document_id": document_id,
            "text": text,
            "start_utf8": start,
            "end_utf8": end,
            "text_sha256": sha256(text.as_bytes()),
            "kind": kind,
            "locator": {"page": 1, "block_id": id},
            "boilerplate_family_id": null
        }));
    }
    let extraction_truth = docs.iter().map(|(id, _, text, _, _, _, _)| {
        json!({
            "document_id": id,
            "locator": {"page": 1},
            "text": text,
            "text_sha256": sha256(text.as_bytes()),
            "truth_origin": "generator-known"
        })
    });
    let duplicate_clusters = json!({
        "cluster_id": "ver-1",
        "kind": "version",
        "canonical_document_id": "doc-2",
        "member_document_ids": ["doc-1", "doc-2"]
    });
    let versions = json!({
        "version_group_id": "ver-1",
        "members": [
            {"document_id": "doc-1", "version_number": 1, "is_latest": false, "changed_passages": []},
            {"document_id": "doc-2", "version_number": 2, "is_latest": true, "changed_passages": [
                {"change": "modified", "from_passage_id": "doc-1:p:1", "to_passage_id": "doc-2:p:1"}
            ]}
        ]
    });
    write_jsonl(&corpus.join("corpus.jsonl"), &corpus_rows);
    write_jsonl(&corpus.join("passages.jsonl"), &passage_rows);
    write_jsonl(
        &corpus.join("extraction-truth.jsonl"),
        &extraction_truth.collect::<Vec<_>>(),
    );
    write(
        &corpus.join("duplicate-clusters.jsonl"),
        &json_line(&duplicate_clusters),
    );
    write(&corpus.join("versions.jsonl"), &json_line(&versions));

    let queries = [
        ("q1", "alpha", "en", "en", "conceptual", "default"),
        ("q2", "alpha", "pt", "pt", "conceptual", "default"),
        ("q3", "main", "en", "en", "code_search", "code_enabled"),
        ("q4", "nothing", "en", "en", "conceptual", "default"),
    ];
    let query_rows: Vec<_> = queries
        .iter()
        .map(|(id, text, language, slice, category, configuration)| {
            json!({
                "_id": id,
                "text": text,
                "language": language,
                "target_languages": [language],
                "language_slice": slice,
                "category": category,
                "configuration": configuration,
                "split": "dev",
                "filters": null,
                "provenance": provenance()
            })
        })
        .collect();
    let document_qrels = [
        json!({
            "judgment_set_id": "sdc-smoke-v1", "query_id": "q1", "document_id": "doc-1",
            "document_text_sha256": sha256(d1_text.as_bytes()), "grade": 3,
            "evidence_passage_ids": ["doc-1:p:1"], "subtopic_labels": [],
            "provenance": provenance()
        }),
        json!({
            "judgment_set_id": "sdc-smoke-v1", "query_id": "q1", "document_id": "doc-2",
            "document_text_sha256": sha256(d2_text.as_bytes()), "grade": 2,
            "evidence_passage_ids": ["doc-2:p:1"], "subtopic_labels": [],
            "provenance": provenance()
        }),
        json!({
            "judgment_set_id": "sdc-smoke-v1", "query_id": "q2", "document_id": "doc-2",
            "document_text_sha256": sha256(d2_text.as_bytes()), "grade": 1,
            "evidence_passage_ids": [], "subtopic_labels": [],
            "provenance": provenance()
        }),
        json!({
            "judgment_set_id": "sdc-smoke-v1", "query_id": "q3", "document_id": "doc-3",
            "document_text_sha256": sha256(d3_text.as_bytes()), "grade": 3,
            "evidence_passage_ids": ["doc-3:p:1"], "subtopic_labels": [],
            "provenance": provenance()
        }),
        json!({
            "judgment_set_id": "sdc-smoke-v1", "query_id": "q4", "document_id": "doc-1",
            "document_text_sha256": sha256(d1_text.as_bytes()), "grade": 0,
            "evidence_passage_ids": [], "subtopic_labels": [],
            "provenance": provenance()
        }),
    ];
    let passage_qrels = [
        json!({
            "judgment_set_id": "sdc-smoke-v1", "query_id": "q1", "document_id": "doc-1",
            "passage_id": "doc-1:p:1", "passage_text_sha256": sha256(b"alpha beta"),
            "grade": 3, "evidence_spans": [], "provenance": provenance()
        }),
        json!({
            "judgment_set_id": "sdc-smoke-v1", "query_id": "q1", "document_id": "doc-2",
            "passage_id": "doc-2:p:1", "passage_text_sha256": sha256(b"alpha beta"),
            "grade": 2, "evidence_spans": [], "provenance": provenance()
        }),
        json!({
            "judgment_set_id": "sdc-smoke-v1", "query_id": "q2", "document_id": "doc-2",
            "passage_id": "doc-2:p:1", "passage_text_sha256": sha256(b"alpha beta"),
            "grade": 1, "evidence_spans": [], "provenance": provenance()
        }),
        json!({
            "judgment_set_id": "sdc-smoke-v1", "query_id": "q3", "document_id": "doc-3",
            "passage_id": "doc-3:p:1", "passage_text_sha256": sha256(b"fn main"),
            "grade": 3, "evidence_spans": [], "provenance": provenance()
        }),
    ];
    write_jsonl(&qrels.join("queries.dev.jsonl"), &query_rows);
    write_jsonl(&qrels.join("qrels.dev.documents.jsonl"), &document_qrels);
    write_jsonl(&qrels.join("qrels.dev.passages.jsonl"), &passage_qrels);
    write(
        &qrels.join("reviewers.json"),
        "{\"reviewer-a\":\"verifier\"}\n",
    );

    write_manifest(&corpus, file_entries);
    write_judgment_manifest(&qrels);
    SdcFixture {
        _dir: dir,
        corpus,
        qrels,
    }
}

fn write_jsonl(path: &Path, rows: &[Value]) {
    let content: String = rows
        .iter()
        .map(|row| format!("{}\n", serde_json::to_string(row).unwrap()))
        .collect();
    write(path, &content);
}

fn write_manifest(corpus: &Path, mut file_entries: Vec<Value>) {
    file_entries.sort_by(|left, right| {
        left["path"]
            .as_str()
            .unwrap_or_default()
            .cmp(right["path"].as_str().unwrap_or_default())
    });
    let sidecars = [
        "corpus.jsonl",
        "passages.jsonl",
        "extraction-truth.jsonl",
        "duplicate-clusters.jsonl",
        "versions.jsonl",
    ]
    .into_iter()
    .map(|name| {
        (
            name.to_owned(),
            sha256(&fs::read(corpus.join(name)).unwrap()),
        )
    })
    .collect::<BTreeMap<_, _>>();
    let default_roots = vec!["files/documents".to_owned()];
    let code_enabled_roots = vec!["files/documents".to_owned(), "files/code".to_owned()];
    let corpus_hash = sha256(
        &serde_json::to_vec(&json!({
            "files": &file_entries,
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
        "document_count": 3,
        "passage_count": 3,
        "default_roots": default_roots,
        "code_enabled_roots": code_enabled_roots,
        "files": file_entries,
        "sidecars": sidecars,
        "corpus_hash": corpus_hash
    });
    write(
        &corpus.join("manifest.json"),
        &serde_json::to_string_pretty(&manifest).unwrap(),
    );
}

fn write_judgment_manifest(qrels: &Path) {
    let mut file_sha256 = BTreeMap::new();
    for name in [
        "queries.dev.jsonl",
        "qrels.dev.documents.jsonl",
        "qrels.dev.passages.jsonl",
    ] {
        file_sha256.insert(
            name.to_owned(),
            sha256(&fs::read(qrels.join(name)).unwrap()),
        );
    }
    let query_hash = file_sha256["queries.dev.jsonl"].clone();
    let manifest = json!({
        "schema_version": 1,
        "judgment_set_id": "sdc-smoke-v1",
        "state": "frozen",
        "split_seed": "sdc-smoke-v1",
        "compatible_corpus_hashes": [corpus_hash(qrels)],
        "query_counts": {"dev": 4, "test": 0},
        "query_file_sha256": {"queries.dev.jsonl": query_hash},
        "file_sha256": file_sha256,
        "test_pool_system_ids": [],
        "supersedes": null,
        "test_exposure": "not-applicable"
    });
    write(
        &qrels.join("judgment-set.json"),
        &serde_json::to_string_pretty(&manifest).unwrap(),
    );
}

fn corpus_hash(qrels: &Path) -> String {
    let corpus = qrels.parent().unwrap().join("corpus");
    let manifest: Value =
        serde_json::from_slice(&fs::read(corpus.join("manifest.json")).unwrap()).unwrap();
    manifest["corpus_hash"].as_str().unwrap().to_owned()
}

#[test]
fn sdc_smoke_loads_with_all_sidecars() {
    let fixture = make_fixture();
    let dataset = load_sdc(
        &fixture.corpus,
        &fixture.qrels,
        Split::Dev,
        EvaluationConfiguration::Default,
    )
    .unwrap();
    assert_eq!(dataset.id, "sdc-smoke");
    assert_eq!(dataset.queries().len(), 3);
    assert!(dataset.document("doc-3").is_none());
    assert_eq!(dataset.duplicate_family("doc-1"), Some("doc-1"));
    assert_eq!(dataset.document_judgments("q1").len(), 2);
    assert_eq!(dataset.document_judgments("q4")[0].grade, 0);
    assert!(dataset.document_judgments("q3").is_empty());
}

#[test]
fn sdc_configuration_filters_documents_and_queries() {
    let fixture = make_fixture();
    let dataset = load_sdc(
        &fixture.corpus,
        &fixture.qrels,
        Split::Dev,
        EvaluationConfiguration::CodeEnabled,
    )
    .unwrap();
    assert_eq!(dataset.queries().len(), 4);
    assert!(dataset.document("doc-3").is_some());
    assert_eq!(dataset.document_judgments("q3").len(), 1);
}

#[test]
fn sdc_rejects_stale_corpus_and_qrel_hashes() {
    let fixture = make_fixture();
    fs::write(fixture.corpus.join("files/documents/doc-1.txt"), "changed").unwrap();
    assert_eq!(
        load_sdc(
            &fixture.corpus,
            &fixture.qrels,
            Split::Dev,
            EvaluationConfiguration::Default
        )
        .unwrap_err()
        .code(),
        "HASH_MISMATCH"
    );

    let fixture = make_fixture();
    let path = fixture.qrels.join("qrels.dev.documents.jsonl");
    let content = fs::read_to_string(&path)
        .unwrap()
        .replace(&sha256(b"alpha beta gamma"), &sha256(b"stale"));
    fs::write(&path, content).unwrap();
    write_judgment_manifest(&fixture.qrels);
    assert_eq!(
        load_sdc(
            &fixture.corpus,
            &fixture.qrels,
            Split::Dev,
            EvaluationConfiguration::Default
        )
        .unwrap_err()
        .code(),
        "HASH_MISMATCH"
    );
}

#[test]
fn sdc_rejects_draft_or_unverified_judgments() {
    let fixture = make_fixture();
    let path = fixture.qrels.join("queries.dev.jsonl");
    let content = fs::read_to_string(&path).unwrap().replacen(
        "\"state\":\"verified\"",
        "\"state\":\"draft\"",
        1,
    );
    fs::write(&path, content).unwrap();
    write_judgment_manifest(&fixture.qrels);
    assert_eq!(
        load_sdc(
            &fixture.corpus,
            &fixture.qrels,
            Split::Dev,
            EvaluationConfiguration::Default
        )
        .unwrap_err()
        .code(),
        "FROZEN_REQUIRED"
    );
}

#[test]
fn sdc_rejects_partial_or_extra_output_files() {
    let fixture = make_fixture();
    write(&fixture.corpus.join("files/documents/extra.txt"), "extra");
    assert_eq!(
        load_sdc(
            &fixture.corpus,
            &fixture.qrels,
            Split::Dev,
            EvaluationConfiguration::Default
        )
        .unwrap_err()
        .code(),
        "SCHEMA"
    );
}

#[test]
fn graded_qrels_validate_evidence_and_hashes() {
    let fixture = make_fixture();
    let path = fixture.qrels.join("qrels.dev.documents.jsonl");
    let content = fs::read_to_string(&path)
        .unwrap()
        .replacen("doc-1:p:1", "missing:p:1", 1);
    fs::write(&path, content).unwrap();
    write_judgment_manifest(&fixture.qrels);
    assert_eq!(
        load_sdc(
            &fixture.corpus,
            &fixture.qrels,
            Split::Dev,
            EvaluationConfiguration::Default
        )
        .unwrap_err()
        .code(),
        "DANGLING_REFERENCE"
    );
}
