//! BEIR loader acceptance tests (SPEC-0003 R2/R14).

#![allow(clippy::unwrap_used)] // Test helpers are outside #[test] functions.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use seeky_eval::{EvalError, Split, load_beir};
use serde_json::json;
use sha2::{Digest, Sha256};
use tempfile::TempDir;

struct BeirFixture {
    _dir: TempDir,
    root: PathBuf,
    manifest: PathBuf,
}

fn sha256(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn write(path: &Path, content: &str) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, content).unwrap();
}

fn make_fixture(empty_title: bool, crlf: bool) -> BeirFixture {
    let dir = TempDir::new().unwrap();
    let root = dir.path().join("dataset");
    let newline = if crlf { "\r\n" } else { "\n" };
    let title = if empty_title { "" } else { "Title" };
    let corpus = format!(
        "{{\"_id\":\"d1\",\"title\":\"{title}\",\"text\":\"alpha beta\",\"metadata\":{{\"relative_path\":\"data/files/{}.txt\"}}}}{newline}{{\"_id\":\"d2\",\"title\":\"Other\",\"text\":\"gamma\",\"metadata\":{{\"relative_path\":\"data/files/{}.txt\"}}}}{newline}",
        sha256(b"d1"),
        sha256(b"d2")
    );
    let queries_dev = format!(
        "{{\"_id\":\"q1\",\"text\":\"alpha\",\"metadata\":{{\"language\":\"en\",\"language_slice\":\"en\",\"category\":\"conceptual\"}}}}{newline}{{\"_id\":\"q2\",\"text\":\"gama\",\"metadata\":{{\"language\":\"pt\",\"language_slice\":\"pt\"}}}}{newline}"
    );
    let queries_test = format!(
        "{{\"_id\":\"q1\",\"text\":\"alpha\"}}{newline}{{\"_id\":\"q2\",\"text\":\"gama\"}}{newline}"
    );
    let qrels_dev =
        format!("query-id\tcorpus-id\tscore{newline}q1\td1\t3{newline}q1\td2\t1{newline}");
    let qrels_test = format!("query-id\tcorpus-id\tscore{newline}q1\td1\t1{newline}");
    write(&root.join("data/corpus.jsonl"), &corpus);
    write(&root.join("data/queries.dev.jsonl"), &queries_dev);
    write(&root.join("data/queries.test.jsonl"), &queries_test);
    write(&root.join("data/qrels.dev.tsv"), &qrels_dev);
    write(&root.join("data/qrels.test.tsv"), &qrels_test);
    write(
        &root.join(format!("data/files/{}.txt", sha256(b"d1"))),
        "alpha beta",
    );
    write(
        &root.join(format!("data/files/{}.txt", sha256(b"d2"))),
        "gamma",
    );
    let mut local = BTreeMap::new();
    let mut paths = vec![
        "data/corpus.jsonl".to_owned(),
        "data/queries.dev.jsonl".to_owned(),
        "data/queries.test.jsonl".to_owned(),
        "data/qrels.dev.tsv".to_owned(),
        "data/qrels.test.tsv".to_owned(),
    ];
    paths.push(format!("data/files/{}.txt", sha256(b"d1")));
    paths.push(format!("data/files/{}.txt", sha256(b"d2")));
    for relative in paths {
        let bytes = fs::read(root.join(&relative)).unwrap();
        local.insert(relative, sha256(&bytes));
    }
    let manifest = json!({
        "schema_version": 1,
        "dataset_id": "fixture",
        "layout": "beir",
        "visibility": "public",
        "license": {
            "id": "CC-BY-4.0",
            "url": "https://example.invalid/license",
            "redistribution": "download-only",
            "terms_url": "https://example.invalid/terms"
        },
        "source": {
            "revision": "r1",
            "urls": ["https://example.invalid/source"],
            "sha256": ["0".repeat(64)]
        },
        "corpus": "data/corpus.jsonl",
        "files_root": "data/files",
        "splits": {
            "dev": {"queries": "data/queries.dev.jsonl", "qrels": "data/qrels.dev.tsv"},
            "test": {"queries": "data/queries.test.jsonl", "qrels": "data/qrels.test.tsv"}
        },
        "query_defaults": {
            "language_slice": "en",
            "category": "conceptual",
            "configuration": "default"
        },
        "transform": {"script": "tools/dataset-fetch", "version": 1, "seed": "s"},
        "local_file_sha256": local
    });
    let manifest_path = root.join("manifest.json");
    fs::write(
        &manifest_path,
        serde_json::to_vec_pretty(&manifest).unwrap(),
    )
    .unwrap();
    BeirFixture {
        _dir: dir,
        root,
        manifest: manifest_path,
    }
}

fn refresh_hash(fixture: &BeirFixture, relative: &str) {
    let hash = sha256(&fs::read(fixture.root.join(relative)).unwrap());
    let mut value: serde_json::Value =
        serde_json::from_slice(&fs::read(&fixture.manifest).unwrap()).unwrap();
    value["local_file_sha256"][relative] = serde_json::Value::String(hash);
    fs::write(
        &fixture.manifest,
        serde_json::to_vec_pretty(&value).unwrap(),
    )
    .unwrap();
}

#[test]
fn beir_loads_reference_layout() {
    let fixture = make_fixture(false, false);
    let dataset = load_beir(&fixture.manifest, Split::Dev).unwrap();
    assert_eq!(dataset.id, "fixture");
    assert_eq!(dataset.queries().len(), 2);
    assert_eq!(dataset.document("d1").unwrap().text, "alpha beta");
    assert_eq!(dataset.document_judgments("q1").len(), 2);
    assert_eq!(dataset.document_judgments("q1")[0].grade, 3);
    assert!(dataset.document_judgments("q2").is_empty());
    assert_eq!(dataset.queries()[1].language_slice.as_str(), "pt");
    assert_eq!(dataset.query_set_sha256().len(), 64);
}

#[test]
fn beir_rejects_bad_header_duplicates_dangling_and_grades() {
    let fixture = make_fixture(false, false);
    write(
        &fixture.root.join("data/qrels.dev.tsv"),
        "wrong\theader\nq1\td1\t3\n",
    );
    refresh_hash(&fixture, "data/qrels.dev.tsv");
    assert_eq!(
        load_beir(&fixture.manifest, Split::Dev).unwrap_err().code(),
        "TSV"
    );

    let fixture = make_fixture(false, false);
    write(
        &fixture.root.join("data/qrels.dev.tsv"),
        "query-id\tcorpus-id\tscore\nq1\td1\t5\n",
    );
    refresh_hash(&fixture, "data/qrels.dev.tsv");
    assert!(load_beir(&fixture.manifest, Split::Dev).is_err());

    let fixture = make_fixture(false, false);
    write(
        &fixture.root.join("data/qrels.dev.tsv"),
        "query-id\tcorpus-id\tscore\nq1\tdX\t2\n",
    );
    refresh_hash(&fixture, "data/qrels.dev.tsv");
    assert_eq!(
        load_beir(&fixture.manifest, Split::Dev).unwrap_err().code(),
        "DANGLING_REFERENCE"
    );
}

#[test]
fn beir_duplicate_and_dangling_ids_are_rejected() {
    let fixture = make_fixture(false, false);
    write(
        &fixture.root.join("data/qrels.dev.tsv"),
        "query-id\tcorpus-id\tscore\nq1\td1\t2\nq1\td1\t3\n",
    );
    refresh_hash(&fixture, "data/qrels.dev.tsv");
    assert_eq!(
        load_beir(&fixture.manifest, Split::Dev).unwrap_err().code(),
        "DUPLICATE_ID"
    );

    let fixture = make_fixture(false, false);
    let corpus = format!(
        "{{\"_id\":\"d1\",\"title\":\"A\",\"text\":\"alpha beta\",\"metadata\":{{\"relative_path\":\"data/files/{}.txt\"}}}}\n{{\"_id\":\"d1\",\"title\":\"B\",\"text\":\"gamma\",\"metadata\":{{\"relative_path\":\"data/files/{}.txt\"}}}}\n",
        sha256(b"d1"),
        sha256(b"d2")
    );
    write(&fixture.root.join("data/corpus.jsonl"), &corpus);
    refresh_hash(&fixture, "data/corpus.jsonl");
    assert_eq!(
        load_beir(&fixture.manifest, Split::Dev).unwrap_err().code(),
        "DUPLICATE_ID"
    );
}

#[test]
fn beir_crlf_and_empty_titles_are_handled() {
    let fixture = make_fixture(true, true);
    let dataset = load_beir(&fixture.manifest, Split::Dev).unwrap();
    assert_eq!(dataset.document("d1").unwrap().title, "");
    assert_eq!(dataset.queries().len(), 2);
}

#[test]
fn beir_files_mapping_matches_corpus_text() {
    let fixture = make_fixture(false, false);
    let relative = format!("data/files/{}.txt", sha256(b"d1"));
    write(&fixture.root.join(&relative), "different text");
    refresh_hash(&fixture, &relative);
    let error = load_beir(&fixture.manifest, Split::Dev).unwrap_err();
    assert_eq!(error.code(), "HASH_MISMATCH");
}

#[test]
fn jsonl_and_tsv_readers_never_panic_on_arbitrary_bytes() {
    let fixture = make_fixture(false, false);
    let mut state = 0x2468_ace0_u64;
    for index in 0..32 {
        let mut bytes = Vec::new();
        for _ in 0..(index * 13) {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            bytes.push((state >> 16) as u8);
        }
        fs::write(fixture.root.join("data/corpus.jsonl"), &bytes).unwrap();
        refresh_hash(&fixture, "data/corpus.jsonl");
        let _ = load_beir(&fixture.manifest, Split::Dev);
        fs::write(fixture.root.join("data/qrels.dev.tsv"), &bytes).unwrap();
        refresh_hash(&fixture, "data/qrels.dev.tsv");
        let _ = load_beir(&fixture.manifest, Split::Dev);
    }
}

#[test]
fn harness_never_panics_on_malformed_inputs() {
    let dir = TempDir::new().unwrap();
    let mut state = 0x1234_5678_u64;
    for index in 0..64 {
        let path = dir.path().join(format!("bad-{index}.json"));
        let mut bytes = vec![0x7b];
        for _ in 0..(index * 7) {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            bytes.push((state >> 32) as u8);
        }
        fs::write(&path, bytes).unwrap();
        let result = load_beir(&path, Split::Dev);
        assert!(result.is_err());
        if let Err(EvalError::Data { location, .. }) = result {
            assert!(!location.is_empty());
        }
    }
}
