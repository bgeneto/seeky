//! Fixed-seed paired randomization, bootstrap, and Holm adjustment
//! (SPEC-0003 R11).

use std::collections::{BTreeMap, BTreeSet};

use sha2::{Digest, Sha256};

use crate::dataset::LanguageSlice;
use crate::error::{EvalError, Result};
use crate::metrics::{EvaluationResult, QueryContext};

/// Paired statistics options.
#[derive(Clone, Debug)]
pub struct StatsOptions {
    /// Deterministic seed.
    pub seed: String,
    /// Number of resamples.
    pub resamples: usize,
    /// Two-sided alpha.
    pub alpha: f64,
}

impl Default for StatsOptions {
    fn default() -> Self {
        Self {
            seed: "seeky-eval-v1".to_owned(),
            resamples: 10_000,
            alpha: 0.05,
        }
    }
}

/// Statistical interpretation of a paired difference.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Significance {
    /// Significant at the configured alpha with an interval excluding zero.
    Significant,
    /// Not significant.
    NotSignificant,
    /// The p-value and interval disagree, or the interval is unavailable.
    Inconclusive,
}

/// Result of one paired metric comparison.
#[derive(Clone, Debug)]
pub struct PairedStatistic {
    /// Candidate minus baseline difference.
    pub delta: f64,
    /// Difference in points.
    pub delta_points: f64,
    /// Lower 95% confidence bound.
    pub ci95_low: f64,
    /// Upper 95% confidence bound.
    pub ci95_high: f64,
    /// Two-sided randomization p-value.
    pub p_value: f64,
    /// Holm-adjusted p-value when part of a family.
    pub holm_p: Option<f64>,
    /// Interpretation.
    pub significance: Significance,
}

/// Paired comparison result.
#[derive(Clone, Debug)]
pub struct Comparison {
    /// Baseline system ID.
    pub baseline_system_id: String,
    /// Candidate system ID(s).
    pub candidate_system_ids: Vec<String>,
    /// Number of paired queries.
    pub paired_queries: usize,
    /// Seed used.
    pub seed: String,
    /// Metric ID → paired statistic.
    pub metrics: BTreeMap<String, PairedStatistic>,
}

/// Compare one baseline/candidate pair.
pub fn compare(
    baseline: &EvaluationResult,
    candidate: &EvaluationResult,
    options: &StatsOptions,
) -> Result<Comparison> {
    compare_many(baseline, &[("candidate", candidate)], options, "baseline")?
        .into_iter()
        .next()
        .ok_or_else(|| EvalError::data("STATS_INPUT_MISMATCH", "compare", "no candidate"))
}

/// Compare a baseline with one or more candidates and apply Holm adjustment
/// across each metric's candidate family.
pub fn compare_many(
    baseline: &EvaluationResult,
    candidates: &[(&str, &EvaluationResult)],
    options: &StatsOptions,
    baseline_name: &str,
) -> Result<Vec<Comparison>> {
    validate_options(options)?;
    if candidates.is_empty() {
        return Err(EvalError::data(
            "STATS_INPUT_MISMATCH",
            "compare",
            "at least one candidate is required",
        ));
    }
    validate_compatible(baseline, candidates)?;
    let mut comparisons = Vec::new();
    for (name, candidate) in candidates {
        comparisons.push(build_comparison(
            baseline,
            candidate,
            options,
            baseline_name,
            name,
        )?);
    }
    let metric_ids: BTreeSet<String> = comparisons
        .iter()
        .flat_map(|comparison| comparison.metrics.keys().cloned())
        .collect();
    for metric in metric_ids {
        let raw: Vec<(String, f64)> = comparisons
            .iter()
            .filter_map(|comparison| {
                comparison.metrics.get(&metric).map(|statistic| {
                    (
                        comparison.candidate_system_ids[0].clone(),
                        statistic.p_value,
                    )
                })
            })
            .collect();
        let adjusted = holm_adjust(&raw)?;
        for comparison in &mut comparisons {
            if let Some(statistic) = comparison.metrics.get_mut(&metric) {
                statistic.holm_p = adjusted.get(&comparison.candidate_system_ids[0]).copied();
            }
        }
    }
    Ok(comparisons)
}

/// Holm step-down adjustment. Returns candidate ID → adjusted p-value.
pub fn holm_adjust(raw: &[(String, f64)]) -> Result<BTreeMap<String, f64>> {
    if raw
        .iter()
        .any(|(id, p)| id.is_empty() || !(0.0..=1.0).contains(p))
    {
        return Err(EvalError::data(
            "STATS_INPUT_MISMATCH",
            "holm",
            "invalid candidate ID or p-value",
        ));
    }
    let mut sorted = raw.to_vec();
    sorted.sort_by(|left, right| {
        left.1
            .total_cmp(&right.1)
            .then_with(|| left.0.cmp(&right.0))
    });
    let m = sorted.len();
    let mut result = BTreeMap::new();
    let mut running = 0.0_f64;
    for (index, (id, p)) in sorted.into_iter().enumerate() {
        let adjusted = ((m - index) as f64 * p).min(1.0).max(running);
        running = adjusted;
        result.insert(id, adjusted);
    }
    Ok(result)
}

fn validate_options(options: &StatsOptions) -> Result<()> {
    if options.seed.is_empty()
        || options.seed.len() > 64
        || !options.seed.bytes().all(|byte| byte.is_ascii_graphic())
    {
        return Err(EvalError::data(
            "SCHEMA",
            "stats.seed",
            "seed must be 1..=64 printable ASCII bytes",
        ));
    }
    if options.resamples == 0 {
        return Err(EvalError::data(
            "SCHEMA",
            "stats.resamples",
            "resamples must be positive",
        ));
    }
    if !(0.0..1.0).contains(&options.alpha) {
        return Err(EvalError::data(
            "SCHEMA",
            "stats.alpha",
            "alpha must be in (0, 1)",
        ));
    }
    Ok(())
}

fn validate_compatible(
    baseline: &EvaluationResult,
    candidates: &[(&str, &EvaluationResult)],
) -> Result<()> {
    for (name, candidate) in candidates {
        if name.trim().is_empty() {
            return Err(EvalError::data(
                "STATS_INPUT_MISMATCH",
                "compare",
                "candidate ID is empty",
            ));
        }
        if baseline.dataset_fingerprint != candidate.dataset_fingerprint
            || baseline.query_set_sha256 != candidate.query_set_sha256
            || baseline.split != candidate.split
            || baseline.configuration != candidate.configuration
        {
            return Err(EvalError::data(
                "STATS_INPUT_MISMATCH",
                "compare",
                "datasets, query sets, splits, or configurations differ",
            ));
        }
        if baseline.query_contexts != candidate.query_contexts {
            return Err(EvalError::data(
                "STATS_INPUT_MISMATCH",
                "compare",
                "query contexts differ",
            ));
        }
        let metrics = |result: &EvaluationResult| {
            result
                .per_query
                .values()
                .flat_map(|rows| rows.keys().cloned())
                .collect::<BTreeSet<_>>()
        };
        if metrics(baseline) != metrics(candidate) {
            return Err(EvalError::data(
                "STATS_INPUT_MISMATCH",
                "compare",
                "metric definitions differ",
            ));
        }
    }
    Ok(())
}

fn build_comparison(
    baseline: &EvaluationResult,
    candidate: &EvaluationResult,
    options: &StatsOptions,
    baseline_name: &str,
    candidate_name: &str,
) -> Result<Comparison> {
    let metric_ids = baseline
        .per_query
        .values()
        .flat_map(|rows| rows.keys().cloned())
        .collect::<BTreeSet<_>>();
    let mut metrics = BTreeMap::new();
    let mut paired_queries = 0;
    for metric in metric_ids {
        let mut pairs = Vec::new();
        for (query_id, base_rows) in &baseline.per_query {
            let Some(base_value) = base_rows.get(&metric) else {
                continue;
            };
            let candidate_value = candidate
                .per_query
                .get(query_id)
                .and_then(|rows| rows.get(&metric))
                .ok_or_else(|| {
                    EvalError::data(
                        "STATS_INPUT_MISMATCH",
                        "compare",
                        format!("metric {metric} is missing for {query_id}"),
                    )
                })?;
            let context = baseline.query_contexts.get(query_id).ok_or_else(|| {
                EvalError::data(
                    "STATS_INPUT_MISMATCH",
                    "compare",
                    "query context is missing",
                )
            })?;
            pairs.push((query_id.clone(), *base_value, *candidate_value, *context));
        }
        if pairs.is_empty() {
            continue;
        }
        paired_queries = paired_queries.max(pairs.len());
        let statistic = paired_statistic(&pairs, options, false)?;
        metrics.insert(metric, statistic);
    }
    if let (Some(baseline_weighted), Some(candidate_weighted)) =
        (baseline.weighted_primary, candidate.weighted_primary)
    {
        let mut pairs = Vec::new();
        for (query_id, context) in &baseline.query_contexts {
            if context.configuration != crate::dataset::EvaluationConfiguration::Default {
                continue;
            }
            if slice_weight(context.language_slice).is_none() {
                continue;
            }
            let base_value = baseline
                .per_query
                .get(query_id)
                .and_then(|rows| rows.get("ndcg_10"))
                .copied();
            let candidate_value = candidate
                .per_query
                .get(query_id)
                .and_then(|rows| rows.get("ndcg_10"))
                .copied();
            if let (Some(base_value), Some(candidate_value)) = (base_value, candidate_value) {
                pairs.push((query_id.clone(), base_value, candidate_value, *context));
            }
        }
        if !pairs.is_empty() {
            let mut statistic = paired_statistic(&pairs, options, true)?;
            statistic.delta = candidate_weighted - baseline_weighted;
            statistic.delta_points = 100.0 * statistic.delta;
            metrics.insert("weighted_primary".to_owned(), statistic);
        }
    }
    Ok(Comparison {
        baseline_system_id: baseline_name.to_owned(),
        candidate_system_ids: vec![candidate_name.to_owned()],
        paired_queries,
        seed: options.seed.clone(),
        metrics,
    })
}

fn slice_weight(slice: LanguageSlice) -> Option<f64> {
    match slice {
        LanguageSlice::Pt => Some(0.35),
        LanguageSlice::En => Some(0.35),
        LanguageSlice::CrossLingual => Some(0.15),
        LanguageSlice::Other => Some(0.15),
        LanguageSlice::NonLatinNonRegression => None,
    }
}

fn paired_statistic(
    pairs: &[(String, f64, f64, QueryContext)],
    options: &StatsOptions,
    weighted: bool,
) -> Result<PairedStatistic> {
    let differences: Vec<f64> = pairs
        .iter()
        .map(|(_, baseline, candidate, _)| candidate - baseline)
        .collect();
    let weights = if weighted {
        let counts = pair_slice_counts(pairs);
        pairs
            .iter()
            .map(|(_, _, _, context)| {
                let weight = slice_weight(context.language_slice).ok_or_else(|| {
                    EvalError::data(
                        "STATS_INPUT_MISMATCH",
                        "compare",
                        "non-weighted query in weighted statistic",
                    )
                })?;
                let count = counts.get(&context.language_slice).copied().unwrap_or(1);
                Ok(weight / count as f64)
            })
            .collect::<Result<Vec<_>>>()?
    } else {
        vec![1.0 / differences.len() as f64; differences.len()]
    };
    let observed: f64 = differences
        .iter()
        .zip(&weights)
        .map(|(difference, weight)| difference * weight)
        .sum();
    let mut extreme = 0;
    for resample in 0..options.resamples {
        let sampled: f64 = differences
            .iter()
            .enumerate()
            .map(|(index, difference)| {
                let sign = if unit(
                    &options.seed,
                    "paired-randomization",
                    &format!("{resample}:{}", pairs[index].0),
                ) < 0.5
                {
                    -1.0
                } else {
                    1.0
                };
                sign * difference * weights[index]
            })
            .sum();
        if sampled.abs() >= observed.abs() - 1e-15 {
            extreme += 1;
        }
    }
    let p_value = (1.0 + extreme as f64) / (options.resamples as f64 + 1.0);
    let slice_positions = if weighted {
        let mut positions: BTreeMap<LanguageSlice, Vec<usize>> = BTreeMap::new();
        for (index, (_, _, _, context)) in pairs.iter().enumerate() {
            positions
                .entry(context.language_slice)
                .or_default()
                .push(index);
        }
        Some(positions)
    } else {
        None
    };
    let mut boot = Vec::with_capacity(options.resamples);
    for resample in 0..options.resamples {
        let sampled = if let Some(positions) = &slice_positions {
            let mut sum = 0.0;
            for (slice, indices) in positions {
                let weight = slice_weight(*slice).ok_or_else(|| {
                    EvalError::data(
                        "STATS_INPUT_MISMATCH",
                        "compare",
                        "non-weighted query in weighted statistic",
                    )
                })?;
                for global_index in indices {
                    let pick = random_index(
                        &options.seed,
                        "paired-bootstrap",
                        resample,
                        *global_index,
                        indices.len(),
                    );
                    sum += differences[indices[pick]] * weight / indices.len() as f64;
                }
            }
            sum
        } else {
            let mut sum = 0.0;
            for (index, weight) in weights.iter().enumerate().take(pairs.len()) {
                let pick = random_index(
                    &options.seed,
                    "paired-bootstrap",
                    resample,
                    index,
                    pairs.len(),
                );
                sum += differences[pick] * weight;
            }
            sum
        };
        boot.push(sampled);
    }
    boot.sort_by(f64::total_cmp);
    let ci95_low = quantile(&boot, 0.025);
    let ci95_high = quantile(&boot, 0.975);
    let significant = p_value < options.alpha && (ci95_low > 0.0 || ci95_high < 0.0);
    let significance = if significant {
        Significance::Significant
    } else if (ci95_low <= 0.0 && ci95_high >= 0.0) && p_value >= options.alpha {
        Significance::NotSignificant
    } else {
        Significance::Inconclusive
    };
    Ok(PairedStatistic {
        delta: observed,
        delta_points: 100.0 * observed,
        ci95_low,
        ci95_high,
        p_value,
        holm_p: None,
        significance,
    })
}

fn pair_slice_counts(pairs: &[(String, f64, f64, QueryContext)]) -> BTreeMap<LanguageSlice, usize> {
    let mut counts = BTreeMap::new();
    for (_, _, _, context) in pairs {
        *counts.entry(context.language_slice).or_default() += 1;
    }
    counts
}

fn random_index(seed: &str, purpose: &str, resample: usize, position: usize, len: usize) -> usize {
    let key = format!("{resample}:{position}");
    let value = unit(seed, purpose, &key);
    usize::try_from((value * len as f64).floor() as u64)
        .unwrap_or(0)
        .min(len.saturating_sub(1))
}

fn unit(seed: &str, purpose: &str, key: &str) -> f64 {
    let input = format!("SDC1\0{seed}\0{purpose}\0{key}");
    let digest = Sha256::digest(input.as_bytes());
    let mut bytes = [0_u8; 8];
    bytes.copy_from_slice(&digest[..8]);
    u64::from_be_bytes(bytes) as f64 / 18_446_744_073_709_551_616.0
}

fn quantile(values: &[f64], probability: f64) -> f64 {
    if values.len() == 1 {
        return values[0];
    }
    let position = (values.len() - 1) as f64 * probability;
    let lower = position.floor() as usize;
    let upper = position.ceil() as usize;
    let fraction = position - lower as f64;
    values[lower] + (values[upper] - values[lower]) * fraction
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dataset::{EvaluationConfiguration, LanguageSlice, QueryCategory};

    #[test]
    fn randomization_and_bootstrap_match_fixed_seed_reference() {
        let pairs: Vec<_> = [0.00, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.16]
            .into_iter()
            .enumerate()
            .map(|(index, difference)| {
                (
                    format!("q{:02}", index + 1),
                    0.0,
                    difference,
                    QueryContext {
                        category: QueryCategory::Conceptual,
                        language_slice: LanguageSlice::En,
                        configuration: EvaluationConfiguration::Default,
                    },
                )
            })
            .collect();
        let options = StatsOptions {
            seed: "seeky-eval-reference-v1".to_owned(),
            resamples: 10_000,
            alpha: 0.05,
        };
        let stat = paired_statistic(&pairs, &options, false).unwrap();
        let expected: serde_json::Value =
            serde_json::from_str(include_str!("../tests/fixtures/reference-v1/expected.json"))
                .unwrap();
        let statistics = &expected["statistics-v1"];
        let ci = statistics["bootstrap_ci95"].as_array().unwrap();
        assert!(
            (stat.delta - statistics["observed_mean_difference"].as_f64().unwrap()).abs() < 1e-12
        );
        assert!(
            (stat.p_value - statistics["randomization_p_two_sided"].as_f64().unwrap()).abs()
                < 1e-12
        );
        assert!((stat.ci95_low - ci[0].as_f64().unwrap()).abs() < 1e-12);
        assert!((stat.ci95_high - ci[1].as_f64().unwrap()).abs() < 1e-12);
        // p = (1 + n_extreme) / (10_000 + 1), so the count is recoverable.
        let extreme_count = (stat.p_value * 10_001.0 - 1.0).round();
        assert_eq!(
            extreme_count as u64,
            statistics["randomization_extreme_count"].as_u64().unwrap()
        );
        assert_eq!(stat.significance, Significance::Significant);
    }

    #[test]
    fn paired_statistics_are_seed_reproducible() {
        let pairs: Vec<_> = ["q1", "q2", "q3"]
            .into_iter()
            .map(|id| {
                (
                    id.to_owned(),
                    0.1,
                    0.2,
                    QueryContext {
                        category: QueryCategory::Conceptual,
                        language_slice: LanguageSlice::En,
                        configuration: EvaluationConfiguration::Default,
                    },
                )
            })
            .collect();
        let options = StatsOptions {
            seed: "fixed".to_owned(),
            resamples: 100,
            alpha: 0.05,
        };
        let first = paired_statistic(&pairs, &options, false).unwrap();
        let second = paired_statistic(&pairs, &options, false).unwrap();
        assert_eq!(first.p_value, second.p_value);
        assert_eq!(first.ci95_low, second.ci95_low);
    }

    fn simple_result(offset: f64) -> EvaluationResult {
        let contexts = ["q1", "q2"]
            .into_iter()
            .map(|id| {
                (
                    id.to_owned(),
                    QueryContext {
                        category: QueryCategory::Conceptual,
                        language_slice: LanguageSlice::En,
                        configuration: EvaluationConfiguration::Default,
                    },
                )
            })
            .collect();
        let per_query = ["q1", "q2"]
            .into_iter()
            .enumerate()
            .map(|(index, id)| {
                (
                    id.to_owned(),
                    BTreeMap::from([("ndcg_10".to_owned(), 0.5 + offset + index as f64 * 0.01)]),
                )
            })
            .collect();
        EvaluationResult {
            dataset_fingerprint: "f".to_owned(),
            query_set_sha256: "q".to_owned(),
            split: crate::dataset::Split::Dev,
            configuration: EvaluationConfiguration::Default,
            per_query,
            query_contexts: contexts,
            macro_metrics: BTreeMap::new(),
            category_metrics: BTreeMap::new(),
            language_metrics: BTreeMap::new(),
            weighted_primary: None,
            queries_without_positive: 0,
            unavailable_metrics: BTreeSet::new(),
        }
    }

    #[test]
    fn compare_builds_paired_statistics_and_holm_family() {
        let baseline = simple_result(0.0);
        let candidate_a = simple_result(0.1);
        let candidate_b = simple_result(0.2);
        let options = StatsOptions {
            seed: "fixed".to_owned(),
            resamples: 200,
            alpha: 0.05,
        };
        let comparisons = compare_many(
            &baseline,
            &[("a", &candidate_a), ("b", &candidate_b)],
            &options,
            "base",
        )
        .unwrap();
        assert_eq!(comparisons.len(), 2);
        assert!(comparisons[0].metrics["ndcg_10"].holm_p.is_some());
        assert!(comparisons[1].metrics["ndcg_10"].holm_p.is_some());
    }

    #[test]
    fn weighted_statistic_uses_fixed_slice_weights() {
        fn result(offset: f64) -> EvaluationResult {
            let entries = [
                ("qpt", LanguageSlice::Pt, 0.4),
                ("qen", LanguageSlice::En, 0.5),
                ("qx", LanguageSlice::CrossLingual, 0.6),
                ("qo", LanguageSlice::Other, 0.7),
            ];
            let contexts = entries
                .iter()
                .map(|(id, slice, _)| {
                    (
                        (*id).to_owned(),
                        QueryContext {
                            category: QueryCategory::Conceptual,
                            language_slice: *slice,
                            configuration: EvaluationConfiguration::Default,
                        },
                    )
                })
                .collect();
            let per_query = entries
                .iter()
                .map(|(id, _, value)| {
                    (
                        (*id).to_owned(),
                        BTreeMap::from([("ndcg_10".to_owned(), value + offset)]),
                    )
                })
                .collect();
            EvaluationResult {
                dataset_fingerprint: "f".to_owned(),
                query_set_sha256: "q".to_owned(),
                split: crate::dataset::Split::Dev,
                configuration: EvaluationConfiguration::Default,
                per_query,
                query_contexts: contexts,
                macro_metrics: BTreeMap::new(),
                category_metrics: BTreeMap::new(),
                language_metrics: BTreeMap::new(),
                weighted_primary: Some(0.51 + offset),
                queries_without_positive: 0,
                unavailable_metrics: BTreeSet::new(),
            }
        }
        let comparison = compare(
            &result(0.0),
            &result(0.1),
            &StatsOptions {
                seed: "fixed".to_owned(),
                resamples: 200,
                alpha: 0.05,
            },
        )
        .unwrap();
        let weighted = &comparison.metrics["weighted_primary"];
        assert!((weighted.delta - 0.1).abs() < 1e-12);
        assert!((weighted.delta_points - 10.0).abs() < 1e-12);
    }

    #[test]
    fn holm_adjustment_matches_reference() {
        let raw = vec![
            ("cand-a".to_owned(), 0.04),
            ("cand-b".to_owned(), 0.01),
            ("cand-c".to_owned(), 0.03),
        ];
        let adjusted = holm_adjust(&raw).unwrap();
        assert!((adjusted["cand-b"] - 0.03).abs() < 1e-12);
        assert!((adjusted["cand-c"] - 0.06).abs() < 1e-12);
        assert!((adjusted["cand-a"] - 0.06).abs() < 1e-12);
    }

    #[test]
    fn property_sign_symmetry_and_query_permutation() {
        let base = [
            ("q1".to_owned(), 0.1),
            ("q2".to_owned(), 0.2),
            ("q3".to_owned(), -0.05),
        ];
        let mut pairs: Vec<_> = base
            .into_iter()
            .map(|(id, difference)| {
                (
                    id,
                    0.0,
                    difference,
                    QueryContext {
                        category: QueryCategory::Conceptual,
                        language_slice: LanguageSlice::En,
                        configuration: EvaluationConfiguration::Default,
                    },
                )
            })
            .collect();
        let options = StatsOptions {
            seed: "fixed".to_owned(),
            resamples: 1000,
            alpha: 0.05,
        };
        let first = paired_statistic(&pairs, &options, false).unwrap();
        pairs.reverse();
        let permuted = paired_statistic(&pairs, &options, false).unwrap();
        assert!((first.delta - permuted.delta).abs() < 1e-12);
        assert!((first.p_value - permuted.p_value).abs() < 1e-12);
        for pair in &mut pairs {
            pair.2 = -pair.2;
        }
        let reversed = paired_statistic(&pairs, &options, false).unwrap();
        assert!((first.p_value - reversed.p_value).abs() < 1e-12);
    }
}
