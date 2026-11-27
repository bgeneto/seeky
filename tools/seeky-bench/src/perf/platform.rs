//! Process and host facts for `perf` (SPEC-0003 R27, R28).
//!
//! Windows facts come from three Win32 calls in this one audited module
//! (SPEC-0001 section 5.3); Linux facts come from `/proc`. Any other platform,
//! or any failed call, yields `None`; nothing is ever estimated.

/// Current process resident set size (Windows working set), in bytes.
#[must_use]
pub fn current_rss_bytes() -> Option<u64> {
    imp::current_rss_bytes()
}

/// Installed physical memory, in bytes.
#[must_use]
pub fn total_memory_bytes() -> Option<u64> {
    imp::total_memory_bytes()
}

/// Logical CPUs this process may run on, sorted ascending.
#[must_use]
pub fn process_affinity() -> Option<Vec<u32>> {
    imp::process_affinity()
}

#[cfg(windows)]
mod imp {
    use windows_sys::Win32::System::ProcessStatus::{
        K32GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS,
    };
    use windows_sys::Win32::System::SystemInformation::{GlobalMemoryStatusEx, MEMORYSTATUSEX};
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, GetProcessAffinityMask};

    #[allow(unsafe_code)]
    pub(super) fn current_rss_bytes() -> Option<u64> {
        let size = u32::try_from(std::mem::size_of::<PROCESS_MEMORY_COUNTERS>()).ok()?;
        // SAFETY: `PROCESS_MEMORY_COUNTERS` is a plain C struct for which all-zero
        // bytes are valid. `GetCurrentProcess` returns a pseudo-handle that needs
        // no closing and is always valid for the calling process. The pointer
        // refers to a live, writable local whose size is passed as `cb`, so the
        // call writes only within it, and it is read only after success.
        unsafe {
            let mut counters: PROCESS_MEMORY_COUNTERS = std::mem::zeroed();
            counters.cb = size;
            if K32GetProcessMemoryInfo(GetCurrentProcess(), &raw mut counters, size) == 0 {
                return None;
            }
            u64::try_from(counters.WorkingSetSize).ok()
        }
    }

    #[allow(unsafe_code)]
    pub(super) fn total_memory_bytes() -> Option<u64> {
        let size = u32::try_from(std::mem::size_of::<MEMORYSTATUSEX>()).ok()?;
        // SAFETY: `MEMORYSTATUSEX` is a plain C struct for which all-zero bytes are
        // valid; `dwLength` is set to its size as the API requires. The pointer
        // refers to a live, writable local, and it is read only after success.
        unsafe {
            let mut status: MEMORYSTATUSEX = std::mem::zeroed();
            status.dwLength = size;
            if GlobalMemoryStatusEx(&raw mut status) == 0 {
                return None;
            }
            Some(status.ullTotalPhys)
        }
    }

    #[allow(unsafe_code)]
    pub(super) fn process_affinity() -> Option<Vec<u32>> {
        let mut process_mask: usize = 0;
        let mut system_mask: usize = 0;
        // SAFETY: `GetCurrentProcess` returns an always-valid pseudo-handle; both
        // out-pointers refer to live, writable locals that are read only after
        // the call reports success.
        let ok = unsafe {
            GetProcessAffinityMask(
                GetCurrentProcess(),
                &raw mut process_mask,
                &raw mut system_mask,
            )
        };
        if ok == 0 || process_mask == 0 {
            return None;
        }
        Some(
            (0..usize::BITS)
                .filter(|bit| process_mask & (1usize << bit) != 0)
                .collect(),
        )
    }
}

#[cfg(target_os = "linux")]
mod imp {
    pub(super) fn current_rss_bytes() -> Option<u64> {
        let status = std::fs::read_to_string("/proc/self/status").ok()?;
        super::kib_field(&status, "VmRSS:")
    }

    pub(super) fn total_memory_bytes() -> Option<u64> {
        let meminfo = std::fs::read_to_string("/proc/meminfo").ok()?;
        super::kib_field(&meminfo, "MemTotal:")
    }

    pub(super) fn process_affinity() -> Option<Vec<u32>> {
        let status = std::fs::read_to_string("/proc/self/status").ok()?;
        let line = status
            .lines()
            .find_map(|line| line.strip_prefix("Cpus_allowed_list:"))?;
        super::parse_cpu_list(line.trim()).ok()
    }
}

#[cfg(not(any(windows, target_os = "linux")))]
mod imp {
    pub(super) fn current_rss_bytes() -> Option<u64> {
        None
    }

    pub(super) fn total_memory_bytes() -> Option<u64> {
        None
    }

    pub(super) fn process_affinity() -> Option<Vec<u32>> {
        None
    }
}

/// Parse a `/proc` field given in kB into bytes.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn kib_field(text: &str, name: &str) -> Option<u64> {
    let value = text.lines().find_map(|line| line.strip_prefix(name))?;
    let kib: u64 = value.trim().trim_end_matches("kB").trim().parse().ok()?;
    kib.checked_mul(1024)
}

/// Parse a CPU list such as `0,2,4-7`: sorted, unique, nonempty.
pub fn parse_cpu_list(list: &str) -> Result<Vec<u32>, String> {
    let mut cpus = Vec::new();
    for part in list.split(',') {
        let part = part.trim();
        if part.is_empty() {
            return Err("empty CPU entry".to_string());
        }
        if let Some((start, end)) = part.split_once('-') {
            let start: u32 = start
                .trim()
                .parse()
                .map_err(|_| format!("invalid CPU range start {start:?}"))?;
            let end: u32 = end
                .trim()
                .parse()
                .map_err(|_| format!("invalid CPU range end {end:?}"))?;
            if end < start || end - start > 4095 {
                return Err("invalid CPU range".to_string());
            }
            cpus.extend(start..=end);
        } else {
            cpus.push(
                part.parse()
                    .map_err(|_| format!("invalid CPU index {part:?}"))?,
            );
        }
    }
    let count = cpus.len();
    cpus.sort_unstable();
    cpus.dedup();
    if cpus.len() != count {
        return Err("duplicate CPU index".to_string());
    }
    Ok(cpus)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cpu_lists_parse_ranges_and_reject_malformed_entries() {
        // SPEC-0003-R28
        assert_eq!(parse_cpu_list("0,2,4-6"), Ok(vec![0, 2, 4, 5, 6]));
        for malformed in ["", "a", "1,,2", "3-1", "1,1", "0-", "-1", "1.5"] {
            assert!(parse_cpu_list(malformed).is_err(), "{malformed}");
        }
    }

    #[test]
    fn proc_fields_parse_kib_values() {
        // SPEC-0003-R27
        let status = "Name:\tseeky\nVmRSS:\t  2048 kB\n";
        assert_eq!(kib_field(status, "VmRSS:"), Some(2_097_152));
        assert_eq!(kib_field(status, "VmHWM:"), None);
        assert_eq!(kib_field("VmRSS: lots kB", "VmRSS:"), None);
    }

    #[test]
    fn host_facts_are_real_or_absent() {
        // SPEC-0003-R27: never a fabricated zero.
        if let Some(rss) = current_rss_bytes() {
            assert!(rss > 0);
        }
        if let Some(total) = total_memory_bytes() {
            assert!(total > 0);
        }
        if let Some(cpus) = process_affinity() {
            assert!(!cpus.is_empty());
        }
    }
}
