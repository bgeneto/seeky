#![allow(dead_code)]

use anyhow::{Context, Result, anyhow};
use seeky_lib::db::{self, ChunkInput, FileSignature};
use seeky_lib::indexer::{self, IndexContext, PreparedFile};
use seeky_lib::inference::{Backend, Engine, find_gety_model_root, resolve_npu_dir};
use seeky_lib::search::{self, SearchHit};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

const POC_COMMIT: &str = "5943bc61a3354978fe93750af71c1a3a3d16eb44";
const CAPTURE_ENV: &str = "SEEKY_CAPTURE_GOLDEN";
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

struct CaptureContext<'a> {
    conn: &'a mut rusqlite::Connection,
    engine: Option<&'a mut Engine>,
}

impl IndexContext for CaptureContext<'_> {
    fn signature(&mut self, _root_id: &str, path: &Path) -> Result<Option<FileSignature>> {
        db::document_signature(self.conn, path)
    }

    fn embed(&mut self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        match self.engine.as_deref_mut() {
            Some(engine) => engine.embed(texts),
            None => Ok(texts.iter().map(|_| Vec::new()).collect()),
        }
    }

    fn store(
        &mut self,
        root_id: &str,
        prepared: &PreparedFile,
        chunks: &[ChunkInput],
    ) -> Result<usize> {
        let lexical_chunks;
        let chunks = if self.engine.is_none() {
            lexical_chunks = chunks
                .iter()
                .cloned()
                .map(|chunk| ChunkInput {
                    embedding: None,
                    ..chunk
                })
                .collect::<Vec<_>>();
            &lexical_chunks
        } else {
            chunks
        };
        db::upsert_document(
            self.conn,
            root_id,
            &prepared.path,
            &prepared.title,
            &prepared.ext,
            prepared.size,
            prepared.modified,
            prepared.modified_ns,
            &prepared.content,
            chunks,
        )
    }

    fn prune_missing(&mut self, root_id: &str, keep: &[PathBuf]) -> Result<usize> {
        db::prune_missing(self.conn, root_id, keep)
    }
}

struct TestDir(PathBuf);

impl TestDir {
    fn new(mode: Mode) -> Result<Self> {
        let path = std::env::temp_dir().join(format!(
            "seeky-poc-golden-{}-{}",
            mode.name(),
            std::process::id()
        ));
        if path.exists() {
            std::fs::remove_dir_all(&path).context("remove previous golden test directory")?;
        }
        std::fs::create_dir_all(&path).context("create golden test directory")?;
        Ok(Self(path))
    }
}

impl Drop for TestDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn repo_path(relative: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .join(relative)
}

fn snapshot_path(mode: Mode) -> PathBuf {
    repo_path(&format!(
        "crates/seeky-engine/tests/golden/{}.json",
        mode.name()
    ))
}

fn relative_path(hit: &SearchHit, root: &Path) -> Result<String> {
    let path = Path::new(&hit.path)
        .strip_prefix(root)
        .with_context(|| format!("search result is outside the demo root: {}", hit.path))?;
    Ok(path.to_string_lossy().replace('\\', "/"))
}

pub fn capture_or_verify(mode: Mode) -> Result<()> {
    let test_dir = TestDir::new(mode)?;
    let demo = std::fs::canonicalize(repo_path("apps/desktop/demo"))
        .context("resolve committed demo corpus")?;
    let pdfium = match mode {
        Mode::Lexical => test_dir.0.join("missing").join("pdfium.dll"),
        Mode::HybridCpu => PathBuf::from(
            std::env::var("LOCALAPPDATA").context("LOCALAPPDATA is needed for local PDFium")?,
        )
        .join("Gety")
        .join("lib")
        .join("pdfium.dll"),
    };
    let mut conn = db::open(&test_dir.0.join("seeky.db")).context("open capture database")?;
    let root = db::add_root(&conn, demo.to_str().context("demo path is not UTF-8")?)
        .context("add demo root")?;
    let model_root = match mode {
        Mode::Lexical => None,
        Mode::HybridCpu => Some(find_gety_model_root().context("find local Gety model")?),
    };
    let npu_dir = resolve_npu_dir(None);
    let mut engine = match (mode, model_root) {
        (Mode::HybridCpu, Some(model_root)) => Some(
            Engine::create(Backend::Cpu, &model_root, &npu_dir).context("create CPU embedder")?,
        ),
        _ => None,
    };

    {
        let mut context = CaptureContext {
            conn: &mut conn,
            engine: engine.as_mut(),
        };
        let mut progress = |_| {};
        indexer::index_root(&mut context, &root, &pdfium, &mut progress)
            .context("index demo corpus")?;
    }

    let root_path = Path::new(&root.path);
    let mut queries = Vec::with_capacity(QUERIES.len());
    for query in QUERIES {
        let query_vector = match engine.as_mut() {
            Some(engine) => engine
                .embed(&[(*query).to_string()])
                .context("embed golden query")?
                .pop(),
            None => None,
        };
        let hits = search::search(&conn, query, query_vector.as_deref(), 20)
            .with_context(|| format!("run golden query {query:?}"))?;
        let hits = hits
            .iter()
            .enumerate()
            .map(|(index, hit)| {
                Ok(HitSnapshot {
                    rank: index + 1,
                    path: relative_path(hit, root_path)?,
                    start: hit.start,
                    end: hit.end,
                    page: hit.page,
                    matched: hit.matched.clone(),
                    score: hit.score,
                })
            })
            .collect::<Result<Vec<_>>>()?;
        queries.push(QuerySnapshot {
            query: (*query).to_string(),
            hits,
        });
    }

    let actual = Snapshot {
        poc_commit: POC_COMMIT.to_string(),
        backend: mode.backend().to_string(),
        seeky_version: env!("CARGO_PKG_VERSION").to_string(),
        queries,
    };
    let path = snapshot_path(mode);
    if std::env::var_os(CAPTURE_ENV).is_some() {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).context("create golden snapshot directory")?;
        }
        let json = serde_json::to_string_pretty(&actual).context("serialize golden snapshot")?;
        std::fs::write(&path, format!("{json}\n")).context("write golden snapshot")?;
        return Ok(());
    }

    let json = std::fs::read_to_string(&path).with_context(|| {
        format!(
            "read golden snapshot {}; run the PoC capture first",
            path.display()
        )
    })?;
    let expected: Snapshot = serde_json::from_str(&json).context("parse golden snapshot")?;
    compare(mode, &expected, &actual)
}

fn compare(mode: Mode, expected: &Snapshot, actual: &Snapshot) -> Result<()> {
    if expected.poc_commit != actual.poc_commit
        || expected.backend != actual.backend
        || expected.seeky_version != actual.seeky_version
        || expected.queries.len() != actual.queries.len()
    {
        return Err(anyhow!("golden snapshot header or query count changed"));
    }
    for (expected_query, actual_query) in expected.queries.iter().zip(&actual.queries) {
        if expected_query.query != actual_query.query
            || expected_query.hits.len() != actual_query.hits.len()
        {
            return Err(anyhow!(
                "golden result count changed for {:?}: expected {}, got {}",
                expected_query.query,
                expected_query.hits.len(),
                actual_query.hits.len()
            ));
        }
        compare_hits(mode, expected_query, actual_query)?;
    }
    Ok(())
}

fn compare_hits(mode: Mode, expected: &QuerySnapshot, actual: &QuerySnapshot) -> Result<()> {
    let mut start = 0;
    while start < expected.hits.len() {
        let mut end = start + 1;
        while end < expected.hits.len()
            && (expected.hits[end].score - expected.hits[start].score).abs() <= mode.tolerance()
        {
            end += 1;
        }
        let mut used = vec![false; end - start];
        for (offset, expected_hit) in expected.hits[start..end].iter().enumerate() {
            let rank = start + offset + 1;
            let mut found = None;
            for (actual_offset, actual_hit) in actual.hits[start..end].iter().enumerate() {
                if !used[actual_offset]
                    && expected_hit.path == actual_hit.path
                    && expected_hit.start == actual_hit.start
                    && expected_hit.end == actual_hit.end
                    && expected_hit.page == actual_hit.page
                    && expected_hit.matched == actual_hit.matched
                    && (expected_hit.score - actual_hit.score).abs() <= mode.tolerance()
                {
                    found = Some(actual_offset);
                    break;
                }
            }
            let Some(actual_offset) = found else {
                return Err(anyhow!(
                    "golden rank {rank} changed for {:?}: expected {expected_hit:?}, actual group {:?}",
                    expected.query,
                    &actual.hits[start..end]
                ));
            };
            used[actual_offset] = true;
            if actual.hits[start + actual_offset].rank != rank
                && expected.hits[start..end]
                    .iter()
                    .any(|hit| (hit.score - expected_hit.score).abs() > mode.tolerance())
            {
                return Err(anyhow!("golden rank changed without a score tie"));
            }
        }
        start = end;
    }
    Ok(())
}
