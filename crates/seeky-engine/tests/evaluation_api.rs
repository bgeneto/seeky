//! SPEC-0002 v1.1 evaluation-API acceptance tests (section 9.6.1).
//!
//! Hardware-free: lexical engines and a deterministic fake embedder only.

#![allow(clippy::unwrap_used)]

mod common;

use common::{NoopEvents, TestDir, lexical_engine};
use seeky_engine::{
    Backend, CandidateDepths, DeliveryStage, DepthReport, Engine, EngineConfig, EngineError,
    FilterKind, FilterMode, FolderFilter, MetadataFilter, ModelIdentity, QueryEmbeddingProbe,
    SearchMode, SearchOptions, SearchRequest, SearchStage,
};
use seeky_infer::{DIM, Embedder};
use std::error::Error;
use std::fs::FileTimes;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, UNIX_EPOCH};

type TestResult = Result<(), Box<dyn Error>>;

const NEEDLE: &str =
    "The needle appears in this benchmark document so lexical retrieval can find it. ";

fn write(root: &Path, relative: &str, content: &str) -> Result<PathBuf, Box<dyn Error>> {
    let path = root.join(relative);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&path, content)?;
    Ok(path)
}

fn set_modified_secs(path: &Path, secs: u64) -> Result<(), Box<dyn Error>> {
    let file = std::fs::OpenOptions::new().write(true).open(path)?;
    file.set_times(FileTimes::new().set_modified(UNIX_EPOCH + Duration::from_secs(secs)))?;
    Ok(())
}

fn index_corpus(
    test_dir: &TestDir,
    files: &[(&str, &str)],
) -> Result<(Engine, PathBuf), Box<dyn Error>> {
    let corpus = test_dir.join("corpus");
    std::fs::create_dir_all(&corpus)?;
    for (relative, content) in files {
        write(&corpus, relative, content)?;
    }
    let engine = lexical_engine(test_dir, Arc::new(NoopEvents))?;
    engine.index_path(&corpus)?;
    Ok((engine, corpus))
}

fn eval_request(query: &str, limit: usize) -> SearchRequest {
    SearchRequest {
        query: query.to_string(),
        limit: Some(limit),
    }
}

fn eval_options() -> SearchOptions {
    SearchOptions {
        mode: SearchMode::Evaluation,
        filters: None,
        telemetry: false,
    }
}

fn hits_json(hits: &[seeky_engine::SearchHit]) -> String {
    serde_json::to_string(hits).expect("hits serialize")
}

struct FakeEmbedder {
    batches: Arc<Mutex<Vec<usize>>>,
}

impl FakeEmbedder {
    fn new() -> Self {
        Self {
            batches: Arc::new(Mutex::new(Vec::new())),
        }
    }

    fn identity() -> ModelIdentity {
        ModelIdentity {
            task: "embedder".into(),
            id: "fake-embedder".into(),
            revision: "test".into(),
            variant: "fake".into(),
            dimension: Some(DIM as u32),
        }
    }
}

impl Embedder for FakeEmbedder {
    fn info(&self) -> seeky_engine::EngineInfo {
        seeky_engine::EngineInfo {
            backend: "CPU".into(),
            model: "fake".into(),
            device: "in-memory".into(),
            detail: "fake".into(),
        }
    }

    fn identity(&self) -> ModelIdentity {
        Self::identity()
    }

    fn embed(&mut self, texts: &[String]) -> seeky_infer::Result<Vec<Vec<f32>>> {
        self.batches.lock().unwrap().push(texts.len());
        Ok(texts.iter().map(|_| vec![0.25_f32; DIM]).collect())
    }
}

#[allow(clippy::type_complexity)]
fn fake_engine(
    test_dir: &TestDir,
    files: &[(&str, &str)],
) -> Result<(Engine, Arc<Mutex<Vec<usize>>>, PathBuf), Box<dyn Error>> {
    let corpus = test_dir.join("corpus");
    std::fs::create_dir_all(&corpus)?;
    for (relative, content) in files {
        write(&corpus, relative, content)?;
    }
    let fake = FakeEmbedder::new();
    let batches = fake.batches.clone();
    let engine = Engine::open_with_embedder_for_test(
        EngineConfig {
            data_dir: test_dir.join("data"),
            resource_dir: None,
        },
        Arc::new(NoopEvents),
        Box::new(fake),
    )?;
    engine.index_path(&corpus)?;
    Ok((engine, batches, corpus))
}

/// SPEC-0002-R17
#[test]
fn eval_depth_accepts_1000_and_rejects_1001() -> TestResult {
    let test_dir = TestDir::new("eval-depth-bounds")?;
    let (engine, _corpus) = index_corpus(&test_dir, &[("a.txt", NEEDLE)])?;
    for limit in [0, 1_001, usize::MAX] {
        let error = engine
            .search_with(&eval_request("needle", limit), &eval_options())
            .expect_err("out-of-range depth");
        assert!(matches!(error, EngineError::InvalidInput(_)), "{error:?}");
    }
    let error = engine
        .search_with(
            &SearchRequest {
                query: "needle".into(),
                limit: None,
            },
            &eval_options(),
        )
        .expect_err("missing evaluation depth");
    assert!(matches!(error, EngineError::InvalidInput(_)), "{error:?}");
    assert_eq!(
        engine
            .search_with(&eval_request("needle", 1), &eval_options())?
            .response
            .hits
            .len(),
        1
    );
    assert!(
        engine
            .search_with(&eval_request("needle", 1_000), &eval_options())
            .is_ok()
    );
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R17
#[test]
fn eval_depth_fills_requested_hits_when_matches_exist() -> TestResult {
    let test_dir = TestDir::new("eval-depth-fill")?;
    let files: Vec<(String, String)> = (0..120)
        .map(|index| {
            (
                format!("doc-{index:03}.txt"),
                format!("{NEEDLE} document {index}"),
            )
        })
        .collect();
    let refs: Vec<(&str, &str)> = files
        .iter()
        .map(|(name, text)| (name.as_str(), text.as_str()))
        .collect();
    let (engine, _corpus) = index_corpus(&test_dir, &refs)?;
    let outcome = engine.search_with(&eval_request("needle", 100), &eval_options())?;
    assert_eq!(outcome.response.hits.len(), 100);
    assert_eq!(outcome.depth.requested_hits, 100);
    assert_eq!(outcome.depth.returned_hits, 100);
    assert_eq!(outcome.depth.candidate_depths.lexical, 100);
    assert_eq!(outcome.depth.candidate_depths.dense, 0);
    assert!(outcome.depth.candidate_cap_reached);
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R17
#[test]
fn depth_report_counts_distinct_documents_and_cap() -> TestResult {
    let test_dir = TestDir::new("eval-depth-distinct")?;
    let long = format!("{} {}", NEEDLE.repeat(40), NEEDLE.repeat(40));
    let (engine, _corpus) = index_corpus(
        &test_dir,
        &[
            ("one.txt", long.as_str()),
            ("two.txt", NEEDLE),
            ("three.txt", NEEDLE),
        ],
    )?;
    let outcome = engine.search_with(&eval_request("needle", 20), &eval_options())?;
    assert!(outcome.response.hits.len() >= 3);
    assert!(outcome.depth.distinct_documents < outcome.response.hits.len());
    assert!(!outcome.depth.candidate_cap_reached);
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R17, SPEC-0002-R25
#[test]
fn interactive_search_keeps_v1_depth_clamp() -> TestResult {
    let test_dir = TestDir::new("interactive-clamp")?;
    let files: Vec<(String, String)> = (0..60)
        .map(|index| (format!("doc-{index:02}.txt"), format!("{NEEDLE} {index}")))
        .collect();
    let refs: Vec<(&str, &str)> = files
        .iter()
        .map(|(name, text)| (name.as_str(), text.as_str()))
        .collect();
    let (engine, _corpus) = index_corpus(&test_dir, &refs)?;
    for (limit, expected) in [(None, 20), (Some(100), 50), (Some(0), 1), (Some(1_000), 50)] {
        let response = engine.search(&SearchRequest {
            query: "needle".into(),
            limit,
        })?;
        assert_eq!(response.hits.len(), expected, "limit={limit:?}");
    }
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R18
#[test]
fn repeated_search_is_byte_identical() -> TestResult {
    let test_dir = TestDir::new("repeat-identical")?;
    let (engine, _corpus) = index_corpus(
        &test_dir,
        &[
            ("a.txt", NEEDLE),
            ("b.txt", &format!("{NEEDLE} second")),
            ("c.txt", &format!("{NEEDLE} third")),
        ],
    )?;
    let first = engine.search_with(&eval_request("needle", 10), &eval_options())?;
    let expected = hits_json(&first.response.hits);
    for _ in 0..3 {
        let next = engine.search_with(&eval_request("needle", 10), &eval_options())?;
        assert_eq!(expected, hits_json(&next.response.hits));
    }
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R19
#[test]
fn telemetry_records_each_executed_stage_once() -> TestResult {
    let test_dir = TestDir::new("telemetry-stages")?;
    let (engine, _batches, _corpus) = fake_engine(
        &test_dir,
        &[("a.txt", NEEDLE), ("b.txt", &format!("{NEEDLE} second"))],
    )?;
    let outcome = engine.search_with(
        &eval_request("needle", 10),
        &SearchOptions {
            telemetry: true,
            ..eval_options()
        },
    )?;
    let telemetry = outcome.telemetry.expect("telemetry");
    assert_eq!(
        telemetry
            .stages
            .iter()
            .map(|stage| stage.stage)
            .collect::<Vec<_>>(),
        vec![
            SearchStage::Filename,
            SearchStage::Lexical,
            SearchStage::Dense,
            SearchStage::Fuse,
            SearchStage::Snippets,
        ]
    );
    assert!(telemetry.total_ns > 0);
    assert!(telemetry.query_embedding.is_some());
    assert_eq!(telemetry.results_requested, 10);
    assert_eq!(telemetry.results_returned, outcome.response.hits.len());
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R19
#[test]
fn telemetry_does_not_change_hits_or_filter_outcome() -> TestResult {
    let test_dir = TestDir::new("telemetry-no-change")?;
    let (engine, _batches, _corpus) = fake_engine(
        &test_dir,
        &[("a.txt", NEEDLE), ("b.md", &format!("{NEEDLE} second"))],
    )?;
    let filter = MetadataFilter {
        extensions: vec!["txt".into()],
        ..MetadataFilter::default()
    };
    let request = eval_request("needle", 10);
    let plain = engine.search_with(
        &request,
        &SearchOptions {
            filters: Some(filter.clone()),
            ..eval_options()
        },
    )?;
    let traced = engine.search_with(
        &request,
        &SearchOptions {
            filters: Some(filter),
            telemetry: true,
            ..eval_options()
        },
    )?;
    assert_eq!(
        hits_json(&plain.response.hits),
        hits_json(&traced.response.hits)
    );
    assert_eq!(plain.filter, traced.filter);
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R19, SPEC-0002-R25
#[test]
fn telemetry_omits_query_document_and_path_fields() -> TestResult {
    let test_dir = TestDir::new("telemetry-privacy")?;
    let (engine, _batches, corpus) = fake_engine(&test_dir, &[("private-name.txt", NEEDLE)])?;
    let outcome = engine.search_with(
        &eval_request("private-query-term", 10),
        &SearchOptions {
            telemetry: true,
            ..eval_options()
        },
    )?;
    let telemetry = outcome.telemetry.expect("telemetry");
    let debug = format!("{telemetry:?}");
    assert!(!debug.contains("private-query-term"));
    assert!(!debug.contains("private-name"));
    for hit in &outcome.response.hits {
        assert!(!debug.contains(&hit.doc_id));
        assert!(!debug.contains(&hit.path));
    }
    assert!(!debug.contains(&corpus.to_string_lossy().to_string()));
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R19
#[test]
fn telemetry_emits_single_delivery_stage_only() -> TestResult {
    let test_dir = TestDir::new("telemetry-delivery")?;
    let (engine, _corpus) = index_corpus(&test_dir, &[("a.txt", NEEDLE)])?;
    let outcome = engine.search_with(
        &eval_request("needle", 5),
        &SearchOptions {
            telemetry: true,
            ..eval_options()
        },
    )?;
    let telemetry = outcome.telemetry.expect("telemetry");
    assert_eq!(telemetry.schema_version, 1);
    assert_eq!(telemetry.delivery_stage, DeliveryStage::Single);
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R20
#[test]
fn query_embedding_probe_is_batch_one_and_uncached() -> TestResult {
    let test_dir = TestDir::new("probe-batch-one")?;
    let (engine, batches, _corpus) = fake_engine(&test_dir, &[("a.txt", NEEDLE)])?;
    batches.lock().unwrap().clear();
    let probe = engine.probe_query_embedding("first probe")?;
    match probe {
        QueryEmbeddingProbe::Available { model, duration_ns } => {
            assert_eq!(model.id, FakeEmbedder::identity().id);
            assert!(duration_ns > 0);
        }
        QueryEmbeddingProbe::Unavailable => panic!("fake embedder is available"),
    }
    assert_eq!(*batches.lock().unwrap(), vec![1]);
    engine.probe_query_embedding("second probe")?;
    assert_eq!(*batches.lock().unwrap(), vec![1, 1]);
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R20
#[test]
fn query_embedding_probe_reports_unavailable_without_model() -> TestResult {
    let test_dir = TestDir::new("probe-unavailable")?;
    let (engine, _corpus) = index_corpus(&test_dir, &[("a.txt", NEEDLE)])?;
    assert!(matches!(
        engine.probe_query_embedding("anything")?,
        QueryEmbeddingProbe::Unavailable
    ));
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R20
#[test]
fn query_embedding_probe_does_not_change_search_results() -> TestResult {
    let test_dir = TestDir::new("probe-no-change")?;
    let (engine, _batches, _corpus) = fake_engine(
        &test_dir,
        &[("a.txt", NEEDLE), ("b.txt", &format!("{NEEDLE} b"))],
    )?;
    let before = engine.search_with(&eval_request("needle", 10), &eval_options())?;
    engine.probe_query_embedding("another query")?;
    let after = engine.search_with(&eval_request("needle", 10), &eval_options())?;
    assert_eq!(
        hits_json(&before.response.hits),
        hits_json(&after.response.hits)
    );
    engine.shutdown()?;
    Ok(())
}

fn metadata_corpus(test_dir: &TestDir) -> Result<(Engine, PathBuf), Box<dyn Error>> {
    let corpus = test_dir.join("corpus");
    std::fs::create_dir_all(&corpus)?;
    let files = [
        ("a.txt", format!("{NEEDLE} alpha")),
        ("b.md", format!("{NEEDLE} beta")),
        ("c.csv", format!("{NEEDLE} gamma")),
        ("a/b/c.txt", format!("{NEEDLE} nested")),
        ("a/bc.txt", format!("{NEEDLE} prefix only")),
        ("a/b/c/d.txt", format!("{NEEDLE} deeper")),
        ("other/e.txt", format!("{NEEDLE} outside")),
    ];
    for (relative, content) in files {
        write(&corpus, relative, &content)?;
    }
    let engine = lexical_engine(test_dir, Arc::new(NoopEvents))?;
    engine.index_path(&corpus)?;
    Ok((engine, corpus))
}

fn filtered(
    engine: &Engine,
    filter: MetadataFilter,
) -> Result<seeky_engine::SearchOutcome, EngineError> {
    engine.search_with(
        &eval_request("needle", 50),
        &SearchOptions {
            filters: Some(filter),
            ..eval_options()
        },
    )
}

fn relative_paths(outcome: &seeky_engine::SearchOutcome, root: &Path) -> Vec<String> {
    let root = std::fs::canonicalize(root).unwrap_or_else(|_| root.to_path_buf());
    let mut paths: Vec<String> = outcome
        .response
        .hits
        .iter()
        .map(|hit| {
            Path::new(&hit.path)
                .strip_prefix(&root)
                .expect("hit under root")
                .to_string_lossy()
                .replace('\\', "/")
        })
        .collect();
    paths.sort();
    paths.dedup();
    paths
}

/// SPEC-0002-R21
#[test]
fn extension_filter_matches_case_insensitively_and_exactly() -> TestResult {
    let test_dir = TestDir::new("filter-extension")?;
    let (engine, corpus) = metadata_corpus(&test_dir)?;
    for token in ["txt", "TXT"] {
        let outcome = filtered(
            &engine,
            MetadataFilter {
                extensions: vec![token.into()],
                ..MetadataFilter::default()
            },
        )?;
        assert_eq!(
            relative_paths(&outcome, &corpus),
            vec![
                "a.txt".to_string(),
                "a/b/c.txt".to_string(),
                "a/b/c/d.txt".to_string(),
                "a/bc.txt".to_string(),
                "other/e.txt".to_string()
            ],
            "token={token}"
        );
    }
    let markdown = filtered(
        &engine,
        MetadataFilter {
            extensions: vec!["md".into()],
            ..MetadataFilter::default()
        },
    )?;
    assert_eq!(relative_paths(&markdown, &corpus), vec!["b.md".to_string()]);
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R21
#[test]
fn modified_filter_uses_inclusive_after_and_exclusive_before() -> TestResult {
    let test_dir = TestDir::new("filter-modified")?;
    let corpus = test_dir.join("corpus");
    std::fs::create_dir_all(&corpus)?;
    let t0 = 1_000_000_000_u64;
    let t1 = t0 + 100;
    let t2 = t0 + 200;
    let files = [
        ("early.txt", format!("{NEEDLE} early"), t0),
        ("middle.txt", format!("{NEEDLE} middle"), t1),
        ("late.txt", format!("{NEEDLE} late"), t2),
    ];
    for (name, content, seconds) in &files {
        let path = write(&corpus, name, content)?;
        set_modified_secs(&path, *seconds)?;
    }
    let engine = lexical_engine(&test_dir, Arc::new(NoopEvents))?;
    engine.index_path(&corpus)?;
    let t1_ns = (t1 as i64) * 1_000_000_000;
    let t2_ns = (t2 as i64) * 1_000_000_000;

    let after = filtered(
        &engine,
        MetadataFilter {
            modified_after_ns: Some(t1_ns),
            ..MetadataFilter::default()
        },
    )?;
    assert_eq!(
        relative_paths(&after, &corpus),
        vec!["late.txt".to_string(), "middle.txt".to_string()]
    );
    let before = filtered(
        &engine,
        MetadataFilter {
            modified_before_ns: Some(t1_ns),
            ..MetadataFilter::default()
        },
    )?;
    assert_eq!(
        relative_paths(&before, &corpus),
        vec!["early.txt".to_string()]
    );
    let window = filtered(
        &engine,
        MetadataFilter {
            modified_after_ns: Some(t1_ns),
            modified_before_ns: Some(t2_ns),
            ..MetadataFilter::default()
        },
    )?;
    assert_eq!(
        relative_paths(&window, &corpus),
        vec!["middle.txt".to_string()]
    );
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R21
#[test]
fn folder_filter_matches_complete_root_relative_segments() -> TestResult {
    let test_dir = TestDir::new("filter-folder")?;
    let (engine, corpus) = metadata_corpus(&test_dir)?;
    let canonical = std::fs::canonicalize(&corpus)?;
    let root = engine
        .list_roots()?
        .into_iter()
        .find(|root| Path::new(&root.path) == canonical)
        .expect("corpus root");
    let outcome = filtered(
        &engine,
        MetadataFilter {
            folder: Some(FolderFilter {
                root_id: root.id,
                relative_prefix: "a/b/".into(),
            }),
            ..MetadataFilter::default()
        },
    )?;
    assert_eq!(
        relative_paths(&outcome, &corpus),
        vec!["a/b/c.txt".to_string(), "a/b/c/d.txt".to_string()]
    );
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R21
#[test]
fn size_filter_uses_inclusive_bounds() -> TestResult {
    let test_dir = TestDir::new("filter-size")?;
    let corpus = test_dir.join("corpus");
    std::fs::create_dir_all(&corpus)?;
    let small = format!("{NEEDLE} s");
    let large = format!("{NEEDLE} long long long long");
    let small_path = write(&corpus, "small.txt", &small)?;
    let large_path = write(&corpus, "large.txt", &large)?;
    let small_len = std::fs::metadata(&small_path)?.len();
    let large_len = std::fs::metadata(&large_path)?.len();
    let engine = lexical_engine(&test_dir, Arc::new(NoopEvents))?;
    engine.index_path(&corpus)?;
    let exact = filtered(
        &engine,
        MetadataFilter {
            min_bytes: Some(small_len),
            max_bytes: Some(small_len),
            ..MetadataFilter::default()
        },
    )?;
    assert_eq!(
        relative_paths(&exact, &corpus),
        vec!["small.txt".to_string()]
    );
    let at_least = filtered(
        &engine,
        MetadataFilter {
            min_bytes: Some(large_len),
            ..MetadataFilter::default()
        },
    )?;
    assert_eq!(
        relative_paths(&at_least, &corpus),
        vec!["large.txt".to_string()]
    );
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R21
#[test]
fn combined_filters_are_conjunctive() -> TestResult {
    let test_dir = TestDir::new("filter-combined")?;
    let (engine, corpus) = metadata_corpus(&test_dir)?;
    let canonical = std::fs::canonicalize(&corpus)?;
    let root = engine
        .list_roots()?
        .into_iter()
        .find(|root| Path::new(&root.path) == canonical)
        .expect("corpus root");
    let outcome = filtered(
        &engine,
        MetadataFilter {
            extensions: vec!["txt".into()],
            folder: Some(FolderFilter {
                root_id: root.id,
                relative_prefix: "a/b/".into(),
            }),
            ..MetadataFilter::default()
        },
    )?;
    assert_eq!(
        relative_paths(&outcome, &corpus),
        vec!["a/b/c.txt".to_string(), "a/b/c/d.txt".to_string()]
    );
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R21, SPEC-0002-R25
#[test]
fn interactive_filters_are_rejected() -> TestResult {
    let test_dir = TestDir::new("filter-interactive")?;
    let (engine, _corpus) = index_corpus(&test_dir, &[("a.txt", NEEDLE)])?;
    let error = engine
        .search_with(
            &eval_request("needle", 10),
            &SearchOptions {
                mode: SearchMode::Interactive,
                filters: Some(MetadataFilter {
                    extensions: vec!["txt".into()],
                    ..MetadataFilter::default()
                }),
                telemetry: false,
            },
        )
        .expect_err("interactive filters rejected");
    assert!(matches!(error, EngineError::InvalidInput(_)), "{error:?}");
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R22
#[test]
fn filter_report_records_pushdown_and_post_per_predicate() -> TestResult {
    let test_dir = TestDir::new("filter-report")?;
    let (engine, _corpus) = metadata_corpus(&test_dir)?;
    let outcome = filtered(
        &engine,
        MetadataFilter {
            extensions: vec!["txt".into()],
            modified_after_ns: Some(1),
            ..MetadataFilter::default()
        },
    )?;
    let report = outcome.filter.expect("filter report");
    assert_eq!(report.mode, FilterMode::Pushdown);
    assert_eq!(
        report
            .applications
            .iter()
            .map(|application| application.kind)
            .collect::<Vec<_>>(),
        vec![FilterKind::Extension, FilterKind::Modified]
    );
    assert!(
        report
            .applications
            .iter()
            .all(|application| application.mode == FilterMode::Pushdown)
    );
    assert_eq!(report.examined, report.matched);
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R22
#[test]
fn filtered_search_at_exhausted_depth_is_complete() -> TestResult {
    let test_dir = TestDir::new("filter-complete")?;
    let (engine, _corpus) = index_corpus(
        &test_dir,
        &[
            ("a.txt", NEEDLE),
            ("b.txt", &format!("{NEEDLE} b")),
            ("c.md", &format!("{NEEDLE} c")),
        ],
    )?;
    let outcome = filtered(
        &engine,
        MetadataFilter {
            extensions: vec!["txt".into()],
            ..MetadataFilter::default()
        },
    )?;
    let report = outcome.filter.expect("filter report");
    assert_eq!(report.returned, 2);
    assert!(!outcome.depth.candidate_cap_reached);
    assert!(!report.possibly_incomplete);
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R22
#[test]
fn filtered_search_with_no_matches_is_empty_success() -> TestResult {
    let test_dir = TestDir::new("filter-empty")?;
    let (engine, _corpus) = index_corpus(&test_dir, &[("a.txt", NEEDLE)])?;
    let outcome = filtered(
        &engine,
        MetadataFilter {
            extensions: vec!["json".into()],
            ..MetadataFilter::default()
        },
    )?;
    assert!(outcome.response.hits.is_empty());
    let report = outcome.filter.expect("filter report");
    assert_eq!(report.returned, 0);
    assert!(!report.possibly_incomplete);
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R23
#[test]
fn missing_filter_metadata_is_metadata_unavailable() -> TestResult {
    let test_dir = TestDir::new("filter-missing-metadata")?;
    let corpus = test_dir.join("corpus");
    std::fs::create_dir_all(&corpus)?;
    let path = write(&corpus, "zero-time.txt", NEEDLE)?;
    set_modified_secs(&path, 0)?;
    let engine = lexical_engine(&test_dir, Arc::new(NoopEvents))?;
    engine.index_path(&corpus)?;
    let error = filtered(
        &engine,
        MetadataFilter {
            modified_after_ns: Some(1),
            ..MetadataFilter::default()
        },
    )
    .expect_err("missing modified metadata");
    assert!(
        matches!(&error, EngineError::MetadataUnavailable(field) if field == "modified"),
        "{error:?}"
    );
    assert!(
        !error
            .to_string()
            .contains(&corpus.to_string_lossy().to_string())
    );
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R23
#[test]
fn malformed_filter_is_invalid_input() -> TestResult {
    let test_dir = TestDir::new("filter-malformed")?;
    let (engine, _corpus) = index_corpus(&test_dir, &[("a.txt", NEEDLE)])?;
    let malformed = [
        MetadataFilter::default(),
        MetadataFilter {
            extensions: vec![".pdf".into()],
            ..MetadataFilter::default()
        },
        MetadataFilter {
            modified_after_ns: Some(2),
            modified_before_ns: Some(2),
            ..MetadataFilter::default()
        },
        MetadataFilter {
            min_bytes: Some(2),
            max_bytes: Some(1),
            ..MetadataFilter::default()
        },
        MetadataFilter {
            folder: Some(FolderFilter {
                root_id: engine
                    .list_roots()?
                    .first()
                    .expect("indexed root")
                    .id
                    .clone(),
                relative_prefix: "../escape/".into(),
            }),
            ..MetadataFilter::default()
        },
    ];
    for filter in malformed {
        let error = filtered(&engine, filter).expect_err("malformed filter");
        assert!(matches!(error, EngineError::InvalidInput(_)), "{error:?}");
    }
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R23
#[test]
fn unknown_filter_root_is_not_found() -> TestResult {
    let test_dir = TestDir::new("filter-unknown-root")?;
    let (engine, _corpus) = index_corpus(&test_dir, &[("a.txt", NEEDLE)])?;
    let error = filtered(
        &engine,
        MetadataFilter {
            folder: Some(FolderFilter {
                root_id: "no-such-root".into(),
                relative_prefix: "a/".into(),
            }),
            ..MetadataFilter::default()
        },
    )
    .expect_err("unknown root");
    assert!(matches!(error, EngineError::NotFound(_)), "{error:?}");
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R23, SPEC-0002-R25
#[test]
fn filter_error_names_field_not_path() -> TestResult {
    let test_dir = TestDir::new("filter-field-name")?;
    let corpus = test_dir.join("corpus");
    std::fs::create_dir_all(&corpus)?;
    let path = write(&corpus, "no-extension-metadata.txt", NEEDLE)?;
    set_modified_secs(&path, 0)?;
    let engine = lexical_engine(&test_dir, Arc::new(NoopEvents))?;
    engine.index_path(&corpus)?;
    let error = filtered(
        &engine,
        MetadataFilter {
            modified_before_ns: Some(i64::MAX),
            ..MetadataFilter::default()
        },
    )
    .expect_err("missing metadata");
    let message = error.to_string();
    assert!(message.contains("modified"), "{message}");
    assert!(!message.contains("no-extension-metadata"));
    assert!(!message.contains(&corpus.to_string_lossy().to_string()));
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R24
#[test]
fn config_snapshot_is_canonical_and_stable() -> TestResult {
    let test_dir = TestDir::new("snapshot-canonical")?;
    let (engine, _corpus) = index_corpus(&test_dir, &[("a.txt", NEEDLE)])?;
    let first = engine.config_snapshot()?;
    let second = engine.config_snapshot()?;
    assert_eq!(first.canonical_json(), second.canonical_json());
    assert_eq!(first.sha256(), second.sha256());
    let json = first.canonical_json();
    assert!(!json.contains('\n'));
    assert!(!json.contains(": "));
    assert!(json.starts_with("{\"execution\":"));
    assert!(json.contains("\"models\":[]"));
    assert_eq!(first.sha256().len(), 64);
    assert!(first.sha256().chars().all(|c| c.is_ascii_hexdigit()));
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R24
#[test]
fn config_snapshot_is_path_independent() -> TestResult {
    let first_dir = TestDir::new("snapshot-path-a")?;
    let second_dir = TestDir::new("snapshot-path-b")?;
    let (first, _) = index_corpus(&first_dir, &[("a.txt", NEEDLE)])?;
    let (second, _) = index_corpus(&second_dir, &[("b.txt", NEEDLE)])?;
    assert_eq!(
        first.config_snapshot()?.canonical_json(),
        second.config_snapshot()?.canonical_json()
    );
    first.shutdown()?;
    second.shutdown()?;
    Ok(())
}

/// SPEC-0002-R24
#[test]
fn config_snapshot_changes_when_semantic_setting_changes() -> TestResult {
    let test_dir = TestDir::new("snapshot-setting")?;
    let (engine, _corpus) = index_corpus(&test_dir, &[("a.txt", NEEDLE)])?;
    let before = engine.config_snapshot()?;
    engine.set_backend(Backend::Npu)?;
    let after = engine.config_snapshot()?;
    assert_ne!(before.sha256(), after.sha256());
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R24
#[test]
fn config_snapshot_requires_active_model_hash() -> TestResult {
    let test_dir = TestDir::new("snapshot-model-hash")?;
    let model_root = test_dir.join("missing-model");
    std::fs::create_dir_all(model_root.join("onnx"))?;
    let engine = Engine::open_with_model_root_for_test(
        EngineConfig {
            data_dir: test_dir.join("data"),
            resource_dir: None,
        },
        Arc::new(NoopEvents),
        Some(model_root),
    )?;
    let error = engine.config_snapshot().expect_err("missing model bytes");
    assert!(
        matches!(&error, EngineError::MetadataUnavailable(field) if field == "model.sha256"),
        "{error:?}"
    );
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R24
#[test]
fn config_snapshot_hashes_active_model_bytes() -> TestResult {
    let test_dir = TestDir::new("snapshot-model-bytes")?;
    let model_root = test_dir.join("model");
    std::fs::create_dir_all(model_root.join("onnx"))?;
    let model_file = model_root.join("onnx").join("model_uint8.onnx");
    std::fs::write(&model_file, b"first-model-bytes")?;
    let engine = Engine::open_with_model_root_for_test(
        EngineConfig {
            data_dir: test_dir.join("data"),
            resource_dir: None,
        },
        Arc::new(NoopEvents),
        Some(model_root.clone()),
    )?;
    let first = engine.config_snapshot()?;
    std::fs::write(&model_file, b"second-model-bytes")?;
    let second = engine.config_snapshot()?;
    assert_ne!(first.sha256(), second.sha256());
    assert!(first.canonical_json().contains("\"sha256\":\""));
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R24, SPEC-0002-R25
#[test]
fn config_snapshot_contains_no_paths_or_user_data() -> TestResult {
    let test_dir = TestDir::new("snapshot-privacy")?;
    let (engine, corpus) = index_corpus(&test_dir, &[("a.txt", NEEDLE)])?;
    let json = engine.config_snapshot()?.canonical_json();
    assert!(!json.contains(&corpus.to_string_lossy().to_string()));
    assert!(!json.contains(&test_dir.0.to_string_lossy().to_string()));
    assert!(!json.contains("\\\\?\\"));
    assert!(!json.contains("a.txt"));
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R25
#[test]
fn v1_search_results_and_payload_are_unchanged() -> TestResult {
    let test_dir = TestDir::new("v1-payload")?;
    let (engine, _corpus) = index_corpus(
        &test_dir,
        &[
            ("a.txt", NEEDLE),
            ("b.txt", &format!("{NEEDLE} b")),
            ("c.md", &format!("{NEEDLE} c")),
        ],
    )?;
    let request = SearchRequest {
        query: "needle".into(),
        limit: Some(10),
    };
    let v1 = engine.search(&request)?;
    let with = engine.search_with(&request, &SearchOptions::default())?;
    assert_eq!(hits_json(&v1.hits), hits_json(&with.response.hits));
    assert_eq!(v1.backend, with.response.backend);
    assert_eq!(v1.semantic_used, with.response.semantic_used);
    let payload = serde_json::to_value(&v1)?;
    let keys: Vec<&str> = payload
        .as_object()
        .expect("object")
        .keys()
        .map(String::as_str)
        .collect();
    assert_eq!(keys, vec!["backend", "hits", "semantic_used", "took_ms"]);
    let hit = payload["hits"][0].as_object().expect("hit object");
    assert!(hit.contains_key("chunk_id"));
    assert!(hit.contains_key("doc_id"));
    assert!(hit.contains_key("snippet"));
    assert!(hit.contains_key("start"));
    assert!(hit.contains_key("end"));
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R25
#[test]
fn new_outputs_contain_no_content_or_paths() -> TestResult {
    let test_dir = TestDir::new("new-outputs-privacy")?;
    let (engine, _batches, corpus) = fake_engine(
        &test_dir,
        &[("secret-name.txt", "secret-query-token content here")],
    )?;
    let outcome = engine.search_with(
        &eval_request("secret-query-token", 5),
        &SearchOptions {
            telemetry: true,
            filters: Some(MetadataFilter {
                extensions: vec!["txt".into()],
                ..MetadataFilter::default()
            }),
            ..eval_options()
        },
    )?;
    let debug = format!(
        "{:?}{:?}{:?}",
        outcome.depth, outcome.filter, outcome.telemetry
    );
    assert!(!debug.contains("secret-query-token"));
    assert!(!debug.contains("secret-name"));
    assert!(!debug.contains(&corpus.to_string_lossy().to_string()));
    let depth: &DepthReport = &outcome.depth;
    assert_eq!(depth.candidate_depths.filename, 40);
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R25 (inspection)
#[test]
fn v1_1_methods_are_not_shell_commands() -> TestResult {
    let shell = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("apps/desktop/src-tauri/src");
    let mut sources = String::new();
    for entry in std::fs::read_dir(&shell)? {
        let entry = entry?;
        let path = entry.path();
        if path.extension().and_then(|value| value.to_str()) == Some("rs") {
            sources.push_str(&std::fs::read_to_string(&path)?);
        }
    }
    for forbidden in ["search_with", "probe_query_embedding", "config_snapshot"] {
        assert!(
            !sources.contains(forbidden),
            "{forbidden} leaked into the shell"
        );
    }
    Ok(())
}

/// Static assertion that the new types remain usable from `seeky-engine`.
#[test]
fn evaluation_types_are_reexported() {
    fn assert_send_sync_clone<T: Send + Sync + Clone>() {}
    assert_send_sync_clone::<MetadataFilter>();
    assert_send_sync_clone::<FolderFilter>();
    let _ = CandidateDepths::default();
}
