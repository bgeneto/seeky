//! Measurement loops for the `perf` suites (SPEC-0003 R25, R26, section 5.5).
//!
//! Every loop takes an injected [`Clock`] and target trait so tests can drive
//! it deterministically; production wires them to the monotonic clock and the
//! SPEC-0002 v1.1 `Engine` API.

use crate::{Failure, Result};
use seeky_eval::IndexingMetrics;
use std::time::Instant;

/// Monotonic nanosecond clock.
pub trait Clock: Send + Sync {
    /// Nanoseconds since an arbitrary fixed origin; never decreases.
    fn now_ns(&self) -> u64;
}

/// Production clock backed by [`Instant`].
pub struct MonotonicClock {
    origin: Instant,
}

impl MonotonicClock {
    /// A clock whose origin is now.
    #[must_use]
    pub fn new() -> Self {
        Self {
            origin: Instant::now(),
        }
    }
}

impl Default for MonotonicClock {
    fn default() -> Self {
        Self::new()
    }
}

impl Clock for MonotonicClock {
    fn now_ns(&self) -> u64 {
        u64::try_from(self.origin.elapsed().as_nanos()).unwrap_or(u64::MAX)
    }
}

/// One end-to-end search execution.
pub trait SearchTarget {
    /// Execute `query` and wait for the complete result list.
    fn run_query(&self, query: &str) -> Result<()>;
}

/// One uncached batch-1 query embedding.
pub trait EmbeddingTarget {
    /// Embedding duration in nanoseconds, or `None` when no semantic model is
    /// active (not an error).
    fn embed_ns(&self, query: &str) -> Result<Option<u64>>;
}

/// Fixed query set and repetition count.
#[derive(Clone, Debug)]
pub struct QueryPlan {
    /// Fixed dev query texts, in dataset order (kept in memory only).
    pub queries: Vec<String>,
    /// Measured repetitions of the fixed set (warm-up excluded).
    pub repetitions: u64,
}

impl QueryPlan {
    /// Measured executions per stage.
    #[must_use]
    pub fn executions(&self) -> u64 {
        self.queries.len() as u64 * self.repetitions
    }
}

/// Measured search samples.
#[derive(Clone, Debug)]
pub struct SearchSamples {
    /// One latency sample per measured query execution, in milliseconds.
    pub samples_ms: Vec<f64>,
    /// Measured query executions.
    pub queries: u64,
    /// Measured repetitions.
    pub repetitions: u64,
}

fn elapsed_ms(start: u64, end: u64) -> f64 {
    end.saturating_sub(start) as f64 / 1_000_000.0
}

fn require_queries(plan: &QueryPlan) -> Result<()> {
    if plan.queries.is_empty() {
        return Err(Failure::dataset("perf needs at least one dev query"));
    }
    if plan.repetitions == 0 {
        return Err(Failure::usage("--repetitions must be at least 1"));
    }
    Ok(())
}

/// Warm-up pass over the fixed set (discarded), then `repetitions` timed
/// passes: one sample per query execution around the engine call.
pub fn measure_search(
    clock: &dyn Clock,
    target: &dyn SearchTarget,
    plan: &QueryPlan,
) -> Result<SearchSamples> {
    require_queries(plan)?;
    for query in &plan.queries {
        target.run_query(query)?;
    }
    let mut samples_ms = Vec::with_capacity(usize::try_from(plan.executions()).unwrap_or(0));
    for _ in 0..plan.repetitions {
        for query in &plan.queries {
            let start = clock.now_ns();
            target.run_query(query)?;
            samples_ms.push(elapsed_ms(start, clock.now_ns()));
        }
    }
    Ok(SearchSamples {
        queries: samples_ms.len() as u64,
        repetitions: plan.repetitions,
        samples_ms,
    })
}

/// Time the fixed set while `active()` holds (warm-indexing condition). Only
/// executions that both start and finish while active are kept; the loop
/// stops after `repetitions` passes or as soon as the condition ends.
pub fn measure_search_while(
    clock: &dyn Clock,
    target: &dyn SearchTarget,
    plan: &QueryPlan,
    active: &dyn Fn() -> bool,
) -> Result<SearchSamples> {
    require_queries(plan)?;
    let mut samples_ms = Vec::new();
    let mut repetitions = 0;
    'outer: for _ in 0..plan.repetitions {
        for query in &plan.queries {
            if !active() {
                break 'outer;
            }
            let start = clock.now_ns();
            target.run_query(query)?;
            let end = clock.now_ns();
            if !active() {
                break 'outer;
            }
            samples_ms.push(elapsed_ms(start, end));
        }
        repetitions += 1;
    }
    Ok(SearchSamples {
        queries: samples_ms.len() as u64,
        repetitions,
        samples_ms,
    })
}

/// Batch-1 query-embedding latency over the fixed set: a discarded warm-up
/// pass, then `repetitions` passes. `None` when no semantic model is active.
pub fn measure_embedding(
    target: &dyn EmbeddingTarget,
    plan: &QueryPlan,
) -> Result<Option<SearchSamples>> {
    require_queries(plan)?;
    for query in &plan.queries {
        if target.embed_ns(query)?.is_none() {
            return Ok(None);
        }
    }
    let mut samples_ms = Vec::with_capacity(usize::try_from(plan.executions()).unwrap_or(0));
    for _ in 0..plan.repetitions {
        for query in &plan.queries {
            let Some(duration_ns) = target.embed_ns(query)? else {
                return Ok(None);
            };
            samples_ms.push(duration_ns as f64 / 1_000_000.0);
        }
    }
    Ok(Some(SearchSamples {
        queries: samples_ms.len() as u64,
        repetitions: plan.repetitions,
        samples_ms,
    }))
}

/// Milliseconds from `start_ns` to the first poll whose search found the
/// target; `None` when no poll within `max_polls` matched.
pub fn time_to_searchable(
    clock: &dyn Clock,
    start_ns: u64,
    max_polls: usize,
    poll: &mut dyn FnMut() -> Result<bool>,
) -> Result<Option<f64>> {
    for _ in 0..max_polls {
        if poll()? {
            return Ok(Some(elapsed_ms(start_ns, clock.now_ns())));
        }
    }
    Ok(None)
}

/// Bulk indexing throughput over one timed run.
pub fn indexing_throughput(
    files: u64,
    source_bytes: u64,
    passages: u64,
    elapsed_ns: u64,
    provider: &str,
) -> Result<IndexingMetrics> {
    if elapsed_ns == 0 {
        return Err(Failure::report(
            "indexing throughput is undefined for a zero duration",
        ));
    }
    let seconds = elapsed_ns as f64 / 1e9;
    Ok(IndexingMetrics {
        files_per_s: files as f64 / seconds,
        extract_mb_per_s: source_bytes as f64 / 1e6 / seconds,
        passages_per_s: passages as f64 / seconds,
        provider: provider.to_string(),
        samples: 1,
    })
}
