//! Seeky search: query parsing, candidate generation, fusion, ranking, and
//! snippets.
//!
//! Responsibilities and allowed dependencies:
//! `docs/specs/SPEC-0001-workspace-and-crate-boundaries.md` (sections 4.2 and 4.4).

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("storage error: {0}")]
    Storage(#[from] seeky_store::Error),
}

impl Error {
    pub fn into_storage(self) -> seeky_store::Error {
        match self {
            Self::Storage(error) => error,
        }
    }
}

pub type Result<T> = std::result::Result<T, Error>;

mod search;
pub use search::search;
pub use seeky_core::SearchHit;
