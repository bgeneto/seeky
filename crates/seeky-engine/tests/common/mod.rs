#![allow(dead_code)]
#![allow(clippy::unwrap_used)]

use seeky_engine::{Engine, EngineConfig, EngineEvents, IndexHealth, IndexProgress, SearchRequest};
use serde::{Deserialize, Serialize};
use std::error::Error;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

pub type TestResult = Result<(), Box<dyn Error>>;

const POC_COMMIT: &str = "5943bc61a3354978fe93750af71c1a3a3d16eb44";
const QUERIES: &[&str] = &[
    "renewal",
    "written notice",
    "annual budget",
    "semantic chunks",
    "sample",
    "budget OR (atlas*",
    "contrato",
    "orçamento anual",
    "Renovação",
    "local documents",
    "thirty days",
    "zzyzx quaternion",
];

#[derive(Clone, Copy)]
pub enum Mode {
    Lexical,
    HybridCpu,
}

impl Mode {
    fn name(self) -> &'static str {
        match self {
            Self::Lexical => "lexical",
            Self::HybridCpu => "hybrid-cpu",
        }
    }

    fn backend(self) -> &'static str {
        match self {
            Self::Lexical => "lexical-only",
            Self::HybridCpu => "CPU",
        }
    }

    fn tolerance(self) -> f64 {
        match self {
            Self::Lexical => 1e-9,
            Self::HybridCpu => 1e-6,
        }
    }
}

#[derive(Debug, Serialize, Deserialize)]
struct Snapshot {
    poc_commit: String,
    backend: String,
    seeky_version: String,
    queries: Vec<QuerySnapshot>,
}

#[derive(Debug, Serialize, Deserialize)]
struct QuerySnapshot {
    query: String,
    hits: Vec<HitSnapshot>,
}

#[derive(Debug, Serialize, Deserialize)]
struct HitSnapshot {
    rank: usize,
    path: String,
    start: i64,
    end: i64,
    page: Option<i64>,
    matched: Vec<String>,
    score: f64,
}

pub struct NoopEvents;

impl EngineEvents for NoopEvents {
    fn index_progress(&self, _progress: &IndexProgress) {}

    fn index_health(&self, _health: &IndexHealth) {}
}

#[derive(Default)]
pub struct RecordingEvents {
    pub progress: Mutex<Vec<IndexProgress>>,
    pub health: Mutex<Vec<IndexHealth>>,
    engine: OnceLock<Engine>,
    cancel_next_progress: AtomicBool,
    active_indexing: AtomicUsize,
    max_active_indexing: AtomicUsize,
}

impl RecordingEvents {
    pub fn attach(&self, engine: Engine) {
        let _ = self.engine.set(engine);
    }

    pub fn cancel_on_next_progress(&self) {
        self.cancel_next_progress.store(true, Ordering::SeqCst);
    }

    pub fn max_active_indexing(&self) -> usize {
        self.max_active_indexing.load(Ordering::SeqCst)
    }
}

impl EngineEvents for RecordingEvents {
    fn index_progress(&self, progress: &IndexProgress) {
        self.progress.lock().unwrap().push(progress.clone());
        if self.cancel_next_progress.swap(false, Ordering::SeqCst)
            && let Some(engine) = self.engine.get()
        {
            engine.cancel_indexing();
        }
    }

    fn index_health(&self, health: &IndexHealth) {
        self.health.lock().unwrap().push(health.clone());
        if health.indexing {
            let active = self.active_indexing.fetch_add(1, Ordering::SeqCst) + 1;
            self.max_active_indexing.fetch_max(active, Ordering::SeqCst);
        } else {
            let _ = self
                .active_indexing
                .try_update(Ordering::SeqCst, Ordering::SeqCst, |active| {
                    Some(active.saturating_sub(1))
                });
        }
    }
}

static NEXT_TEST_DIR: AtomicUsize = AtomicUsize::new(0);

pub struct TestDir(pub PathBuf);

impl TestDir {
    pub fn new(name: &str) -> Result<Self, Box<dyn Error>> {
        let sequence = NEXT_TEST_DIR.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "seeky-engine-{name}-{}-{sequence}",
            std::process::id()
        ));
        if path.exists() {
            std::fs::remove_dir_all(&path)?;
        }
        std::fs::create_dir_all(&path)?;
        Ok(Self(path))
    }

    pub fn join(&self, path: &str) -> PathBuf {
        self.0.join(path)
    }
}

impl Drop for TestDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

pub fn repo_path(relative: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(relative)
}

pub fn config(test_dir: &TestDir) -> EngineConfig {
    EngineConfig {
        data_dir: test_dir.join("data"),
        resource_dir: None,
    }
}

pub fn lexical_engine(
    test_dir: &TestDir,
    events: Arc<dyn EngineEvents>,
) -> Result<Engine, Box<dyn Error>> {
    Ok(Engine::open_lexical_for_test(config(test_dir), events)?)
}

pub fn write_documents(root: &Path, count: usize) -> Result<(), Box<dyn Error>> {
    std::fs::create_dir_all(root)?;
    for index in 0..count {
        std::fs::write(
            root.join(format!("document-{index:02}.txt")),
            format!(
                "Document {index} contains a private-document-token and enough text for lexical indexing."
            ),
        )?;
    }
    Ok(())
}

pub fn run_golden(mode: Mode) -> TestResult {
    let test_dir = TestDir::new(mode.name())?;
    let demo = std::fs::canonicalize(repo_path("apps/desktop/demo"))?;
    let events = Arc::new(NoopEvents);
    let engine = match mode {
        Mode::Lexical => lexical_engine(&test_dir, events)?,
        Mode::HybridCpu => {
            let engine = Engine::open(config(&test_dir), events)?;
            engine.set_backend(seeky_engine::Backend::Cpu)?;
            engine
        }
    };
    engine.index_path(&demo)?;

    let mut queries = Vec::with_capacity(QUERIES.len());
    for query in QUERIES {
        let response = engine.search(&SearchRequest {
            query: (*query).to_string(),
            limit: Some(20),
        })?;
        match mode {
            Mode::Lexical => assert!(!response.semantic_used),
            Mode::HybridCpu => assert!(response.semantic_used),
        }
        let hits = response
            .hits
            .iter()
            .enumerate()
            .map(|(index, hit)| {
                let path = Path::new(&hit.path).strip_prefix(&demo)?;
                Ok(HitSnapshot {
                    rank: index + 1,
                    path: path.to_string_lossy().replace('\\', "/"),
                    start: hit.start,
                    end: hit.end,
                    page: hit.page,
                    matched: hit.matched.clone(),
                    score: hit.score,
                })
            })
            .collect::<Result<Vec<_>, std::path::StripPrefixError>>()?;
        queries.push(QuerySnapshot {
            query: (*query).to_string(),
            hits,
        });
    }
    engine.shutdown()?;

    let actual = Snapshot {
        poc_commit: POC_COMMIT.to_string(),
        backend: mode.backend().to_string(),
        seeky_version: env!("CARGO_PKG_VERSION").to_string(),
        queries,
    };
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("golden")
        .join(format!("{}.json", mode.name()));
    let json = std::fs::read_to_string(path)?;
    let expected: Snapshot = serde_json::from_str(&json)?;
    compare(mode, &expected, &actual)
}

fn compare(mode: Mode, expected: &Snapshot, actual: &Snapshot) -> TestResult {
    assert_eq!(expected.poc_commit, actual.poc_commit);
    assert_eq!(expected.backend, actual.backend);
    assert_eq!(expected.seeky_version, actual.seeky_version);
    assert_eq!(expected.queries.len(), actual.queries.len());
    for (expected_query, actual_query) in expected.queries.iter().zip(&actual.queries) {
        assert_eq!(expected_query.query, actual_query.query);
        assert_eq!(
            expected_query.hits.len(),
            actual_query.hits.len(),
            "result count changed for {:?}",
            expected_query.query
        );
        compare_hits(mode, expected_query, actual_query)?;
    }
    Ok(())
}

fn compare_hits(mode: Mode, expected: &QuerySnapshot, actual: &QuerySnapshot) -> TestResult {
    let mut start = 0;
    while start < expected.hits.len() {
        let mut end = start + 1;
        while end < expected.hits.len()
            && (expected.hits[end].score - expected.hits[start].score).abs() <= mode.tolerance()
        {
            end += 1;
        }
        let mut used = vec![false; end - start];
        for expected_hit in &expected.hits[start..end] {
            let found = actual.hits[start..end]
                .iter()
                .enumerate()
                .find(|(actual_offset, actual_hit)| {
                    !used[*actual_offset]
                        && expected_hit.path == actual_hit.path
                        && expected_hit.start == actual_hit.start
                        && expected_hit.end == actual_hit.end
                        && expected_hit.page == actual_hit.page
                        && expected_hit.matched == actual_hit.matched
                        && (expected_hit.score - actual_hit.score).abs() <= mode.tolerance()
                })
                .map(|(actual_offset, _)| actual_offset);
            let Some(actual_offset) = found else {
                return Err(format!(
                    "golden ranking changed for {:?}: expected {expected_hit:?}, actual group {:?}",
                    expected.query,
                    &actual.hits[start..end]
                )
                .into());
            };
            used[actual_offset] = true;
        }
        start = end;
    }
    for (index, hit) in actual.hits.iter().enumerate() {
        assert_eq!(hit.rank, index + 1);
    }
    Ok(())
}
