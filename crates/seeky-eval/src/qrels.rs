//! Graded document and passage judgment records (SPEC-0003 R4).

use serde::Deserialize;

use crate::error::{EvalError, Result};

/// Provenance shared by SDC queries and judgments.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Provenance {
    pub(crate) drafted_by: String,
    #[serde(default)]
    pub(crate) llm_prompt_sha256: Option<String>,
    #[serde(default)]
    pub(crate) tool_config_sha256: Option<String>,
    #[serde(default)]
    pub(crate) verified_by: Vec<String>,
    pub(crate) state: String,
    #[serde(default)]
    pub(crate) adjudicated_by: Option<String>,
}

impl Provenance {
    pub(crate) fn validate_gate_eligible(&self, location: &str) -> Result<()> {
        if self.drafted_by.trim().is_empty() {
            return Err(EvalError::data(
                "PROVENANCE_INCOMPLETE",
                location,
                "drafted_by is empty",
            ));
        }
        if self.drafted_by.starts_with("llm:") && self.llm_prompt_sha256.is_none() {
            return Err(EvalError::data(
                "PROVENANCE_INCOMPLETE",
                location,
                "LLM draft lacks llm_prompt_sha256",
            ));
        }
        if self.drafted_by.starts_with("tool:") && self.tool_config_sha256.is_none() {
            return Err(EvalError::data(
                "PROVENANCE_INCOMPLETE",
                location,
                "tool draft lacks tool_config_sha256",
            ));
        }
        match self.state.as_str() {
            "verified" | "adjudicated" => {}
            "draft" | "rejected" => {
                return Err(EvalError::data(
                    "FROZEN_REQUIRED",
                    location,
                    "draft or rejected record is not benchmark-eligible",
                ));
            }
            other => {
                return Err(EvalError::data(
                    "SCHEMA",
                    location,
                    format!("unknown provenance state: {other}"),
                ));
            }
        }
        if self.verified_by.is_empty() {
            return Err(EvalError::data(
                "PROVENANCE_INCOMPLETE",
                location,
                "verified_by is empty",
            ));
        }
        let mut unique = std::collections::BTreeSet::new();
        for reviewer in &self.verified_by {
            if !reviewer.starts_with("human:") || reviewer.len() <= "human:".len() {
                return Err(EvalError::data(
                    "PROVENANCE_INCOMPLETE",
                    location,
                    "verified_by entries must be pseudonymous human IDs",
                ));
            }
            if !unique.insert(reviewer.as_str()) {
                return Err(EvalError::data(
                    "PROVENANCE_INCOMPLETE",
                    location,
                    "verified_by contains duplicate reviewer IDs",
                ));
            }
        }
        if self.state == "adjudicated" {
            if unique.len() < 2 {
                return Err(EvalError::data(
                    "PROVENANCE_INCOMPLETE",
                    location,
                    "adjudication requires at least two distinct humans",
                ));
            }
            let adjudicator = self.adjudicated_by.as_deref().ok_or_else(|| {
                EvalError::data(
                    "PROVENANCE_INCOMPLETE",
                    location,
                    "adjudicated_by is required",
                )
            })?;
            if !unique.iter().any(|existing| *existing == adjudicator) {
                return Err(EvalError::data(
                    "PROVENANCE_INCOMPLETE",
                    location,
                    "adjudicated_by must be one of verified_by",
                ));
            }
        } else if self.adjudicated_by.is_some() {
            return Err(EvalError::data(
                "PROVENANCE_INCOMPLETE",
                location,
                "adjudicated_by is only valid for adjudicated records",
            ));
        }
        Ok(())
    }
}

/// A graded document qrel row from `qrels.<split>.documents.jsonl`.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct DocumentQrel {
    pub(crate) judgment_set_id: String,
    pub(crate) query_id: String,
    pub(crate) document_id: String,
    pub(crate) document_text_sha256: String,
    pub(crate) grade: u8,
    #[serde(default)]
    pub(crate) evidence_passage_ids: Vec<String>,
    #[serde(default)]
    pub(crate) subtopic_labels: Vec<String>,
    pub(crate) provenance: Provenance,
}

/// A graded passage qrel row from `qrels.<split>.passages.jsonl`.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PassageQrel {
    pub(crate) judgment_set_id: String,
    pub(crate) query_id: String,
    pub(crate) document_id: String,
    pub(crate) passage_id: String,
    pub(crate) passage_text_sha256: String,
    pub(crate) grade: u8,
    #[serde(default)]
    pub(crate) evidence_spans: Vec<EvidenceSpan>,
    pub(crate) provenance: Provenance,
}

/// A UTF-8 half-open evidence span inside a canonical passage.
#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct EvidenceSpan {
    pub(crate) start_utf8: u64,
    pub(crate) end_utf8: u64,
}

pub(crate) fn validate_grade(grade: u8, location: &str) -> Result<()> {
    if grade <= 3 {
        Ok(())
    } else {
        Err(EvalError::data(
            "SCHEMA",
            location,
            "grade must be an integer in 0..=3",
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::Provenance;

    fn parse(value: &serde_json::Value) -> Provenance {
        match serde_json::from_value(value.clone()) {
            Ok(provenance) => provenance,
            Err(error) => panic!("provenance should parse: {error}"),
        }
    }

    fn error_code(provenance: &Provenance) -> Option<String> {
        provenance
            .validate_gate_eligible("probe")
            .err()
            .map(|error| error.to_string())
    }

    // SPEC-0004-R20: a verified tool draft carries its config hash and loads.
    #[test]
    fn verified_tool_draft_with_config_hash_is_gate_eligible() {
        let provenance = parse(&serde_json::json!({
            "drafted_by": "tool:qrels-drafter@0.1.0",
            "tool_config_sha256": "a".repeat(64),
            "verified_by": ["human:reviewer-a"],
            "state": "verified",
            "adjudicated_by": null
        }));
        assert_eq!(error_code(&provenance), None);
    }
}
