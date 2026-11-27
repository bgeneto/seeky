use crate::Result;
use crate::indexer::{self, IndexContext, PreparedFile};
use notify::event::{ModifyKind, RenameMode};
use notify::{Event, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use seeky_core::{
    Backend, DocId, EngineInfo, EngineStatus, FileSignature, IndexHealth, IndexProgress,
    IndexSummary, Root, RootId, SearchRequest, SearchResponse,
};
use seeky_infer::{
    Engine as InferenceEngine, available_backends, find_gety_model_root, resolve_npu_dir,
};
use seeky_store::{self as db, ChunkInput};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

macro_rules! internal {
    ($($argument:tt)*) => {
        EngineError::Internal(format!($($argument)*))
    };
}

#[derive(Debug, thiserror::Error)]
pub enum EngineError {
    #[error("not found: {0}")]
    NotFound(String),
    #[error("invalid input: {0}")]
    InvalidInput(String),
    #[error("model unavailable: {0}")]
    ModelUnavailable(String),
    #[error("storage error: {0}")]
    Storage(#[from] seeky_store::Error),
    #[error("inference error: {0}")]
    Inference(#[from] seeky_infer::Error),
    #[error("extraction error: {0}")]
    Extraction(#[from] seeky_extract::Error),
    #[error("watcher error: {0}")]
    Watcher(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("internal error: {0}")]
    Internal(String),
}

impl From<seeky_core::Error> for EngineError {
    fn from(error: seeky_core::Error) -> Self {
        Self::InvalidInput(error.to_string())
    }
}

#[derive(Clone, Debug)]
pub struct EngineConfig {
    pub data_dir: PathBuf,
    pub resource_dir: Option<PathBuf>,
}

#[derive(Clone, Debug)]
pub struct ResolvedEngineConfig {
    pub data_dir: PathBuf,
    pub db_path: PathBuf,
    pub model_root: Option<PathBuf>,
    pub npu_dir: PathBuf,
    pub pdfium_dll: PathBuf,
}

impl EngineConfig {
    pub fn resolve(&self) -> Result<ResolvedEngineConfig> {
        Ok(ResolvedEngineConfig {
            db_path: self.data_dir.join("seeky.db"),
            model_root: find_gety_model_root().ok(),
            npu_dir: resolve_npu_dir(self.resource_dir.as_deref()),
            pdfium_dll: get_pdfium_path(),
            data_dir: self.data_dir.clone(),
        })
    }
}

pub trait EngineEvents: Send + Sync + 'static {
    fn index_progress(&self, progress: &IndexProgress);
    fn index_health(&self, health: &IndexHealth);
}

#[derive(Clone)]
pub struct Engine {
    inner: Arc<Inner>,
}

struct Inner {
    db: Arc<Mutex<db::Connection>>,
    engine: Arc<Mutex<Option<InferenceEngine>>>,
    backend: Arc<Mutex<Backend>>,
    watcher: Arc<WatchManager>,
    health: Arc<Mutex<IndexHealth>>,
    index_lock: Arc<Mutex<()>>,
    cancel_index: Arc<AtomicBool>,
    model_root: Option<PathBuf>,
    npu_dir: PathBuf,
    pdfium_dll: PathBuf,
    db_path: PathBuf,
    events: Arc<dyn EngineEvents>,
    watch_worker: Mutex<Option<std::thread::JoinHandle<()>>>,
    test_lexical: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum ChangeKind {
    Upsert,
    Remove,
}

#[derive(Clone, Debug)]
struct WatchChange {
    root_id: String,
    path: PathBuf,
    kind: ChangeKind,
}

enum WatchMessage {
    Fs { root_id: String, event: Event },
    Error { root_id: String, message: String },
    Shutdown,
}

struct WatchManager {
    watchers: Mutex<HashMap<String, RecommendedWatcher>>,
    tx: Sender<WatchMessage>,
    pending: Arc<AtomicUsize>,
}

impl WatchManager {
    fn new(tx: Sender<WatchMessage>) -> Self {
        Self {
            watchers: Mutex::new(HashMap::new()),
            tx,
            pending: Arc::new(AtomicUsize::new(0)),
        }
    }

    fn start(&self, root: &Root) -> Result<()> {
        if !root.watch_enabled {
            return Ok(());
        }
        let mut watchers = self
            .watchers
            .lock()
            .map_err(|_| internal!("watcher lock poisoned"))?;
        if watchers.contains_key(&root.id) {
            return Ok(());
        }

        let tx = self.tx.clone();
        let pending = self.pending.clone();
        let root_id = root.id.clone();
        let root_id_for_error = root_id.clone();
        let mut watcher =
            notify::recommended_watcher(move |result: notify::Result<Event>| match result {
                Ok(event) => {
                    pending.fetch_add(1, Ordering::Relaxed);
                    let _ = tx.send(WatchMessage::Fs {
                        root_id: root_id.clone(),
                        event,
                    });
                }
                Err(err) => {
                    let _ = tx.send(WatchMessage::Error {
                        root_id: root_id_for_error.clone(),
                        message: err.to_string(),
                    });
                }
            })
            .map_err(|error| EngineError::Watcher(format!("create filesystem watcher: {error}")))?;
        watcher
            .watch(Path::new(&root.path), RecursiveMode::Recursive)
            .map_err(|error| EngineError::Watcher(format!("watch {}: {error}", root.path)))?;
        watchers.insert(root.id.clone(), watcher);
        Ok(())
    }

    fn stop(&self, root_id: &str) {
        if let Ok(mut watchers) = self.watchers.lock() {
            watchers.remove(root_id);
        }
    }

    fn stop_all(&self) {
        if let Ok(mut watchers) = self.watchers.lock() {
            watchers.clear();
        }
    }

    fn count(&self) -> usize {
        self.watchers
            .lock()
            .map(|watchers| watchers.len())
            .unwrap_or(0)
    }

    fn pending(&self) -> usize {
        self.pending.load(Ordering::Relaxed)
    }
}

struct AppIndexContext<'a> {
    state: &'a Inner,
}

impl IndexContext for AppIndexContext<'_> {
    fn signature(&mut self, _root_id: &str, path: &Path) -> Result<Option<FileSignature>> {
        let conn = self
            .state
            .db
            .lock()
            .map_err(|_| internal!("db lock poisoned"))?;
        Ok(db::document_signature(&conn, path)?)
    }

    fn embed(&mut self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        if self.state.test_lexical {
            return Ok(texts.iter().map(|_| Vec::new()).collect());
        }
        ensure_engine(self.state)?;
        let mut engine = self
            .state
            .engine
            .lock()
            .map_err(|_| internal!("engine lock poisoned"))?;
        Ok(engine
            .as_mut()
            .ok_or_else(|| internal!("engine not initialized"))?
            .embed(texts)?)
    }

    fn store(
        &mut self,
        root_id: &str,
        prepared: &PreparedFile,
        chunks: &[ChunkInput],
    ) -> Result<usize> {
        let mut conn = self
            .state
            .db
            .lock()
            .map_err(|_| internal!("db lock poisoned"))?;
        let lexical_chunks;
        let chunks = if self.state.test_lexical {
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
        Ok(db::upsert_document(
            &mut conn,
            root_id,
            &prepared.path,
            &prepared.title,
            &prepared.ext,
            prepared.size,
            prepared.modified,
            prepared.modified_ns,
            &prepared.content,
            chunks,
        )?)
    }

    fn prune_missing(&mut self, root_id: &str, keep: &[PathBuf]) -> Result<usize> {
        let conn = self
            .state
            .db
            .lock()
            .map_err(|_| internal!("db lock poisoned"))?;
        Ok(db::prune_missing(&conn, root_id, keep)?)
    }

    fn cancelled(&self) -> bool {
        self.state.cancel_index.load(Ordering::Relaxed)
    }
}

fn get_pdfium_path() -> PathBuf {
    if let Ok(path) = std::env::var("SEEKY_PDFIUM_DLL") {
        return PathBuf::from(path);
    }
    std::env::var("LOCALAPPDATA")
        .map(|path| {
            PathBuf::from(path)
                .join("Gety")
                .join("lib")
                .join("pdfium.dll")
        })
        .unwrap_or_else(|_| PathBuf::from("pdfium.dll"))
}

fn backend_from_state(state: &Inner) -> Result<Backend> {
    Ok(*state
        .backend
        .lock()
        .map_err(|_| internal!("backend lock poisoned"))?)
}

fn ensure_engine(state: &Inner) -> Result<()> {
    let mut engine = state
        .engine
        .lock()
        .map_err(|_| internal!("engine lock poisoned"))?;
    if engine.is_some() {
        return Ok(());
    }
    let model_root = state.model_root.as_ref().ok_or_else(|| {
        EngineError::ModelUnavailable("gety-embed-v0 not found; set SEEKY_GETY_MODEL_DIR".into())
    })?;
    let backend = backend_from_state(state)?;
    *engine = Some(InferenceEngine::create(
        backend,
        model_root,
        &state.npu_dir,
    )?);
    Ok(())
}

fn update_health(state: &Inner, update: impl FnOnce(&mut IndexHealth)) {
    let Ok(mut health) = state.health.lock() else {
        return;
    };
    update(&mut health);
    health.pending = state.watcher.pending();
    health.watched_roots = state.watcher.count();
    health.watching = health.watched_roots > 0;
    let payload = health.clone();
    drop(health);
    state.events.index_health(&payload);
}

fn status_of(state: &Inner) -> Result<EngineStatus> {
    let conn = state.db.lock().map_err(|_| internal!("db lock poisoned"))?;
    let roots = db::list_roots(&conn)?;
    let counts = db::counts(&conn)?;
    drop(conn);
    let backend = backend_from_state(state)?;
    let engine = state
        .engine
        .lock()
        .map_err(|_| internal!("engine lock poisoned"))?
        .as_ref()
        .map(InferenceEngine::info);
    let available = available_backends(state.model_root.as_deref(), &state.npu_dir);
    let mut health = state
        .health
        .lock()
        .map_err(|_| internal!("health lock poisoned"))?
        .clone();
    health.pending = state.watcher.pending();
    health.watched_roots = state.watcher.count();
    health.watching = health.watched_roots > 0;
    Ok(EngineStatus {
        roots,
        counts,
        backend: backend.label().to_ascii_lowercase(),
        backend_label: engine
            .as_ref()
            .map(|engine| engine.backend.clone())
            .unwrap_or_else(|| backend.label().to_string()),
        available_backends: available,
        engine,
        model_root: state
            .model_root
            .as_ref()
            .map(|path| path.to_string_lossy().to_string()),
        npu_model: state.npu_dir.to_string_lossy().to_string(),
        pdfium: state.pdfium_dll.to_string_lossy().to_string(),
        db_path: state.db_path.to_string_lossy().to_string(),
        model_ready: state.model_root.is_some(),
        health,
    })
}

impl Engine {
    #[allow(clippy::needless_pass_by_value)] // SPEC-0002 section 4.2 takes the config by value
    pub fn open(config: EngineConfig, events: Arc<dyn EngineEvents>) -> Result<Engine> {
        Self::open_resolved(config.resolve()?, events, false)
    }

    #[doc(hidden)]
    #[allow(clippy::needless_pass_by_value)] // matches the production constructor
    pub fn open_lexical_for_test(
        config: EngineConfig,
        events: Arc<dyn EngineEvents>,
    ) -> Result<Engine> {
        let mut resolved = config.resolve()?;
        resolved.model_root = None;
        resolved.pdfium_dll = resolved.data_dir.join("missing-pdfium.dll");
        Self::open_resolved(resolved, events, true)
    }

    fn open_resolved(
        config: ResolvedEngineConfig,
        events: Arc<dyn EngineEvents>,
        test_lexical: bool,
    ) -> Result<Engine> {
        std::fs::create_dir_all(&config.data_dir).ok();
        let conn = db::open(&config.db_path)?;
        let backend = db::get_setting(&conn, "backend")
            .ok()
            .flatten()
            .and_then(|value| Backend::parse(&value).ok())
            .unwrap_or(Backend::Auto);
        let last_indexed = db::last_indexed_at(&conn).ok().flatten();
        let roots = db::list_roots(&conn).unwrap_or_default();
        let (watch_tx, watch_rx) = mpsc::channel();
        let watcher = Arc::new(WatchManager::new(watch_tx));
        let health = Arc::new(Mutex::new(IndexHealth {
            last_indexed_at: last_indexed,
            ..IndexHealth::default()
        }));
        let inner = Arc::new(Inner {
            db: Arc::new(Mutex::new(conn)),
            engine: Arc::new(Mutex::new(None)),
            backend: Arc::new(Mutex::new(backend)),
            watcher,
            health,
            index_lock: Arc::new(Mutex::new(())),
            cancel_index: Arc::new(AtomicBool::new(false)),
            model_root: config.model_root,
            npu_dir: config.npu_dir,
            pdfium_dll: config.pdfium_dll,
            db_path: config.db_path,
            events,
            watch_worker: Mutex::new(None),
            test_lexical,
        });
        let engine = Engine { inner };
        let worker = spawn_watch_worker(engine.inner.clone(), watch_rx)?;
        *engine
            .inner
            .watch_worker
            .lock()
            .map_err(|_| internal!("watch worker lock poisoned"))? = Some(worker);

        let mut watcher_errors = Vec::new();
        for root in roots {
            if root.watch_enabled
                && let Err(err) = engine.inner.watcher.start(&root)
            {
                watcher_errors.push(format!("{}: {err}", root.path));
                if let Ok(conn) = engine.inner.db.lock() {
                    let _ = db::set_root_watching(&conn, &root.id, false);
                }
            }
        }
        update_health(&engine.inner, |health| {
            health.last_message = Some(if watcher_errors.is_empty() {
                "Watcher ready".into()
            } else {
                "Some folders could not be watched".into()
            });
            if let Some(error) = watcher_errors.first() {
                health.last_error = Some(error.clone());
                health.details = watcher_errors.iter().take(12).cloned().collect();
            }
        });
        Ok(engine)
    }

    pub fn status(&self) -> Result<EngineStatus> {
        status_of(&self.inner)
    }

    pub fn add_root(&self, path: &Path) -> Result<Root> {
        let path = path
            .to_str()
            .ok_or_else(|| EngineError::InvalidInput("root path is not UTF-8".into()))?;
        let mut root = {
            let conn = self
                .inner
                .db
                .lock()
                .map_err(|_| internal!("db lock poisoned"))?;
            db::add_root(&conn, path)?
        };

        if root.watch_enabled
            && let Err(err) = self.inner.watcher.start(&root)
        {
            if let Ok(conn) = self.inner.db.lock() {
                let _ = db::set_root_watching(&conn, &root.id, false);
            }
            root.watch_enabled = false;
            update_health(&self.inner, |health| {
                health.last_error = Some(format!("watching {}: {err}", root.path));
            });
        }
        update_health(&self.inner, |_| {});
        Ok(root)
    }

    pub fn remove_root(&self, id: &RootId) -> Result<()> {
        self.inner.watcher.stop(id);
        {
            let conn = self
                .inner
                .db
                .lock()
                .map_err(|_| internal!("db lock poisoned"))?;
            db::remove_root(&conn, id)?;
        }
        update_health(&self.inner, |_| {});
        Ok(())
    }

    pub fn list_roots(&self) -> Result<Vec<Root>> {
        let conn = self
            .inner
            .db
            .lock()
            .map_err(|_| internal!("db lock poisoned"))?;
        Ok(db::list_roots(&conn)?)
    }

    pub fn set_root_watching(&self, id: &RootId, enabled: bool) -> Result<Root> {
        {
            let conn = self
                .inner
                .db
                .lock()
                .map_err(|_| internal!("db lock poisoned"))?;
            db::set_root_watching(&conn, id, enabled)?;
        }
        let root = {
            let conn = self
                .inner
                .db
                .lock()
                .map_err(|_| internal!("db lock poisoned"))?;
            db::get_root(&conn, id)?
                .ok_or_else(|| EngineError::NotFound("folder not found".into()))?
        };

        if enabled {
            if let Err(err) = self.inner.watcher.start(&root) {
                if let Ok(conn) = self.inner.db.lock() {
                    let _ = db::set_root_watching(&conn, id, false);
                }
                update_health(&self.inner, |health| {
                    health.last_error = Some(format!("watching {}: {err}", root.path));
                });
                return Err(err);
            }
        } else {
            self.inner.watcher.stop(id);
        }
        update_health(&self.inner, |_| {});
        let conn = self
            .inner
            .db
            .lock()
            .map_err(|_| internal!("db lock poisoned"))?;
        db::get_root(&conn, id)?.ok_or_else(|| EngineError::NotFound("folder not found".into()))
    }

    pub fn set_backend(&self, backend: Backend) -> Result<EngineStatus> {
        self.select_backend(backend, &backend.label().to_ascii_lowercase())
    }

    pub fn set_backend_from_str(&self, backend: &str) -> Result<EngineStatus> {
        let parsed = Backend::parse(backend)?;
        self.select_backend(parsed, backend)
    }

    fn select_backend(&self, backend: Backend, setting: &str) -> Result<EngineStatus> {
        *self
            .inner
            .backend
            .lock()
            .map_err(|_| internal!("backend lock poisoned"))? = backend;
        *self
            .inner
            .engine
            .lock()
            .map_err(|_| internal!("engine lock poisoned"))? = None;
        {
            let conn = self
                .inner
                .db
                .lock()
                .map_err(|_| internal!("db lock poisoned"))?;
            db::set_setting(&conn, "backend", setting)?;
        }
        self.status()
    }

    pub fn probe_backend(&self, backend: Backend) -> Result<EngineInfo> {
        self.select_backend(backend, &backend.label().to_ascii_lowercase())?;
        self.probe_selected_backend()
    }

    pub fn probe_backend_from_str(&self, backend: &str) -> Result<EngineInfo> {
        let parsed = Backend::parse(backend)?;
        self.select_backend(parsed, backend)?;
        self.probe_selected_backend()
    }

    fn probe_selected_backend(&self) -> Result<EngineInfo> {
        ensure_engine(&self.inner)?;
        self.inner
            .engine
            .lock()
            .map_err(|_| internal!("engine lock poisoned"))?
            .as_ref()
            .map(InferenceEngine::info)
            .ok_or_else(|| internal!("engine not initialized"))
    }

    pub fn index_path(&self, path: &Path) -> Result<IndexSummary> {
        let _span = tracing::info_span!("index.path").entered();
        self.inner.cancel_index.store(false, Ordering::SeqCst);
        if !self.inner.test_lexical {
            ensure_engine(&self.inner)?;
        }
        let path = path
            .to_str()
            .ok_or_else(|| EngineError::InvalidInput("root path is not UTF-8".into()))?;
        let root = {
            let conn = self
                .inner
                .db
                .lock()
                .map_err(|_| internal!("db lock poisoned"))?;
            db::add_root(&conn, path)?
        };
        if root.watch_enabled
            && let Err(err) = self.inner.watcher.start(&root)
        {
            update_health(&self.inner, |health| {
                health.last_error = Some(format!("watching {}: {err}", root.path));
            });
        }

        let _index_guard = self
            .inner
            .index_lock
            .lock()
            .map_err(|_| internal!("index lock poisoned"))?;
        update_health(&self.inner, |health| {
            health.indexing = true;
            health.current_file = None;
            health.last_error = None;
            health.last_message = Some(format!("Scanning {}", root.path));
        });

        let mut progress = |payload: IndexProgress| {
            set_current_file(
                &self.inner,
                if payload.file.is_empty() {
                    None
                } else {
                    Some(payload.file.clone())
                },
            );
            self.inner.events.index_progress(&payload);
        };
        let result = {
            let mut context = AppIndexContext { state: &self.inner };
            indexer::index_root(&mut context, &root, &self.inner.pdfium_dll, &mut progress)
        };

        match &result {
            Ok(summary) => {
                update_health(&self.inner, |health| {
                    health.indexing = false;
                    health.current_file = None;
                    health.last_indexed_at = Some(db::now_secs());
                    health.last_message = Some(if summary.cancelled {
                        format!(
                            "Index cancelled after {} files / {} chunks",
                            summary.files, summary.chunks
                        )
                    } else {
                        format!(
                            "Indexed {} files / {} unchanged / {} chunks / {} removed",
                            summary.files, summary.unchanged, summary.chunks, summary.removed
                        )
                    });
                    health.skipped = summary.skipped;
                    health.errors = summary.errors;
                    health.details = summary.details.iter().take(12).cloned().collect();
                    if health.errors > 0 {
                        health.last_error = summary.details.first().cloned();
                    }
                });
            }
            Err(err) => {
                update_health(&self.inner, |health| {
                    health.indexing = false;
                    health.current_file = None;
                    health.last_error = Some(err.to_string());
                    health.last_message = Some("Index failed".into());
                });
            }
        }
        result
    }

    pub fn cancel_indexing(&self) {
        self.inner.cancel_index.store(true, Ordering::SeqCst);
    }

    pub fn search(&self, request: &SearchRequest) -> Result<SearchResponse> {
        let started = Instant::now();
        let limit = request.limit.unwrap_or(20);
        let _span = tracing::info_span!("search", limit).entered();
        let semantic_used = ensure_engine(&self.inner).is_ok();
        let query_vector = if semantic_used {
            let mut engine = self
                .inner
                .engine
                .lock()
                .map_err(|_| internal!("engine lock poisoned"))?;
            engine
                .as_mut()
                .and_then(|engine| engine.embed(std::slice::from_ref(&request.query)).ok())
                .and_then(|mut vectors| vectors.pop())
        } else {
            None
        };
        let conn = self
            .inner
            .db
            .lock()
            .map_err(|_| internal!("db lock poisoned"))?;
        let hits = seeky_search::search(&*conn, &request.query, query_vector.as_deref(), limit)
            .map_err(|error| EngineError::Storage(error.into_storage()))?;
        let backend = self
            .inner
            .engine
            .lock()
            .map_err(|_| internal!("engine lock poisoned"))?
            .as_ref()
            .map(|engine| engine.info().backend)
            .unwrap_or_else(|| "BM25".to_string());
        Ok(SearchResponse {
            hits,
            backend,
            semantic_used: query_vector.is_some(),
            took_ms: started.elapsed().as_millis() as u64,
        })
    }

    pub fn document(&self, id: &DocId) -> Result<Option<seeky_core::DocumentView>> {
        let conn = self
            .inner
            .db
            .lock()
            .map_err(|_| internal!("db lock poisoned"))?;
        Ok(db::get_document(&conn, id)?)
    }

    pub fn document_path(&self, id: &DocId) -> Result<Option<PathBuf>> {
        let conn = self
            .inner
            .db
            .lock()
            .map_err(|_| internal!("db lock poisoned"))?;
        Ok(db::document_path(&conn, id)?)
    }

    pub fn shutdown(self) -> Result<()> {
        self.inner.watcher.stop_all();
        let _ = self.inner.watcher.tx.send(WatchMessage::Shutdown);
        let worker = self
            .inner
            .watch_worker
            .lock()
            .map_err(|_| internal!("watch worker lock poisoned"))?
            .take();
        if let Some(worker) = worker {
            worker
                .join()
                .map_err(|_| internal!("watcher worker panicked"))?;
        }
        Ok(())
    }
}

fn collect_watch_changes(messages: Vec<WatchMessage>) -> (Vec<WatchChange>, Vec<String>) {
    let mut changes: HashMap<(String, PathBuf), ChangeKind> = HashMap::new();
    let mut errors = Vec::new();
    for message in messages {
        match message {
            WatchMessage::Error { root_id, message } => {
                errors.push(format!("{root_id}: {message}"));
            }
            WatchMessage::Shutdown => {}
            WatchMessage::Fs { root_id, event } => {
                let upsert = |path: &PathBuf, changes: &mut HashMap<_, _>| {
                    changes.insert((root_id.clone(), path.clone()), ChangeKind::Upsert);
                };
                let remove = |path: &PathBuf, changes: &mut HashMap<_, _>| {
                    changes.insert((root_id.clone(), path.clone()), ChangeKind::Remove);
                };
                match &event.kind {
                    EventKind::Access(_) => {}
                    EventKind::Create(_) => {
                        for path in &event.paths {
                            upsert(path, &mut changes);
                        }
                    }
                    EventKind::Remove(_) => {
                        for path in &event.paths {
                            remove(path, &mut changes);
                        }
                    }
                    EventKind::Modify(ModifyKind::Name(RenameMode::Both)) => {
                        if let Some(old) = event.paths.first() {
                            remove(old, &mut changes);
                        }
                        for path in event.paths.iter().skip(1) {
                            upsert(path, &mut changes);
                        }
                    }
                    EventKind::Modify(ModifyKind::Name(RenameMode::From)) => {
                        for path in &event.paths {
                            remove(path, &mut changes);
                        }
                    }
                    EventKind::Modify(ModifyKind::Name(RenameMode::Any | RenameMode::Other)) => {
                        if event.paths.len() >= 2 {
                            if let Some(old) = event.paths.first() {
                                remove(old, &mut changes);
                            }
                            for path in event.paths.iter().skip(1) {
                                upsert(path, &mut changes);
                            }
                        } else {
                            for path in &event.paths {
                                upsert(path, &mut changes);
                            }
                        }
                    }
                    EventKind::Modify(ModifyKind::Name(_)) => {
                        for path in &event.paths {
                            upsert(path, &mut changes);
                        }
                    }
                    EventKind::Modify(_) | EventKind::Any | EventKind::Other => {
                        for path in &event.paths {
                            upsert(path, &mut changes);
                        }
                    }
                }
            }
        }
    }
    let mut changes: Vec<WatchChange> = changes
        .into_iter()
        .map(|((root_id, path), kind)| WatchChange {
            root_id,
            path,
            kind,
        })
        .collect();
    changes.sort_by(|left, right| {
        left.root_id
            .cmp(&right.root_id)
            .then_with(|| left.path.cmp(&right.path))
    });
    (changes, errors)
}

fn index_watched_file(state: &Inner, root: &Root, path: &Path, summary: &mut IndexSummary) {
    let mut context = AppIndexContext { state };
    match indexer::index_file(&mut context, root, path, &state.pdfium_dll) {
        Ok(indexer::FileOutcome::Updated { chunks }) => {
            summary.files += 1;
            summary.chunks += chunks;
        }
        Ok(indexer::FileOutcome::Unchanged) => summary.unchanged += 1,
        Ok(indexer::FileOutcome::Skipped { reason }) => {
            summary.skipped += 1;
            if summary.details.len() < 12 {
                summary
                    .details
                    .push(format!("{}: {reason}", path.display()));
            }
        }
        Ok(indexer::FileOutcome::Missing) => {}
        Err(err) => {
            summary.errors += 1;
            if summary.details.len() < 12 {
                summary.details.push(format!("{}: {err}", path.display()));
            }
        }
    }
}

fn set_current_file(state: &Inner, file: Option<String>) {
    if let Ok(mut health) = state.health.lock() {
        health.current_file = file;
    }
}

fn process_watch_batch(state: &Inner, messages: Vec<WatchMessage>) -> Result<()> {
    let _span = tracing::info_span!(
        "watch.batch",
        messages = messages.len(),
        changes = tracing::field::Empty
    )
    .entered();
    let pending = state.watcher.pending.swap(0, Ordering::Relaxed);
    let (changes, watch_errors) = collect_watch_changes(messages);
    tracing::Span::current().record("changes", changes.len());
    if changes.is_empty() {
        if !watch_errors.is_empty() {
            update_health(state, |health| {
                health.last_error = watch_errors.first().cloned();
                health.errors += watch_errors.len();
                health.details.extend(watch_errors.iter().take(6).cloned());
                health.details.truncate(12);
            });
        }
        return Ok(());
    }

    state.cancel_index.store(false, Ordering::SeqCst);
    if !state.test_lexical {
        ensure_engine(state)?;
    }
    let _index_guard = state
        .index_lock
        .lock()
        .map_err(|_| internal!("index lock poisoned"))?;
    update_health(state, |health| {
        health.indexing = true;
        health.current_file = None;
        health.last_message = Some(format!("Applying {} watched changes", changes.len()));
        health.pending = pending;
    });

    let mut roots: HashMap<String, Option<Root>> = HashMap::new();
    let mut summary = IndexSummary::default();
    for change in changes {
        if state.cancel_index.load(Ordering::Relaxed) {
            summary.cancelled = true;
            break;
        }
        let root = match roots.entry(change.root_id.clone()) {
            std::collections::hash_map::Entry::Occupied(entry) => entry.into_mut(),
            std::collections::hash_map::Entry::Vacant(entry) => {
                let conn = state.db.lock().map_err(|_| internal!("db lock poisoned"))?;
                entry.insert(db::get_root(&conn, &change.root_id)?)
            }
        };
        let Some(root) = root else {
            continue;
        };
        let root_path = Path::new(&root.path);
        if indexer::is_ignored_under(root_path, &change.path) {
            continue;
        }
        match change.kind {
            ChangeKind::Remove => {
                let conn = state.db.lock().map_err(|_| internal!("db lock poisoned"))?;
                summary.removed += db::delete_document_by_path(&conn, &change.path)?;
                summary.removed += db::delete_documents_under(&conn, &root.id, &change.path)?;
            }
            ChangeKind::Upsert => {
                if change.path.is_dir() {
                    for file in indexer::scan_root(&change.path) {
                        set_current_file(state, Some(file.to_string_lossy().to_string()));
                        index_watched_file(state, root, &file, &mut summary);
                    }
                } else if indexer::is_supported_file(&change.path) {
                    set_current_file(state, Some(change.path.to_string_lossy().to_string()));
                    index_watched_file(state, root, &change.path, &mut summary);
                }
            }
        }
    }

    if !watch_errors.is_empty() {
        summary.errors += watch_errors.len();
        summary.details.extend(watch_errors.iter().take(6).cloned());
    }
    update_health(state, |health| {
        health.indexing = false;
        health.current_file = None;
        health.pending = state.watcher.pending();
        health.last_message = Some(if summary.cancelled {
            "Watcher batch cancelled".into()
        } else {
            format!(
                "Watched: {} updated / {} unchanged / {} removed",
                summary.files, summary.unchanged, summary.removed
            )
        });
        if summary.files > 0 || summary.removed > 0 {
            health.last_indexed_at = Some(db::now_secs());
        }
        health.skipped = summary.skipped;
        health.errors = summary.errors;
        health.details = summary.details.clone();
        if summary.errors > 0 {
            health.last_error = summary.details.first().cloned();
        } else {
            health.last_error = None;
        }
        health.current_file = None;
    });
    Ok(())
}

fn spawn_watch_worker(
    state: Arc<Inner>,
    receiver: Receiver<WatchMessage>,
) -> Result<std::thread::JoinHandle<()>> {
    std::thread::Builder::new()
        .name("seeky-watcher".into())
        .spawn(move || {
            loop {
                let first = match receiver.recv() {
                    Ok(WatchMessage::Shutdown) | Err(_) => break,
                    Ok(message) => message,
                };
                let mut messages = vec![first];
                let deadline = Instant::now() + Duration::from_millis(600);
                loop {
                    let now = Instant::now();
                    if now >= deadline {
                        break;
                    }
                    match receiver.recv_timeout(deadline - now) {
                        Ok(WatchMessage::Shutdown) => return,
                        Ok(message) => messages.push(message),
                        Err(RecvTimeoutError::Timeout) => break,
                        Err(RecvTimeoutError::Disconnected) => return,
                    }
                }
                if let Err(err) = process_watch_batch(&state, messages) {
                    update_health(&state, |health| {
                        health.indexing = false;
                        health.last_error = Some(err.to_string());
                        health.last_message = Some("Watcher batch failed".into());
                    });
                }
            }
        })
        .map_err(Into::into)
}

#[cfg(test)]
mod tests {
    use super::*;
    use notify::event::{CreateKind, RemoveKind};

    fn message(kind: EventKind, paths: &[&str]) -> WatchMessage {
        let mut event = Event::new(kind);
        for path in paths {
            event = event.add_path(PathBuf::from(path));
        }
        WatchMessage::Fs {
            root_id: "root".into(),
            event,
        }
    }

    #[test]
    fn maps_watch_events_to_upserts_and_removes() {
        let messages = vec![
            message(EventKind::Create(CreateKind::File), &["C:/docs/new.txt"]),
            message(
                EventKind::Modify(ModifyKind::Data(notify::event::DataChange::Content)),
                &["C:/docs/edited.txt"],
            ),
            message(
                EventKind::Remove(RemoveKind::File),
                &["C:/docs/deleted.txt"],
            ),
            message(
                EventKind::Modify(ModifyKind::Name(RenameMode::Both)),
                &["C:/docs/old.txt", "C:/docs/new-name.txt"],
            ),
            message(
                EventKind::Modify(ModifyKind::Name(RenameMode::Any)),
                &["C:/docs/old-any.txt", "C:/docs/new-any.txt"],
            ),
        ];
        let (changes, errors) = collect_watch_changes(messages);
        assert!(errors.is_empty());
        let find = |path: &str| {
            changes
                .iter()
                .find(|change| change.path == *path)
                .map(|change| change.kind.clone())
        };
        assert_eq!(find("C:/docs/new.txt"), Some(ChangeKind::Upsert));
        assert_eq!(find("C:/docs/edited.txt"), Some(ChangeKind::Upsert));
        assert_eq!(find("C:/docs/deleted.txt"), Some(ChangeKind::Remove));
        assert_eq!(find("C:/docs/old.txt"), Some(ChangeKind::Remove));
        assert_eq!(find("C:/docs/new-name.txt"), Some(ChangeKind::Upsert));
        assert_eq!(find("C:/docs/old-any.txt"), Some(ChangeKind::Remove));
        assert_eq!(find("C:/docs/new-any.txt"), Some(ChangeKind::Upsert));
    }
}
