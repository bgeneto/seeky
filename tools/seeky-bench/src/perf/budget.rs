//! Tier declaration, quiet-window check, and budget eligibility
//! (SPEC-0003 R25, R28; methodology section 4).

use crate::{Failure, Result};
use std::collections::BTreeSet;

/// Minimum query executions per stage for a budget-eligible value.
pub const MIN_QUERY_SAMPLES: u64 = 1_000;
/// Minimum fixed-set repetitions for a budget-eligible value.
pub const MIN_REPETITIONS: u64 = 30;

/// SPEC-0003 R25 sample criterion: at least 1,000 query executions per stage
/// or at least 30 repetitions of the fixed set.
#[must_use]
pub fn sample_criteria_met(queries: u64, repetitions: u64) -> bool {
    queries >= MIN_QUERY_SAMPLES || repetitions >= MIN_REPETITIONS
}

/// Hardware tier (methodology section 4).
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Tier {
    /// Floor: 4 cores / 8 threads, AVX2, no AVX-512, 8 GB.
    T0,
    /// Reference laptop: 8-12 cores, 16 GB; budgets are verified here.
    T1,
    /// T1 emulated on a larger machine by CPU pinning and a memory cap.
    T1Emulated,
    /// Development workstation; never claims a budget.
    T2,
}

impl Tier {
    /// Parse the `--tier` value.
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "T0" => Ok(Self::T0),
            "T1" => Ok(Self::T1),
            "T1-emulated" => Ok(Self::T1Emulated),
            "T2" => Ok(Self::T2),
            _ => Err(Failure::usage("--tier must be T0, T1, T1-emulated, or T2")),
        }
    }

    /// Wire name.
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::T0 => "T0",
            Self::T1 => "T1",
            Self::T1Emulated => "T1-emulated",
            Self::T2 => "T2",
        }
    }

    /// Budgets are defined and verified on T1 (physical or emulated) only.
    #[must_use]
    pub fn verifies_budgets(self) -> bool {
        matches!(self, Self::T1 | Self::T1Emulated)
    }
}

/// The tier the user declared on the command line.
#[derive(Clone, Debug)]
pub struct TierDeclaration {
    /// Tier.
    pub tier: Tier,
    /// `--cpus`, sorted and unique.
    pub cpus: Option<Vec<u32>>,
    /// `--memory-limit` in bytes.
    pub memory_limit_bytes: Option<u64>,
}

/// Captured host facts the declaration is checked against; `None` = unknown.
#[derive(Clone, Debug, Default)]
pub struct HostFacts {
    /// Logical CPUs visible to the OS.
    pub logical_cores: Option<usize>,
    /// Installed memory.
    pub memory_bytes: Option<u64>,
    /// Detected CPU features (`avx2`, `avx512f`, `vnni`).
    pub cpu_features: Vec<String>,
    /// CPUs the process is pinned to.
    pub process_affinity: Option<Vec<u32>>,
}

fn conflict(message: impl std::fmt::Display) -> Failure {
    Failure::usage(format!("TIER_CONFLICT: {message}"))
}

/// Reject a declaration that conflicts with the captured environment.
///
/// T1-emulated must name the pinned CPUs and the memory cap, every CPU must
/// exist, the process must actually be pinned to exactly those CPUs, and the
/// cap cannot exceed installed memory. `--cpus`/`--memory-limit` are valid only
/// for T1-emulated. A T0 claim needs AVX2, no AVX-512, and at most 8 logical
/// CPUs; a T1 claim needs at least 8 logical CPUs.
pub fn validate_tier(declaration: &TierDeclaration, host: &HostFacts) -> Result<()> {
    let has = |feature: &str| host.cpu_features.iter().any(|value| value == feature);
    match declaration.tier {
        Tier::T1Emulated => {
            let Some(cpus) = declaration.cpus.as_deref() else {
                return Err(Failure::usage(
                    "--tier T1-emulated requires --cpus and --memory-limit",
                ));
            };
            let Some(limit) = declaration.memory_limit_bytes else {
                return Err(Failure::usage(
                    "--tier T1-emulated requires --cpus and --memory-limit",
                ));
            };
            if let Some(logical) = host.logical_cores
                && let Some(cpu) = cpus.iter().find(|cpu| **cpu as usize >= logical)
            {
                return Err(conflict(format!(
                    "--cpus names CPU {cpu} but the host has {logical} logical CPUs"
                )));
            }
            if let Some(memory) = host.memory_bytes
                && limit > memory
            {
                return Err(conflict(format!(
                    "--memory-limit {limit} exceeds installed memory {memory}"
                )));
            }
            match host.process_affinity.as_deref() {
                Some(affinity) if affinity != cpus => {
                    return Err(conflict(
                        "the process is not pinned to the --cpus set; start it with that affinity",
                    ));
                }
                Some(_) => {}
                None => {
                    return Err(conflict(
                        "process CPU affinity cannot be verified on this platform",
                    ));
                }
            }
        }
        tier => {
            if declaration.cpus.is_some() || declaration.memory_limit_bytes.is_some() {
                return Err(conflict(format!(
                    "--cpus and --memory-limit are valid only with T1-emulated, not {}",
                    tier.as_str()
                )));
            }
            if tier == Tier::T0 {
                if !has("avx2") || has("avx512f") {
                    return Err(conflict("T0 requires AVX2 and no AVX-512"));
                }
                if host.logical_cores.is_some_and(|logical| logical > 8) {
                    return Err(conflict("T0 has at most 8 logical CPUs"));
                }
            }
            if tier == Tier::T1 && host.logical_cores.is_some_and(|logical| logical < 8) {
                return Err(conflict("T1 has at least 8 logical CPUs"));
            }
        }
    }
    Ok(())
}

/// Lists running process image names (no command lines, no IDs).
pub trait ProcessLister {
    /// Image names, or `None` when the platform cannot list processes.
    fn process_names(&self) -> Option<Vec<String>>;
}

/// The recorded quiet-window result (environment `quiet_window`).
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuietWindow {
    /// True only when processes were listed and none is heavy.
    pub verified: bool,
    /// Heavy process classes only: `cargo`, `rustc`, `node`, `python`,
    /// `other-benchmark`.
    pub heavy_processes: Vec<String>,
}

/// Classify running processes into the SPEC-0003 section 4.9 heavy classes.
/// One `seeky-bench` process is this run; any other is `other-benchmark`.
#[must_use]
pub fn quiet_window(lister: &dyn ProcessLister) -> QuietWindow {
    let Some(names) = lister.process_names() else {
        return QuietWindow {
            verified: false,
            heavy_processes: Vec::new(),
        };
    };
    let mut classes = BTreeSet::new();
    let mut benches = 0_usize;
    for name in names {
        let lower = name.to_ascii_lowercase();
        let stem = lower.strip_suffix(".exe").unwrap_or(&lower);
        match stem {
            "cargo" => {
                classes.insert("cargo");
            }
            "rustc" => {
                classes.insert("rustc");
            }
            "node" => {
                classes.insert("node");
            }
            "seeky-bench" => benches += 1,
            _ if stem.starts_with("python") => {
                classes.insert("python");
            }
            _ => {}
        }
    }
    if benches > 1 {
        classes.insert("other-benchmark");
    }
    QuietWindow {
        verified: classes.is_empty(),
        heavy_processes: classes.into_iter().map(str::to_string).collect(),
    }
}

/// Production process lister: `tasklist` on Windows, `/proc` on Linux.
pub struct SystemProcesses;

impl ProcessLister for SystemProcesses {
    #[cfg(windows)]
    fn process_names(&self) -> Option<Vec<String>> {
        let output = std::process::Command::new("tasklist")
            .args(["/FO", "CSV", "/NH"])
            .output()
            .ok()?;
        if !output.status.success() {
            return None;
        }
        Some(
            String::from_utf8_lossy(&output.stdout)
                .lines()
                .filter_map(|line| {
                    line.strip_prefix('"')
                        .and_then(|rest| rest.split('"').next())
                        .map(str::to_string)
                })
                .collect(),
        )
    }

    #[cfg(target_os = "linux")]
    fn process_names(&self) -> Option<Vec<String>> {
        let entries = std::fs::read_dir("/proc").ok()?;
        Some(
            entries
                .filter_map(std::result::Result::ok)
                .filter(|entry| entry.file_name().to_string_lossy().parse::<u32>().is_ok())
                .filter_map(|entry| std::fs::read_to_string(entry.path().join("comm")).ok())
                .map(|name| name.trim().to_string())
                .collect(),
        )
    }

    #[cfg(not(any(windows, target_os = "linux")))]
    fn process_names(&self) -> Option<Vec<String>> {
        None
    }
}

/// Budget eligibility with one explicit reason per failed condition.
#[derive(Clone, Debug, Default)]
pub struct Eligibility {
    reasons: Vec<String>,
}

impl Eligibility {
    /// Start from the run-level conditions (tier, quiet window, synthetic).
    #[must_use]
    pub fn new(tier: Tier, quiet: &QuietWindow, synthetic: bool) -> Self {
        let mut eligibility = Self::default();
        if !tier.verifies_budgets() {
            eligibility.reject(format!(
                "not budget-eligible: tier {} never verifies a budget",
                tier.as_str()
            ));
        }
        if !quiet.verified {
            eligibility.reject("not budget-eligible: quiet window not verified (exploratory run)");
        }
        if synthetic {
            eligibility.reject("not budget-eligible: synthetic measurement");
        }
        eligibility
    }

    /// Record a latency set's sample criterion.
    pub fn check_samples(&mut self, label: &str, queries: u64, repetitions: u64) {
        if !sample_criteria_met(queries, repetitions) {
            self.reject(format!(
                "not budget-eligible: {label} undersampled ({queries} executions, {repetitions} repetitions; need {MIN_QUERY_SAMPLES} or {MIN_REPETITIONS})"
            ));
        }
    }

    /// Add an explicit reason.
    pub fn reject(&mut self, reason: impl Into<String>) {
        self.reasons.push(reason.into());
    }

    /// `qualifies_for_budget`.
    #[must_use]
    pub fn qualifies(&self) -> bool {
        self.reasons.is_empty()
    }

    /// Reasons, in the order recorded.
    #[must_use]
    pub fn reasons(&self) -> &[String] {
        &self.reasons
    }
}
