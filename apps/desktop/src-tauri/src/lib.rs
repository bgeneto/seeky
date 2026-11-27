use anyhow::Context;
use seeky_engine::{
    Engine, EngineConfig, EngineEvents, EngineInfo, EngineStatus, IndexHealth, IndexProgress,
    IndexSummary, Root, SearchRequest, SearchResponse,
};
use std::path::Path;
use std::sync::Arc;
use tauri::{AppHandle, Emitter, Manager, State};

struct TauriEvents {
    app: AppHandle,
}

impl EngineEvents for TauriEvents {
    fn index_progress(&self, progress: &IndexProgress) {
        let _ = self.app.emit("index-progress", progress);
    }

    fn index_health(&self, health: &IndexHealth) {
        let _ = self.app.emit("index-health", health);
    }
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn get_status(state: State<'_, Engine>) -> Result<EngineStatus, String> {
    state.status().map_err(|error| error.to_string())
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn add_root(state: State<'_, Engine>, path: String) -> Result<Root, String> {
    state
        .add_root(Path::new(&path))
        .map_err(|error| error.to_string())
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn remove_root(state: State<'_, Engine>, id: String) -> Result<(), String> {
    state.remove_root(&id).map_err(|error| error.to_string())
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn list_roots(state: State<'_, Engine>) -> Result<Vec<Root>, String> {
    state.list_roots().map_err(|error| error.to_string())
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn set_root_watching(state: State<'_, Engine>, id: String, enabled: bool) -> Result<Root, String> {
    state
        .set_root_watching(&id, enabled)
        .map_err(|error| error.to_string())
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn set_backend(state: State<'_, Engine>, backend: String) -> Result<EngineStatus, String> {
    state
        .set_backend_from_str(&backend)
        .map_err(|error| error.to_string())
}

#[tauri::command]
async fn probe_backend(state: State<'_, Engine>, backend: String) -> Result<EngineInfo, String> {
    let engine = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || engine.probe_backend_from_str(&backend))
        .await
        .map_err(|error| format!("probe task failed: {error}"))?
        .map_err(|error| error.to_string())
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn cancel_index(state: State<'_, Engine>) -> Result<(), String> {
    state.cancel_indexing();
    Ok(())
}

#[tauri::command]
async fn start_index(state: State<'_, Engine>, path: String) -> Result<IndexSummary, String> {
    let engine = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || engine.index_path(Path::new(&path)))
        .await
        .map_err(|error| format!("index task failed: {error}"))?
        .map_err(|error| error.to_string())
}

#[tauri::command]
async fn search_documents(
    state: State<'_, Engine>,
    query: String,
    limit: Option<usize>,
) -> Result<SearchResponse, String> {
    let engine = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || engine.search(&SearchRequest { query, limit }))
        .await
        .map_err(|error| format!("search task failed: {error}"))?
        .map_err(|error| error.to_string())
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn get_document(
    state: State<'_, Engine>,
    id: String,
) -> Result<Option<seeky_engine::DocumentView>, String> {
    state.document(&id).map_err(|error| error.to_string())
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

// WP-0.3 replaces this command with `open_document`, which resolves a
// document ID through `Engine::document_path` before opening or revealing it.
#[tauri::command]
fn open_local_file(path: String) -> Result<(), String> {
    let path = openable_path(path);
    tauri_plugin_opener::open_path(&path, None::<&str>).map_err(|error| format!("{error}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let data_dir = app.path().app_data_dir().context("resolve app data dir")?;
            let config = EngineConfig {
                data_dir,
                resource_dir: app.path().resource_dir().ok(),
            };
            let events = Arc::new(TauriEvents {
                app: app.handle().clone(),
            });
            let engine = Engine::open(config, events).context("open seeky engine")?;
            app.manage(engine);
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
