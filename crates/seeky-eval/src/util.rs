//! Internal deterministic parsing, hashing, and path helpers.

use std::fs;
use std::io::{BufRead, BufReader};
use std::path::{Component, Path, PathBuf};

use serde::de::DeserializeOwned;
use sha2::{Digest, Sha256};

use crate::error::{EvalError, Result, display_path};

/// Lowercase SHA-256 over raw bytes.
pub(crate) fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut out = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        // Writing to a String cannot fail; ignoring the error is safe and
        // avoids a panic path in library code.
        let _ = write!(out, "{byte:02x}");
    }
    out
}

/// SHA-256 of one file's exact bytes.
pub(crate) fn sha256_file(path: &Path) -> Result<String> {
    let bytes = fs::read(path).map_err(|error| EvalError::io(path, error))?;
    Ok(sha256_hex(&bytes))
}

/// Canonical JSON: UTF-8, sorted keys, compact separators, no trailing newline.
pub(crate) fn canonical_json<T: serde::Serialize + ?Sized>(value: &T) -> Result<String> {
    serde_json::to_string(value)
        .map_err(|error| EvalError::data("SCHEMA", "canonical-json", error.to_string()))
}

/// Read a UTF-8 file.
pub(crate) fn read_utf8(path: &Path) -> Result<String> {
    fs::read_to_string(path).map_err(|error| EvalError::io(path, error))
}

/// Parse one JSON file with a typed, location-bearing failure.
pub(crate) fn read_json<T: DeserializeOwned>(path: &Path) -> Result<T> {
    let bytes = fs::read(path).map_err(|error| EvalError::io(path, error))?;
    serde_json::from_slice(&bytes).map_err(|error| {
        EvalError::data(
            "SCHEMA",
            format!("{}:{}", display_path(path), error.line()),
            error.to_string(),
        )
    })
}

/// Parse compact JSONL, rejecting blank lines and trailing junk.
pub(crate) fn read_jsonl<T: DeserializeOwned>(path: &Path) -> Result<Vec<T>> {
    let file = fs::File::open(path).map_err(|error| EvalError::io(path, error))?;
    let reader = BufReader::new(file);
    let mut values = Vec::new();
    for (index, line) in reader.lines().enumerate() {
        let line_number = index + 1;
        let line = line.map_err(|error| EvalError::io(path, error))?;
        let line = line.strip_suffix('\r').unwrap_or(&line);
        if line.trim().is_empty() {
            return Err(EvalError::data(
                "JSONL",
                format!("{}:{line_number}", display_path(path)),
                "blank JSONL line",
            ));
        }
        let value = serde_json::from_str(line).map_err(|error| {
            EvalError::data(
                "JSONL",
                format!("{}:{line_number}", display_path(path)),
                error.to_string(),
            )
        })?;
        values.push(value);
    }
    Ok(values)
}

/// Convert a read-only JSON value into deterministic canonical JSON.
pub(crate) fn value_sha256(value: &serde_json::Value) -> Result<String> {
    Ok(sha256_hex(canonical_json(value)?.as_bytes()))
}

/// Validate and normalize a corpus-relative POSIX path.
pub(crate) fn normalize_relative_path(raw: &str) -> Result<String> {
    if raw.is_empty() || raw.starts_with('/') || raw.starts_with('\\') {
        return Err(EvalError::data(
            "SCHEMA",
            "relative_path",
            "path must be nonempty and relative",
        ));
    }
    let path = Path::new(raw);
    let mut parts = Vec::new();
    for component in path.components() {
        match component {
            Component::Normal(value) => {
                let value = value.to_str().ok_or_else(|| {
                    EvalError::data("SCHEMA", "relative_path", "path is not UTF-8")
                })?;
                parts.push(value);
            }
            Component::CurDir => {}
            Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                return Err(EvalError::data(
                    "SCHEMA",
                    "relative_path",
                    "path escapes its root",
                ));
            }
        }
    }
    if parts.is_empty() {
        return Err(EvalError::data(
            "SCHEMA",
            "relative_path",
            "path has no normal component",
        ));
    }
    Ok(parts.join("/"))
}

/// Join a verified relative path below a root.
pub(crate) fn join_relative(root: &Path, relative: &str) -> Result<PathBuf> {
    let relative = normalize_relative_path(relative)?;
    Ok(root.join(relative.replace('/', std::path::MAIN_SEPARATOR_STR)))
}

/// True when the file is a regular file.
pub(crate) fn is_regular_file(path: &Path) -> bool {
    path.metadata().is_ok_and(|metadata| metadata.is_file())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sha256_known_value() {
        assert_eq!(
            sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn relative_path_rejects_escape() {
        assert!(normalize_relative_path("../secret").is_err());
        assert!(normalize_relative_path("/absolute").is_err());
        assert_eq!(normalize_relative_path("a/./b").unwrap(), "a/b".to_owned());
    }
}
