#![allow(clippy::unwrap_used)]

mod common;

use common::{RecordingEvents, TestDir, lexical_engine, write_documents};
use seeky_engine::{DocId, Engine, EngineConfig, EngineEvents, IndexHealth, IndexProgress};
use std::path::PathBuf;
use std::sync::mpsc::{self, RecvTimeoutError, Sender};
use std::sync::{Arc, Barrier};
use std::time::Duration;

/// SPEC-0002-R2: the facade is cloneable and safe to move between threads.
#[test]
fn engine_is_send_sync_clone() {
    fn assert_send_sync_clone<T: Send + Sync + Clone>() {}
    assert_send_sync_clone::<Engine>();
}

/// SPEC-0002-R6: an unknown document ID cannot resolve to a filesystem path.
#[test]
fn document_path_unknown_id_is_none() -> common::TestResult {
    let test_dir = TestDir::new("unknown-document")?;
    let engine = lexical_engine(&test_dir, Arc::new(common::NoopEvents))?;
    let id: DocId = "not-in-the-index".to_string();
    assert_eq!(engine.document_path(&id)?, None);
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R9: indexing emits the PoC progress and health payloads.
#[test]
fn events_sink_receives_progress_and_health() -> common::TestResult {
    let test_dir = TestDir::new("events")?;
    let corpus = test_dir.join("corpus");
    write_documents(&corpus, 1)?;
    let events = Arc::new(RecordingEvents::default());
    let engine = lexical_engine(&test_dir, events.clone())?;
    let summary = engine.index_path(&corpus)?;
    assert_eq!(summary.files, 1);
    assert!(!events.progress.lock().unwrap().is_empty());
    let health = events.health.lock().unwrap();
    assert!(!health.is_empty());
    assert!(!health.last().unwrap().indexing);
    drop(health);
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R10: cancellation during a scan returns a cancelled summary.
#[test]
fn cancel_returns_cancelled_summary() -> common::TestResult {
    let test_dir = TestDir::new("cancel")?;
    let corpus = test_dir.join("corpus");
    write_documents(&corpus, 2)?;
    let events = Arc::new(RecordingEvents::default());
    let engine = lexical_engine(&test_dir, events.clone())?;
    events.attach(engine.clone());
    events.cancel_on_next_progress();
    let summary = engine.index_path(&corpus)?;
    assert!(summary.cancelled, "summary={summary:?}");
    engine.shutdown()?;
    Ok(())
}

/// SPEC-0002-R11: concurrent callers never enter the indexing stage together.
#[test]
fn index_path_calls_are_serialized() -> common::TestResult {
    let test_dir = TestDir::new("serialized")?;
    let corpus = test_dir.join("corpus");
    write_documents(&corpus, 16)?;
    let events = Arc::new(RecordingEvents::default());
    let engine = lexical_engine(&test_dir, events.clone())?;
    let barrier = Arc::new(Barrier::new(3));
    std::thread::scope(|scope| {
        let mut handles = Vec::new();
        for _ in 0..2 {
            let engine = engine.clone();
            let corpus = corpus.clone();
            let barrier = barrier.clone();
            handles.push(scope.spawn(move || {
                barrier.wait();
                engine.index_path(&corpus)
            }));
        }
        barrier.wait();
        for handle in handles {
            handle.join().map_err(|_| "index thread panicked")??;
        }
        Ok::<(), Box<dyn std::error::Error>>(())
    })?;
    assert_eq!(events.max_active_indexing(), 1);
    engine.shutdown()?;
    Ok(())
}

struct ChannelEvents(Sender<()>);

impl EngineEvents for ChannelEvents {
    fn index_progress(&self, _progress: &IndexProgress) {}

    fn index_health(&self, _health: &IndexHealth) {
        let _ = self.0.send(());
    }
}

/// SPEC-0002-R14: shutdown stops watchers and joins their worker before returning.
#[test]
fn shutdown_stops_watchers() -> common::TestResult {
    let test_dir = TestDir::new("shutdown")?;
    let corpus = test_dir.join("corpus");
    write_documents(&corpus, 1)?;
    let (tx, rx) = mpsc::channel();
    let events = Arc::new(ChannelEvents(tx));
    let engine = lexical_engine(&test_dir, events.clone())?;
    engine.add_root(&corpus)?;
    engine.shutdown()?;
    for _ in rx.try_iter() {}

    std::fs::write(
        corpus.join("after-shutdown.txt"),
        "This file was created only after shutdown completed and must not be indexed.",
    )?;
    assert_eq!(
        rx.recv_timeout(Duration::from_millis(150)),
        Err(RecvTimeoutError::Timeout)
    );
    Ok(())
}

/// SPEC-0002-R16: path resolution retains the PoC's data and runtime locations.
#[test]
fn config_resolves_poc_locations() -> common::TestResult {
    let test_dir = TestDir::new("config")?;
    let resource_dir = test_dir.join("resources");
    let npu_dir = resource_dir
        .join("resources")
        .join("models")
        .join("gety-embed-v0")
        .join("openvino");
    std::fs::create_dir_all(&npu_dir)?;
    std::fs::write(npu_dir.join("model.xml"), b"")?;
    let config = EngineConfig {
        data_dir: test_dir.join("app-data"),
        resource_dir: Some(resource_dir),
    };
    let resolved = config.resolve()?;
    assert_eq!(resolved.db_path, config.data_dir.join("seeky.db"));
    assert_eq!(
        resolved.model_root,
        seeky_infer::find_gety_model_root().ok()
    );
    assert_eq!(resolved.npu_dir, npu_dir);
    let expected_pdfium = if let Some(path) = std::env::var_os("SEEKY_PDFIUM_DLL") {
        PathBuf::from(path)
    } else {
        std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_default()
            .join("Gety")
            .join("lib")
            .join("pdfium.dll")
    };
    assert_eq!(resolved.pdfium_dll, expected_pdfium);
    Ok(())
}
