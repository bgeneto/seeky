//! Cold start to Instant- and semantic-capable (SPEC-0003 R27, section 5.5
//! step 7).
//!
//! The parent starts a fresh `seeky-bench __startup-probe` process on the
//! existing index and timestamps each capability line as it arrives, so the
//! measurement includes process start, engine open, and the first search.

use super::suites::Clock;
use crate::{Failure, Result};
use seeky_eval::StartupMetrics;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

/// Hidden subcommand name; not part of the documented CLI.
pub const PROBE_COMMAND: &str = "__startup-probe";
/// Probe line once a search on the opened index succeeds.
pub const INSTANT_LINE: &str = "instant-capable";
/// Probe line once a batch-1 query embedding succeeds.
pub const SEMANTIC_LINE: &str = "semantic-capable";
/// Probe line when no semantic model is configured or available.
pub const NO_SEMANTIC_LINE: &str = "semantic-unavailable";

/// OS page cache is never flushed by the harness.
pub const OS_CACHE: &str = "uncontrolled";

/// Startup metrics for a fresh process (`cold = true`).
#[must_use]
pub fn startup_metrics(instant_ms: f64, semantic_ms: Option<f64>) -> StartupMetrics {
    StartupMetrics {
        cold: true,
        os_cache: OS_CACHE.to_string(),
        instant_capable_ms: instant_ms,
        semantic_capable_ms: semantic_ms,
    }
}

/// Timestamp each capability line of a probe's output relative to `start_ns`.
/// Returns `(instant_ms, semantic_ms)`; instant is required.
pub fn read_probe_lines(
    clock: &dyn Clock,
    start_ns: u64,
    reader: &mut dyn BufRead,
) -> Result<(f64, Option<f64>)> {
    let mut instant = None;
    let mut semantic = None;
    let mut line = String::new();
    loop {
        line.clear();
        let read = reader
            .read_line(&mut line)
            .map_err(|error| Failure::engine(format!("startup probe output: {error}")))?;
        if read == 0 {
            break;
        }
        let now = clock.now_ns().saturating_sub(start_ns) as f64 / 1_000_000.0;
        match line.trim() {
            INSTANT_LINE if instant.is_none() => instant = Some(now),
            SEMANTIC_LINE if semantic.is_none() => semantic = Some(now),
            _ => {}
        }
    }
    let instant = instant
        .ok_or_else(|| Failure::engine("startup probe never reported Instant capability"))?;
    Ok((instant, semantic))
}

/// The `seeky-bench` executable: this process when it is the binary, else the
/// binary next to (or one directory above) the running test executable.
#[must_use]
pub fn bench_executable() -> Option<PathBuf> {
    let current = std::env::current_exe().ok()?;
    let name = format!("seeky-bench{}", std::env::consts::EXE_SUFFIX);
    if current
        .file_name()
        .is_some_and(|file| file == name.as_str())
    {
        return Some(current);
    }
    let parent = current.parent()?;
    [parent.join(&name), parent.parent()?.join(&name)]
        .into_iter()
        .find(|candidate| candidate.is_file())
}

/// Run one cold-start probe against `data_dir` with `config`.
pub fn measure_cold_start(
    clock: &dyn Clock,
    executable: &Path,
    data_dir: &Path,
    config: &Path,
) -> Result<StartupMetrics> {
    let start = clock.now_ns();
    let mut child = Command::new(executable)
        .arg(PROBE_COMMAND)
        .arg("--data-dir")
        .arg(data_dir)
        .arg("--config")
        .arg(config)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| Failure::engine(format!("cannot start the startup probe: {error}")))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| Failure::engine("startup probe has no stdout"))?;
    let parsed = read_probe_lines(clock, start, &mut BufReader::new(stdout));
    let status = child
        .wait()
        .map_err(|error| Failure::engine(format!("startup probe failed: {error}")))?;
    let (instant, semantic) = parsed?;
    if !status.success() {
        return Err(Failure::engine("startup probe exited with an error"));
    }
    Ok(startup_metrics(instant, semantic))
}

/// Child side: open the existing index, report Instant capability after the
/// first successful search, then semantic capability after a batch-1 query
/// embedding. Uses a fixed probe text, never a dataset query.
pub fn run_probe(data_dir: &Path, config: &crate::environment::RunConfig) -> Result<()> {
    let adapter = crate::engine::EngineAdapter::open(data_dir, config)?;
    let engine = adapter.engine();
    engine
        .search(&seeky_engine::SearchRequest {
            query: "seeky startup probe".to_string(),
            limit: None,
        })
        .map_err(|error| Failure::engine(error.to_string()))?;
    emit(INSTANT_LINE)?;
    let semantic = config.semantic
        && matches!(
            engine
                .probe_query_embedding("seeky startup probe")
                .map_err(|error| Failure::engine(error.to_string()))?,
            seeky_engine::QueryEmbeddingProbe::Available { .. }
        );
    emit(if semantic {
        SEMANTIC_LINE
    } else {
        NO_SEMANTIC_LINE
    })?;
    adapter.shutdown()
}

fn emit(line: &str) -> Result<()> {
    let mut stdout = std::io::stdout().lock();
    writeln!(stdout, "{line}")
        .and_then(|()| stdout.flush())
        .map_err(|error| Failure::engine(format!("startup probe output: {error}")))
}
