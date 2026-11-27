//! Typed evaluation errors (SPEC-0003 R1/R14).

use std::path::Path;

/// Result alias used by every public evaluation API.
pub type Result<T> = std::result::Result<T, EvalError>;

/// A stable, typed failure from loading, validating, evaluating, or writing.
#[derive(Debug, thiserror::Error)]
pub enum EvalError {
    /// A required file could not be read or written.
    #[error("IO at {location}: {source}")]
    Io {
        /// Repository-relative or file-name-only location.
        location: String,
        /// Underlying I/O failure.
        #[source]
        source: std::io::Error,
    },

    /// A structural, semantic, or consistency failure with a stable code.
    #[error("{code} at {location}: {message}")]
    Data {
        /// Stable machine-readable code (for example `SCHEMA`).
        code: &'static str,
        /// Location such as `manifest.json:12` or a logical field name.
        location: String,
        /// Human-readable detail; never contains user document content.
        message: String,
    },
}

impl EvalError {
    pub(crate) fn io(path: &Path, source: std::io::Error) -> Self {
        Self::Io {
            location: display_path(path),
            source,
        }
    }

    pub(crate) fn data(
        code: &'static str,
        location: impl Into<String>,
        message: impl Into<String>,
    ) -> Self {
        Self::Data {
            code,
            location: location.into(),
            message: message.into(),
        }
    }

    /// Stable error code exposed to callers and diagnostics.
    #[must_use]
    pub fn code(&self) -> &'static str {
        match self {
            Self::Io { .. } => "IO",
            Self::Data { code, .. } => code,
        }
    }

    /// Location attached to the failure.
    #[must_use]
    pub fn location(&self) -> &str {
        match self {
            Self::Io { location, .. } | Self::Data { location, .. } => location,
        }
    }
}

/// Return a path suitable for diagnostics: file name only, never a full user
/// path. Callers may prefix logical artifacts if they need more context.
pub(crate) fn display_path(path: &Path) -> String {
    path.file_name()
        .and_then(std::ffi::OsStr::to_str)
        .map_or_else(|| "<path>".to_owned(), ToOwned::to_owned)
}
