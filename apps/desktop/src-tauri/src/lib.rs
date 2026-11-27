use anyhow::Context;
use seeky_engine::{
    Engine, EngineConfig, EngineEvents, EngineInfo, EngineStatus, IndexHealth, IndexProgress,
    IndexSummary, Root, SearchRequest, SearchResponse,
};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
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

const OPEN_EXTENSIONS: &[&str] = &[
    "txt", "md", "markdown", "rst", "log", "pdf", "docx", "xlsx", "xls", "pptx", "csv", "json",
    "jsonl", "xml", "yaml", "yml", "toml", "html", "htm",
];

fn is_open_allowlisted(path: &Path) -> bool {
    path.extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| {
            let extension = extension.to_ascii_lowercase();
            OPEN_EXTENSIONS.contains(&extension.as_str())
        })
}

fn resolve_document_path(path: Option<PathBuf>) -> Result<PathBuf, String> {
    path.ok_or_else(|| "document is not in the index".to_string())
}

fn ensure_document_exists(path: &Path) -> Result<(), String> {
    if path.is_file() {
        Ok(())
    } else {
        Err("indexed document no longer exists".to_string())
    }
}

fn openable_path(path: &Path) -> PathBuf {
    let text = path.to_string_lossy();
    if let Some(rest) = text.strip_prefix(r"\\?\UNC\") {
        PathBuf::from(format!(r"\\{rest}"))
    } else if let Some(rest) = text.strip_prefix(r"\\?\") {
        PathBuf::from(rest)
    } else {
        path.to_path_buf()
    }
}

#[tauri::command]
#[allow(clippy::needless_pass_by_value)] // Tauri passes command arguments by value
fn open_document(state: State<'_, Engine>, id: String) -> Result<(), String> {
    let path = state
        .document_path(&id)
        .map_err(|error| error.to_string())?;
    let path = resolve_document_path(path)?;
    ensure_document_exists(&path)?;
    let path = openable_path(&path);
    if is_open_allowlisted(&path) {
        tauri_plugin_opener::open_path(&path, None::<&str>)
    } else {
        tauri_plugin_opener::reveal_item_in_dir(&path)
    }
    .map_err(|error| error.to_string())
}

/// SPEC-0014-R13: the main window starts hidden and the frontend shows it
/// once the theme is applied. If the frontend never gets that far (for
/// example its bundle fails to load), the shell shows it after this delay
/// so the window is never left hidden.
const STARTUP_SHOW_FALLBACK: Duration = Duration::from_secs(5);

/// The two window calls the startup fallback needs (fakes in tests).
trait StartupWindow {
    fn is_visible(&self) -> bool;
    fn show(&self);
}

impl StartupWindow for tauri::WebviewWindow {
    fn is_visible(&self) -> bool {
        // An unknown visibility is treated as hidden: showing twice is harmless.
        tauri::WebviewWindow::is_visible(self).unwrap_or(false)
    }

    fn show(&self) {
        let _ = tauri::WebviewWindow::show(self);
    }
}

/// Shows the window if it is still hidden; returns whether it did.
fn show_if_hidden(window: &impl StartupWindow) -> bool {
    if window.is_visible() {
        return false;
    }
    window.show();
    true
}

fn spawn_startup_show_fallback(app: AppHandle) {
    std::thread::spawn(move || {
        std::thread::sleep(STARTUP_SHOW_FALLBACK);
        if let Some(window) = app.get_webview_window("main") {
            show_if_hidden(&window);
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            spawn_startup_show_fallback(app.handle().clone());
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
            open_document
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    struct FakeWindow {
        visible: Cell<bool>,
        shows: Cell<u32>,
    }

    impl StartupWindow for FakeWindow {
        fn is_visible(&self) -> bool {
            self.visible.get()
        }

        fn show(&self) {
            self.shows.set(self.shows.get() + 1);
            self.visible.set(true);
        }
    }

    /// SPEC-0014-R13: a window the frontend never showed is shown by the
    /// shell fallback; one the frontend already showed is left alone.
    #[test]
    fn startup_fallback_shows_only_a_hidden_window() {
        let hidden = FakeWindow {
            visible: Cell::new(false),
            shows: Cell::new(0),
        };
        assert!(show_if_hidden(&hidden));
        assert!(hidden.visible.get());
        assert!(!show_if_hidden(&hidden));
        assert_eq!(hidden.shows.get(), 1);

        let shown = FakeWindow {
            visible: Cell::new(true),
            shows: Cell::new(0),
        };
        assert!(!show_if_hidden(&shown));
        assert_eq!(shown.shows.get(), 0);
    }

    /// SPEC-0002-R7: only document formats are opened; code and unknown types
    /// are revealed instead.
    #[test]
    fn open_allowlist_reveals_code_and_unknown_types() {
        for extension in [
            "txt", "md", "markdown", "rst", "log", "pdf", "docx", "xlsx", "xls", "pptx", "csv",
            "json", "jsonl", "xml", "yaml", "yml", "toml", "html", "htm",
        ] {
            let path = Path::new("document").with_extension(extension);
            assert!(is_open_allowlisted(&path), "{extension} should open");
        }
        for extension in [
            "py", "js", "ts", "rs", "go", "java", "c", "cpp", "cs", "sh", "ps1", "sql", "exe",
            "bin", "dll", "",
        ] {
            let path = Path::new("document").with_extension(extension);
            assert!(!is_open_allowlisted(&path), "{extension} should reveal");
        }
        assert!(is_open_allowlisted(Path::new("REPORT.PDF")));
    }

    /// SPEC-0002-R6: an ID with no indexed path fails before any file action.
    #[test]
    fn unknown_document_path_opens_nothing() {
        assert!(resolve_document_path(None).is_err());
        let expected = std::env::temp_dir().join("seeky-known-document.pdf");
        assert_eq!(
            resolve_document_path(Some(expected.clone())).unwrap(),
            expected
        );
    }

    /// SPEC-0002 §5.4: a stale indexed path is rejected before any file action.
    #[test]
    fn missing_document_path_is_rejected() {
        let path =
            std::env::temp_dir().join(format!("seeky-missing-document-{}.pdf", std::process::id()));
        let _ = std::fs::remove_file(&path);
        assert!(ensure_document_exists(&path).is_err());
    }
}
