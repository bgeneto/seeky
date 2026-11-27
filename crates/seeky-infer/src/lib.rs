//! Seeky inference: ONNX Runtime sessions, execution-provider selection,
//! tokenizers, model discovery and registry, and embedder implementations.
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
    #[error("ONNX Runtime error: {0}")]
    Ort(#[from] ort::Error),
    #[error("OpenVINO error: {0}")]
    OpenVino(#[from] openvino::InferenceError),
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

mod inference;

pub use inference::{
    ActiveModel, DIM, Embedder, Engine, MODEL_ID, MODEL_PREPROCESSING, MODEL_REVISION,
    available_backends, describe_active_model, find_gety_model_root, gety_data_dir,
    gety_openvino_dir, gety_ort_dll, prepare_cuda_paths, prepare_openvino_path, resolve_npu_dir,
};
pub use seeky_core::{Backend, EngineInfo, ModelIdentity};
