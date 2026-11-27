//! Seeky extraction: format extraction, normalization, language
//! identification, chunking, and the OCR adapter.
//!
//! Responsibilities and allowed dependencies:
//! `docs/specs/SPEC-0001-workspace-and-crate-boundaries.md` (sections 4.2 and 4.4).

use std::fmt::Display;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Message(String),
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
}

impl Error {
    pub(crate) fn message(message: String) -> Self {
        Self::Message(message)
    }
}

pub type Result<T> = std::result::Result<T, Error>;

pub(crate) trait Context<T> {
    fn context<C: Display>(self, context: C) -> Result<T>;
    fn with_context<C: Display, F: FnOnce() -> C>(self, context: F) -> Result<T>;
}

impl<T, E: Display> Context<T> for std::result::Result<T, E> {
    fn context<C: Display>(self, context: C) -> Result<T> {
        self.map_err(|error| Error::message(format!("{context}: {error}")))
    }

    fn with_context<C: Display, F: FnOnce() -> C>(self, context: F) -> Result<T> {
        self.map_err(|error| Error::message(format!("{}: {error}", context())))
    }
}

macro_rules! error {
    ($($argument:tt)*) => {
        $crate::Error::message(format!($($argument)*))
    };
}

mod chunk;
mod extract;

pub use chunk::chunk_text;
pub use extract::{extract, supported_ext};
