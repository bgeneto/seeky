//! WP-1.8 CI smoke gate (SPEC-0003 R29-R31, section 5.6).
//!
//! `compare --gate wp1.8` loads three quality results (the baseline built at
//! the current `main` SHA, the candidate, and a second clean run of the same
//! candidate), their TREC document runs, and the committed `sdc-smoke-v1`
//! judgment set. [`evaluate`] then applies every rule in a fixed order and
//! returns one typed [`GateResult`]: the first failing rule wins, its
//! [`Reason`] code leads `details` and is repeated as `observed.reason`. A
//! missing query, metric, or artifact is a failure, never a skip.

use crate::corpus::BenchPaths;
use crate::environment::sha256_hex;
use seeky_eval::{
    EvaluationConfiguration, GateResult, GateStatus, QueryCategory, Report, ReportKind, Split,
};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

/// Gate row ID.
pub const GATE_ID: &str = "WP-1.8";
/// Human-readable threshold recorded in the gate row.
pub const THRESHOLD: &str = "candidate macro nDCG@10 drop <= 1.0 point vs main";
/// Maximum allowed drop in nDCG points (100 x nDCG).
pub const MAX_DROP_POINTS: f64 = 1.0;
/// Absorbs binary floating representation only (section 5.6 step 4).
pub const DROP_TOLERANCE: f64 = 1e-12;
/// Score and metric tolerance between the candidate and its repeat.
pub const REPEAT_TOLERANCE: f64 = 1e-9;
/// The only corpus the gate accepts.
pub const SMOKE_CORPUS: &str = "sdc-smoke";
/// The only judgment set the gate accepts.
pub const SMOKE_JUDGMENT_SET: &str = "sdc-smoke-v1";
/// Minimum default `dev` queries per non-code category.
pub const MIN_QUERIES_PER_CATEGORY: usize = 5;
/// The eight non-code categories the gate macro covers (ADR-0024).
pub const NON_CODE_CATEGORIES: [QueryCategory; 8] = [
    QueryCategory::KnownItem,
    QueryCategory::Conceptual,
    QueryCategory::ExactIdentifier,
    QueryCategory::CrossLanguage,
    QueryCategory::NeedleInHaystack,
    QueryCategory::Exploratory,
    QueryCategory::MixedSemanticMetadata,
    QueryCategory::FilenamePartial,
];

/// Why the gate passed or failed. Every outcome carries exactly one reason.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Reason {
    /// Pass: the drop is within the threshold.
    WithinThreshold,
    /// A required input (candidate, repeat, baseline SHA, run artifact) is missing.
    MissingInput,
    /// R30: the baseline is not the supplied current-`main` SHA.
    NotMainBaseline,
    /// R29: a run comes from a dirty tree, or the repeat is another commit.
    DirtyCommit,
    /// R29: not a `sdc-smoke-v1` `dev` quality report in the default configuration.
    WrongDataset,
    /// `bench/qrels/sdc/sdc-smoke-v1` is not published.
    SmokeSetUnpublished,
    /// R30: the judgment set is not frozen with `test_exposure` not applicable.
    NotFrozen,
    /// R30: a query or judgment is not verified or adjudicated.
    UnverifiedData,
    /// The published set fails full SDC validation or cannot be read.
    SmokeSetInvalid,
    /// R29: corpus, judgment set, config hash, or query membership differs.
    InputMismatch,
    /// R29: OS family, architecture, or hardware tier differs.
    EnvironmentMismatch,
    /// R30: a `code_search` query or source-code document is present.
    CodeResults,
    /// R29: fewer than five default `dev` queries in a non-code category.
    CategoryCoverage,
    /// R31: per-query results do not cover exactly the expected queries.
    QueryCoverage,
    /// A per-query nDCG@10 is missing or out of range.
    MissingMetric,
    /// R31: a run breaks a ranking invariant.
    RankingInvariant,
    /// R31: the repeat run differs from the candidate.
    NondeterministicRepeat,
    /// R29: the candidate drops more than 1.0 nDCG point.
    Regression,
}

impl Reason {
    /// Stable reason code.
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::WithinThreshold => "WITHIN_THRESHOLD",
            Self::MissingInput => "MISSING_INPUT",
            Self::NotMainBaseline => "NOT_MAIN_BASELINE",
            Self::DirtyCommit => "DIRTY_COMMIT",
            Self::WrongDataset => "WRONG_DATASET",
            Self::SmokeSetUnpublished => "SMOKE_SET_UNPUBLISHED",
            Self::NotFrozen => "NOT_FROZEN",
            Self::UnverifiedData => "UNVERIFIED_DATA",
            Self::SmokeSetInvalid => "SMOKE_SET_INVALID",
            Self::InputMismatch => "INPUT_MISMATCH",
            Self::EnvironmentMismatch => "ENVIRONMENT_MISMATCH",
            Self::CodeResults => "CODE_RESULTS",
            Self::CategoryCoverage => "CATEGORY_COVERAGE",
            Self::QueryCoverage => "QUERY_COVERAGE",
            Self::MissingMetric => "MISSING_METRIC",
            Self::RankingInvariant => "RANKING_INVARIANT",
            Self::NondeterministicRepeat => "NONDETERMINISTIC_REPEAT",
            Self::Regression => "REGRESSION",
        }
    }
}

/// Build the gate row for one reason.
#[must_use]
pub fn gate_result(reason: Reason, message: &str, observed: Value) -> GateResult {
    let mut object = match observed {
        Value::Object(object) => object,
        Value::Null => Map::new(),
        other => {
            let mut object = Map::new();
            object.insert("value".to_string(), other);
            object
        }
    };
    object.insert("reason".to_string(), json!(reason.code()));
    GateResult {
        id: GATE_ID.to_string(),
        status: if reason == Reason::WithinThreshold {
            GateStatus::Pass
        } else {
            GateStatus::Fail
        },
        threshold: THRESHOLD.to_string(),
        observed: Value::Object(object),
        details: format!("{}: {message}", reason.code()),
    }
}

/// The reason code recorded in a gate row, if any.
#[must_use]
pub fn reason_code(result: &GateResult) -> Option<&str> {
    result.observed.get("reason").and_then(Value::as_str)
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

/// One TREC document-run line, parsed without dataset validation so that a
/// broken run becomes a typed gate failure rather than a loader error.
#[derive(Clone, Debug, PartialEq)]
pub struct TrecRow {
    /// Query ID.
    pub query_id: String,
    /// Target (document) ID.
    pub target: String,
    /// One-based rank as written.
    pub rank: u32,
    /// Score as written (may be non-finite; the invariants reject it).
    pub score: f64,
}

/// Parse a TREC run (`qid Q0 target rank score run_id`).
pub fn parse_trec(text: &str) -> std::result::Result<Vec<TrecRow>, String> {
    let mut rows = Vec::new();
    for (index, line) in text.lines().enumerate() {
        let number = index + 1;
        let line = line.strip_suffix('\r').unwrap_or(line);
        let fields: Vec<&str> = line.split(' ').collect();
        if fields.len() != 6 || fields.iter().any(|field| field.is_empty()) || fields[1] != "Q0" {
            return Err(format!("run line {number} is not a six-column TREC row"));
        }
        let rank = fields[3]
            .parse::<u32>()
            .map_err(|_| format!("run line {number} has a non-integer rank"))?;
        let score = fields[4]
            .parse::<f64>()
            .map_err(|_| format!("run line {number} has a non-numeric score"))?;
        rows.push(TrecRow {
            query_id: fields[0].to_string(),
            target: fields[2].to_string(),
            rank,
            score,
        });
    }
    Ok(rows)
}

/// Rows grouped by query and ordered by rank (stable for duplicate ranks).
fn by_query(rows: &[TrecRow]) -> BTreeMap<&str, Vec<&TrecRow>> {
    let mut grouped: BTreeMap<&str, Vec<&TrecRow>> = BTreeMap::new();
    for row in rows {
        grouped.entry(row.query_id.as_str()).or_default().push(row);
    }
    for list in grouped.values_mut() {
        list.sort_by_key(|row| row.rank);
    }
    grouped
}

/// R31 ranking invariants for one run: every query is expected, ranks are
/// contiguous from 1, targets are unique, scores are finite and nonincreasing
/// by rank, and every target is a default (non-code) document.
pub fn check_ranking(
    rows: &[TrecRow],
    expected_queries: &BTreeSet<String>,
    default_documents: &BTreeSet<String>,
) -> std::result::Result<(), String> {
    for (query_id, list) in by_query(rows) {
        if !expected_queries.contains(query_id) {
            return Err(format!("query {query_id} is not an expected smoke query"));
        }
        let mut targets = BTreeSet::new();
        let mut previous: Option<f64> = None;
        for (index, row) in list.iter().enumerate() {
            let expected_rank = u32::try_from(index + 1).unwrap_or(u32::MAX);
            if row.rank != expected_rank {
                return Err(format!(
                    "ranks for {query_id} are not contiguous from 1 (found {} at position {expected_rank})",
                    row.rank
                ));
            }
            if !targets.insert(row.target.as_str()) {
                return Err(format!("duplicate target {} for {query_id}", row.target));
            }
            if !row.score.is_finite() {
                return Err(format!("non-finite score at {query_id} rank {}", row.rank));
            }
            if previous.is_some_and(|previous| row.score > previous) {
                return Err(format!("score increases at {query_id} rank {}", row.rank));
            }
            previous = Some(row.score);
            if !default_documents.contains(&row.target) {
                return Err(format!(
                    "target {} for {query_id} is not a default document",
                    row.target
                ));
            }
        }
    }
    Ok(())
}

/// R31 repeat determinism: identical query and target order, scores within
/// [`REPEAT_TOLERANCE`].
pub fn check_repeat(candidate: &[TrecRow], repeat: &[TrecRow]) -> std::result::Result<(), String> {
    let left = by_query(candidate);
    let right = by_query(repeat);
    let left_queries: Vec<&str> = left.keys().copied().collect();
    let right_queries: Vec<&str> = right.keys().copied().collect();
    if left_queries != right_queries {
        return Err("the repeat run covers different queries".to_string());
    }
    for (query_id, rows) in &left {
        let other = &right[query_id];
        if rows.len() != other.len() {
            return Err(format!(
                "the repeat returns a different depth for {query_id}"
            ));
        }
        for (a, b) in rows.iter().zip(other) {
            if a.target != b.target {
                return Err(format!(
                    "the repeat changes the target order for {query_id} at rank {}",
                    a.rank
                ));
            }
            if (a.score - b.score).abs() > REPEAT_TOLERANCE || a.score.is_nan() != b.score.is_nan()
            {
                return Err(format!(
                    "the repeat changes a score for {query_id} at rank {}",
                    a.rank
                ));
            }
        }
    }
    Ok(())
}

/// One results file with its document run.
#[derive(Clone, Debug)]
pub struct GateRun {
    /// The validated report.
    pub report: Report,
    /// The parsed document run, or why it is unusable.
    pub rows: std::result::Result<Vec<TrecRow>, (Reason, String)>,
    /// SHA-256 of `results.json`.
    pub results_sha256: String,
    /// SHA-256 of the run artifact, when present.
    pub run_sha256: Option<String>,
}

impl GateRun {
    /// Load the run artifact named by `report.artifacts.run` next to `results`.
    pub fn load(results: &Path, report: Report) -> crate::Result<Self> {
        let bytes = std::fs::read(results)
            .map_err(|error| crate::Failure::report(format!("cannot read results: {error}")))?;
        let results_sha256 = sha256_hex(&bytes);
        let Some(name) = report.artifacts.run.clone() else {
            return Ok(Self {
                report,
                rows: Err((
                    Reason::MissingInput,
                    "a results file names no run artifact".to_string(),
                )),
                results_sha256,
                run_sha256: None,
            });
        };
        let path = results
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join(&name);
        let (rows, run_sha256) = match std::fs::read(&path) {
            Ok(bytes) => {
                let sha = sha256_hex(&bytes);
                let rows = String::from_utf8(bytes)
                    .map_err(|_| "the run artifact is not UTF-8".to_string())
                    .and_then(|text| parse_trec(&text))
                    .map_err(|message| (Reason::RankingInvariant, message));
                (rows, Some(sha))
            }
            Err(_) => (
                Err((
                    Reason::MissingInput,
                    format!("run artifact {name} is missing"),
                )),
                None,
            ),
        };
        Ok(Self {
            report,
            rows,
            results_sha256,
            run_sha256,
        })
    }
}

// ---------------------------------------------------------------------------
// The published smoke set
// ---------------------------------------------------------------------------

/// Provenance facts the gate needs (SPEC-0004 judgment format).
#[derive(Clone, Debug)]
pub struct SmokeProvenance {
    /// `verified`, `adjudicated`, `draft`, or `rejected`.
    pub state: String,
    /// Number of `verified_by` entries.
    pub verifiers: usize,
}

impl SmokeProvenance {
    fn from_value(value: Option<&Value>) -> Self {
        let state = value
            .and_then(|value| value.get("state"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let verifiers = value
            .and_then(|value| value.get("verified_by"))
            .and_then(Value::as_array)
            .map_or(0, Vec::len);
        Self { state, verifiers }
    }

    /// Verified or adjudicated with at least one recorded reviewer (ADR-0026).
    #[must_use]
    pub fn is_verified(&self) -> bool {
        matches!(self.state.as_str(), "verified" | "adjudicated") && self.verifiers > 0
    }
}

/// One published smoke query.
#[derive(Clone, Debug)]
pub struct SmokeQuery {
    /// Query ID.
    pub id: String,
    /// Category wire ID.
    pub category: String,
    /// Configuration wire ID.
    pub configuration: String,
    /// Split wire ID.
    pub split: String,
    /// Provenance.
    pub provenance: SmokeProvenance,
}

/// One published judgment (document or passage).
#[derive(Clone, Debug)]
pub struct SmokeJudgment {
    /// `file:line` location.
    pub location: String,
    /// Provenance.
    pub provenance: SmokeProvenance,
}

/// The committed `sdc-smoke-v1` set as the gate sees it.
#[derive(Clone, Debug, Default)]
pub struct SmokeSet {
    /// SHA-256 of `judgment-set.json` (the report's `judgment_set_hash`).
    pub judgment_set_hash: String,
    /// Manifest `judgment_set_id`.
    pub judgment_set_id: String,
    /// Manifest `state`.
    pub state: String,
    /// Manifest `test_exposure`.
    pub test_exposure: String,
    /// Manifest `compatible_corpus_hashes`.
    pub compatible_corpus_hashes: Vec<String>,
    /// Every published `dev` query.
    pub queries: Vec<SmokeQuery>,
    /// Every published `dev` document and passage judgment.
    pub judgments: Vec<SmokeJudgment>,
    /// Corpus documents: ID to whether ADR-0024 classifies it as source code.
    pub documents: BTreeMap<String, bool>,
    /// Why full SDC loader validation of the default `dev` selection failed.
    pub validation_error: Option<String>,
}

/// Publication state of the smoke set.
#[derive(Clone, Debug)]
pub enum SmokeSetState {
    /// `bench/qrels/sdc/sdc-smoke-v1/judgment-set.json` does not exist.
    Unpublished,
    /// The set exists but cannot be read.
    Invalid(String),
    /// The set was read.
    Loaded(Box<SmokeSet>),
}

fn read_jsonl(path: &Path) -> std::result::Result<Vec<Value>, String> {
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("file")
        .to_string();
    let text = std::fs::read_to_string(path).map_err(|_| format!("cannot read {name}"))?;
    text.lines()
        .enumerate()
        .map(|(index, line)| {
            serde_json::from_str(line).map_err(|_| format!("{name}:{} is not JSON", index + 1))
        })
        .collect()
}

fn text_field(value: &Value, key: &str) -> String {
    value
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string()
}

/// Read the committed smoke set under `paths` without the SDC loader, so that
/// draft data yields [`Reason::UnverifiedData`] instead of a loader error,
/// then run the full loader for the default `dev` selection.
#[must_use]
pub fn load_smoke_set(paths: &BenchPaths) -> SmokeSetState {
    let dir = paths.qrels().join(SMOKE_JUDGMENT_SET);
    let manifest_path = dir.join("judgment-set.json");
    let bytes = match std::fs::read(&manifest_path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return SmokeSetState::Unpublished;
        }
        Err(_) => return SmokeSetState::Invalid("cannot read judgment-set.json".to_string()),
    };
    let manifest: Value = match serde_json::from_slice(&bytes) {
        Ok(value) => value,
        Err(_) => return SmokeSetState::Invalid("judgment-set.json is not JSON".to_string()),
    };
    let mut set = SmokeSet {
        judgment_set_hash: sha256_hex(&bytes),
        judgment_set_id: text_field(&manifest, "judgment_set_id"),
        state: text_field(&manifest, "state"),
        test_exposure: text_field(&manifest, "test_exposure"),
        compatible_corpus_hashes: manifest
            .get("compatible_corpus_hashes")
            .and_then(Value::as_array)
            .map(|hashes| {
                hashes
                    .iter()
                    .filter_map(Value::as_str)
                    .map(str::to_string)
                    .collect()
            })
            .unwrap_or_default(),
        validation_error: None,
        ..SmokeSet::default()
    };
    let queries = match read_jsonl(&dir.join("queries.dev.jsonl")) {
        Ok(rows) => rows,
        Err(message) => return SmokeSetState::Invalid(message),
    };
    for query in &queries {
        set.queries.push(SmokeQuery {
            id: text_field(query, "_id"),
            category: text_field(query, "category"),
            configuration: text_field(query, "configuration"),
            split: text_field(query, "split"),
            provenance: SmokeProvenance::from_value(query.get("provenance")),
        });
    }
    for name in ["qrels.dev.documents.jsonl", "qrels.dev.passages.jsonl"] {
        let rows = match read_jsonl(&dir.join(name)) {
            Ok(rows) => rows,
            Err(message) => return SmokeSetState::Invalid(message),
        };
        for (index, row) in rows.iter().enumerate() {
            set.judgments.push(SmokeJudgment {
                location: format!("{name}:{}", index + 1),
                provenance: SmokeProvenance::from_value(row.get("provenance")),
            });
        }
    }
    let corpus_dir = paths.corpora().join(SMOKE_CORPUS);
    let documents = match read_jsonl(&corpus_dir.join("corpus.jsonl")) {
        Ok(rows) => rows,
        Err(message) => return SmokeSetState::Invalid(message),
    };
    for document in &documents {
        let source_code = document
            .get("metadata")
            .and_then(|metadata| metadata.get("file_class"))
            .and_then(Value::as_str)
            == Some("source_code");
        set.documents
            .insert(text_field(document, "_id"), source_code);
    }
    set.validation_error = seeky_eval::load_sdc(
        &corpus_dir,
        &dir,
        Split::Dev,
        EvaluationConfiguration::Default,
    )
    .err()
    .map(|error| error.to_string());
    SmokeSetState::Loaded(Box::new(set))
}

// ---------------------------------------------------------------------------
// The gate
// ---------------------------------------------------------------------------

/// Everything [`evaluate`] reads.
pub struct GateInputs<'a> {
    /// Baseline at the current `main` SHA.
    pub baseline: &'a GateRun,
    /// Candidate at the PR head.
    pub candidate: &'a GateRun,
    /// Second clean run of the candidate.
    pub repeat: &'a GateRun,
    /// The supplied current-`main` SHA.
    pub baseline_commit: &'a str,
    /// The committed smoke set.
    pub smoke_set: &'a SmokeSetState,
}

type Check = std::result::Result<(), (Reason, String)>;

fn fail(reason: Reason, message: impl Into<String>) -> Check {
    Err((reason, message.into()))
}

fn environment_key(report: &Report) -> (Option<String>, Option<String>, Option<String>) {
    let text = |pointer: &str| {
        report
            .environment
            .pointer(pointer)
            .and_then(Value::as_str)
            .map(str::to_string)
    };
    (text("/os/family"), text("/os/arch"), text("/tier"))
}

fn per_query(report: &Report) -> &[seeky_eval::QueryMetrics] {
    report
        .quality
        .as_ref()
        .map_or(&[], |quality| quality.per_query.as_slice())
}

/// Apply R29-R31 in order. The first failure wins; otherwise the threshold
/// decides.
#[must_use]
pub fn evaluate(inputs: &GateInputs<'_>) -> GateResult {
    let runs = [
        ("baseline", inputs.baseline),
        ("candidate", inputs.candidate),
        ("repeat", inputs.repeat),
    ];
    let mut observed = json!({
        "baseline_commit": inputs.baseline.report.commit.sha,
        "candidate_commit": inputs.candidate.report.commit.sha,
        "artifacts": runs
            .iter()
            .map(|(label, run)| ((*label).to_string(), json!({
                "results_sha256": run.results_sha256,
                "run_sha256": run.run_sha256,
            })))
            .collect::<Map<String, Value>>(),
    });
    match evaluate_inner(inputs, &runs, &mut observed) {
        Ok(drop_points) => {
            if drop_points <= MAX_DROP_POINTS + DROP_TOLERANCE {
                gate_result(
                    Reason::WithinThreshold,
                    &format!("drop {drop_points:.6} points is within 1.0"),
                    observed,
                )
            } else {
                gate_result(
                    Reason::Regression,
                    &format!("drop {drop_points:.6} points exceeds 1.0"),
                    observed,
                )
            }
        }
        Err((reason, message)) => gate_result(reason, &message, observed),
    }
}

#[allow(clippy::too_many_lines)]
fn evaluate_inner(
    inputs: &GateInputs<'_>,
    runs: &[(&str, &GateRun); 3],
    observed: &mut Value,
) -> std::result::Result<f64, (Reason, String)> {
    let baseline = &inputs.baseline.report;
    let candidate = &inputs.candidate.report;
    let repeat = &inputs.repeat.report;

    // R30: the baseline must be the supplied current-main SHA.
    if inputs.baseline_commit.trim().is_empty() || baseline.commit.sha != inputs.baseline_commit {
        fail(
            Reason::NotMainBaseline,
            "the baseline commit is not the supplied current-main SHA",
        )?;
    }
    // R29: clean runs; the repeat is the same candidate commit.
    for (label, run) in runs {
        if run.report.commit.dirty {
            fail(Reason::DirtyCommit, format!("the {label} run is dirty"))?;
        }
    }
    if repeat.commit.sha != candidate.commit.sha {
        fail(
            Reason::DirtyCommit,
            "the repeat run is not the candidate commit",
        )?;
    }
    // R29: sdc-smoke-v1 dev quality reports in the default configuration.
    for (label, run) in runs {
        let dataset = &run.report.dataset;
        if run.report.kind != ReportKind::Quality
            || dataset.id != SMOKE_CORPUS
            || dataset.judgment_set_id != SMOKE_JUDGMENT_SET
            || dataset.split != Split::Dev
            || dataset.configuration != EvaluationConfiguration::Default
        {
            fail(
                Reason::WrongDataset,
                format!(
                    "the {label} run is not a sdc-smoke-v1 dev quality report in the default configuration"
                ),
            )?;
        }
    }
    // R30: published, frozen, test not applicable, every record verified.
    let set = match inputs.smoke_set {
        SmokeSetState::Unpublished => {
            return Err((
                Reason::SmokeSetUnpublished,
                "sdc-smoke-v1 not published (H6)".to_string(),
            ));
        }
        SmokeSetState::Invalid(message) => {
            return Err((Reason::SmokeSetInvalid, message.clone()));
        }
        SmokeSetState::Loaded(set) => set,
    };
    if set.judgment_set_id != SMOKE_JUDGMENT_SET || set.state != "frozen" {
        fail(
            Reason::NotFrozen,
            "the sdc-smoke-v1 judgment set is not frozen",
        )?;
    }
    if set.test_exposure != "not-applicable" {
        fail(
            Reason::NotFrozen,
            "sdc-smoke-v1 must declare test_exposure not-applicable",
        )?;
    }
    if let Some(query) = set
        .queries
        .iter()
        .find(|query| !query.provenance.is_verified())
    {
        fail(
            Reason::UnverifiedData,
            format!(
                "query {} is {} rather than verified or adjudicated",
                query.id,
                if query.provenance.state.is_empty() {
                    "unlabelled"
                } else {
                    query.provenance.state.as_str()
                }
            ),
        )?;
    }
    if let Some(judgment) = set
        .judgments
        .iter()
        .find(|judgment| !judgment.provenance.is_verified())
    {
        fail(
            Reason::UnverifiedData,
            format!(
                "judgment {} is not verified or adjudicated",
                judgment.location
            ),
        )?;
    }
    if let Some(message) = &set.validation_error {
        fail(Reason::SmokeSetInvalid, message.clone())?;
    }

    // R29: identical corpus, judgment set, config hash, query membership.
    for (label, run) in runs {
        let dataset = &run.report.dataset;
        if dataset.judgment_set_hash != set.judgment_set_hash {
            fail(
                Reason::InputMismatch,
                format!("the {label} run used a different sdc-smoke-v1 revision"),
            )?;
        }
        if !set
            .compatible_corpus_hashes
            .iter()
            .any(|hash| hash == &dataset.corpus_hash)
        {
            fail(
                Reason::InputMismatch,
                format!("the {label} corpus hash is not compatible with sdc-smoke-v1"),
            )?;
        }
    }
    for (label, run) in &runs[1..] {
        let left = &baseline.dataset;
        let right = &run.report.dataset;
        if left.corpus_hash != right.corpus_hash
            || left.fingerprint != right.fingerprint
            || left.query_set_sha256 != right.query_set_sha256
            || left.query_count != right.query_count
        {
            fail(
                Reason::InputMismatch,
                format!("the {label} corpus or query membership differs from the baseline"),
            )?;
        }
        if baseline.system.config_hash != run.report.system.config_hash {
            fail(
                Reason::InputMismatch,
                format!("the {label} config hash differs from the baseline"),
            )?;
        }
    }
    // R29: identical OS family/architecture and hardware tier.
    let environment = environment_key(baseline);
    if environment.0.is_none() || environment.1.is_none() || environment.2.is_none() {
        fail(
            Reason::EnvironmentMismatch,
            "the baseline environment lacks OS family, architecture, or tier",
        )?;
    }
    for (label, run) in &runs[1..] {
        if environment_key(&run.report) != environment {
            fail(
                Reason::EnvironmentMismatch,
                format!("the {label} OS family, architecture, or tier differs"),
            )?;
        }
    }

    // R30: no code queries or code documents in any run.
    let source_code: BTreeSet<&str> = set
        .documents
        .iter()
        .filter(|(_, code)| **code)
        .map(|(id, _)| id.as_str())
        .collect();
    let code_queries: BTreeSet<&str> = set
        .queries
        .iter()
        .filter(|query| query.category == QueryCategory::CodeSearch.as_str())
        .map(|query| query.id.as_str())
        .collect();
    for (label, run) in runs {
        if per_query(&run.report)
            .iter()
            .any(|row| row.category == QueryCategory::CodeSearch)
        {
            fail(
                Reason::CodeResults,
                format!("the {label} run reports a code_search query"),
            )?;
        }
        if let Ok(rows) = &run.rows
            && let Some(row) = rows.iter().find(|row| {
                source_code.contains(row.target.as_str())
                    || code_queries.contains(row.query_id.as_str())
            })
        {
            fail(
                Reason::CodeResults,
                format!("the {label} run contains code results for {}", row.query_id),
            )?;
        }
    }

    // R29: all default non-code dev queries, five per category.
    let mut expected: BTreeMap<String, String> = BTreeMap::new();
    for query in &set.queries {
        if query.split == "dev"
            && query.configuration == EvaluationConfiguration::Default.as_str()
            && query.category != QueryCategory::CodeSearch.as_str()
        {
            expected.insert(query.id.clone(), query.category.clone());
        }
    }
    for category in NON_CODE_CATEGORIES {
        let count = expected
            .values()
            .filter(|value| value.as_str() == category.as_str())
            .count();
        if count < MIN_QUERIES_PER_CATEGORY {
            fail(
                Reason::CategoryCoverage,
                format!(
                    "category {} has {count} default dev queries; at least {MIN_QUERIES_PER_CATEGORY} are required",
                    category.as_str()
                ),
            )?;
        }
    }
    if expected
        .values()
        .any(|category| !NON_CODE_CATEGORIES.iter().any(|c| c.as_str() == category))
    {
        fail(
            Reason::CategoryCoverage,
            "a default dev query has an unknown category",
        )?;
    }
    let expected_ids: BTreeSet<String> = expected.keys().cloned().collect();

    // R31: complete expected query coverage.
    for (label, run) in runs {
        let rows = per_query(&run.report);
        let ids: BTreeSet<String> = rows.iter().map(|row| row.query_id.clone()).collect();
        if ids.len() != rows.len() {
            fail(
                Reason::QueryCoverage,
                format!("the {label} run reports a query twice"),
            )?;
        }
        if ids != expected_ids {
            let missing = expected_ids.difference(&ids).count();
            let extra = ids.difference(&expected_ids).count();
            fail(
                Reason::QueryCoverage,
                format!(
                    "the {label} run misses {missing} and adds {extra} queries against sdc-smoke-v1"
                ),
            )?;
        }
        if run.report.dataset.query_count != expected_ids.len() as u64 {
            fail(
                Reason::QueryCoverage,
                format!("the {label} query count differs from sdc-smoke-v1"),
            )?;
        }
        if let Some(row) = rows.iter().find(|row| {
            expected.get(&row.query_id).map(String::as_str) != Some(row.category.as_str())
        }) {
            fail(
                Reason::QueryCoverage,
                format!(
                    "the {label} run reports {} under another category",
                    row.query_id
                ),
            )?;
        }
    }

    // Per-query nDCG@10 must be measured for every query.
    let metric_of =
        |report: &Report| -> std::result::Result<BTreeMap<String, f64>, (Reason, String)> {
            let mut values = BTreeMap::new();
            for row in per_query(report) {
                match row.metrics.get("ndcg_10") {
                    Some(value) if value.is_finite() && (0.0..=1.0).contains(value) => {
                        values.insert(row.query_id.clone(), *value);
                    }
                    _ => {
                        return Err((
                            Reason::MissingMetric,
                            format!("nDCG@10 is missing or out of range for {}", row.query_id),
                        ));
                    }
                }
            }
            Ok(values)
        };
    let baseline_values = metric_of(baseline)?;
    let candidate_values = metric_of(candidate)?;
    let repeat_values = metric_of(repeat)?;

    // R31: ranking invariants on every run.
    let default_documents: BTreeSet<String> = set
        .documents
        .iter()
        .filter(|(_, code)| !**code)
        .map(|(id, _)| id.clone())
        .collect();
    for (label, run) in runs {
        let rows = run
            .rows
            .as_ref()
            .map_err(|(reason, message)| (*reason, format!("{label}: {message}")))?;
        check_ranking(rows, &expected_ids, &default_documents)
            .map_err(|message| (Reason::RankingInvariant, format!("{label}: {message}")))?;
    }

    // R31: the repeat matches the candidate run and metrics.
    if let (Ok(left), Ok(right)) = (&inputs.candidate.rows, &inputs.repeat.rows) {
        check_repeat(left, right).map_err(|message| (Reason::NondeterministicRepeat, message))?;
    }
    for (query_id, value) in &candidate_values {
        if repeat_values
            .get(query_id)
            .is_none_or(|other| (value - other).abs() > REPEAT_TOLERANCE)
        {
            fail(
                Reason::NondeterministicRepeat,
                format!("the repeat changes nDCG@10 for {query_id}"),
            )?;
        }
    }
    for (repeat_row, candidate_row) in per_query(repeat).iter().zip(per_query(candidate)) {
        let same = repeat_row.metrics.len() == candidate_row.metrics.len()
            && repeat_row.metrics.iter().all(|(metric, value)| {
                candidate_row
                    .metrics
                    .get(metric)
                    .is_some_and(|other| (value - other).abs() <= REPEAT_TOLERANCE)
            });
        if !same {
            fail(
                Reason::NondeterministicRepeat,
                format!("the repeat changes metrics for {}", repeat_row.query_id),
            )?;
        }
    }

    // Macro nDCG@10 over the selected queries with equal query weight.
    let macro_of = |values: &BTreeMap<String, f64>, ids: &mut dyn Iterator<Item = &String>| {
        let selected: Vec<f64> = ids.filter_map(|id| values.get(id).copied()).collect();
        if selected.is_empty() {
            0.0
        } else {
            selected.iter().sum::<f64>() / selected.len() as f64
        }
    };
    let baseline_macro = macro_of(&baseline_values, &mut expected_ids.iter());
    let candidate_macro = macro_of(&candidate_values, &mut expected_ids.iter());
    let drop_points = 100.0 * (baseline_macro - candidate_macro);

    let mut categories = Map::new();
    for category in NON_CODE_CATEGORIES {
        let ids: Vec<&String> = expected
            .iter()
            .filter(|(_, value)| value.as_str() == category.as_str())
            .map(|(id, _)| id)
            .collect();
        categories.insert(
            category.as_str().to_string(),
            json!({
                "queries": ids.len(),
                "baseline": macro_of(&baseline_values, &mut ids.iter().copied()),
                "candidate": macro_of(&candidate_values, &mut ids.iter().copied()),
            }),
        );
    }
    let mut languages: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for row in per_query(candidate) {
        languages
            .entry(row.language_slice.as_str().to_string())
            .or_default()
            .push(row.query_id.clone());
    }
    let languages: Map<String, Value> = languages
        .into_iter()
        .map(|(slice, ids)| {
            (
                slice,
                json!({
                    "queries": ids.len(),
                    "baseline": macro_of(&baseline_values, &mut ids.iter()),
                    "candidate": macro_of(&candidate_values, &mut ids.iter()),
                }),
            )
        })
        .collect();
    if let Value::Object(object) = observed {
        object.insert("drop_points".to_string(), json!(drop_points));
        object.insert("baseline".to_string(), json!(baseline_macro));
        object.insert("candidate".to_string(), json!(candidate_macro));
        object.insert("queries".to_string(), json!(expected_ids.len()));
        object.insert("categories".to_string(), Value::Object(categories));
        object.insert("language_slices".to_string(), Value::Object(languages));
    }
    Ok(drop_points)
}
