//! Latency percentiles, fixed-seed bootstrap intervals, and the S5
//! interference ratio (SPEC-0003 R25, R26, sections 4.5 and 4.10).
//!
//! The random primitive is the SPEC-0004 section 4.4 one restated in SPEC-0003
//! section 4.5: `u = be_u64(SHA-256("SDC1\0" + seed + "\0" + purpose + "\0" +
//! key)[0..8]) / 2^64`, with purpose `latency-bootstrap` and key
//! `"<resample>:<sample-index>"`.

use crate::{Failure, Result};
use seeky_eval::{InterferenceRatio, LatencyMetrics};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fmt::Write as _;

/// Bootstrap purpose for latency intervals (SPEC-0003 section 4.5).
pub const LATENCY_PURPOSE: &str = "latency-bootstrap";
/// Required resample count (SPEC-0003 section 4.10).
pub const RESAMPLES: usize = 10_000;
/// Reported percentiles, in report order.
pub const PERCENTILES: [(&str, f64); 3] = [("p50", 0.50), ("p95", 0.95), ("p99", 0.99)];

/// Type-7 (linear interpolation) percentile of ascending `sorted` values.
#[must_use]
pub fn percentile_type7(sorted: &[f64], probability: f64) -> f64 {
    match sorted.len() {
        0 => f64::NAN,
        1 => sorted[0],
        len => {
            let position = (len - 1) as f64 * probability.clamp(0.0, 1.0);
            let lower = position.floor() as usize;
            let upper = (lower + 1).min(len - 1);
            let fraction = position - lower as f64;
            sorted[lower] + fraction * (sorted[upper] - sorted[lower])
        }
    }
}

/// Deterministic resampling source for one seed, purpose, and key prefix.
struct Resampler {
    prefix: Sha256,
    key: String,
}

impl Resampler {
    fn new(seed: &str, purpose: &str) -> Self {
        let mut prefix = Sha256::new();
        prefix.update(b"SDC1\0");
        prefix.update(seed.as_bytes());
        prefix.update(b"\0");
        prefix.update(purpose.as_bytes());
        prefix.update(b"\0");
        Self {
            prefix,
            key: String::with_capacity(32),
        }
    }

    /// `floor(U(key_prefix + "<resample>:<index>") * len)`.
    fn index(&mut self, key_prefix: &str, resample: usize, index: usize, len: usize) -> usize {
        self.key.clear();
        let _ = write!(self.key, "{key_prefix}{resample}:{index}");
        let mut hasher = self.prefix.clone();
        hasher.update(self.key.as_bytes());
        let digest = hasher.finalize();
        let mut word = [0_u8; 8];
        word.copy_from_slice(&digest[..8]);
        let unit = u64::from_be_bytes(word) as f64 / 18_446_744_073_709_551_616.0;
        ((unit * len as f64) as usize).min(len - 1)
    }
}

/// Run `resamples` bootstrap draws in parallel; `statistic` receives one sorted
/// resample per draw. Results are returned in resample order.
fn bootstrap<F>(
    seed: &str,
    resamples: usize,
    draw: &(dyn Fn(&mut Resampler, usize, &mut Vec<f64>) + Sync),
    statistic: F,
) -> Vec<Vec<f64>>
where
    F: Fn(&[f64]) -> Vec<f64> + Sync,
{
    let threads = std::thread::available_parallelism()
        .map(std::num::NonZeroUsize::get)
        .unwrap_or(1)
        .clamp(1, 16);
    let chunk = resamples.div_ceil(threads).max(1);
    let mut results: Vec<Vec<f64>> = vec![Vec::new(); resamples];
    std::thread::scope(|scope| {
        for (chunk_index, slots) in results.chunks_mut(chunk).enumerate() {
            let statistic = &statistic;
            scope.spawn(move || {
                let mut resampler = Resampler::new(seed, LATENCY_PURPOSE);
                let mut buffer = Vec::new();
                for (offset, slot) in slots.iter_mut().enumerate() {
                    let resample = chunk_index * chunk + offset;
                    buffer.clear();
                    draw(&mut resampler, resample, &mut buffer);
                    buffer.sort_by(f64::total_cmp);
                    *slot = statistic(&buffer);
                }
            });
        }
    });
    results
}

fn ci95(values: &mut [f64]) -> [f64; 2] {
    values.sort_by(f64::total_cmp);
    [
        percentile_type7(values, 0.025),
        percentile_type7(values, 0.975),
    ]
}

fn validate_samples(samples: &[f64], what: &str) -> Result<()> {
    if samples.is_empty() {
        return Err(Failure::report(format!("{what}: no latency samples")));
    }
    if samples
        .iter()
        .any(|value| !value.is_finite() || *value < 0.0)
    {
        return Err(Failure::report(format!(
            "{what}: latency samples must be finite and non-negative"
        )));
    }
    Ok(())
}

/// p50/p95/p99 with fixed-seed 95% bootstrap intervals.
pub fn latency_metrics(samples_ms: &[f64], seed: &str, resamples: usize) -> Result<LatencyMetrics> {
    validate_samples(samples_ms, "latency")?;
    if resamples == 0 {
        return Err(Failure::report("bootstrap needs at least one resample"));
    }
    let mut sorted = samples_ms.to_vec();
    sorted.sort_by(f64::total_cmp);
    let len = samples_ms.len();
    let draw = |resampler: &mut Resampler, resample: usize, buffer: &mut Vec<f64>| {
        for position in 0..len {
            buffer.push(samples_ms[resampler.index("", resample, position, len)]);
        }
    };
    let draws = bootstrap(seed, resamples, &draw, |resample| {
        PERCENTILES
            .iter()
            .map(|(_, probability)| percentile_type7(resample, *probability))
            .collect()
    });
    let mut ci = BTreeMap::new();
    for (index, (name, _)) in PERCENTILES.iter().enumerate() {
        let mut values: Vec<f64> = draws.iter().map(|draw| draw[index]).collect();
        ci.insert((*name).to_string(), ci95(&mut values));
    }
    Ok(LatencyMetrics {
        p50: percentile_type7(&sorted, 0.50),
        p95: percentile_type7(&sorted, 0.95),
        p99: percentile_type7(&sorted, 0.99),
        ci95: ci,
    })
}

/// S5 interference ratio `p95(indexing) / p95(idle)` with a fixed-seed
/// bootstrap interval that resamples both sets independently (keys prefixed
/// `idle:` and `indexing:`). An idle p95 of zero is an error.
pub fn interference_ratio(
    idle_ms: &[f64],
    indexing_ms: &[f64],
    seed: &str,
    resamples: usize,
) -> Result<InterferenceRatio> {
    validate_samples(idle_ms, "interference idle")?;
    validate_samples(indexing_ms, "interference indexing")?;
    if resamples == 0 {
        return Err(Failure::report("bootstrap needs at least one resample"));
    }
    let p95 = |values: &[f64]| {
        let mut sorted = values.to_vec();
        sorted.sort_by(f64::total_cmp);
        percentile_type7(&sorted, 0.95)
    };
    let idle_p95 = p95(idle_ms);
    let indexing_p95 = p95(indexing_ms);
    if idle_p95 <= 0.0 {
        return Err(Failure::report(
            "interference ratio is undefined: idle p95 is 0",
        ));
    }
    let draw = |resampler: &mut Resampler, resample: usize, buffer: &mut Vec<f64>| {
        // Both resamples are packed into one buffer: idle first, then indexing.
        let mut idle: Vec<f64> = (0..idle_ms.len())
            .map(|position| idle_ms[resampler.index("idle:", resample, position, idle_ms.len())])
            .collect();
        let mut indexing: Vec<f64> = (0..indexing_ms.len())
            .map(|position| {
                indexing_ms[resampler.index("indexing:", resample, position, indexing_ms.len())]
            })
            .collect();
        idle.sort_by(f64::total_cmp);
        indexing.sort_by(f64::total_cmp);
        let idle = percentile_type7(&idle, 0.95);
        let indexing = percentile_type7(&indexing, 0.95);
        buffer.push(if idle > 0.0 {
            indexing / idle
        } else {
            f64::INFINITY
        });
    };
    let draws = bootstrap(seed, resamples, &draw, <[f64]>::to_vec);
    let mut ratios: Vec<f64> = draws.iter().map(|draw| draw[0]).collect();
    Ok(InterferenceRatio {
        value: indexing_p95 / idle_p95,
        idle_p95_ms: idle_p95,
        indexing_p95_ms: indexing_p95,
        ci95: ci95(&mut ratios),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn type7_matches_hand_calculation() {
        // SPEC-0003-R25
        let values: Vec<f64> = (12..=21).map(f64::from).collect();
        assert!((percentile_type7(&values, 0.95) - 20.55).abs() < 1e-12);
        assert!((percentile_type7(&values, 0.50) - 16.5).abs() < 1e-12);
        assert_eq!(percentile_type7(&[7.0], 0.99), 7.0);
        assert!(percentile_type7(&[], 0.5).is_nan());
    }

    #[test]
    fn malformed_samples_are_typed_errors() {
        // SPEC-0003-R25
        assert!(latency_metrics(&[], "s", 10).is_err());
        assert!(latency_metrics(&[1.0, f64::NAN], "s", 10).is_err());
        assert!(latency_metrics(&[1.0, -1.0], "s", 10).is_err());
        assert!(latency_metrics(&[1.0], "s", 0).is_err());
        assert!(interference_ratio(&[], &[1.0], "s", 10).is_err());
    }
}
