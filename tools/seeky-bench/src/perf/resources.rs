//! Process RSS sampling and index size (SPEC-0003 R27, section 5.5 step 6).

use crate::{Failure, Result};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

/// Sampling interval required by SPEC-0003 section 5.5.
pub const SAMPLING_INTERVAL_MS: u64 = 50;
/// Measurement scope: the headless engine in the `seeky-bench` process.
pub const SCOPE: &str = "engine_headless";

/// Samples the resident set size of the measured process.
pub trait RssSampler: Send + Sync {
    /// Current RSS in bytes, or `None` when the platform cannot sample it.
    fn rss_bytes(&self) -> Option<u64>;
}

/// Production sampler for this process.
pub struct ProcessRss;

impl RssSampler for ProcessRss {
    fn rss_bytes(&self) -> Option<u64> {
        super::platform::current_rss_bytes()
    }
}

/// Background sampler that keeps every sample for the peak.
pub struct RssMonitor {
    stop: Arc<AtomicBool>,
    samples: Arc<Mutex<Vec<u64>>>,
    handle: Option<JoinHandle<()>>,
}

impl RssMonitor {
    /// Start sampling every `interval`.
    pub fn start(sampler: Arc<dyn RssSampler>, interval: Duration) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let samples = Arc::new(Mutex::new(Vec::new()));
        let handle = {
            let stop = Arc::clone(&stop);
            let samples = Arc::clone(&samples);
            std::thread::spawn(move || {
                while !stop.load(Ordering::Relaxed) {
                    if let Some(value) = sampler.rss_bytes()
                        && let Ok(mut samples) = samples.lock()
                    {
                        samples.push(value);
                    }
                    std::thread::park_timeout(interval);
                }
            })
        };
        Self {
            stop,
            samples,
            handle: Some(handle),
        }
    }

    /// Stop sampling and return every sample in order.
    pub fn finish(mut self) -> Vec<u64> {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(handle) = self.handle.take() {
            handle.thread().unpark();
            let _ = handle.join();
        }
        self.samples
            .lock()
            .map(|samples| samples.clone())
            .unwrap_or_default()
    }
}

impl Drop for RssMonitor {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(handle) = self.handle.take() {
            handle.thread().unpark();
            let _ = handle.join();
        }
    }
}

/// Take `count` samples `interval` apart once the engine is idle and return
/// the last one (the stabilized idle RSS), or `None` when unavailable.
pub fn idle_rss(sampler: &dyn RssSampler, count: usize, interval: Duration) -> Option<u64> {
    let mut last = None;
    for index in 0..count {
        if index > 0 {
            std::thread::sleep(interval);
        }
        last = sampler.rss_bytes().or(last);
    }
    last
}

/// Peak = maximum sample; `None` when nothing was sampled.
#[must_use]
pub fn peak_rss(samples: &[u64], idle: Option<u64>) -> Option<u64> {
    samples.iter().copied().chain(idle).max()
}

/// `index_bytes * 1000 / passage_count`; a zero passage count is an error.
pub fn disk_bytes_per_1k_passages(index_bytes: u64, passages: u64) -> Result<f64> {
    if passages == 0 {
        return Err(Failure::report(
            "REPORT_INVALID: disk bytes per 1k passages needs a nonzero passage count",
        ));
    }
    Ok(index_bytes as f64 * 1000.0 / passages as f64)
}

/// Total bytes of regular files under `dir`, skipping the named top-level
/// entries (harness metadata, never engine state). Symlinks are not followed.
pub fn directory_bytes(dir: &Path, skip: &[&str]) -> Result<u64> {
    let mut total = 0_u64;
    let mut stack = vec![(dir.to_path_buf(), true)];
    while let Some((current, top)) = stack.pop() {
        let entries = std::fs::read_dir(&current)
            .map_err(|error| Failure::engine(format!("cannot measure index size: {error}")))?;
        for entry in entries {
            let entry = entry
                .map_err(|error| Failure::engine(format!("cannot measure index size: {error}")))?;
            if top && skip.iter().any(|name| entry.file_name() == **name) {
                continue;
            }
            let kind = entry
                .file_type()
                .map_err(|error| Failure::engine(format!("cannot measure index size: {error}")))?;
            if kind.is_dir() {
                stack.push((entry.path(), false));
            } else if kind.is_file() {
                let length = entry
                    .metadata()
                    .map_err(|error| {
                        Failure::engine(format!("cannot measure index size: {error}"))
                    })?
                    .len();
                total = total.saturating_add(length);
            }
        }
    }
    Ok(total)
}
