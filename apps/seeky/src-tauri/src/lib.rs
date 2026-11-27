mod db;
mod extract;
mod indexer;
mod inference;
mod search;

use anyhow::{Context, Result, anyhow};
use db::{ChunkInput, Counts, DocumentView, FileSignature, Root};
use indexer::{IndexContext, IndexProgress, IndexSummary, PreparedFile};
use inference::{
    Backend, Engine, EngineInfo, available_backends, find_gety_model_root, resolve_npu_dir,
};
use notify::event::{ModifyKind, RenameMode};
use notify::{Event, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use search::SearchHit;
use serde::Serialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager, State};

#[derive(Clone)]
struct AppState {
    db: Arc<Mutex<rusqlite::Connection>>,
    engine: Arc<Mutex<Option<Engine>>>,
    backend: Arc<Mutex<Backend>>,
    watcher: Arc<WatchManager>,
    health: Arc<Mutex<IndexHealth>>,
    index_lock: Arc<Mutex<()>>,
    cancel_index: Arc<AtomicBool>,
    model_root: Option<PathBuf>,
    npu_dir: PathBuf,
    pdfium_dll: PathBuf,
    db_path: PathBuf,
}

#[derive(Clone, Debug, Default, Serialize)]
struct IndexHealth {
    indexing: bool,
    watching: bool,
    watched_roots: usize,
    pending: usize,
    last_indexed_at: Option<i64>,
    last_message: Option<String>,
    last_error: Option<String>,
    current_file: Option<String>,
    skipped: usize,
    errors: usize,
    details: Vec<String>,
}

#[derive(Serialize)]
struct Status {
    roots: Vec<Root>,
    counts: Counts,
    backend: String,
    backend_label: String,
    available_backends: Vec<String>,
    engine: Option<EngineInfo>,
    model_root: Option<String>,
    npu_model: String,
    pdfium: String,
    db_path: String,
    model_ready: bool,
    health: IndexHealth,
}

#[derive(Serialize)]
struct SearchResponse {
    hits: Vec<SearchHit>,
    backend: String,
    semantic_used: bool,
    took_ms: u64,
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
            .map_err(|_| anyhow!("watcher lock poisoned"))?;
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
            .context("create filesystem watcher")?;
        watcher
            .watch(Path::new(&root.path), RecursiveMode::Recursive)
            .with_context(|| format!("watch {}", root.path))?;
        watchers.insert(root.id.clone(), watcher);
        Ok(())
    }

    fn stop(&self, root_id: &str) {
        if let Ok(mut watchers) = self.watchers.lock() {
            watchers.remove(root_id);
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
    state: &'a AppState,
}

impl IndexContext for AppIndexContext<'_> {
    fn signature(&mut self, _root_id: &str, path: &Path) -> Result<Option<FileSignature>> {
        let conn = self
            .state
            .db
            .lock()
            .map_err(|_| anyhow!("db lock poisoned"))?;
        db::document_signature(&conn, path)
    }

    fn embed(&mut self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        ensure_engine(self.state)?;
        let mut engine = self
            .state
            .engine
            .lock()
            .map_err(|_| anyhow!("engine lock poisoned"))?;
        engine
            .as_mut()
            .ok_or_else(|| anyhow!("engine not initialized"))?
            .embed(texts)
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
            .map_err(|_| anyhow!("db lock poisoned"))?;
        db::upsert_document(
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
        )
    }

    fn prune_missing(&mut self, root_id: &str, keep: &[PathBuf]) -> Result<usize> {
        let conn = self
            .state
            .db
            .lock()
            .map_err(|_| anyhow!("db lock poisoned"))?;
        db::prune_missing(&conn, root_id, keep)
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

fn backend_from_state(state: &AppState) -> Backend {
    *state.backend.lock().expect("backend lock")
}

fn ensure_engine(state: &AppState) -> Result<()> {
    let mut engine = state
        .engine
        .lock()
        .map_err(|_| anyhow!("engine lock poisoned"))?;
    if engine.is_some() {
        return Ok(());
    }
    let model_root = state
        .model_root
        .as_ref()
        .ok_or_else(|| anyhow!("gety-embed-v0 not found; set SEEKY_GETY_MODEL_DIR"))?;
    let backend = backend_from_state(state);
    *engine = Some(Engine::create(backend, model_root, &state.npu_dir)?);
    Ok(())
}

fn update_health(app: &AppHandle, state: &AppState, update: impl FnOnce(&mut IndexHealth)) {
    let Ok(mut health) = state.health.lock() else {
        return;
    };
    update(&mut health);
    health.pending = state.watcher.pending();
    health.watched_roots = state.watcher.count();
    health.watching = health.watched_roots > 0;
    let payload = health.clone();
    drop(health);
    let _ = app.emit("index-health", payload);
}

fn status_of(state: &AppState) -> Result<Status> {
    let conn = state.db.lock().map_err(|_| anyhow!("db lock poisoned"))?;
    let roots = db::list_roots(&conn)?;
    let counts = db::counts(&conn)?;
    drop(conn);
    let backend = backend_from_state(state);
    let engine = state
        .engine
        .lock()
        .map_err(|_| anyhow!("engine lock poisoned"))?
        .as_ref()
        .map(inference::Engine::info);
    let available = available_backends(state.model_root.as_deref(), &state.npu_dir);
    let mut health = state
        .health
        .lock()
        .map_err(|_| anyhow!("health lock poisoned"))?
        .clone();
    health.pending = state.watcher.pending();
    health.watched_roots = state.watcher.count();
    health.watching = health.watched_roots > 0;
    Ok(Status {
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

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn get_status(state: State<'_, AppState>) -> Result<Status, String> {
    status_of(&state).map_err(|err| format!("{err:#}"))
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn add_root(app: AppHandle, state: State<'_, AppState>, path: String) -> Result<Root, String> {
    let mut root = {
        let conn = state
            .db
            .lock()
            .map_err(|_| "db lock poisoned".to_string())?;
        db::add_root(&conn, &path).map_err(|err| format!("{err:#}"))?
    };

    if root.watch_enabled
        && let Err(err) = state.watcher.start(&root)
    {
        if let Ok(conn) = state.db.lock() {
            let _ = db::set_root_watching(&conn, &root.id, false);
        }
        root.watch_enabled = false;
        update_health(&app, &state, |health| {
            health.last_error = Some(format!("watching {}: {err:#}", root.path));
        });
    }
    update_health(&app, &state, |_| {});
    Ok(root)
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn remove_root(app: AppHandle, state: State<'_, AppState>, id: String) -> Result<(), String> {
    state.watcher.stop(&id);
    {
        let conn = state
            .db
            .lock()
            .map_err(|_| "db lock poisoned".to_string())?;
        db::remove_root(&conn, &id).map_err(|err| format!("{err:#}"))?;
    }
    update_health(&app, &state, |_| {});
    Ok(())
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn list_roots(state: State<'_, AppState>) -> Result<Vec<Root>, String> {
    let conn = state
        .db
        .lock()
        .map_err(|_| "db lock poisoned".to_string())?;
    db::list_roots(&conn).map_err(|err| format!("{err:#}"))
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn set_root_watching(
    app: AppHandle,
    state: State<'_, AppState>,
    id: String,
    enabled: bool,
) -> Result<Root, String> {
    {
        let conn = state
            .db
            .lock()
            .map_err(|_| "db lock poisoned".to_string())?;
        db::set_root_watching(&conn, &id, enabled).map_err(|err| format!("{err:#}"))?;
    }
    let root = {
        let conn = state
            .db
            .lock()
            .map_err(|_| "db lock poisoned".to_string())?;
        db::get_root(&conn, &id)
            .map_err(|err| format!("{err:#}"))?
            .ok_or_else(|| "folder not found".to_string())?
    };

    if enabled {
        if let Err(err) = state.watcher.start(&root) {
            if let Ok(conn) = state.db.lock() {
                let _ = db::set_root_watching(&conn, &id, false);
            }
            update_health(&app, &state, |health| {
                health.last_error = Some(format!("watching {}: {err:#}", root.path));
            });
            return Err(format!("{err:#}"));
        }
    } else {
        state.watcher.stop(&id);
    }
    update_health(&app, &state, |_| {});
    let conn = state
        .db
        .lock()
        .map_err(|_| "db lock poisoned".to_string())?;
    db::get_root(&conn, &id)
        .map_err(|err| format!("{err:#}"))?
        .ok_or_else(|| "folder not found".to_string())
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn set_backend(state: State<'_, AppState>, backend: String) -> Result<Status, String> {
    let parsed = Backend::parse(&backend).map_err(|err| format!("{err:#}"))?;
    *state
        .backend
        .lock()
        .map_err(|_| "backend lock poisoned".to_string())? = parsed;
    *state
        .engine
        .lock()
        .map_err(|_| "engine lock poisoned".to_string())? = None;
    let conn = state
        .db
        .lock()
        .map_err(|_| "db lock poisoned".to_string())?;
    db::set_setting(&conn, "backend", &backend).map_err(|err| format!("{err:#}"))?;
    drop(conn);
    status_of(&state).map_err(|err| format!("{err:#}"))
}

#[tauri::command]
async fn probe_backend(state: State<'_, AppState>, backend: String) -> Result<EngineInfo, String> {
    let parsed = Backend::parse(&backend).map_err(|err| format!("{err:#}"))?;
    *state
        .backend
        .lock()
        .map_err(|_| "backend lock poisoned".to_string())? = parsed;
    *state
        .engine
        .lock()
        .map_err(|_| "engine lock poisoned".to_string())? = None;
    {
        let conn = state
            .db
            .lock()
            .map_err(|_| "db lock poisoned".to_string())?;
        db::set_setting(&conn, "backend", &backend).map_err(|err| format!("{err:#}"))?;
    }
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || -> Result<EngineInfo> {
        ensure_engine(&state)?;
        let info = state
            .engine
            .lock()
            .map_err(|_| anyhow!("engine lock poisoned"))?
            .as_ref()
            .map(inference::Engine::info)
            .ok_or_else(|| anyhow!("engine not initialized"))?;
        Ok(info)
    })
    .await
    .map_err(|err| format!("probe task failed: {err}"))?
    .map_err(|err| format!("{err:#}"))
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn cancel_index(state: State<'_, AppState>) -> Result<(), String> {
    state.cancel_index.store(true, Ordering::SeqCst);
    Ok(())
}

#[tauri::command]
async fn start_index(
    app: AppHandle,
    state: State<'_, AppState>,
    path: String,
) -> Result<IndexSummary, String> {
    let state = state.inner().clone();
    let app = app.clone();
    tauri::async_runtime::spawn_blocking(move || -> Result<IndexSummary> {
        state.cancel_index.store(false, Ordering::SeqCst);
        ensure_engine(&state)?;
        let root = {
            let conn = state.db.lock().map_err(|_| anyhow!("db lock poisoned"))?;
            db::add_root(&conn, &path)?
        };
        if root.watch_enabled
            && let Err(err) = state.watcher.start(&root)
        {
            update_health(&app, &state, |health| {
                health.last_error = Some(format!("watching {}: {err:#}", root.path));
            });
        }

        let _index_guard = state
            .index_lock
            .lock()
            .map_err(|_| anyhow!("index lock poisoned"))?;
        update_health(&app, &state, |health| {
            health.indexing = true;
            health.current_file = None;
            health.last_error = None;
            health.last_message = Some(format!("Scanning {}", root.path));
        });

        let mut progress = |payload: IndexProgress| {
            set_current_file(
                &state,
                if payload.file.is_empty() {
                    None
                } else {
                    Some(payload.file.clone())
                },
            );
            let _ = app.emit("index-progress", payload);
        };
        let result = {
            let mut context = AppIndexContext { state: &state };
            indexer::index_root(&mut context, &root, &state.pdfium_dll, &mut progress)
        };

        match &result {
            Ok(summary) => {
                update_health(&app, &state, |health| {
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
                update_health(&app, &state, |health| {
                    health.indexing = false;
                    health.current_file = None;
                    health.last_error = Some(format!("{err:#}"));
                    health.last_message = Some("Index failed".into());
                });
            }
        }
        result
    })
    .await
    .map_err(|err| format!("index task failed: {err}"))?
    .map_err(|err| format!("{err:#}"))
}

#[tauri::command]
async fn search_documents(
    state: State<'_, AppState>,
    query: String,
    limit: Option<usize>,
) -> Result<SearchResponse, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || -> Result<SearchResponse> {
        let started = std::time::Instant::now();
        let limit = limit.unwrap_or(20);
        let semantic_used = ensure_engine(&state).is_ok();
        let query_vector = if semantic_used {
            let mut engine = state
                .engine
                .lock()
                .map_err(|_| anyhow!("engine lock poisoned"))?;
            engine
                .as_mut()
                .and_then(|engine| engine.embed(std::slice::from_ref(&query)).ok())
                .and_then(|mut vectors| vectors.pop())
        } else {
            None
        };
        let conn = state.db.lock().map_err(|_| anyhow!("db lock poisoned"))?;
        let hits = search::search(&conn, &query, query_vector.as_deref(), limit)?;
        let backend = state
            .engine
            .lock()
            .map_err(|_| anyhow!("engine lock poisoned"))?
            .as_ref()
            .map(|engine| engine.info().backend)
            .unwrap_or_else(|| "BM25".to_string());
        Ok(SearchResponse {
            hits,
            backend,
            semantic_used: query_vector.is_some(),
            took_ms: started.elapsed().as_millis() as u64,
        })
    })
    .await
    .map_err(|err| format!("search task failed: {err}"))?
    .map_err(|err| format!("{err:#}"))
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn get_document(state: State<'_, AppState>, id: String) -> Result<Option<DocumentView>, String> {
    let conn = state
        .db
        .lock()
        .map_err(|_| "db lock poisoned".to_string())?;
    db::get_document(&conn, &id).map_err(|err| format!("{err:#}"))
}

fn openable_path(path: String) -> String {
    if let Some(rest) = path.strip_prefix(r"\\?\UNC\") {
        format!(r"\\{rest}")
    } else if let Some(rest) = path.strip_prefix(r"\\?\") {
        rest.to_string()
    } else {
        path
    }
}

#[tauri::command]
fn open_local_file(path: String) -> Result<(), String> {
    let path = openable_path(path);
    tauri_plugin_opener::open_path(&path, None::<&str>).map_err(|err| format!("{err}"))
}

fn collect_watch_changes(messages: Vec<WatchMessage>) -> (Vec<WatchChange>, Vec<String>) {
    let mut changes: HashMap<(String, PathBuf), ChangeKind> = HashMap::new();
    let mut errors = Vec::new();
    for message in messages {
        match message {
            WatchMessage::Error { root_id, message } => {
                errors.push(format!("{root_id}: {message}"));
            }
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

fn index_watched_file(state: &AppState, root: &Root, path: &Path, summary: &mut IndexSummary) {
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
                summary.details.push(format!("{}: {err:#}", path.display()));
            }
        }
    }
}

fn set_current_file(state: &AppState, file: Option<String>) {
    if let Ok(mut health) = state.health.lock() {
        health.current_file = file;
    }
}

fn process_watch_batch(
    app: &AppHandle,
    state: &AppState,
    messages: Vec<WatchMessage>,
) -> Result<()> {
    let pending = state.watcher.pending.swap(0, Ordering::Relaxed);
    let (changes, watch_errors) = collect_watch_changes(messages);
    if changes.is_empty() {
        if !watch_errors.is_empty() {
            update_health(app, state, |health| {
                health.last_error = watch_errors.first().cloned();
                health.errors += watch_errors.len();
                health.details.extend(watch_errors.iter().take(6).cloned());
                health.details.truncate(12);
            });
        }
        return Ok(());
    }

    state.cancel_index.store(false, Ordering::SeqCst);
    ensure_engine(state)?;
    let _index_guard = state
        .index_lock
        .lock()
        .map_err(|_| anyhow!("index lock poisoned"))?;
    update_health(app, state, |health| {
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
                let conn = state.db.lock().map_err(|_| anyhow!("db lock poisoned"))?;
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
                let conn = state.db.lock().map_err(|_| anyhow!("db lock poisoned"))?;
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
    update_health(app, state, |health| {
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

fn spawn_watch_worker(app: AppHandle, state: AppState, receiver: Receiver<WatchMessage>) {
    let _ = std::thread::Builder::new()
        .name("seeky-watcher".into())
        .spawn(move || {
            while let Ok(first) = receiver.recv() {
                let mut messages = vec![first];
                let deadline = Instant::now() + Duration::from_millis(600);
                loop {
                    let now = Instant::now();
                    if now >= deadline {
                        break;
                    }
                    match receiver.recv_timeout(deadline - now) {
                        Ok(message) => messages.push(message),
                        Err(RecvTimeoutError::Timeout) => break,
                        Err(RecvTimeoutError::Disconnected) => return,
                    }
                }
                if let Err(err) = process_watch_batch(&app, &state, messages) {
                    update_health(&app, &state, |health| {
                        health.indexing = false;
                        health.last_error = Some(format!("{err:#}"));
                        health.last_message = Some("Watcher batch failed".into());
                    });
                }
            }
        });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let data_dir = app.path().app_data_dir().context("resolve app data dir")?;
            std::fs::create_dir_all(&data_dir).ok();
            let db_path = data_dir.join("seeky.db");
            let conn = db::open(&db_path).context("open seeky database")?;
            let backend = db::get_setting(&conn, "backend")
                .ok()
                .flatten()
                .and_then(|value| Backend::parse(&value).ok())
                .unwrap_or(Backend::Auto);
            let last_indexed = db::last_indexed_at(&conn).ok().flatten();
            let roots = db::list_roots(&conn).unwrap_or_default();
            let model_root = find_gety_model_root().ok();
            let npu_dir = resolve_npu_dir(app.path().resource_dir().ok().as_deref());
            let pdfium_dll = get_pdfium_path();
            let (watch_tx, watch_rx) = mpsc::channel();
            let watcher = Arc::new(WatchManager::new(watch_tx));
            let health = Arc::new(Mutex::new(IndexHealth {
                last_indexed_at: last_indexed,
                ..IndexHealth::default()
            }));
            let state = AppState {
                db: Arc::new(Mutex::new(conn)),
                engine: Arc::new(Mutex::new(None)),
                backend: Arc::new(Mutex::new(backend)),
                watcher,
                health,
                index_lock: Arc::new(Mutex::new(())),
                cancel_index: Arc::new(AtomicBool::new(false)),
                model_root,
                npu_dir,
                pdfium_dll,
                db_path,
            };
            app.manage(state.clone());
            spawn_watch_worker(app.handle().clone(), state.clone(), watch_rx);

            let mut watcher_errors = Vec::new();
            for root in roots {
                if root.watch_enabled
                    && let Err(err) = state.watcher.start(&root)
                {
                    watcher_errors.push(format!("{}: {err:#}", root.path));
                    if let Ok(conn) = state.db.lock() {
                        let _ = db::set_root_watching(&conn, &root.id, false);
                    }
                }
            }
            update_health(app.handle(), &state, |health| {
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
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_status,
            add_root,
            remove_root,
            list_roots,
            set_root_watching,
            set_backend,
            probe_backend,
            start_index,
            cancel_index,
            search_documents,
            get_document,
            open_local_file
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
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
