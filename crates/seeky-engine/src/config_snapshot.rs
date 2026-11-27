//! Canonical, privacy-safe engine configuration snapshot (SPEC-0002 R24).
//!
//! Only engine-owned settings that can change ranking, filter behavior, or a
//! measured search latency are included. Paths, credentials, timestamps,
//! logging destinations, and host/user identity are excluded.

use crate::Result;
use seeky_core::Backend;
use seeky_infer::ActiveModel;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

/// Canonical semantic configuration plus its digest.
#[derive(Clone, Debug)]
pub struct EngineConfigSnapshot {
    value: Value,
}

impl EngineConfigSnapshot {
    /// Canonical JSON: sorted keys, compact separators, UTF-8, no trailing
    /// newline, shortest round-trippable numbers.
    #[must_use]
    pub fn canonical_json(&self) -> String {
        serde_json::to_string(&self.value).expect("canonical JSON of a value cannot fail")
    }

    /// Lowercase SHA-256 of `canonical_json()`'s UTF-8 bytes.
    #[must_use]
    pub fn sha256(&self) -> String {
        let digest = Sha256::digest(self.canonical_json().as_bytes());
        format!("{digest:x}")
    }

    pub(crate) fn build(
        backend: Backend,
        model: Option<&ActiveModel>,
        intra_op_threads: u32,
    ) -> Result<Self> {
        let provider = match backend {
            Backend::Auto | Backend::Cpu => "cpu",
            Backend::Cuda => "cuda",
            Backend::Npu => "npu",
        };
        let models = match model {
            Some(model) => json!([{
                "task": model.task,
                "id": model.id,
                "revision": model.revision,
                "variant": model.variant,
                "dimension": model.dimension,
                "sha256": model.sha256,
                "provider": model.provider,
                "preprocessing": model.preprocessing,
            }]),
            None => json!([]),
        };
        let value = json!({
            "schema_version": 1,
            "search": {
                "default_limit": 20,
                "interactive_max_hits": 50,
                "evaluation_max_hits": 1000,
                "candidate_depths": {"filename": 40, "lexical": 80, "dense": 80},
                "fusion": {
                    "kind": "rrf",
                    "k": 60.0,
                    "weights": {"filename": 1.0, "lexical": 1.0, "dense": 1.0},
                },
                "document": {"enabled": false, "passages_per_document": null},
                "rerank": {"enabled": false, "depth": null, "token_budget": null},
                "diversity": {"enabled": false, "lambda": null},
                "snippets": {"enabled": true},
                "query_cache": {"enabled": false, "capacity": null},
                "filters": {
                    "pushdown": ["extension", "modified", "folder", "size"],
                    "post_fallback": true,
                    "metadata_fields": ["extension", "modified", "folder", "size"],
                },
            },
            "models": models,
            "execution": {
                "provider": provider,
                "intra_op_threads": intra_op_threads,
                "inter_op_threads": 1,
                "query_batch": 1,
            },
        });
        Ok(Self { value })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshot_json_is_compact_and_sorted() {
        let snapshot = EngineConfigSnapshot::build(Backend::Cpu, None, 4).expect("snapshot");
        let json = snapshot.canonical_json();
        assert!(!json.contains('\n'));
        assert!(!json.contains(": "));
        assert!(json.starts_with("{\"execution\":"));
        assert!(json.contains("\"models\":[]"));
        assert_eq!(snapshot.sha256().len(), 64);
        assert!(snapshot.sha256().chars().all(|c| c.is_ascii_hexdigit()));
    }
}
