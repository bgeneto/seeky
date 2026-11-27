//! Atomic artifact directories and checksums (SPEC-0003 section 4.9).
//!
//! Every file is written into a temporary sibling directory; `commit` writes
//! `checksums.sha256` last and only then replaces the output directory, so a
//! failed command leaves a previous artifact directory unchanged.

use crate::{Failure, Result};
use seeky_eval::Report;
use serde::Serialize;
use std::path::{Path, PathBuf};

/// Builder for one atomic artifact directory.
pub struct ArtifactDir {
    output: PathBuf,
    temporary: PathBuf,
    committed: bool,
}

impl ArtifactDir {
    /// Create a temporary sibling of `output`.
    pub fn new(output: &Path) -> Result<Self> {
        let name = output
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("artifacts");
        let parent = output.parent().unwrap_or_else(|| Path::new("."));
        let temporary = parent.join(format!(".{name}.tmp-{}", std::process::id()));
        if temporary.exists() {
            std::fs::remove_dir_all(&temporary).map_err(|error| {
                Failure::report(format!("cannot clear a stale artifact directory: {error}"))
            })?;
        }
        std::fs::create_dir_all(&temporary).map_err(|error| {
            Failure::report(format!("cannot create the artifact directory: {error}"))
        })?;
        Ok(Self {
            output: output.to_path_buf(),
            temporary,
            committed: false,
        })
    }

    /// Path of an artifact inside the temporary directory.
    pub fn path(&self, name: &str) -> PathBuf {
        self.temporary.join(name)
    }

    /// Write a pretty-printed JSON artifact (matching `seeky-eval`).
    pub fn write_json<T: Serialize>(&self, name: &str, value: &T) -> Result<()> {
        let mut text = serde_json::to_string_pretty(value)
            .map_err(|error| Failure::report(format!("cannot serialize {name}: {error}")))?;
        text.push('\n');
        self.write_text(name, &text)
    }

    /// Write a raw text artifact.
    pub fn write_text(&self, name: &str, text: &str) -> Result<()> {
        std::fs::write(self.path(name), text)
            .map_err(|error| Failure::report(format!("cannot write {name}: {error}")))
    }

    /// Write a validated report through `seeky-eval`'s writer.
    pub fn write_report(&self, name: &str, report: &Report) -> Result<()> {
        seeky_eval::write_report_json(report, &self.path(name))
            .map_err(|error| Failure::report(error.to_string()))
    }

    /// Write a Treck run through `seeky-eval`'s writer.
    pub fn write_run(&self, name: &str, run: &seeky_eval::Run) -> Result<()> {
        seeky_eval::write_trec_run(run, &self.path(name))
            .map_err(|error| Failure::report(error.to_string()))
    }

    /// Write the checksum manifest and replace the output directory.
    pub fn commit(mut self) -> Result<()> {
        let checksums = self.checksums()?;
        std::fs::write(self.temporary.join("checksums.sha256"), checksums)
            .map_err(|error| Failure::report(format!("cannot write checksums: {error}")))?;
        if self.output.exists() {
            std::fs::remove_dir_all(&self.output).map_err(|error| {
                Failure::report(format!("cannot replace the artifact directory: {error}"))
            })?;
        }
        std::fs::rename(&self.temporary, &self.output).map_err(|error| {
            Failure::report(format!("cannot publish the artifact directory: {error}"))
        })?;
        self.committed = true;
        Ok(())
    }

    fn checksums(&self) -> Result<String> {
        let mut entries: Vec<PathBuf> = std::fs::read_dir(&self.temporary)
            .map_err(|error| Failure::report(format!("cannot list artifacts: {error}")))?
            .filter_map(|entry| entry.ok().map(|entry| entry.path()))
            .filter(|path| path.is_file())
            .collect();
        entries.sort();
        let mut text = String::new();
        for path in entries {
            let name = path
                .file_name()
                .and_then(|name| name.to_str())
                .ok_or_else(|| Failure::report("artifact name is not UTF-8"))?;
            if name == "checksums.sha256" {
                continue;
            }
            let bytes = std::fs::read(&path)
                .map_err(|error| Failure::report(format!("cannot read {name}: {error}")))?;
            text.push_str(&crate::environment::sha256_hex(&bytes));
            text.push_str("  ");
            text.push_str(name);
            text.push('\n');
        }
        Ok(text)
    }
}

impl Drop for ArtifactDir {
    fn drop(&mut self) {
        if !self.committed {
            let _ = std::fs::remove_dir_all(&self.temporary);
        }
    }
}
