# SPEC-0003 — Evaluation and benchmark harness (v1)

| Field | Value |
|---|---|
| Status | Accepted (maintainer pre-approval in /goal) |
| Version | 0.3 (Phase 1 quality, statistics, reporting, performance, CI smoke) |
| Owner | Maintainer |
| Phase / work packages | Phase 1 — WP-1.1, WP-1.2, WP-1.5, WP-1.6, WP-1.8 |
| Crates touched | `seeky-eval` (new implementation); `tools/seeky-bench` (new workspace tool); `bench/datasets/` and `bench/exposures/` data contracts |
| Governing docs | [vision](../product/vision.md) §2; [methodology](../benchmarks/methodology.md) §2–§6, §8.2, §10–§11; [ADR-0015](../adr/0015-engine-first-architecture.md); [ADR-0019](../adr/0019-single-inference-engine.md); [ADR-0021](../adr/0021-no-generative-models-in-product.md); [ADR-0022](../adr/0022-permissive-license-gate.md); [ADR-0023](../adr/0023-multimodal-ready-engine.md); [ADR-0024](../adr/0024-source-code-indexing-opt-in.md); [SPEC-0001](SPEC-0001-workspace-and-crate-boundaries.md); [SPEC-0002](SPEC-0002-engine-api.md); [SPEC-0004](SPEC-0004-sdc-corpus-and-judgments.md); [_report-template.md](../benchmarks/_report-template.md) |
| Benchmark gates | Produces evidence for Q1–Q4 and Q7 and the methodology §3.2 search/indexing/resource metrics; owns the WP-1.8 smoke gate. A budget is claimed only by a concrete qualifying run. It defines no new budget and makes no quality claim by itself |

## 1. Problem and goal

Seeky cannot select a model, ranking stage, analyzer, or storage design without
a headless, reproducible way to load a dataset, run the real engine, compute
standard and Seeky-specific metrics, apply paired statistics, and write an
auditable report. The PoC has no evaluation layer at all (plan §4), so today a
change can look faster or better only by anecdote. Benchmark-driven development
(P7) is impossible until one implementation defines every number the project
trusts.

This specification defines `seeky-eval`, the internal `seeky-bench` command, the
BEIR and Seeky Desktop Corpus (SDC) loaders, TREC run interchange, graded qrels,
metric and statistical definitions with fixed reference values, the report JSON
and Markdown formats, environment/config fingerprinting, test-split protection,
the Phase 1 performance suite, and the WP-1.8 CI smoke gate. It consumes the
accepted SPEC-0004 formats without changing them. Python remains confined to
offline tooling; no evaluator or benchmark command ships in the product
(ADR-0008).

Done for the Phase 1 harness means a clean commit can build an index, evaluate a
frozen dataset, emit a TREC run and a report whose numbers a second run
reproduces, compare two systems with paired confidence intervals, measure every
methodology §3.2 Phase 1 metric, and block a smoke pull request on the accepted
eight-category rule. Visual and OCR pack metrics become extensions in later
specs; their optional report fields must not block this version.

## 2. Scope

- **In:** `crates/seeky-eval` types, loaders, metrics, statistics, and writers;
  `tools/seeky-bench` commands `index`, `eval`, `perf`, `compare`, and `report`;
  BEIR and SDC loading; TREC run read/write; graded document and passage qrels;
  nDCG, MRR, Recall, Success, duplicate, diversity, and slice aggregates;
  paired randomization/bootstrap with fixed seeds and Holm correction; report
  JSON/Markdown; environment and config hashing; SDC/dataset fingerprints;
  public-dataset manifest and transformation contracts; test confirmation and
  exposure accounting; methodology §3.2 performance metrics; ranking
  invariants; the WP-1.8 eight-category smoke gate.
- **Out:** changing retrieval or indexing behavior; model bake-offs and the
  `bakeoff` command (WP-2.2/SPEC-0005); OCR CER/WER and visual Q8 metrics
  (SPEC-0009, later SPEC-0003/SPEC-0004 versions); creating the SDC (SPEC-0004);
  selecting or judging queries (WP-1.4); executing the B0 run or locking
  budgets (WP-1.7, human/T1); a product CLI, HTTP service, UI, telemetry, or
  generative feature; committing downloaded public datasets or private
  corpora.

## 3. Requirements (EARS)

All requirements are open. The WP column names the implementation owner.

| ID | WP | Requirement | Verification | Status |
|---|---|---|---|---|
| SPEC-0003-R1 | WP-1.1 | `seeky-eval` shall expose the public dataset, run, judgment, metric, statistics, and report types of §4.1 with `thiserror` failures, no `unwrap`/`expect` on input, and dependencies limited to `seeky-core` plus general-purpose serialization/hash crates permitted by SPEC-0001. | compile-time API tests; `cargo tree -p seeky-eval`; `eval_crate_has_no_engine_ui_or_tauri_dependency` | Implemented (WP-1.1) |
| SPEC-0003-R2 | WP-1.1 | When a BEIR-layout dataset is loaded, the loader shall parse UTF-8 JSONL `corpus.jsonl` and query files plus tab-separated graded qrels exactly as §4.2 specifies, preserve BEIR `_id`, `title`, `text`, and metadata, validate the declared engine files and path mapping when present, and reject malformed headers, duplicate IDs, dangling qrel IDs, noninteger or out-of-range grades, unknown splits, and trailing data with line-bearing errors. | `beir_loads_reference_layout`; malformed BEIR matrix; `beir_duplicate_and_dangling_ids_are_rejected`; `beir_files_mapping_matches_corpus_text` | Implemented (WP-1.1) |
| SPEC-0003-R3 | WP-1.1 | When an SDC corpus and judgment set are loaded, the loader shall validate the SPEC-0004 manifest and sidecar hashes, read only a `frozen` judgment set whose files match and whose provenance is verified or adjudicated, enforce compatible corpus hashes and target text hashes, select documents and queries by evaluation configuration, and reject draft, stale, partial, unverified, or split-incomplete data. | `sdc_smoke_loads_with_all_sidecars`; `sdc_rejects_stale_corpus_and_qrel_hashes`; `sdc_rejects_draft_or_unverified_judgments`; `sdc_configuration_filters_documents_and_queries` | Implemented (WP-1.1) |
| SPEC-0003-R4 | WP-1.1 | The evaluator shall represent graded document and passage judgments as unique `(query_id, target_id)` records with integer grades 0–3, validate evidence and target hashes against the loaded corpus, distinguish explicit grade 0 from absence, and expose queries with zero positive judgments without silently dropping them. | `graded_qrels_validate_evidence_and_hashes`; `explicit_zero_is_not_missing`; `queries_without_positive_judgments_are_retained` | Implemented (WP-1.1) |
| SPEC-0003-R5 | WP-1.1 | The evaluator shall read and write the six-column TREC run format in §4.3 with finite scores, unique targets per query, ranks 1–1000 and contiguous rank order, preserve document/passage target type resolved from the dataset, and reject unknown query or target IDs, malformed columns, duplicate targets, gaps, nonfinite scores, and mixed or malformed run IDs. | `trec_run_round_trip_preserves_rank_and_scores`; malformed TREC matrix; `duplicate_targets_and_rank_gaps_are_rejected` | Implemented (WP-1.1) |
| SPEC-0003-R6 | WP-1.1 | The evaluator shall implement document and passage nDCG@k, MRR@k, Recall@k, and Success@k exactly as §4.4 and §5.2 define, including the reference values in §5.8, with no implementation-defined tie or unjudged behavior. | `ndcg_matches_reference_values`; `mrr_recall_success_match_reference_values`; property tests for boundedness and monotonicity | Implemented (WP-1.1) |
| SPEC-0003-R7 | WP-1.1 | When a run contains engine chunks rather than canonical passage IDs, the harness shall map each chunk to at most one SPEC-0004 gold passage using the deterministic overlap rule in §5.1, deduplicate mapped passages by best rank, and report unmapped chunks without silently inflating passage metrics. | `chunk_overlap_maps_to_one_gold_passage`; `duplicate_chunks_keep_best_passage_rank`; `unmapped_chunks_are_counted` | Implemented (WP-1.1) |
| SPEC-0003-R8 | WP-1.1 | The evaluator shall compute duplicate rate@k from the union-find of all SPEC-0004 duplicate-cluster kinds, the duplicate-heavy slice, and macro aggregates exactly as §4.4 defines, while leaving duplicate metrics unavailable for datasets without cluster labels. | `duplicate_rate_matches_reference_value`; `duplicate_slice_is_derived_from_judged_clusters`; `missing_clusters_report_metric_unavailable` | Implemented (WP-1.1) |
| SPEC-0003-R9 | WP-1.1 | The evaluator shall compute α-nDCG@k with α = 0.5, distinct relevant@k, and subtopic recall@k exactly as §4.4 and §5.2 define, require subtopic labels for exploratory queries, and report diversity only on eligible exploratory queries. | `alpha_ndcg_matches_reference_value`; `distinct_and_subtopic_recall_match_reference_values`; `missing_subtopic_labels_are_typed_errors` | Implemented (WP-1.1) |
| SPEC-0003-R10 | WP-1.1 | The evaluator shall compute macro query metrics, per-category and per-language aggregates, and the weighted primary nDCG@10 with weights pt 0.35, en 0.35, cross-lingual 0.15, and other 0.15; default evaluation shall use the eight non-code categories, and code-enabled results shall be computed and compared separately. | `weighted_primary_matches_hand_calculation`; `default_aggregate_excludes_code_search`; `code_enabled_aggregate_is_separate` | Implemented (WP-1.1) |
| SPEC-0003-R11 | WP-1.1 | When two evaluations on the same query IDs are compared, the evaluator shall run a two-sided paired randomization test and a paired percentile bootstrap with 10,000 resamples, a caller-supplied fixed seed, the deterministic hash stream of §5.3, 95% confidence intervals, and Holm-adjusted p-values for multi-candidate families. | `randomization_and_bootstrap_match_fixed_seed_reference`; `paired_statistics_are_seed_reproducible`; `holm_adjustment_matches_reference` | Implemented (WP-1.1) |
| SPEC-0003-R12 | WP-1.1 | The evaluator shall serialize the versioned report object of §4.6 with deterministic key and row order and shall reject reports missing required provenance, dataset, configuration, environment, metric, or artifact fields. | `report_json_round_trip_and_schema_validation`; `report_json_is_deterministic`; malformed-report matrix | Implemented (WP-1.1) |
| SPEC-0003-R13 | WP-1.1 | The evaluator shall render the Markdown report sections and tables of [_report-template.md](../benchmarks/_report-template.md) exactly as §4.7 defines, deriving every number from the report object and writing `—` or an explicit unavailable note instead of inventing a value. | `markdown_report_matches_golden`; `missing_measurements_are_not_invented`; report privacy test | Implemented (WP-1.1) |
| SPEC-0003-R14 | WP-1.1 | If any dataset, qrels, run, report, configuration, or statistics input is malformed, then `seeky-eval` and `seeky-bench` shall return a stable typed error with a nonempty location and shall not panic; JSONL/TSV/TREC readers shall be fuzzed with arbitrary bytes. | fuzz targets for JSONL, TSV, TREC, and report readers; `harness_never_panics_on_malformed_inputs` | Implemented (WP-1.1) |
| SPEC-0003-R15 | WP-1.2 | `seeky-bench` shall expose the `index`, `eval`, `perf`, `compare`, and `report` subcommands with the required flags in §4.8, resolve corpus names only through built-in SDC mappings or `bench/datasets/<dataset-id>/manifest.json`, and reject unknown, conflicting, or unsupported flag combinations before touching the engine. | `cli_exposes_all_five_subcommands_and_flags`; `unknown_or_conflicting_flags_fail_before_engine_open`; corpus-resolution tests | Implemented (WP-1.2) |
| SPEC-0003-R16 | WP-1.2 | Before any run, `seeky-bench` shall capture the privacy-safe environment of §4.9 and hash the semantic engine/ranking configuration with SHA-256 over canonical JSON excluding paths, credentials, output locations, and wall-clock values; a second run with the same effective configuration shall produce the same hash. | `config_hash_is_stable_and_path_independent`; `semantic_changes_change_config_hash`; `environment_capture_contains_no_user_or_private_path` | Implemented (WP-1.2) |
| SPEC-0003-R17 | WP-1.2 | When `index` runs, it shall add the selected corpus roots through the `Engine` API with watching disabled for deterministic benchmark indexing, wait for the requested coverage, and write an index metadata sidecar binding corpus hash, code configuration, config hash, model hashes, counts, and timings; `eval` and `perf` shall reject a sidecar that does not match. | `index_writes_metadata_and_disables_watching`; `eval_rejects_mismatched_index_metadata`; `index_reuses_only_compatible_data_directory` | Implemented (WP-1.2) |
| SPEC-0003-R18 | WP-1.2 | When `eval` runs, it shall load exactly one frozen split/configuration, issue the fixed queries through `Engine::search` in deterministic query-ID order, request at least the maximum metric cutoff, build a document TREC run and, where supported, a mapped passage run, evaluate them with `seeky-eval`, and atomically write `run.trec` (documents), optional `run.passages.trec`, `results.json`, `summary.md`, the environment, the config snapshot, and checksums. | `eval_writes_complete_reproducible_artifact_set`; `eval_query_order_is_deterministic`; `eval_rejects_insufficient_result_depth` | Implemented (WP-1.2) |
| SPEC-0003-R19 | WP-1.2 | When `compare` runs, it shall validate identical report/evaluator schema versions, dataset, split, judgment-set, query membership, and compatible metric definitions, compute paired statistics and the requested gate, and write a comparison report without rerunning the engine. | `compare_requires_compatible_runs`; `compare_writes_paired_statistics`; `compare_never_opens_engine` | Implemented (WP-1.2) |
| SPEC-0003-R20 | WP-1.2 | When `report` runs, it shall render a new Markdown report solely from an existing validated results JSON, without recomputing metrics or reading corpus content, and shall refuse to overwrite differing report content without explicit `--overwrite`. | `report_recomputes_nothing`; `report_requires_existing_results`; `report_overwrite_requires_flag` | Implemented (WP-1.2) |
| SPEC-0003-R21 | WP-1.2 | If `eval` targets `test`, then it shall require a valid predeclared confirmation manifest, clean source, a matching frozen judgment set, and an append-only matching exposure ledger; it shall record each confirmation before its first query, update only SPEC-0004's `test_exposure` field on the first-ever exposure, allow only the declared baseline and at most two candidate configurations, forbid rerunning a completed confirmation, and never expose a tuning path. | `test_eval_requires_confirmation_and_clean_tree`; `test_exposure_is_written_before_first_query`; `test_rejects_new_or_modified_configs`; `completed_confirmation_cannot_rerun`; `later_confirmation_does_not_rewrite_test_exposure` | Implemented (WP-1.2) |
| SPEC-0003-R22 | WP-1.2 | The harness shall not write query text, document text, document file names, absolute paths, user names, or secrets to results, Markdown reports, logs, or diagnostics; committed reports for private datasets shall contain aggregate metrics only. | privacy scan of golden artifacts; `private_report_omits_per_query_and_paths`; logging review | Implemented (WP-1.2) |
| SPEC-0003-R23 | WP-1.5 | Each public dataset shall have a versioned manifest in `bench/datasets/<dataset-id>/manifest.json` recording source revision/URLs, terms/license, expected hashes, local file hashes, split files, corpus layout, and transformation version; download scripts shall run offline after download, verify hashes and terms, and never commit or redistribute bulk data. | `dataset_manifest_requires_license_source_and_hashes`; `dataset_download_rejects_hash_or_terms_mismatch`; repository-size/license inspection | Implemented (WP-1.5) |
| SPEC-0003-R24 | WP-1.5 | When a public dataset is prepared, the tools shall produce BEIR files with explicit `dev`/`test` mappings, stable query IDs, categories and language slices required by §4.2, deterministic constructed cross-lingual pairs, and a dataset fingerprint; the same inputs, transform version, and seed shall yield identical files and fingerprint. | `public_dataset_transform_is_byte_deterministic`; `constructed_cross_lingual_pairs_are_stable`; `manifest_splits_categories_and_languages_validate` | Implemented (WP-1.5) |
| SPEC-0003-R25 | WP-1.6 | When `perf` measures search, it shall time each requested stage/condition on a fixed `dev` query set, discard warm-up, compute p50/p95/p99 with bootstrap confidence intervals, and require at least 1,000 query samples per stage or 30 repetitions of the fixed set before a value is budget-eligible. | `perf_latency_percentiles_match_reference`; `perf_bootstrap_ci_matches_fixed_seed_reference`; `undersampled_perf_is_marked_not_budget_eligible` | Implemented (WP-1.6) |
| SPEC-0003-R26 | WP-1.6 | When `perf` runs indexing/interference suites, it shall measure query-embedding batch-1 latency, extraction files/s and MB/s, embedding passages/s, lexical and semantic time-to-searchable, and S5 interference ratio using the same query set and hardware as the idle run. | `perf_indexing_and_embedding_metrics_are_present`; `time_to_searchable_uses_first_matching_result`; `interference_ratio_matches_hand_calculation` | Implemented (WP-1.6) |
| SPEC-0003-R27 | WP-1.6 | When `perf` runs resource/startup/distribution suites, it shall record idle and peak RSS with scope and sampling interval, separate page-cache bytes where available, index bytes per 1k passages, cold start to Instant- and semantic-capable, and optional installer/download/OCR/visual/energy fields without inventing unavailable measurements. | `perf_resources_match_reference_fixture`; `perf_startup_marks_cold_and_scope`; `unavailable_optional_metrics_are_explicit` | Implemented (WP-1.6) |
| SPEC-0003-R28 | WP-1.6 | `perf` shall record the hardware tier and T1-emulated profile, reject a tier/emulation declaration that conflicts with the captured environment, use an explicit quiet-window check, and label every undersampled or synthetic measurement with `qualifies_for_budget = false`. | `perf_rejects_tier_emulation_conflict`; `perf_records_tier_emulation_and_quiet_window`; `perf_budget_eligibility_is_explicit` | Implemented (WP-1.6) |
| SPEC-0003-R29 | WP-1.8 | When `compare --gate wp1.8` runs, it shall require two clean `sdc-smoke-v1` `dev` evaluations in the default configuration with identical corpus, judgment set, config hash, query membership, OS family/architecture, and hardware tier; compare macro nDCG@10 over the eight non-code categories; and pass only when the candidate drop from the baseline is at most 1.0 nDCG point. | `wp18_gate_passes_at_exactly_one_point_drop`; `wp18_gate_fails_above_threshold`; `wp18_requires_eight_non_code_categories_and_same_config` | Implemented |
| SPEC-0003-R30 | WP-1.8 | The WP-1.8 gate shall fail unless every `sdc-smoke-v1` query and judgment is verified or adjudicated (by a human or model reviewer, ADR-0026), the judgment set is frozen with `test_exposure` not applicable, no source-code document or `code_search` query is present, and the baseline commit matches the supplied current-`main` SHA. | `wp18_rejects_unverified_or_draft_smoke_data`; `wp18_rejects_code_results`; `wp18_rejects_non_main_baseline` | Implemented |
| SPEC-0003-R31 | WP-1.8 | Before passing WP-1.8, `compare` shall validate ranking invariants and rerun determinism: unique targets, contiguous ranks, finite nonincreasing scores, complete expected query coverage, only default documents, and identical target order in a second clean run of the same candidate. | `wp18_ranking_invariants_reject_bad_runs`; `wp18_requires_identical_repeat_order`; boundary tests for every invariant | Implemented |
| SPEC-0003-R32 | WP-1.2 | Where a query declares structured filters, `seeky-bench` shall apply the supported extension/date/folder/size predicates exactly to corpus metadata, report whether filtering was pushed into retrieval or applied to returned hits, and fail with a typed error when required metadata is unavailable rather than ignoring a filter. | `filters_are_applied_exactly_and_reported`; `unsupported_filter_metadata_is_an_error`; `post_filtering_does_not_hide_truncated_depth` | Implemented (WP-1.2) |

Status: `Open` → `Implemented` (code and tests merged, tagged with the WP) →
`Verified` (applicable benchmark gate passed with a linked report). The
implementing commit updates only its rows; header and index lifecycle changes
remain maintainer-controlled.

## 4. Interfaces

### 4.1 Crate, tool, and public types

`seeky-eval` owns dataset parsing, judgments, metrics, statistics, and report
serialization. It shall not depend on `seeky-engine`, `seeky-store`,
`seeky-search`, `seeky-infer`, `tauri`, or UI types. `tools/seeky-bench` is the
only bridge to `seeky-engine`; it may use `anyhow` at its binary edge, and must
not contain a second metric implementation.

The public module layout is:

```text
seeky-eval/src/
  dataset.rs   validated corpus, documents, passages, queries, slices
  beir.rs      BEIR JSONL/TSV loader
  sdc.rs       SPEC-0004 loader and fingerprint validation
  qrels.rs     graded document/passage judgments and evidence
  run.rs       TREC run, run rows, target mapping
  metrics.rs   metric definitions and per-query aggregation
  stats.rs     paired randomization, bootstrap, Holm
  report.rs    versioned report object and schema validation
  error.rs     EvalError
  lib.rs       stable re-exports

tools/seeky-bench/src/
  main.rs      CLI and error mapping
  corpus.rs    built-in SDC and dataset-manifest resolution
  engine.rs    Engine adapter, index lifecycle, query execution
  environment.rs environment and config capture
  perf.rs      performance suites
  gate.rs      sample/ranking invariants and WP-1.8 gate
  artifact.rs  atomic artifact directories and checksums
```

The minimum public API is:

```rust
pub type QueryId = String;
pub type DocumentId = String;
pub type PassageId = String;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Split { Dev, Test }

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum EvaluationConfiguration { Default, CodeEnabled }

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum QueryCategory {
    KnownItem, Conceptual, ExactIdentifier, CrossLanguage, NeedleInHaystack,
    Exploratory, MixedSemanticMetadata, CodeSearch, FilenamePartial,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum LanguageSlice {
    Pt, En, CrossLingual, Other, NonLatinNonRegression,
}

#[derive(Clone, Debug)]
pub struct Document {
    pub id: DocumentId,
    pub title: String,
    pub text: String,                 // canonical NFC/LF text
    pub relative_path: String,        // corpus-relative, POSIX separators
    pub source_code: bool,
    pub metadata: serde_json::Value,  // validated filters and source metadata
}

#[derive(Clone, Debug)]
pub struct Passage {
    pub id: PassageId,
    pub document_id: DocumentId,
    pub text: String,
    pub start_utf8: u64,
    pub end_utf8: u64,
    pub kind: String,                 // SPEC-0004 passage kind
    pub locator: serde_json::Value,   // canonical SPEC-0004 locator object
    pub boilerplate_family_id: Option<String>,
}

#[derive(Clone, Debug)]
pub struct Query {
    pub id: QueryId,
    pub text: String,
    pub language: String,
    pub target_languages: Vec<String>,
    pub language_slice: LanguageSlice,
    pub category: QueryCategory,
    pub configuration: EvaluationConfiguration,
    pub split: Split,
    pub filters: Option<serde_json::Value>,
}

#[derive(Clone, Debug)]
pub struct DocumentJudgment {
    pub query_id: QueryId,
    pub document_id: DocumentId,
    pub grade: u8,                    // 0..=3
    pub evidence_passage_ids: Vec<PassageId>,
    pub subtopic_labels: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct PassageJudgment {
    pub query_id: QueryId,
    pub document_id: DocumentId,
    pub passage_id: PassageId,
    pub grade: u8,                    // 0..=3
}

#[derive(Clone, Debug)]
pub struct Dataset {
    pub id: String,
    pub corpus_hash: String,
    pub fingerprint: String,
    pub judgment_set_id: String,
    pub judgment_set_hash: String,
    pub split: Split,
    pub configuration: EvaluationConfiguration,
    // Private validated maps; accessors return slices/iterators.
}

impl Dataset {
    pub fn document(&self, id: &str) -> Option<&Document>;
    pub fn passage(&self, id: &str) -> Option<&Passage>;
    pub fn queries(&self) -> &[Query];
    pub fn document_judgments(&self, query_id: &str) -> &[DocumentJudgment];
    pub fn passage_judgments(&self, query_id: &str) -> &[PassageJudgment];
    pub fn duplicate_family(&self, document_id: &str) -> Option<&str>;
    pub fn duplicate_heavy_query_ids(&self) -> &[QueryId];
    pub fn query_set_sha256(&self) -> &str;
}

#[derive(Clone, Debug)]
pub struct EvaluationResult {
    pub dataset_fingerprint: String,
    pub query_set_sha256: String,
    pub split: Split,
    pub configuration: EvaluationConfiguration,
    pub per_query: BTreeMap<QueryId, BTreeMap<String, f64>>,
    pub macro_metrics: BTreeMap<String, f64>,
    pub unavailable_metrics: BTreeSet<String>,
}

#[derive(Clone, Debug)]
pub struct Comparison {
    pub baseline_system_id: String,
    pub candidate_system_ids: Vec<String>,
    pub paired_queries: usize,
    pub seed: String,
    pub metrics: BTreeMap<String, PairedStatistic>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Significance { Significant, NotSignificant, Inconclusive }

#[derive(Clone, Debug)]
pub struct PairedStatistic {
    pub delta: f64,
    pub delta_points: f64,
    pub ci95_low: f64,
    pub ci95_high: f64,
    pub p_value: f64,
    pub holm_p: Option<f64>,
    pub significance: Significance,
}

// Report/QualityReport/PerformanceReport/GateResult mirror the JSON schema
// in §4.6/§4.10 and serialize with snake_case field names.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Report { /* fields required by §4.6 */ }


#[derive(Clone, Debug)]
pub struct Run {
    pub run_id: String,
    pub system_id: String,
    pub rows: Vec<RunRow>,
}

#[derive(Clone, Debug)]
pub struct RunRow {
    pub query_id: QueryId,
    pub target: RunTarget,       // Document(DocumentId) | Passage(PassageId)
    pub rank: u32,               // 1..=1000
    pub score: f64,              // finite
}

#[derive(Clone, Copy, Debug)]
pub struct MetricSelection { /* cutoff list 1..=1000, alpha default 0.5 */ }

pub struct StatsOptions {
    pub seed: String,             // default "seeky-eval-v1"
    pub resamples: usize,         // default and required reference value 10_000
    pub alpha: f64,               // default 0.05
}

pub fn load_beir(manifest: &Path, split: Split) -> Result<Dataset, EvalError>;
pub fn load_sdc(
    corpus_dir: &Path,
    judgment_set_dir: &Path,
    split: Split,
    configuration: EvaluationConfiguration,
) -> Result<Dataset, EvalError>;

pub fn read_trec_run(path: &Path, dataset: &Dataset) -> Result<Run, EvalError>;
pub fn write_trec_run(run: &Run, path: &Path) -> Result<(), EvalError>;
pub fn evaluate(
    dataset: &Dataset,
    run: &Run,
    selection: &MetricSelection,
) -> Result<EvaluationResult, EvalError>;
pub fn compare(
    baseline: &EvaluationResult,
    candidate: &EvaluationResult,
    options: &StatsOptions,
) -> Result<Comparison, EvalError>;
pub fn write_report_json(report: &Report, path: &Path) -> Result<(), EvalError>;
pub fn write_report_markdown(report: &Report, path: &Path) -> Result<(), EvalError>;
```

All identifiers are opaque nonempty UTF-8 strings with no path semantics.
Serde wire names are snake_case (`dev`, `test`, `default`, `code_enabled`,
`known_item`, `needle_in_haystack`, `cross_lingual`,
`non_latin_non_regression`, …), exactly matching SPEC-0004. Collections that
appear in reports serialize in deterministic key order. No public method
returns an internal map whose iteration order could change a report. `Dataset` accessors provide documents, passages, queries, document
judgments, passage judgments, duplicate families, and data fingerprints.

`EvalError` is `thiserror` with at least these stable variants/codes:

| Code | Condition |
|---|---|
| `IO` | A required file cannot be read/written |
| `SCHEMA` | Missing/unknown field, wrong type, bad enum, bad header |
| `UTF8` / `JSONL` / `TSV` / `TREC` | Syntax failure with file and line |
| `DUPLICATE_ID` | Repeated primary/reference key |
| `DANGLING_REFERENCE` | Unknown query/document/passage/evidence target |
| `HASH_MISMATCH` | Corpus, sidecar, judgment set, or target hash differs |
| `FROZEN_REQUIRED` | Data is draft, split-frozen but unpublished, or unverified |
| `PROVENANCE_INCOMPLETE` | Missing or rejected gate provenance |
| `UNSUPPORTED_METRIC` | Data lacks clusters/subtopics or cutoff exceeds depth |
| `INSUFFICIENT_DEPTH` | Requested metric cutoff exceeds run/engine depth |
| `STATS_INPUT_MISMATCH` | Paired query IDs/slices/configs differ |
| `REPORT_INVALID` | Required report field absent or inconsistent |
| `TEST_NOT_ALLOWED` | Test guard, confirmation, exposure, or clean-tree failure |
| `INDEX_INCOMPATIBLE` | Data directory metadata does not match run |
| `PRIVACY` | A public artifact would contain private content or paths |

Messages may change; codes and conditions may not.

### 4.2 Dataset loading

#### Built-in SDC resolution

| `--corpus` | Corpus root | Default judgment set |
|---|---|---|
| `sdc-smoke` | `bench/corpora/sdc/sdc-smoke` | `bench/qrels/sdc/sdc-smoke-v1` |
| `sdc-s` | `bench/corpora/sdc/sdc-s` | `bench/qrels/sdc/sdc-v1` |
| `sdc-m` | `bench/corpora/sdc/sdc-m` | `bench/qrels/sdc/sdc-v1`; `--judgment-set` names a top-up version when required |

The SDC loader implements SPEC-0004 §4.3–§4.7 exactly:

1. Parse `manifest.json`; require `schema_version = 1`, five expected sidecars,
   a valid canonical `corpus_hash`, and all file/sidecar hashes.
2. Parse `corpus.jsonl`, `passages.jsonl`, `extraction-truth.jsonl`,
   `duplicate-clusters.jsonl`, and `versions.jsonl`; validate schema, ordering,
   cross-references, UTF-8 offsets, booleans/enums, and target hashes.
3. Parse only the selected split files from a `judgment-set.json` whose
   `state = "frozen"`, whose `file_sha256` and `query_file_sha256` match, whose
   `compatible_corpus_hashes` contains the corpus hash, and whose provenance is
   `verified` or `adjudicated` with nonempty `verified_by`. Draft/rejected
   records are never benchmark-eligible.
4. Apply `EvaluationConfiguration::Default`: omit all `source_code` rows and
   select only `configuration = "default"` queries. Apply `CodeEnabled`: include
   both file classes and all nine categories, while keeping `code_search`
   reported separately from the default weighted score.
5. Require every qrel's `document_text_sha256`/`passage_text_sha256`,
   evidence target, query ID, and split to resolve exactly. A mismatch is
   `HASH_MISMATCH`/`DANGLING_REFERENCE`, never a warning.
6. For `sdc-smoke-v1`, require no published test files and
   `test_exposure = "not-applicable"`. For other sets, a test split may load only
   under the confirmation workflow in §4.11.
7. Build deterministic duplicate families with union-find over every
   `exact_byte`, `exact_text`, `near_duplicate`, `version`, and
   `scanned_variant` cluster. Component key is the lexicographically smallest
   member ID; this has no relevance effect.

The loader returns `corpus_hash`, judgment-set manifest hash, query/qrel file
hashes, and the SPEC-0004 `judgment_set_id`; reports use these exact values.
For every dataset, `query_set_sha256` is SHA-256 over canonical JSON of the
selected query records sorted by ID, including id, text, language,
target_languages, language_slice, category, configuration, split, and filters.
For SDC, `fingerprint = SHA-256(canonical {corpus_hash, judgment_set_id,
judgment_set_hash, query_set_sha256})`; for BEIR it is the file-based value in
§4.2. Comparisons require equal fingerprints.

#### BEIR-layout datasets

A BEIR manifest is `bench/datasets/<dataset-id>/manifest.json`:

```json
{
  "schema_version": 1,
  "dataset_id": "example-beir",
  "layout": "beir",
  "visibility": "public",
  "license": {
    "id": "Apache-2.0",
    "url": "https://example.invalid/license",
    "redistribution": "download-only",
    "terms_url": "https://example.invalid/terms"
  },
  "source": {
    "revision": "immutable-upstream-revision",
    "urls": ["https://example.invalid/immutable/archive"],
    "sha256": ["<64 lowercase hex characters>"]
  },
  "corpus": "data/corpus.jsonl",
  "files_root": "data/files",
  "splits": {
    "dev": {
      "queries": "data/queries.dev.jsonl",
      "qrels": "data/qrels.dev.tsv"
    },
    "test": {
      "queries": "data/queries.test.jsonl",
      "qrels": "data/qrels.test.tsv"
    }
  },
  "query_defaults": {
    "language_slice": "en",
    "category": "conceptual",
    "configuration": "default"
  },
  "transform": {
    "script": "tools/dataset-fetch",
    "version": 1,
    "seed": "dataset-transform-v1"
  },
  "local_file_sha256": {
    "data/corpus.jsonl": "<64 lowercase hex characters>",
    "data/queries.dev.jsonl": "<64 lowercase hex characters>",
    "data/qrels.dev.tsv": "<64 lowercase hex characters>",
    "data/queries.test.jsonl": "<64 lowercase hex characters>",
    "data/qrels.test.tsv": "<64 lowercase hex characters>",
    "data/files/<document-id-sha256>.txt": "<64 lowercase hex characters>"
  }
}
```

`example.invalid` is illustrative. `visibility` is `public` or `private`;
`redistribution` is `download-only` for all non-redistributable evaluation
data. Each local file hash must match on load; the manifest is never edited by
the loader. The dataset fingerprint is SHA-256 over canonical JSON containing
the manifest without `local_file_sha256` plus the sorted `{path, sha256}` local
files, so a byte change changes the fingerprint.

`corpus.jsonl` rows are `{"_id": "...", "title": "...", "text": "..."}` plus
optional JSON `metadata`, in BEIR style. When `files_root` is present, every
row's `metadata.relative_path` names a UTF-8 file below it, and `text` is
exactly the file's normalized NFC/LF contents so offset mapping is exact. The
preparation tool materializes one `.txt` file per document under
`files_root/<sha256(document-id)>.txt`; corpus text is the retrieval
text (title handling is recorded by the transform). Without `files_root`, the
dataset is usable only with external cached TREC runs, not `index`/`perf`.
Query rows are `{"_id": "...", "text": "...", "metadata": {...}}`; if present,
metadata keys `language`, `target_languages`, `language_slice`, `category`,
and `configuration` override manifest defaults. Qrels are UTF-8 TSV with header
`query-id	corpus-id	score`, one header row, three tab-separated columns,
integer scores 0–3, and no duplicate `(query,doc)` pair. An empty title is
allowed; empty text, blank IDs, duplicate query/document IDs, dangling qrels,
and unknown splits are rejected. CRLF is accepted and normalized. No gzip is
read directly: WP-1.5 normalizes downloads to plain UTF-8 JSONL/TSV.

BEIR has document judgments only; passage metrics are reported unavailable,
not zero. Duplicate metrics are likewise unavailable without a cluster file.
A manifest may add `duplicate_clusters` pointing to a SPEC-0004-compatible
JSONL file for a public dataset that declares labels.

#### Public-dataset preparation interface

WP-1.5 places an isolated Python 3.12 package under `tools/dataset-fetch/`.
It never ships and never computes retrieval metrics. Its dependencies are
hash-locked and license-checked under ADR-0022 even though the tool is not a
product artifact. From an activated environment at the repository root:

```text
python -m dataset_fetch prepare \
  --dataset <dataset-id> \
  --cache <download-cache> \
  --output bench/datasets/<dataset-id>/data

python -m dataset_fetch verify \
  --dataset <dataset-id> \
  --data-dir bench/datasets/<dataset-id>/data
```

`prepare` downloads only the manifest's declared source URLs into the cache,
verifies upstream terms/hashes and license eligibility for internal use,
decompresses, normalizes identifiers, constructs declared `dev`/`test` files,
and writes `dataset-lock.json` with the local file hashes and dataset
fingerprint. `verify` performs no network access and fails on any hash, license,
split, category, language, or transform mismatch. Bulk `data/` and cache
contents stay untracked; only manifests, notices, lock metadata, and scripts
are committed. If a source's terms are unclear or incompatible with internal
evaluation, preparation stops before download or transformation.

| Dataset IDs | Required mapping |
|---|---|
| `mldr-{lang}`, `miracl-{lang}` | Long-document/passage source splits; category `conceptual`, language slice from the source language; dev/test never fabricated from test by tuning |
| `mmarco-pt`, `mmarco-pt-en`, `mmarco-en-pt` | Portuguese monolingual and constructed cross-lingual pairs per the rules below |
| `quati-pt` | Only after the manifest records a confirmed license and permitted internal-evaluation use; otherwise absent |
| `beir-scifact`, `beir-nfcorpus`, `beir-fiqa`, `beir-trec-covid` | English domain-shift sanity checks; document-level judgments only; category `conceptual` unless a verified query override exists |

The transformations preserve source query/document IDs unless the manifest
declares a stable prefix. Constructed mMARCO Portuguese↔English queries use a
query ID `<source-query-id>-xl-pt-en` or `-xl-en-pt`, record both target
languages, and map the manifest-declared source relevance labels/triples to the
original document IDs. Category and language-slice mappings are explicit in
the manifest or per-query metadata; no language is guessed from content.

### 4.3 Runs and TREC interchange

The writer emits exactly:

```text
<query-id> Q0 <target-id> <rank> <score> <run-id>
```

- Fields are separated by one ASCII space; lines end in LF; file ends in one LF.
- `Q0` is literal. Query and target IDs are nonempty and contain no whitespace
  or control characters; their strings are opaque, not path or filename
  syntax. The reader resolves target type by exact lookup: a canonical passage
  ID means passage, otherwise a document ID means document; an ID that matches
  both or neither is an error.
- `rank` is a decimal integer 1–1000. For one query, ranks are strictly
  increasing and contiguous starting at 1. The rank, not score, defines order.
- `score` parses as a finite IEEE-754 f64; the writer uses a shortest
  round-trippable decimal. Nonfinite, `NaN`, `inf`, or exponent overflow is
  rejected.
- `run-id` matches `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` and is identical on
  every line of one file.
- A query with no results is omitted; it still counts as an evaluated query
  with all metrics at their zero convention. A run may omit no other query and
  may not contain a query outside the selected dataset split.
- The reader rejects duplicate `(query,target)` rows, repeated ranks, gaps,
  mixed run IDs or target types, unknown query or target IDs, and more than
  1000 rows per query. A file is either a document run or a passage run.
- A passage target must resolve to a canonical passage in the dataset. A
  chunk-mapped run is always converted to canonical SPEC-0004 passage IDs
  before writing. External Stage A runs use these exact canonical IDs.

`read_trec_run` is also the Stage A interchange: Python or reference-runtime
tooling writes a TREC run, and `seeky-eval` computes every metric. The metric
implementation never exists twice.

### 4.4 Metrics and aggregates

All metrics are computed per query first and then macro-averaged over the
eligible query set. A metric cutoff is in `1..=1000`; `--limit` must be at
least the largest requested cutoff. The default metric selection is nDCG@10,
MRR@10, Success@1, Recall@100, passage nDCG@10, DuplicateRate@10,
DistinctRelevant@10, SubtopicRecall@10, and α-nDCG@10 (α = 0.5); metrics that
the dataset cannot support are reported unavailable as specified below.

Let `rel(q,d)` be the integer 0–3 qrel grade, or 0 when the judged target is
absent. An absent judgment is treated as 0 for ranking metrics but remains
distinct in data and coverage reports.

| Metric | Definition |
|---|---|
| `nDCG@k` | `Σ_i rel(q,d_i)/log2(i+1)` for the first `min(k, returned)` results, divided by the same sum over all positive qrels for `q` sorted descending and truncated to `k`. Gain is the linear grade, the trec_eval `ndcg_cut` convention. If the ideal sum is 0, query value is 0. |
| `MRR@k` | Reciprocal rank of the first rank ≤ `k` with grade ≥ 1; 0 if none. |
| `Recall@k` | Number of distinct positive qrel targets among the first `k` unique targets divided by the number of distinct positive qrel targets. If the denominator is 0, query value is 0. |
| `Success@k` | 1 if any target in the first `k` has grade ≥ 1, else 0. |
| `DuplicateRate@k` | Over the first `k` unique document IDs, `redundant / returned`, where the first encountered member of a duplicate-family component is not redundant and every later member is redundant. If `returned = 0`, value is 0. |
| `DistinctRelevant@k` | Count of distinct positive `subtopic_labels` on grade ≥ 1 retrieved documents in the first `k`; labels are unioned, not summed. |
| `SubtopicRecall@k` | `DistinctRelevant@k / total_positive_subtopics`; query value 0 if the denominator is 0. |
| `α-nDCG@k` | Binary subtopic novelty with `α = 0.5`, as defined in §5.2. Query value 0 if ideal α-DCG is 0. |

Duplicate rate uses union-find families from all SPEC-0004 cluster kinds. The
duplicate-heavy slice is the set of queries with at least one positive judged
document in a nontrivial family; its query IDs and count are recorded. If no
clusters exist, duplicate metrics are `unavailable`, not 0.

Diversity metrics are meaningful only for `exploratory` queries whose verified
judgments have positive subtopic labels. `seeky-eval` returns
`UNSUPPORTED_METRIC` if they are requested for a query set lacking labels.
`non_latin_non_regression` queries are reported separately and never enter the
weighted primary score.

Document ranking deduplicates repeated document IDs before metric computation.
Passage ranking follows §5.1. Macro averages use all selected queries,
including those whose zero convention is defined above, and report
`queries_without_positive` separately.

Aggregates are:

- `macro`: arithmetic mean of per-query values.
- `category`: macro within each `QueryCategory`, including `code_search` only in
  a code-enabled evaluation.
- `language`: macro within each `LanguageSlice`, reported separately.
- `weighted_primary`: `0.35*Pt + 0.35*En + 0.15*CrossLingual + 0.15*Other`
  of macro nDCG@10 over `configuration = default` queries. All four slices must
  be present; missing slices are an error, never reweighted. In a code-enabled
  evaluation it is still computed over the same eight default-configuration
  categories, so its change reflects retrieval/index pollution; code results
  remain separate.
- `default` evaluation contains the eight non-code categories. `code_enabled`
  evaluation contains all nine and reports `code_search` and its comparison
  separately; code results never enter the weighted primary or the WP-1.8 gate.
- Report points are `100 * ratio`. A drop is
  `100 * (baseline_ratio - candidate_ratio)`.

Requirements Q2 and Q7 compare category/language or duplicate/diversity slices
using the same paired machinery; no raw score is compared across modalities or
different embeddings.

### 4.5 Paired statistics

`StatsOptions` requires `seed = "seeky-eval-v1"` unless a caller supplies a
nonempty printable ASCII seed of at most 64 bytes, `resamples = 10_000`, and
`alpha = 0.05`. The deterministic random primitive is the one specified in
SPEC-0004 §4.4, repeated here so statistics have no RNG dependency:

```text
D = SHA-256(UTF8("SDC1\0" + seed + "\0" + purpose + "\0" + stable_key))
x = unsigned_big_endian_u64(D[0..8])
u = x / 2^64
```

For each metric and paired query ID set:

- **Randomization (primary p-value).** For resample `b = 0..9_999`, draw sign
  `s_i = -1` when `U("paired-randomization", "<b>:<query_id>") < 0.5`, else
  `+1`; compute the weighted mean of `s_i * (candidate_i - baseline_i)` using
  the same language-slice weights as the metric. Let `n_extreme` count
  resamples whose absolute value is at least the absolute observed difference.
  Two-sided `p = (1 + n_extreme) / (10_000 + 1)`.
- **Paired bootstrap (95% CI).** For resample `b`, for each sorted query
  position `i`, choose index `floor(U("paired-bootstrap", "<b>:<i>") * n)`,
  preserving whole query pairs. Recompute the metric/weighted difference on the
  resample. The CI is the 2.5th/97.5th percentile by type-7 linear
  interpolation over 10,000 sorted resample values. For the weighted primary,
  resample within each language slice and reapply the fixed slice weights.
- **Significance.** A difference is significant only if two-sided `p < 0.05`
  and the 95% CI excludes zero. If they disagree, the result is
  `inconclusive`; a difference inside the CI is a tie.
- **Holm.** For a family of `m` candidate comparisons sorted by raw p and then
  stable comparison ID, adjusted `p_(i) = max_{j≤i} min(1,
  (m - j + 1) * p_(j))`.
- **Paired input validation.** Query IDs and slice/category assignments must be
  identical; differing metric cutoffs, datasets, or splits fail. Input metric
  values are the already computed ratios, not rounded report values.

Latency bootstrap uses the same primitive with purposes
`latency-bootstrap` and keys `"<b>:<sample-index>"`; the resample statistic is
the requested percentile. It is not a paired quality test. The S5
interference-ratio interval resamples the idle and indexing sample sets
independently with the same purpose and keys `"idle:<b>:<sample-index>"` and
`"indexing:<b>:<sample-index>"`; the resample statistic is
`p95(indexing) / p95(idle)`.

### 4.6 Report JSON

`results.json` is one versioned `Report` object. `kind` is `quality`,
`performance`, `comparison`, or `smoke_gate`; exactly one primary payload is
present, except a comparison may carry a pointer to both source results.

```json
{
  "schema_version": 1,
  "run_id": "2026-11-27T120000Z-sdc-smoke-q7a6b",
  "kind": "quality",
  "generated_at": "2026-11-27T12:00:00Z",
  "report": {
    "work_package": "WP-1.2",
    "spec": "SPEC-0003",
    "area": "quality",
    "title": "SDC smoke baseline",
    "hypothesis": "The candidate preserves default-pipeline quality",
    "gate_ids": ["WP-1.8"]
  },
  "tool": {
    "name": "seeky-bench",
    "version": "0.1.0",
    "eval_version": "0.1.0"
  },
  "commit": {"sha": "<40-60 lowercase hex>", "dirty": false},
  "environment": {},
  "dataset": {
    "id": "sdc-smoke",
    "split": "dev",
    "configuration": "default",
    "corpus_hash": "<sha256>",
    "fingerprint": "<sha256>",
    "judgment_set_id": "sdc-smoke-v1",
    "judgment_set_hash": "<sha256>",
    "query_count": 40,
    "query_set_sha256": "<sha256>",
    "visibility": "public"
  },
  "system": {
    "system_id": "lexical-b0",
    "config_hash": "<sha256>",
    "models": [],
    "provider": "cpu"
  },
  "command": ["seeky-bench", "eval", "--corpus", "sdc-smoke"],
  "quality": {
    "filter_mode": "post",
    "macro": {
      "ndcg_10": 0.0,
      "mrr_10": 0.0,
      "recall_100": 0.0,
      "success_1": 0.0,
      "passage_ndcg_10": 0.0
    },
    "weighted_primary": 0.0,
    "slices": {},
    "categories": {},
    "duplicate": {"duplicate_rate_10": 0.0, "query_count": 0},
    "diversity": {"alpha_ndcg_10": 0.0, "query_count": 0},
    "queries_without_positive": 0,
    "unmapped_chunks": 0,
    "per_query": [],
    "warnings": []
  },
  "performance": null,
  "comparisons": [],
  "gates": [],
  "decision": {"status": "not-applicable", "text": "Benchmark evidence only"},
  "artifacts": {
    "run": "run.trec",
    "passage_run": "run.passages.trec",
    "config_snapshot": "config.snapshot.json",
    "environment": "environment.json",
    "checksums": "checksums.sha256"
  }
}
```

The JSON above is structural; its `0.0` and empty values are placeholders, not
measurements. Required semantics for fields beyond this example:

| Path | Type/rule |
|---|---|
| `generated_at`, `run_id` | RFC 3339 / unique run identifier; never derived from user content |
| `report.*` | Work package, spec, area, short title, hypothesis, and gate IDs that supply the template header; bounded plain text, never corpus content |
| `tool.*`, `commit.sha`, `commit.dirty` | Actual tool versions and repository state; clean required for confirming/smoke reports |
| `environment` | Object from §4.9; no hostname, user, or absolute path |
| `dataset` | Exact hashes and split/configuration; per-query coverage fields |
| `system.models` | Ordered list of `{id, task, variant, sha256, provider}` or empty |
| `quality.filter_mode` | `none`, `pushdown`, or `post`; records whether structured metadata filters were applied by retrieval or to returned hits |
| `quality.macro` | `ndcg_10`, `mrr_10`, `recall_100`, `success_1`, plus optional passage/snippet metrics; `null` only where the dataset makes the metric unavailable |
| `quality.weighted_primary` | Exact §4.4 weighted value over the eight default-configuration categories; code-enabled runs report the same eight-category subscore plus separate code metrics |
| `quality.slices` | Map of `language` / `category` / `configuration` groups, each with query count and metrics |
| `quality.per_query` | Local/public only; list of `{query_id, category, language_slice, metrics}` sorted by query ID; never query text |
| `performance` | The object in §4.10 or null |
| `comparisons` | Baseline/candidate IDs, paired query count, seed, per-metric `{delta, delta_points, ci95, p_value, holm_p, significance}`; no raw private content |
| `gates` | List of `{id, status, threshold, observed, details}` with status `pass`, `fail`, `not-applicable` |
| `decision` | `adopt`, `reject`, `inconclusive`, or `not-applicable`, plus bounded text; a harness never invents a bake-off ADR decision |
| `artifacts` | Relative filenames and digests only; no absolute paths |

For `visibility = "private"`, per-query rows, run target IDs, and any local
artifact references are omitted from committed report JSON; only aggregate
metrics, query counts, and hashes remain. The local run may retain opaque IDs
but never content or paths.

### 4.7 Markdown report

`write_report_markdown` follows
[`_report-template.md`](../benchmarks/_report-template.md) exactly:

```text
# <YYYY-MM-DD> — <area>: <short title>

| Field | Value |
|---|---|
| Work package / spec | <WP-x.y> / <SPEC-NNNN> |
| Hypothesis | <hypothesis> |
| Gate(s) | <gate IDs> |
| Decision | <adopt/reject/inconclusive/not-applicable> |
| Commit | `<sha>` |
| Config hash | `<sha256>` |
| Hardware tier | <tier plus environment reference> |

## 1. Setup
## 2. Results
### Quality
### Performance
### Pareto view
## 3. Analysis
## 4. Decision and follow-ups
## 5. Reproduction
```

Quality writes a system table ordered baseline first with weighted nDCG@10 and
the pt/en/cross-lingual/other columns, Recall@100, MRR@10, then per-category
rows and paired differences with 95% CIs and p-values. A missing slice/metric
is `—`; the writer must not turn `null` into 0. Performance uses the S1/S2/S3,
passages/s, RSS idle/peak, disk/1M, download columns; missing values are `—`.
The Pareto section names `pareto.svg` only when that file exists, otherwise
`Not generated`. Analysis uses query IDs, never query/document text. Decision
uses the methodology rule and records an ADR only when a report owner did so;
the writer never asserts a decision absent from `results.json`.

The Markdown writer escapes `|`, backslashes, and newlines in scalar values,
formats percentages as points with three decimals, p-values with six
significant digits (or `<0.000001`), and hashes in full. Its output is
deterministic for the same report object. A golden fixture in §5.8 verifies
every heading and row label.

### 4.8 `seeky-bench` commands and flags

All commands require `--output <dir>` except `report`, accept
`--seed <string>` (statistics only), and emit exit code 0 only on success.
`eval`, `perf`, and `compare` also accept `--work-package <WP-x.y>`,
`--spec <SPEC-NNNN>`, `--area <text>`, `--title <text>`,
`--hypothesis <text>`, and repeatable `--gate-id <id>` to fill the template
metadata; defaults are `area` = corpus/dataset ID, `title` = run type plus
split/configuration, `work_package`/`spec` = the implementing WP/SPEC, and an
empty hypothesis. Paths in commands are reported as repository-relative when
under `<repo>`; external data directories are rendered as
`<data-dir>`/`<cache>`.

| Command | Required flags and behavior |
|---|---|
| `index` | `--corpus <id> --data-dir <dir> --config <path> [--code-enabled] [--fresh]`. Adds the dataset roots, indexes headlessly, disables watching, waits for each enabled capability (lexical always; semantic when configured), and writes `<output>/index.json` plus a run summary. `--fresh` is required to reuse a nonempty data directory. |
| `eval` | `--corpus <id> --split <dev\|test> --config <path> --data-dir <dir> [--judgment-set <id>] [--system-id <id>] [--limit <1..=1000>] [--code-enabled] [--purpose <screen\|deploy\|confirm>] [--confirmation <path>] [--baseline <results.json>] [--require-clean]`. Default `--limit` is 100; `--system-id` defaults to the config hash prefix. Dev defaults to `screen`; test requires `confirm`, `--confirmation`, clean tree, and §4.11. |
| `perf` | `--corpus <id> --config <path> --data-dir <dir> [--suite <search,embedding,indexing,interference,resources,startup,all>] [--stage <single\|instant\|hybrid\|refined>] [--repetitions <n>] [--queries <n>] [--tier <T0\|T1\|T1-emulated\|T2>] [--cpus <list>] [--memory-limit <bytes>] [--code-enabled]`. `--split` is always `dev`; test is rejected. Defaults are `--suite all`, `--stage single`, 30 repetitions, all dev queries up to 1,000, and the tier detected from the environment. `--tier T1-emulated` requires documented CPU affinity and memory cap. |
| `compare` | `--baseline <results.json> --candidate <results.json> [--candidate <results.json> ...] [--repeat-candidate <results.json>] [--gate <wp1.8>] [--baseline-commit <sha>] [--output <dir>] [--seed <seed>]`. No engine is opened. One or more candidates form one Holm family; `--gate wp1.8` requires exactly one candidate, its repeat input, and the current main SHA. |
| `report` | `--results <results.json> --output <summary.md> [--overwrite]`. Reads only report JSON and writes Markdown. |

Common defaults and rules:

- Built-in corpora are `sdc-smoke`, `sdc-s`, and `sdc-m`. Any other corpus ID
  must resolve to a committed `bench/datasets/<id>/manifest.json`.
- `--code-enabled` is rejected for BEIR datasets that do not declare a code
  root, and for SDC smoke it produces a separate code-enabled report; the
  default and code-enabled queries/roots are never mixed.
- `--purpose screen` or `deploy` is valid only with `--split dev`. `--purpose
  confirm` with `--split dev` is a dry validation of confirmation metadata only;
  it never touches test.
- `--limit` must be at least the largest requested metric cutoff; otherwise
  the command fails with `INSUFFICIENT_DEPTH`.
- A corpus path or dataset manifest cannot point into a user's home by default;
  private-corpus support is explicit and redacted, never a default.
- No command accepts a query, document, or path typed by the webview.

### 4.9 Environment, configuration hash, and artifacts

`environment.json` contains only:

```json
{
  "schema_version": 1,
  "captured_at": "2026-11-27T12:00:00Z",
  "os": {"family": "windows", "version": "...", "build": "...", "arch": "x86_64"},
  "cpu": {
    "vendor": "...",
    "model": "...",
    "physical_cores": 8,
    "logical_cores": 16,
    "features": ["avx2", "avx512f", "vnni"]
  },
  "memory_bytes": 17179869184,
  "power": {"source": "ac", "plan": "..."},
  "tier": "T1-emulated",
  "emulation": {"logical_cpus": [0, 1, 2, 3], "memory_limit_bytes": 8589934592},
  "runtime": {"rustc": "...", "seeky_version": "...", "ort_version": null},
  "devices": {"npu": null, "gpu": null},
  "quiet_window": {"verified": true, "heavy_processes": []},
  "process": {"scope": "engine_headless", "sampling_interval_ms": 50}
}
```

`quiet_window.heavy_processes` names only process classes (`cargo`, `rustc`,
`node`, `python`, `other-benchmark`) and never command lines. The `tier` is
exactly `T0`, `T1`, `T1-emulated`, or `T2`. When a device is present, its
`npu`/`gpu` object records `name`, `vendor`, `driver_version`,
`runtime_version`, and `memory_bytes`; absent devices are `null`. The capture
never contains hostname, user name, home directory, database path, absolute
corpus path, document content, file name, or query text. Missing optional
OS/device facts are `null`; they are never fabricated. Commit SHA, config hash,
dataset hashes, and model hashes are recorded in the report/dataset/system
sections, not duplicated as untrusted environment strings.

The semantic config snapshot is canonical JSON of every setting that can affect
ranking or measured performance: provider/EP and thread counts, session and
batch settings, model IDs/revisions/quantized variant hashes and preprocessing,
chunker/input recipe, lexical/filename/vector settings, fusion/ranking/stage
toggles and weights, candidate/document limits, diversity/dedupe settings,
`code_enabled`, evaluation result depth, metric cutoffs, and seed. It excludes
data/output paths, resource-dir paths, temp/cache roots, credentials,
timestamps, and logging destinations. `config_hash = SHA-256(canonical_json(snapshot))`.
Model files, when present, are also hashed; model IDs alone are insufficient.

Artifacts are written atomically under `<output>/`:

```text
results.json                 validated report object
summary.md                   deterministic Markdown
run.trec                     eval document run only
run.passages.trec            eval passage run only, when supported
environment.json             captured environment
config.snapshot.json         canonical semantic config
checksums.sha256             SHA-256 of every artifact, paths relative
index.json                   index command only
exposure.json                test eval only, append-only record
```

A directory is created only after input validation; a failed command leaves a
previous artifact directory unchanged. `checksums.sha256` includes all files
except itself, sorted by path. Raw runs larger than a few MB stay outside the
repository and are referenced by hash and regeneration command.

### 4.10 Performance report

`performance` contains the following fields plus `qualifies_for_budget` and
`tier`. A required metric that was not measured is null with a warning, never
a fabricated zero. Required Phase 1 shape:

```json
{
  "tier": "T1-emulated",
  "qualifies_for_budget": false,
  "search": [
    {
      "stage": "single",
      "condition": "warm_idle",
      "queries": 1000,
      "repetitions": 1,
      "latency_ms": {
        "p50": 0.0, "p95": 0.0, "p99": 0.0,
        "ci95": {"p50": [0.0, 0.0], "p95": [0.0, 0.0], "p99": [0.0, 0.0]}
      }
    }
  ],
  "query_embedding": {
    "batch": 1, "samples": 1000,
    "latency_ms": {
      "p50": 0.0, "p95": 0.0, "p99": 0.0,
      "ci95": {"p50": [0.0, 0.0], "p95": [0.0, 0.0], "p99": [0.0, 0.0]}
    }
  },
  "indexing": {
    "files_per_s": 0.0, "extract_mb_per_s": 0.0,
    "passages_per_s": 0.0, "provider": "cpu", "samples": 0
  },
  "time_to_searchable": {
    "lexical_ms": {"samples": 0, "p50": 0.0, "p95": 0.0},
    "semantic_ms": {"samples": 0, "p50": 0.0, "p95": 0.0}
  },
  "interference_ratio": {
    "value": 0.0, "idle_p95_ms": 0.0, "indexing_p95_ms": 0.0,
    "ci95": [0.0, 0.0]
  },
  "resources": {
    "idle_rss_bytes": 0, "peak_rss_bytes": 0, "page_cache_bytes": null,
    "index_bytes": 0, "disk_bytes_per_1k_passages": 0.0,
    "scope": "engine_headless", "sampling_interval_ms": 50
  },
  "startup": {
    "cold": true, "os_cache": "uncontrolled",
    "instant_capable_ms": 0.0, "semantic_capable_ms": null
  },
  "distribution": null,
  "ocr": null,
  "visual": null,
  "energy": null
}
```

The JSON above is a shape example; its numeric values are placeholders, not
measurements. Each search row maps its `stage` to the methodology budget: `single` is
end-to-end v1 search and is not labeled S1/S2/S3; when the engine exposes
progressive updates, rows use `instant`, `hybrid`, and `refined` and may claim
S1/S2/S3. `condition` is `warm_idle`, `warm_indexing`, or `cold`; cold means a
fresh process with the existing index, and `os_cache` records whether the page
cache was controlled. Percentiles use type-7 interpolation. Sample criteria:
at least 1,000 query executions per stage or at least 30 repetitions of a fixed
set; otherwise `qualifies_for_budget` is false. CI resamples are 10,000 with the
fixed seed.

Methodology §3.2 fields are reported as follows: stage latency, query-embedding
latency, indexing throughput (extraction files/MB, embedding passages),
time-to-searchable (single-file and bulk), interference ratio, idle/peak RSS
(engine headless scope; webview-inclusive R1 remains a shell measurement),
disk bytes per 1k passages and total index bytes, cold startup to Instant and
semantic capability, distribution sizes when a package exists, OCR/visual
throughput only when their packs exist, and energy only where measurable.
`disk_bytes_per_1k_passages = index_bytes * 1000 / passage_count`; a zero
passage count is a typed error. Index bytes are the benchmark data directory
excluding source files and report artifacts. Unavailable optional fields are
null with `warning`, never zero.

`perf` measures on one tier only and never compares runs from different tiers.
The quiet-window check records process classes; a failing check marks the run
exploratory. `--repetitions` affects the fixed-set repetition count, not the
query count. Perf uses `dev` queries only and never loads `test`.

### 4.11 Test confirmation and exposure

A confirmation file is immutable JSON:

```json
{
  "schema_version": 1,
  "confirmation_id": "<unique-id>",
  "created_at": "2026-11-27T12:00:00Z",
  "selected_on": "dev",
  "dev_comparison_sha256": "<sha256 of the dev comparison JSON>",
  "dataset": {
    "id": "sdc-s",
    "corpus_hash": "<sha256>",
    "judgment_set_id": "sdc-v1",
    "judgment_set_hash": "<sha256>"
  },
  "split": "test",
  "systems": [
    {"system_id": "baseline", "config_path": "bench/configs/b0.toml", "config_hash": "<sha256>", "role": "baseline"},
    {"system_id": "candidate-a", "config_path": "bench/configs/a.toml", "config_hash": "<sha256>", "role": "candidate"},
    {"system_id": "candidate-b", "config_path": "bench/configs/b.toml", "config_hash": "<sha256>", "role": "candidate"}
  ],
  "gates": ["Q1", "Q2"],
  "evaluation": {
    "limit": 100,
    "metrics": ["ndcg_10", "mrr_10", "recall_100", "success_1"],
    "seed": "seeky-eval-v1"
  }
}
```

`systems` has exactly one baseline and at most two candidates; all rows use the
same dataset/query membership, and config hashes are recomputed from the
effective config before each system runs. Confirmation is created only from a
completed dev comparison whose hash matches. Baseline/result IDs and config
paths are opaque relative or repository paths; no test query content is copied
into it. One `eval` invocation executes exactly one declared system selected by
`--config`; the confirmation is complete only after one successful evaluation
of every declared system. Each invocation uses its own `--output`, must match a
declared config hash, and appends a system-level ledger row; `--baseline`,
`--judgment-set`, `--code-enabled`, and non-confirmation metric/seed settings
are rejected for test runs. The confirmation fixes `--limit`, metric selection,
and seed in its hash and all systems use the same values.

For every dataset, before the first test operation `seeky-bench`:

1. Acquires an exclusive lock on the frozen judgment set/split files.
2. Validates the SPEC-0004/hash or BEIR manifest, the confirmation's
   dataset/judgment hashes, its unique confirmation ID, its system list, and
   the append-only `bench/exposures/<dataset-id>.jsonl` history.
3. Appends a row to that history and writes `exposure.json` with
   `state = "started"`, confirmation ID and SHA-256, system config hashes, and
   timestamp.
4. If this is the dataset's first-ever test exposure, atomically replaces
   `judgment-set.json` with only `test_exposure` changed to `"exposed"`;
   fsyncs the file and directory. A later confirmation records a new ledger
   row but never rewrites `test_exposure`.
5. Runs only the declared systems and records `state = "completed"` after all
   systems succeed.

If a run fails after exposure, only resumption under the same confirmation ID
and same config hashes may finish missing systems; a new candidate, changed
config, or new confirmation is rejected. A completed confirmation is never
rerun. The append-only ledger is the authority for which configurations saw
test and in what order; deleting or editing a row fails validation. For SDC,
the first exposure additionally follows the SPEC-0004 `test_exposure` field.
`report`/`compare` read already produced results and never acquire test data or
rerun search. Test query text, qrels content, and per-query values are never
written to logs or a committed public report.

## 5. Behavior details

### 5.1 Query execution and canonical passage mapping

Queries are sorted by `query_id` before execution. For each query,
`seeky-bench` calls `Engine::search` with `SearchRequest.limit = --limit` and
the frozen config. It must receive an ordered hit list; results are never
sorted by score, which can be rounded. A returned hit beyond the requested
limit or a duplicate chunk is an engine-contract error.

Document runs map `SearchHit.path` to a dataset document only by normalizing
separators, stripping the configured corpus-root prefix, and requiring the
result to be a `metadata.relative_path` for the selected configuration. A path
outside the root or a missing path is an error; the path is never included in
the report. The document ID is the SPEC-0004 or BEIR `_id`.

When the Engine API has no filter pushdown, `seeky-bench` applies the query's
`extensions`, `modified_after`/`modified_before`, `folder_prefix`, and
`min_bytes`/`max_bytes` predicates to the returned document metadata with the
SPEC-0004 inclusive/exclusive rules, records `filter_mode = "post"`, and never
drops a filter silently. Let `available_depth = min(requested_limit,
documented_engine_max_depth)`. If the raw hit count equals `available_depth` and
filtering leaves fewer hits than the largest metric cutoff, the filtered list
might have omitted matching lower-ranked hits and the invocation fails
`INSUFFICIENT_DEPTH` rather than reporting a starved ranking as quality.
When the Engine supports pushdown, the same query is sent with filters and
`filter_mode = "pushdown"`. The current v1 capability gap and its resolved prerequisite are recorded in
§7.

For passage runs, a `SearchHit` carries chunk `start`/`end` character offsets,
a page when present, and a document ID/path. The adapter converts character
offsets to UTF-8 byte offsets in the canonical document text and computes
intersection length with every non-context SPEC-0004 passage on the same
document and page (when both have a page). It picks the passage with the
largest intersection; ties choose the smaller canonical `_id`. A zero
intersection yields no passage row and increments `unmapped_chunks`. This is
deliberately deterministic and independent of engine chunking; a chunk never
counts for two gold passages. If the canonical text/offset contract cannot
produce an exact mapping, the adapter fails with `UNSUPPORTED_METRIC` rather
than inventing a match.

Every query emits a TREC run row per unique document and per mapped passage,
using the best (smallest) rank for a repeated target; ranks are compacted
after deduplication. Document metrics use the document run; passage metrics use
the passage run. A document-only dataset reports passage metrics unavailable.
For external Stage A caches, the TREC file already contains canonical IDs and
is loaded directly, no chunk mapping.

### 5.2 Metric edge cases and implementation rules

- Grades are integers 0–3. Unjudged is absent, not grade 0; ranking uses 0 for
  unjudged and the loader never adds a synthetic qrel.
- nDCG gain is linear grade, matching `pytrec_eval-terrier`/trec_eval
  `ndcg_cut`; no exponential gain is mixed into a report. The ideal uses every
  positive qrel, including an unretrieved one.
- Distinct target IDs are counted once. Duplicate rows are rejected before
  evaluation; mapped passage duplicates keep the best rank.
- Query-level zero conventions are explicit: nDCG/MRR/Recall/Success/
  DuplicateRate all use 0 when the corresponding ideal, relevant, or returned
  count is 0. `queries_without_positive` and coverage counters make this
  visible.
- `DistinctRelevant@k` and `SubtopicRecall@k` use positive labels only. A
  subtopic covered by multiple documents counts once. Non-exploratory data has
  no diversity values, not zero.
- α-nDCG: for a positive document at rank `i`, let `L_i` be its verified
  distinct labels and `c_s(i)` the number of earlier positive documents that
  also carry label `s`. Its gain is
  `Σ_{s∈L_i} (1-α)^{c_s(i)}`; the discounted value is divided by
  `log2(i+1)`. The ideal uses all positive judged documents: at each rank,
  choose the remaining document with maximal immediate gain, breaking ties by
  higher grade and then lexicographically smaller document ID. The reference is
  checked against `ir-measures==0.4.3` with `pyndeval==0.0.8`, which binarizes
  positive subtopic labels; the two implementations must agree on the fixture.
- `weighted_primary` uses only nDCG@10 and only default configuration. Every
  required language slice must exist; no silent reweighting. `code_search`,
  code-enabled roots, and visual categories never enter it.
- Duplicate families are computed once from validated clusters. A query with no
  positive judged document in a nontrivial family is excluded from the
  duplicate-heavy slice and its query count is reported.
- Aggregates are macro over queries. Category and language slices are not
  weighted by their size. The weighted primary is the only cross-language
  weighted score.
- Rounding occurs only at the Markdown/display layer; JSON and statistics use
  IEEE-754 values and paired inputs are never rounded.

### 5.3 Statistics reference values and algorithm

Given paired differences for query IDs `q01`…`q08`:

```text
0.00, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.16
```

with `seed = "seeky-eval-reference-v1"`, 10,000 resamples, and uniform query
weights, the normative output is:

| Value | Expected |
|---|---:|
| Observed mean difference | 0.0725 |
| Randomization extreme count | 155 |
| Two-sided randomization p | 0.015598440155984402 |
| Bootstrap 95% CI | [0.0400, 0.1075] |
| Significance at α = 0.05 | significant |

The bootstrap uses type-7 percentiles; the randomization uses the key
`"<resample>:<query_id>"`; the bootstrap uses `"<resample>:<position>"` with
positions in the sorted query order. A test that changes seed, resample count,
query order, or formula must change these values. For a weighted metric,
resampling happens within each language slice before applying the fixed
weights.

Holm reference: raw p-values `cand-a=0.04`, `cand-b=0.01`, `cand-c=0.03`,
family size 3, sort ascending as `cand-b, cand-c, cand-a`; adjusted values are
`cand-b=0.03`, `cand-c=0.06`, `cand-a=0.06`. The final adjustment is the running
maximum, never a value below the previous adjusted p-value.

### 5.4 Test-split state machine

```text
dev: draft -> split_frozen -> frozen -> screen/deploy evaluations

test first use:
  frozen + unexposed + confirmation-1(dev comparison) -> started ->
  test evaluations (declared systems only) -> completed; test_exposure=exposed

test later independent decision:
  confirmation-2(dev comparison) -> new append-only ledger row ->
  test evaluations (declared systems only) -> completed
```

A test command fails before loading engine data if the tree is dirty, the
confirmation is absent/stale/completed, the judgment set is not frozen, the
ledger and manifest history disagree, the confirmation has more than two
candidates, or a declared system is missing. The first-ever use changes only
`test_exposure`; subsequent confirmations append ledger rows and never rewrite
that field. Exposure is conservative: if the process crashes after the started
record, the incomplete confirmation cannot be bypassed; only its missing
systems may resume with exact config hashes. A later independent confirmation
must still be selected solely from dev and is recorded before its first query.
Independent decision families may reuse the same frozen test set through
separate confirmations; that is a deliberate Stage C reuse and is visible in
the ledger, but no completed confirmation or tuning run may be repeated.
Only `seeky-bench` writes exposure records; no manual edit is accepted, and a
changed `test_exposure` or ledger without a matching transition fails
validation.

### 5.5 Performance measurement protocol

1. Open the existing compatible index and set watching off for search-only
   suites. For indexing/interference, create a fresh temporary data directory,
   add the corpus root, and start the indexing operation.
2. Discard a warm-up pass over the first fixed-set repetition. Measure with a
   monotonic clock around the engine call/stage update, recording one sample per
   query execution. Do not subtract report I/O or process startup from search
   latency.
3. For warm-idle, no benchmark indexing runs. For warm-indexing, start bulk
   indexing first, confirm progress is active, then run the identical query
   set; compute `S5 = p95(indexing) / p95(idle)` and fail/omit if idle p95 is 0.
4. For time-to-searchable, use a temporary copy/small fixture, write one changed
   file of ≤1 MB (when the budget says so), and stop at the first successful
   target search for lexical and semantic capability; for bulk, use the
   engine's coverage/status signal, not a fixed sleep. Record debounce and
   queue state.
5. For query-embedding latency, call the embedder path directly through the
   engine/inference adapter with batch 1, separate from indexing throughput.
6. For resources, sample process RSS every 50 ms; report maximum sample as
   peak and the last idle sample after stabilization as idle. Exclude the
   corpus source and report/output tree from index bytes. Report page-cache
   bytes when the OS exposes them; otherwise null.
7. For startup, start a new process with an existing index, poll capability
   status until Instant and semantic capability, and record cold/warm OS-cache
   status. Webview-inclusive budgets require the shell's separate E2E run.
8. Validate tier and quiet window before measurement; record the exact
   command, commit, config hash, dataset hash, package/hashes, and engine
   process scope. Never compare a T1 number with a T2/T0 number.

### 5.6 WP-1.8 smoke gate

`compare --gate wp1.8` applies this algorithm:

1. Require `kind = "quality"`, split `dev`, configuration `default`,
   `dataset.id = "sdc-smoke"`, judgment set `sdc-smoke-v1`, clean
   baseline/candidate commits, identical corpus/judgment/config/query hashes,
   identical OS family/architecture/hardware tier, and a baseline commit equal
   to `--baseline-commit`.
2. Require all default non-code `dev` queries in `sdc-smoke-v1` (at least 40,
   five per each of the eight categories), all verified or adjudicated,
   no source-code document, no `code_search` query, and no draft/rejected
   provenance.
3. Compute the candidate's **macro nDCG@10 over those selected queries** (equal
   query weight). Report each of the eight category values and all available
   language slices for diagnosis; the gate threshold uses this macro.
4. `drop_points = 100 * (baseline_macro - candidate_macro)`. Pass iff
   `drop_points <= 1.0 + 1e-12` (the tolerance only absorbs binary floating
   representation, not a larger regression). A missing query, metric, or
   artifact is a fail, never a skip.
5. Apply the R31 ranking invariants and require `--repeat-candidate` to have
   identical query/target order and scores within `1e-9`. If a repeat run is
   deterministic except for a documented engine nondeterminism, the gate is
   `inconclusive` until the engine fixes it; it is never relaxed silently.
6. Emit a `gates` row `WP-1.8` with threshold `candidate macro nDCG@10 drop ≤
   1.0 point vs main`, observed drop, status, and artifact hashes. Code-enabled
   results are a separate report and never substitute for this gate.

The baseline is produced by the CI job on the current `main` commit and
candidate on the PR commit, both with the same lexical/default config; no
committed hand-edited baseline numbers are permitted. If WP-1.8 has not been
seeded with a clean main run, the gate fails closed.

### 5.7 Errors, atomicity, and logging

All commands validate inputs before engine open or output creation. Artifact
files are written to a temporary sibling directory and renamed atomically;
checksums and report JSON are written last. Exit codes are `0` success, `2`
usage/configuration, `3` dataset/judgment validation, `4` engine/index
unavailability, `5` statistics/report validation, and `6` gate failure. A
failed gate still writes the report with `status=fail` and nonzero exit.

Errors and logs name repository-relative paths or `<data-dir>`, never user
paths or content. `tracing` may contain counts, durations, query IDs, hashes,
and stage names; it must not contain query text, document titles, snippets, or
absolute paths. The binary owns stdout/stderr printing; the library uses typed
errors and tracing only.

### 5.8 Normative reference fixtures

All fixture IDs here are synthetic. The tests store them under
`crates/seeky-eval/tests/fixtures/reference-v1/` with `qrels`, `run.trec`,
`expected.json`, and a `README.md` header recording generation date, exact
tool/library versions, and the command that produced each expected value.

#### A. Standard metrics (`metrics-v1.json`)

Qrels:

```text
q1: d1=3 d2=1 d3=2 d4=0 d5=3
q2: d6=0 d7=0 d8=2
q3: d9=0
```

Run (rank order shown; scores are descending but rank is authoritative):

```text
q1: d2, d1, d3, d4
q2: d6, d7
q3: d9
```

Expected values (pytrec_eval-terrier 0.5.11, `ndcg_cut.10`, `recip_rank`,
`recall.10`, `success.1`; linear-gain nDCG; no-positive queries use 0):

| Metric | q1 | q2 | q3 | Macro |
|---|---:|---:|---:|---:|
| nDCG@10 | 0.615610074011697 | 0.0 | 0.0 | 0.205203358003899 |
| MRR@10 | 1.0 | 0.0 | 0.0 | 0.3333333333333333 |
| Recall@10 | 0.75 | 0.0 | 0.0 | 0.25 |
| Success@1 | 1.0 | 0.0 | 0.0 | 0.3333333333333333 |

nDCG q1 uses `3 + 3/log2(3) + 2/log2(4) + 1/log2(5)` in the ideal and
`1 + 3/log2(3) + 2/log2(4)` in the actual ranking. A report that uses
`2^rel - 1` does not match this fixture.

Weighted-primary reference: with macro nDCG@10 values `pt=0.8`, `en=0.6`,
`cross_lingual=0.4`, `other=0.2`, the expected weighted primary is
`0.35*0.8 + 0.35*0.6 + 0.15*0.4 + 0.15*0.2 = 0.58`. A ninth `code_search`
slice in a code-enabled run is not included; adding it must leave `0.58`
unchanged for the default score.

#### B. Duplicate rate (`duplicates-v1.json`)

For query `qdup`, rank `[a,b,c,d,e]`; duplicate families are `{a,b,c}` and
`{d,e}`. The first member of each family is kept, so `DuplicateRate@5 = 3/5 =
0.6`. For `qclean`, rank `[f,g]` with distinct families gives 0. The
duplicate-heavy macro is `0.3`. A document in several cluster kinds belongs to
the union-find component, never double-counted.

#### C. Diversity (`diversity-v1.json`)

For `qexp`, qrels are:

```text
dA=3 labels=[x], dB=2 labels=[x], dC=2 labels=[y],
dD=1 labels=[z], dE=3 labels=[y,z]
```

Run `[dA,dB,dC,dD]`, α=0.5, k=10. The expected values from the §5.2 formula,
cross-checked with `ir-measures==0.4.3`/`pyndeval==0.0.8`, are:

| Metric | Expected |
|---|---:|
| α-nDCG@10 | 0.6827811756998109 |
| `DistinctRelevant@2` | 1 |
| `DistinctRelevant@4` | 3 |
| `SubtopicRecall@2` | 0.3333333333333333 |
| `SubtopicRecall@4` | 1.0 |
| total positive subtopics | 3 |

`dE` is unretrieved but changes the ideal and therefore is required in the
fixture. The ideal greedy selection tie-breaks by grade, then document ID;
the fixture's value is also the exact permutation maximum.

#### D. Statistics and latency

Use the §5.3 eight-query differences for randomization/bootstrap. For the
latency arithmetic and CI fixture, observations `12,13,…,21` ms give
`p95 = 20.55 ms`; with the §4.5 primitive, seed
`seeky-eval-reference-v1`, purpose `latency-bootstrap`, and key
`"<resample>:<position>"`, the bootstrap 95% upper CI for p95 is `21.0 ms`.
An idle p95 of 20 ms and indexing p95 of 30 ms gives S5 interference ratio
`1.5`, exactly the threshold boundary. A resource fixture with
`index_bytes = 2_500_000_000` and `passage_count = 1_000_000` gives
`disk_bytes_per_1k_passages = 2_500_000` (§4.10 formula; 2,500 bytes per
passage). These values test arithmetic, schema, and
CI mechanics, not a hardware claim.

#### E. WP-1.8 boundary

For a smoke set containing 40 queries, a baseline macro value of 0.400000 and
candidate 0.390000 has a drop of exactly 1.0 point and passes; 0.389999 fails. A
candidate with a missing category, a code row, a draft qrel, or a second run
whose target order differs fails regardless of its score.

## 6. Acceptance

### 6.1 Tests to write first

Tests are hardware-free by default. Real models, PDFium, or NPU tests are
behind `hw-tests`; evaluator arithmetic and loader tests never need them.
Every test names or comments its requirement IDs and uses temporary
directories, fixed seeds, and no network.

| Test | Requirement IDs |
|---|---|
| `eval_public_api_exposes_dataset_run_metrics_and_report_types` | R1 |
| `eval_crate_has_no_engine_ui_or_tauri_dependency` | R1 |
| `beir_loads_reference_layout` | R2 |
| `beir_rejects_bad_header_duplicates_dangling_and_grades` | R2, R14 |
| `beir_duplicate_and_dangling_ids_are_rejected` | R2 |
| `beir_crlf_and_empty_titles_are_handled` | R2 |
| `beir_files_mapping_matches_corpus_text` | R2 |
| `sdc_smoke_loads_with_all_sidecars` | R3 |
| `sdc_rejects_stale_corpus_and_qrel_hashes` | R3, R4 |
| `sdc_rejects_draft_or_unverified_judgments` | R3, R21, R30 |
| `sdc_configuration_filters_documents_and_queries` | R3, R10 |
| `sdc_rejects_partial_or_extra_output_files` | R3, R14 |
| `graded_qrels_validate_evidence_and_hashes` | R4 |
| `explicit_zero_is_not_missing` | R4, R6 |
| `queries_without_positive_judgments_are_retained` | R4, R6 |
| `trec_run_round_trip_preserves_rank_and_scores` | R5 |
| `trec_reader_rejects_duplicates_gaps_nonfinite_and_unknown_ids` | R5, R14 |
| `duplicate_targets_and_rank_gaps_are_rejected` | R5 |
| `trec_rejects_mixed_target_types_and_run_ids` | R5 |
| `ndcg_matches_reference_values` | R6 |
| `document_metrics_match_reference_values` | R6 |
| `mrr_recall_success_match_reference_values` | R6 |
| Property: nDCG/Recall/Success values stay in their domains, an ideal run scores 1 when positive judgments exist, and adding an unretrieved positive judgment never increases nDCG | R6 |
| `chunk_overlap_maps_to_one_gold_passage` | R7 |
| `duplicate_chunks_keep_best_passage_rank` | R7 |
| `unmapped_chunks_are_counted` | R7 |
| `duplicate_rate_matches_reference_value` | R8 |
| `duplicate_slice_is_derived_from_judged_clusters` | R8 |
| `missing_clusters_report_metric_unavailable` | R8, R14 |
| `alpha_ndcg_matches_reference_value` | R9 |
| `distinct_and_subtopic_recall_match_reference_values` | R9 |
| `missing_subtopic_labels_are_typed_errors` | R9, R14 |
| `weighted_primary_matches_hand_calculation` | R10 |
| `default_aggregate_excludes_code_search` | R10, R30 |
| `code_enabled_aggregate_is_separate` | R10, R29, R30 |
| `missing_language_slice_is_not_silently_reweighted` | R10 |
| `randomization_and_bootstrap_match_fixed_seed_reference` | R11 |
| `paired_statistics_are_seed_reproducible` | R11 |
| `holm_adjustment_matches_reference` | R11 |
| Property: sign symmetry and paired query permutation do not change a randomization result | R11 |
| `report_json_round_trip_and_schema_validation` | R12 |
| `malformed_report_is_rejected` | R12 |
| `report_json_is_deterministic` | R12, R13 |
| `markdown_report_matches_golden` | R13 |
| `missing_measurements_are_not_invented` | R13 |
| `private_report_omits_per_query_and_paths` | R13, R22 |
| Fuzz JSONL/TSV/TREC/report readers with arbitrary bytes | R14 |
| `harness_never_panics_on_malformed_inputs` | R14 |
| `cli_exposes_all_five_subcommands_and_flags` | R15 |
| `unknown_or_conflicting_flags_fail_before_engine_open` | R15 |
| `config_hash_is_stable_and_path_independent` | R16 |
| `semantic_changes_change_config_hash` | R16 |
| `environment_capture_contains_no_user_or_private_path` | R16, R22 |
| `index_writes_metadata_and_disables_watching` | R17 |
| `index_reuses_only_compatible_data_directory` | R17 |
| `eval_rejects_mismatched_index_metadata` | R17, R18 |
| `eval_writes_complete_reproducible_artifact_set` | R18 |
| `eval_query_order_is_deterministic` | R18 |
| `eval_rejects_insufficient_result_depth` | R18, R29 |
| `compare_requires_compatible_runs` | R19 |
| `compare_writes_paired_statistics` | R19 |
| `compare_never_opens_engine` | R19 |
| `report_recomputes_nothing` | R20 |
| `report_requires_existing_results` | R20 |
| `report_overwrite_requires_flag` | R20 |
| `test_eval_requires_confirmation_and_clean_tree` | R21 |
| `test_exposure_is_written_before_first_query` | R21 |
| `test_rejects_new_or_modified_configs` | R21 |
| `completed_confirmation_cannot_rerun` | R21 |
| `later_confirmation_does_not_rewrite_test_exposure` | R21 |
| `test_resume_requires_same_confirmation_and_configs` | R21 |
| `test_never_loads_queries_in_index_or_perf` | R21, R28 |
| `dataset_manifest_requires_license_source_and_hashes` | R23 |
| `dataset_download_rejects_hash_or_terms_mismatch` | R23 |
| `public_dataset_transform_is_byte_deterministic` | R24 |
| `constructed_cross_lingual_pairs_are_stable` | R24 |
| `manifest_splits_categories_and_languages_validate` | R24 |
| `perf_latency_percentiles_match_reference` | R25 |
| `perf_bootstrap_ci_matches_fixed_seed_reference` | R25 |
| `undersampled_perf_is_marked_not_budget_eligible` | R25, R28 |
| `perf_indexing_and_embedding_metrics_are_present` | R26 |
| `time_to_searchable_uses_first_matching_result` | R26 |
| `interference_ratio_matches_hand_calculation` | R26 |
| `perf_resources_match_reference_fixture` | R27 |
| `perf_startup_marks_cold_and_scope` | R27 |
| `unavailable_optional_metrics_are_explicit` | R27 |
| `perf_rejects_tier_emulation_conflict` | R28 |
| `perf_records_tier_emulation_and_quiet_window` | R28 |
| `perf_budget_eligibility_is_explicit` | R28 |
| `wp18_gate_passes_at_exactly_one_point_drop` | R29 |
| `wp18_gate_fails_above_threshold` | R29 |
| `wp18_requires_eight_non_code_categories_and_same_config` | R29 |
| `wp18_rejects_environment_mismatch` | R29 |
| `wp18_rejects_unverified_or_draft_smoke_data` | R30 |
| `wp18_rejects_code_results` | R30 |
| `wp18_rejects_non_main_baseline` | R30 |
| `wp18_ranking_invariants_reject_bad_runs` | R31 |
| `wp18_requires_identical_repeat_order` | R31 |
| Property: a TREC run with gaps, duplicate targets, or non-finite scores never passes a ranking invariant | R31 |
| `filters_are_applied_exactly_and_reported` | R32 |
| `unsupported_filter_metadata_is_an_error` | R32 |
| `post_filtering_does_not_hide_truncated_depth` | R32 |

No unit test asserts ranking quality; quality evidence comes only from a clean
`seeky-bench` run and the methodology.

### 6.2 Benchmark gates

| Gate | Dataset/split | Tier | Threshold | Baseline report |
|---|---|---|---|---|
| Metric conformance | `metrics-v1`, `duplicates-v1`, `diversity-v1` fixtures | Any | Exact values in §5.8 (floating tolerance 1e-12) | Fixture header in tests |
| Statistics conformance | §5.3 eight-query and Holm fixtures | Any | Exact seed, p, CI, and Holm values in §5.3 | Fixture header in tests |
| WP-1.8 smoke | `sdc-smoke-v1` dev, default 8 non-code categories | Hardware-free CI on `main` and PR | Candidate macro nDCG@10 drop ≤ 1.0 point vs the same-config current `main`; invariants pass | Clean `main` run produced by the WP-1.8 CI job |
| Harness reproducibility | `sdc-smoke` eval | Any | Same commit/config/data yields byte-identical TREC order and identical metric/statistic values after excluding declared volatile fields (`run_id`, `generated_at`, capture/load timestamps) | WP-1.2/WP-1.8 run |
| Methodology §3.2 readiness | Phase 1 perf suites | T1/T1-emulated | Every required metric has a sample count or an explicit unavailable/not-budget-eligible status | WP-1.6 perf report |

The harness defines no S/I/R/Q budget of its own and must not claim one is met
from a T2 or undersampled run.

### 6.3 Inspection

- `seeky-eval` has no engine, store, search, infer, Tauri, UI, filesystem-tree
  traversal, or product-runtime dependency; Python only appears in offline
  `tools/` scripts (R1, R23, R24).
- `tools/seeky-bench` is a new internal binary, never packaged, and imports one
  metric implementation from `seeky-eval` (R1, R15, R18).
- No report, log, or golden artifact contains a query, document title/text,
  snippet, absolute/user path, user name, or secret; committed private reports
  have aggregate values only (R22).
- Every frozen SDC test/eval artifact references a real SPEC-0004 judgment-set
  hash and, for SDC test use, an exposure record (R3, R21, R30).
- The WP-1.8 CI command names the eight non-code categories, consumes verified
  `sdc-smoke-v1`, compares to the same-config `main` SHA, and keeps code-enabled
  evidence in a separate report (R29–R31).
- Optional perf fields for OCR/visual/distribution/energy are null until the
  responsible pack exists; they are not mocked (R27).

## 7. Risks and open questions

### Resolved blocking questions (H1)

Questions 1–3 are resolved by maintainer pre-approval in /goal. The
recommendations below are accepted: a behavior-preserving SPEC-0002 v1.1
evaluation extension is a prerequisite for WP-1.2, WP-1.6, and B0, but not for
WP-1.1 or WP-1.3. Until that extension is accepted, no depth-limited or
unsupported metric may be reported and the affected commands fail closed.
Post-filtering is acceptable only while depth remains sufficient; starvation is
an error, never a quality result.

| # | Question and conflict | Recommendation | Decides | By when |
|---|---|---|---|---|
| 1 | **Recall@100 depth versus the Engine API v1 cap.** Methodology Q3 and plan WP-1.1/WP-1.2 require Recall@100, but SPEC-0002 v1 clamps `SearchRequest.limit` to 1–50. `seeky-bench` cannot honestly compute Recall@100 from a 50-result call. | Add a small, behavior-preserving SPEC-0002 v1.1 evaluation capability (raise the maximum documented search/eval limit to 1,000, or expose an explicitly eval-only query depth) before WP-1.2 acceptance. Until then `seeky-eval` supports arbitrary cutoffs but `seeky-bench eval` fails with `INSUFFICIENT_DEPTH` when a requested cutoff exceeds the documented engine depth; it must never report truncated results as Recall@100. | Maintainer | Before H1 and WP-1.2 |
| 2 | **Per-stage timing and embedding telemetry versus Engine API v1.** WP-1.6 and B0 require Instant/Hybrid/Refined latency, query-embedding latency, time-to-searchable, and interference, while SPEC-0002 v1 exposes a single blocking `search` and a PoC status without stage timings or an embedding operation. Measuring internals through logs would violate the headless API boundary. | Add a read-only evaluation telemetry surface (immutable stage-timing/update records and query-embedding capability/status) to the same SPEC-0002 v1.1 extension, or explicitly defer S1/S2/S3/embedding claims to WP-4.3 while reporting only the measurable single-stage baseline as `stage=single`. The latter cannot satisfy the Phase 1 B0 deliverable as written, so the recommendation is the small v1.1 telemetry addition. | Maintainer | Before H1 and WP-1.6/B0 |
| 3 | **Structured metadata filters versus Engine API v1.** SPEC-0004 mixed semantic/metadata queries carry extension/date/folder/size filters, but SPEC-0002 `SearchRequest` has only query text and limit. Post-filtering returned hits can starve the ranking when the engine cap is reached and cannot establish Q2 for that category. | Add structured filters (or an eval-only equivalent) to the same SPEC-0002 v1.1 extension and pass them into retrieval. Until then, R32 permits deterministic post-filtering only when depth remains sufficient; truncation fails rather than producing a quality number, and the maintainer must confirm that post-filter semantics are acceptable for this Phase 1 category. | Maintainer | Before H1 and WP-1.2 |

### Non-blocking questions and risks

| # | Item | Recommendation / mitigation | Decides | By when |
|---|---|---|---|---|
| 4 | Public BEIR datasets do not carry Seeky categories, language slices, or metadata filters; mappings are lossy. | Use explicit manifest defaults plus per-query metadata for constructed MIRACL/mMARCO pairs; report `other`/cross-lingual only where verified mappings exist, and never infer language from untrusted text. WP-1.5 owns the mapping review. | WP-1.5 + maintainer | WP-1.5 |
| 5 | The WP-1.8 gate uses macro nDCG over the selected eight-category non-code queries (at least 40) rather than the full-test weighted primary, because smoke is a fast regression gate and need not cover every language slice. | Keep this macro as the CI threshold, while reporting per-category/language slices diagnostically; Q1/Q2 on full SDC-test remain the decision gates. If the maintainer intends the weighted primary here, add a verified smoke language minimum to SPEC-0004 first. | Maintainer | H1 review |
| 6 | A clean main baseline per CI run can be expensive or unavailable in a fork/offline runner. | Fail closed rather than use stale or hand-edited numbers; cache by commit + corpus/config hashes and permit a documented same-config baseline artifact only after verifying its commit and checksums. | WP-1.8 owner + maintainer | WP-1.8 |
| 7 | Stage 0 Python tooling and Stage B Rust must not implement metrics twice. | Make TREC the only cross-language interface; Stage A writes a run and Rust `seeky-eval` computes all metrics. If Stage A needs a metric earlier, invoke the same Rust evaluator, never a Python reimplementation. | WP-1.1/WP-1.2 | Acceptance |
| 8 | Pareto plots and installer/OCR/visual/energy metrics may not exist in Phase 1. | Render `Not generated` or null with warnings; later specs add real artifacts. A report never fabricates a zero or a plot. | WP-1.2/WP-1.6 | Phase 1 |
| 9 | Private-corpus aggregate-only output can still leak through query IDs or unusual hashes. | Omit per-query rows/run targets and any path-like IDs for private visibility; report only counts, hashes of public config, and aggregate metrics; add a privacy review before committing. | Maintainer + WP-1.2 | WP-1.2 |
| 10 | A failing cancellation or engine-contract test can make an otherwise good quality run unusable. | Treat malformed engine output/depth as a hard run failure, preserve the partial artifact and error report, and never score a truncated run. | WP-1.2 | Implementation |

## 8. Changelog

| Version | Date | Change |
|---|---|---|
| 0.3 | 2026-11-27 | ADR-0026: R30 and §5.6 accept records verified or adjudicated by a human or model reviewer; wording only, the gate logic already counted any recorded verifier |
| 0.3 | 2026-11-27 | WP-1.8 implemented R29-R31: `compare --gate wp1.8` applies the §5.6 rules in order and emits one typed gate row (reason code in `details` and `observed.reason`) in a `smoke_gate` report; R31 run invariants read each `run.trec`; R30 reads provenance from the committed set; `.github/workflows/smoke-gate.yml` is dormant until `sdc-smoke-v1` is published (H6) |
| 0.2 | 2026-11-27 | WP-1.6 implemented R25-R28: `seeky-bench perf` suites, the §4.10 performance shape (`query_embedding` batch/samples, optional RSS, `warnings`), tier/emulation validation, quiet window, and explicit budget eligibility. Errata approved by the maintainer: §5.8 D disk-per-1k reference corrected from 2,500 to 2,500,000 to match the §4.10 formula; §4.5 now names the interference-ratio bootstrap keys. R29-R31 remain with WP-1.8 |
| 0.1 | 2026-11-27 | WP-1.2 implemented R15-R22 and R32: `seeky-bench` index, eval, perf skeleton, compare, and report; environment and config hashing; reproducible artifacts; fail-closed depth; test confirmation/exposure; exact filters with pushdown/post reporting. R23-R24 with WP-1.5, R25-R28 with WP-1.6, R29-R31 with WP-1.8 |
| 0.1 | 2026-11-27 | WP-1.5 implemented R23-R24: offline `dataset-fetch` tooling and four pinned BEIR/MLDR manifests (SciFact, NFCorpus, FiQA, MLDR-pt) with upstream/local hashes, license notices, deterministic transforms, and fingerprints; the mMARCO cross-lingual pair and the largest sources remain unpinned |
| 0.1 | 2026-11-27 | WP-1.1 implemented R1-R14: BEIR/SDC loaders, graded judgments, reference-checked metrics, duplicate/diversity metrics, seeded paired statistics, and deterministic JSON/Markdown reports; R15-R32 remain with WP-1.2, WP-1.5, WP-1.6, and WP-1.8 |
| 0.1 | 2026-11-27 | Accepted (maintainer pre-approval in /goal); resolved H1 questions 1–3 with the draft recommendations: a SPEC-0002 v1.1 evaluation extension for result depth, telemetry, and filters is required before WP-1.2/WP-1.6; fail closed until then |
| 0.1 | 2026-11-27 | Initial Draft for WP-1.1, WP-1.2, WP-1.5, WP-1.6, WP-1.8: evaluator API, BEIR/SDC loaders, TREC runs, graded metrics with reference fixtures, fixed-seed paired statistics, report JSON/Markdown, environment/config hashing, test confirmation/exposure, performance metrics, and the eight-category WP-1.8 smoke gate |
