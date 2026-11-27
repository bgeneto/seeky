//! Privacy-safe environment capture and the semantically hashed configuration
//! (SPEC-0003 R16, section 4.9).
//!
//! Nothing here contains host or user identity, absolute paths, document
//! content, or query text.

use crate::{Failure, Result};
use seeky_eval::{EvaluationConfiguration, Split};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

/// Harness run configuration loaded from `--config`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunConfig {
    /// Config file name.
    pub name: String,
    /// Execution provider preference (`auto`, `cpu`, `cuda`, `npu`).
    pub backend: String,
    /// Whether the semantic channel is enabled.
    pub semantic: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ConfigFile {
    schema_version: u32,
    name: String,
    #[serde(default = "default_backend")]
    backend: String,
    #[serde(default = "default_true")]
    semantic: bool,
}

fn default_backend() -> String {
    "auto".to_string()
}

fn default_true() -> bool {
    true
}

/// Load and validate a JSON run configuration.
pub fn load_run_config(path: &Path) -> Result<RunConfig> {
    let text = std::fs::read_to_string(path)
        .map_err(|error| Failure::usage(format!("cannot read --config: {error}")))?;
    let file: ConfigFile = serde_json::from_str(&text)
        .map_err(|error| Failure::usage(format!("invalid --config JSON: {error}")))?;
    if file.schema_version != 1 {
        return Err(Failure::usage("--config schema_version must be 1"));
    }
    if file.name.trim().is_empty() {
        return Err(Failure::usage("--config name must be nonempty"));
    }
    if !matches!(file.backend.as_str(), "auto" | "cpu" | "cuda" | "npu") {
        return Err(Failure::usage(
            "--config backend must be auto, cpu, cuda, or npu",
        ));
    }
    Ok(RunConfig {
        name: file.name,
        backend: file.backend,
        semantic: file.semantic,
    })
}

/// Evaluation settings that are merged into the combined configuration hash.
#[derive(Clone, Debug)]
pub struct EvaluationSettings {
    /// Split.
    pub split: Split,
    /// Configuration.
    pub configuration: EvaluationConfiguration,
    /// Requested depth.
    pub limit: usize,
    /// Metric cutoffs.
    pub metrics: Vec<String>,
    /// Statistics seed.
    pub seed: String,
}

/// Canonical combined configuration document.
#[derive(Clone, Debug)]
pub struct CombinedConfig {
    value: Value,
}

impl CombinedConfig {
    /// Canonical JSON: compact separators, sorted keys, no trailing newline.
    #[must_use]
    pub fn canonical_json(&self) -> String {
        serde_json::to_string(&self.value).expect("canonical JSON of a value cannot fail")
    }

    /// Lowercase SHA-256 of the canonical JSON bytes.
    #[must_use]
    pub fn sha256(&self) -> String {
        sha256_hex(self.canonical_json().as_bytes())
    }
}

/// Merge the engine snapshot with the harness-owned evaluation settings.
pub fn combined_config(
    snapshot_json: &str,
    config: &RunConfig,
    settings: &EvaluationSettings,
) -> Result<CombinedConfig> {
    let engine: Value = serde_json::from_str(snapshot_json)
        .map_err(|error| Failure::dataset(format!("invalid config snapshot: {error}")))?;
    let split = serde_json::to_value(settings.split)
        .map_err(|error| Failure::dataset(format!("cannot serialize split: {error}")))?;
    let configuration = serde_json::to_value(settings.configuration)
        .map_err(|error| Failure::dataset(format!("cannot serialize configuration: {error}")))?;
    let value = json!({
        "schema_version": 1,
        "engine": engine,
        "run": {
            "name": config.name,
            "backend": config.backend,
            "semantic": config.semantic,
        },
        "evaluation": {
            "split": split,
            "configuration": configuration,
            "limit": settings.limit,
            "metrics": settings.metrics,
            "seed": settings.seed,
        },
    });
    Ok(CombinedConfig { value })
}

/// One model entry extracted from the engine snapshot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SnapshotModel {
    /// Public model identifier.
    pub id: String,
    /// Task.
    pub task: String,
    /// Deployed variant.
    pub variant: String,
    /// Content hash.
    pub sha256: String,
    /// Provider.
    pub provider: String,
}

/// Extract `models` from a canonical engine snapshot.
pub fn snapshot_models(snapshot_json: &str) -> Vec<SnapshotModel> {
    let Ok(value) = serde_json::from_str::<Value>(snapshot_json) else {
        return Vec::new();
    };
    value
        .get("models")
        .and_then(Value::as_array)
        .map(|models| {
            models
                .iter()
                .filter_map(|model| {
                    Some(SnapshotModel {
                        id: model.get("id")?.as_str()?.to_string(),
                        task: model.get("task")?.as_str()?.to_string(),
                        variant: model.get("variant")?.as_str()?.to_string(),
                        sha256: model.get("sha256")?.as_str()?.to_string(),
                        provider: model.get("provider")?.as_str()?.to_string(),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Capture the environment of section 4.9. Missing optional facts are null.
pub fn capture(tier: &str, cpus: Option<&str>, memory_limit: Option<u64>) -> Value {
    let logical_cores = std::thread::available_parallelism()
        .ok()
        .map(std::num::NonZeroUsize::get);
    let emulation = if tier == "T1-emulated" {
        json!({
            "logical_cpus": cpus.map(parse_cpus).unwrap_or_default(),
            "memory_limit_bytes": memory_limit,
        })
    } else {
        Value::Null
    };
    json!({
        "schema_version": 1,
        "captured_at": rfc3339_now(),
        "os": {
            "family": std::env::consts::OS,
            "version": null,
            "build": null,
            "arch": std::env::consts::ARCH,
        },
        "cpu": {
            "vendor": null,
            "model": null,
            "physical_cores": null,
            "logical_cores": logical_cores,
            "features": cpu_features(),
        },
        "memory_bytes": null,
        "power": null,
        "tier": tier,
        "emulation": emulation,
        "runtime": {
            "rustc": null,
            "seeky_version": env!("CARGO_PKG_VERSION"),
            "ort_version": null,
        },
        "devices": {"npu": null, "gpu": null},
        "quiet_window": {"verified": false, "heavy_processes": []},
        "process": {"scope": "engine_headless", "sampling_interval_ms": 50},
    })
}

fn parse_cpus(list: &str) -> Vec<u32> {
    let mut cpus: Vec<u32> = list
        .split(',')
        .filter_map(|value| value.trim().parse().ok())
        .collect();
    cpus.sort_unstable();
    cpus.dedup();
    cpus
}

/// Detected CPU feature names (`avx2`, `avx512f`, `vnni`) for the tier check.
#[must_use]
pub fn cpu_feature_names() -> Vec<String> {
    cpu_features()
        .as_array()
        .map(|values| {
            values
                .iter()
                .filter_map(|value| value.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(any(target_arch = "x86_64", target_arch = "x86"))]
fn cpu_features() -> Value {
    let mut features = Vec::new();
    if std::is_x86_feature_detected!("avx2") {
        features.push("avx2");
    }
    if std::is_x86_feature_detected!("avx512f") {
        features.push("avx512f");
    }
    if std::is_x86_feature_detected!("avx512vnni") {
        features.push("vnni");
    }
    json!(features)
}

#[cfg(not(any(target_arch = "x86_64", target_arch = "x86")))]
fn cpu_features() -> Value {
    Value::Null
}

/// Lowercase SHA-256 of arbitrary bytes.
#[must_use]
pub fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    format!("{digest:x}")
}

/// RFC 3339 UTC timestamp for the current wall clock.
#[must_use]
pub fn rfc3339_now() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs() as i64)
        .unwrap_or(0);
    let (year, month, day, hour, minute, second) = civil_from_seconds(seconds);
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

fn civil_from_seconds(seconds: i64) -> (i64, u32, u32, u32, u32, u32) {
    let days = seconds.div_euclid(86_400);
    let remainder = seconds.rem_euclid(86_400);
    let hour = (remainder / 3_600) as u32;
    let minute = ((remainder % 3_600) / 60) as u32;
    let second = (remainder % 60) as u32;
    let (year, month, day) = civil_from_days(days);
    (year, month, day, hour, minute, second)
}

/// Howard Hinnant's `civil_from_days`, with day 0 = 1970-01-01.
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let month = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if month <= 2 { year + 1 } else { year }, month, day)
}

/// Parse an RFC 3339 timestamp into UTC nanoseconds.
pub fn parse_rfc3339_ns(text: &str) -> Option<i64> {
    let bytes = text.as_bytes();
    if bytes.len() < 20 {
        return None;
    }
    let year: i64 = text.get(0..4)?.parse().ok()?;
    let month: u32 = text.get(5..7)?.parse().ok()?;
    let day: u32 = text.get(8..10)?.parse().ok()?;
    let hour: u32 = text.get(11..13)?.parse().ok()?;
    let minute: u32 = text.get(14..16)?.parse().ok()?;
    let second: u32 = text.get(17..19)?.parse().ok()?;
    if !(1..=12).contains(&month)
        || !(1..=31).contains(&day)
        || hour > 23
        || minute > 59
        || second > 59
    {
        return None;
    }
    let mut index = 19;
    let mut nanos: u64 = 0;
    if bytes.get(index) == Some(&b'.') {
        index += 1;
        let start = index;
        while index < bytes.len() && bytes[index].is_ascii_digit() {
            index += 1;
        }
        let digits = text.get(start..index)?;
        if digits.is_empty() || digits.len() > 9 {
            return None;
        }
        let mut value: u64 = digits.parse().ok()?;
        for _ in digits.len()..9 {
            value *= 10;
        }
        nanos = value;
    }
    let offset_seconds: i64 = match bytes.get(index)? {
        b'Z' | b'z' => {
            index += 1;
            0
        }
        b'+' | b'-' => {
            let sign = if bytes[index] == b'+' { 1 } else { -1 };
            index += 1;
            let offset_hour: i64 = text.get(index..index + 2)?.parse().ok()?;
            index += 2;
            if bytes.get(index) != Some(&b':') {
                return None;
            }
            index += 1;
            let offset_minute: i64 = text.get(index..index + 2)?.parse().ok()?;
            index += 2;
            if offset_hour > 23 || offset_minute > 59 {
                return None;
            }
            sign * (offset_hour * 3_600 + offset_minute * 60)
        }
        _ => return None,
    };
    if index != bytes.len() {
        return None;
    }
    let days = days_from_civil(year, month, day);
    let seconds =
        days * 86_400 + i64::from(hour) * 3_600 + i64::from(minute) * 60 + i64::from(second)
            - offset_seconds;
    let nanos = i128::from(seconds) * 1_000_000_000 + i128::from(nanos);
    i64::try_from(nanos).ok()
}

fn days_from_civil(year: i64, month: u32, day: u32) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = if year >= 0 { year } else { year - 399 } / 400;
    let yoe = year - era * 400;
    let month = i64::from(month);
    let day = i64::from(day);
    let doy = (153 * (if month > 2 { month - 3 } else { month + 9 }) + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rfc3339_round_trips_known_instants() {
        assert_eq!(parse_rfc3339_ns("1970-01-01T00:00:00Z"), Some(0));
        assert_eq!(
            parse_rfc3339_ns("1970-01-02T00:00:00Z"),
            Some(86_400 * 1_000_000_000)
        );
        assert_eq!(
            parse_rfc3339_ns("2026-11-27T12:00:00.5Z"),
            Some(1_795_780_800_500_000_000)
        );
        assert!(parse_rfc3339_ns("2026-11-27T12:00:00+01:00").is_some());
        for malformed in [
            "",
            "not-a-date",
            "2026-13-01T00:00:00Z",
            "2026-11-27T25:00:00Z",
            "2026-11-27T12:00:00",
            "2026-11-27T12:00:00Z trailing",
        ] {
            assert!(parse_rfc3339_ns(malformed).is_none(), "{malformed}");
        }
        assert_eq!(rfc3339_now().len(), 20);
    }

    #[test]
    fn combined_config_hash_is_path_independent_and_semantic() {
        let snapshot =
            r#"{"execution":{"provider":"cpu"},"models":[],"schema_version":1,"search":{}}"#;
        let settings = EvaluationSettings {
            split: Split::Dev,
            configuration: EvaluationConfiguration::Default,
            limit: 100,
            metrics: vec!["ndcg_10".into()],
            seed: DEFAULT_SEED.into(),
        };
        let first = combined_config(
            snapshot,
            &RunConfig {
                name: "default".into(),
                backend: "auto".into(),
                semantic: false,
            },
            &settings,
        )
        .expect("config");
        let second = combined_config(
            snapshot,
            &RunConfig {
                name: "default".into(),
                backend: "auto".into(),
                semantic: false,
            },
            &settings,
        )
        .expect("config");
        assert_eq!(first.sha256(), second.sha256());
        let changed = combined_config(
            snapshot,
            &RunConfig {
                name: "default".into(),
                backend: "auto".into(),
                semantic: true,
            },
            &settings,
        )
        .expect("config");
        assert_ne!(first.sha256(), changed.sha256());
        assert!(!first.canonical_json().contains(": "));
        assert!(!first.canonical_json().contains('\n'));
    }

    use crate::DEFAULT_SEED;
}
