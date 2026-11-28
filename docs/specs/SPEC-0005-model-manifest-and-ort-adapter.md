# SPEC-0005 — Model manifest, ONNX Runtime adapter, and bake-off toolchain

| Field | Value |
|---|---|
| Status | Draft |
| Version | 0.1 |
| Owner | Maintainer |
| Phase / work packages | Phase 2 — WP-2.1, WP-2.2, WP-2.13 (manifest and inference side; [SPEC-0006](SPEC-0006-storage-index-backends-and-generations.md) owns the storage and retrieval side) |
| Crates touched | `seeky-core` (manifest types, inference traits, `ProviderKind`, `Workload`, `CancelToken`, `InferError`), `seeky-infer` (manifest loader/validator, ORT session pools, tokenizers, prompts/pooling/normalization, reranker, sparse encoder, OCR split-graph greedy decoder, parity verifier, image preprocessing), `seeky-search` and `seeky-engine` (consume `seeky-core` traits and `ActiveModelDescriptor`), `tools/model-export` (v2 export, quantization, parity, manifest emission, Stage A screening), `tools/seeky-bench` (`bakeoff` command) |
| Governing docs | [vision](../product/vision.md) P1–P8; [ADR-0016](../adr/0016-cpu-first-npu-ready-execution.md); [ADR-0019](../adr/0019-single-inference-engine.md); [ADR-0021](../adr/0021-no-generative-models-in-product.md); [ADR-0022](../adr/0022-permissive-license-gate.md); [ADR-0023](../adr/0023-multimodal-ready-engine.md); [ADR-0025](../adr/0025-automatic-provider-opt-in-gpu-tier-full-speed.md); [ADR-0027](../adr/0027-progressive-reranking-budget.md); [architecture/overview](../architecture/overview.md) §2, §4–§5; [architecture/inference-and-models](../architecture/inference-and-models.md); [architecture/distribution-and-provisioning](../architecture/distribution-and-provisioning.md) §4–§5, §8; [SPEC-0001](SPEC-0001-workspace-and-crate-boundaries.md) §4.2, §4.4, §5.3; [SPEC-0002](SPEC-0002-engine-api.md) §4.3, §5.5, §9.4.5, §9.5.7; [SPEC-0003](SPEC-0003-evaluation-harness.md) §4.3, §4.8, §4.11; [SPEC-0006](SPEC-0006-storage-index-backends-and-generations.md) §4.2–§4.4, §5.4; [SPEC-0007](SPEC-0007-indexing-pipeline.md) §4–§5.1; [methodology](../benchmarks/methodology.md) §5, §7, §8; [WP-0.6 ORT validation gate report](../benchmarks/results/2026-11-27-ort-gate/summary.md); [conformance audit](../validation/poc-conformance-audit.md) A5, A7, A9, A10 |
| Benchmark gates | S2, S4, S5, S6, I2, I3, R3, R6, D2, O1–O4, V1–V5, K1–K4 (from `docs/benchmarks/methodology.md` §5 and §8.7) |

## 1. Problem and goal

The PoC inference layer (`crates/seeky-infer/src/inference.rs`) hardcodes a
single model (`DIM = 384`, `MODEL_ID = "gety-embed-v0"`, output tensor names
`"sentence_embedding"` and `"embeddings"`, `max_length = 512`, `pad_id = 1`,
and no query/passage prefixes — audit A10), discovers weights and runtimes by
scanning a local Gety installation, runs two inference engines (ONNX Runtime
and native OpenVINO), and mutates the process `PATH` inside an audited `unsafe`
block (audit A9, SPEC-0001 §5.3). One mutex wraps the inference engine, so
query embedding waits behind whole-file indexing batches (audit A7). Switching
backends mixes vectors from different precisions and runtimes with no parity
check (audit A5). Finally, nothing in the manifest or traits supports
rerankers, learned sparse encoders, split-graph OCR transcription models, or
multimodal components.

The WP-0.6 ONNX Runtime validation gate ([gate report](../benchmarks/results/2026-11-27-ort-gate/summary.md))
and maintainer decision H5 (2026-11-27) confirmed [ADR-0019](../adr/0019-single-inference-engine.md)
for embedders and OCR (PP-OCRv6 tiny passes O1–O3 with 0.43 GB isolated RSS;
compact embedders clear K1 on ORT 1.22.0 CPU EP), moved cross-encoder
reranking to progressive refinement under [ADR-0027](../adr/0027-progressive-reranking-budget.md)
(provisional budget S6 ≤ 1.5 s p95, depth ≥ 10), recorded that Intel NPU
OpenVINO EP 2025.1 failed parity and crashed on QDQ (K3, keeping `Auto`
CPU-only until Phase 5 validates an updated stack), and showed that naive
MinMax static-QDQ quantization collapses transformers. The model manifest, ORT
adapter, and bake-off toolchain must encode these lessons from day one.

This specification defines three coupled deliverables for Phase 2:

1. **Model Manifest v1 and `seeky-infer` v2 (WP-2.1):** a versioned,
   fail-closed manifest schema covering every model role, component, ONNX
   variant, tokenizer, prompt template, pooling/truncation rule, license
   provenance, SHA-256 digest, and parity bound; narrow `seeky-core` inference
   traits (`TextEmbedder`, `CrossEncoderReranker`, `SparseEncoder`, gated
   `OcrTranscriber`); isolated query-latency and indexing-throughput ORT
   session pools; cooperative cancellation and bounded dynamic batching;
   execution-provider abstraction with parity-on-load and automatic CPU
   fallback; and complete removal of PoC hardcoded constants, Gety path
   discovery, and `unsafe` `PATH` mutation.
2. **Modality- and component-ready contracts (WP-2.13, inference side):**
   per-component ONNX graphs and `space_id` bindings aligned with
   [SPEC-0006](SPEC-0006-storage-index-backends-and-generations.md) embedding
   channels and [ADR-0023](../adr/0023-multimodal-ready-engine.md), the
   `VisionEmbedder` capability trait, manifest-driven Rust image preprocessing
   with raw-image-byte parity, and a strict residency guarantee that the text
   query path never loads a vision component.
3. **Offline bake-off toolchain (WP-2.2):** `tools/model-export` v2 (export,
   quantization matrix, parity verification against methodology §8.4,
   deterministic manifest + `parity.jsonl` emission, Stage A screening runner
   scoring through `seeky-eval`) and `seeky-bench bakeoff` (Stages A, B, and C
   with Pareto and deployment-cost tables).

Done means: no hardcoded model dimension, tensor name, prompt, or Gety path
remains in engine crates; `seeky-infer` contains zero `unsafe` blocks and never
mutates `PATH`; a query embeds without waiting for an active indexing batch; a
non-CPU provider failure or parity miss falls back cleanly to CPU; a
multimodal manifest runs text queries without ever touching its vision graph;
every model exported by `tools/model-export` loads and passes parity-on-load in
`seeky-infer` without manual edits; and every `seeky-core` trait has hermetic,
hardware-free tests.

## 2. Scope

- **In:**
  - Model Manifest v1 schema (JSON representation and `seeky-core` Rust types),
    fail-closed validation, ADR-0022 license enforcement, SHA-256 verification,
    `SpaceRecipe` and `SPEC-0002` `config_snapshot` descriptor derivation, and
    persistence format for the `SPEC-0006` §4.2 `models` table (WP-2.1).
  - `seeky-core` inference traits (`TextEmbedder`, `CrossEncoderReranker`,
    `SparseEncoder`, `OcrTranscriber` / `OcrEngine` slot), `ProviderKind`,
    `Workload`, `SessionConfig`, `GovernorHint`, `CancelToken`, `InferError`,
    and `InferEvent` (WP-2.1).
  - `seeky-infer` ONNX Runtime adapter: explicit-path dynamic ORT loading
    (closing audit A9), isolated query-latency and indexing-throughput session
    pools (closing inference half of audit A7), tokenizer loading and prompt
    formatting from manifest (closing audit A10), pooling/Matryoshka/L2
    normalization, bounded dynamic batching with length sorting and
    cancellation, ADR-0027 progressive micro-batched reranking, sparse
    encoding, ADR-0021 split-graph greedy OCR transcription decoding,
    static-shape bucketing hooks, runtime parity-on-load with CPU fallback
    (closing inference half of audit A5), and privacy-safe `tracing` spans
    (WP-2.1).
  - Manifest `modalities`, `space_id`, per-component `components[]`,
    `ImagePreprocessingSpec`, `VisionEmbedder` trait in `seeky-core`, lazy
    vision-component loading/unloading, and raw-image-byte parity checks
    (WP-2.13, inference side).
  - Offline `tools/model-export` v2 CLI (`export`, `quantize`, `parity`,
    `emit-manifest`, `screen`) and `tools/seeky-bench` `bakeoff` subcommand
    (`screen`, `deploy`, `confirm`) implementing [methodology §8](../benchmarks/methodology.md)
    (WP-2.2).
- **Out:**
  - Selecting winning default models (embedder WP-2.6, lexical/filename/vector
    WP-2.7–WP-2.9, chunker WP-2.10, OCR screening WP-2.11 and deployment
    WP-3.8, reranker WP-4.8, snippet scorer WP-4.10, sparse WP-4.11, visual
    architecture WP-10.4): bake-offs with their own reports and ADRs.
  - Challenger inference engines (`llama.cpp`/GGUF, native OpenVINO IR) unless
    triggered by a kill criterion (WP-2.3; not triggered for embedders or OCR
    at H5, conditional on WP-4.8 S6 for the reranker under ADR-0027).
  - Hardware detection, per-workload provider auto-benchmarking, power-aware
    provider switching, and NPU EP tuning (OpenVINO, QNN, VitisAI, CoreML,
    Windows ML) → SPEC-0012 (Phase 5).
  - Asset manifest v2, R2 downloads, Ed25519 signature verification, atomic
    cache installs, repair, and offline bundle import → SPEC-0013 (Phase 6).
  - Storage schema, `models` table migrations, index generations, embedding
    channels, and fusion over N rankings → [SPEC-0006](SPEC-0006-storage-index-backends-and-generations.md).
  - Governor state machine and scheduling → [SPEC-0007](SPEC-0007-indexing-pipeline.md).
  - Full OCR extraction pipeline (page rasterization, detection/recognition
    post-processing, OCR provenance) → SPEC-0009 (WP-3.8).
  - Visual-unit selection, visual indexing lane, visual fusion/calibration, and
    image-as-query UI/API → SPEC-0016 (Phase 10).

## 3. Requirements (EARS)

Requirements are grouped by work package so an implementer can take one WP
cleanly. Every requirement starts `Open`.

| ID | WP | Requirement | Verification | Gates | Status |
|---|---|---|---|---|---|
| | | **Model manifest v1, validation, and PoC removal (WP-2.1)** | | | |
| SPEC-0005-R1 | WP-2.1 | When `seeky-infer` parses a Model Manifest v1 document, it shall require `schema_version == 1`, validate every required field, enum, tensor I/O role, and cross-field invariant (§4.1, §5.1), reject unknown fields (`deny_unknown_fields`) and malformed syntax with a typed `InferError::ManifestInvalid`, and never panic on arbitrary bytes. | unit `manifest_v1_valid_round_trip`; unit `manifest_rejects_unknown_version_and_fields`; fuzz/proptest `malformed_manifest_never_panics` | — | Open |
| SPEC-0005-R2 | WP-2.1 | Every file path inside a model manifest (weights, external data, tokenizer, parity vectors, license, notice) shall be a relative POSIX path with no leading `/`, no backslash, no drive prefix, no NUL, and no `.` or `..` segment; if any path violates this rule or resolves outside the model directory, then the loader shall reject the manifest with `InferError::InvalidAssetPath` before opening any file. | unit `manifest_rejects_path_traversal_and_absolute_paths`; unit `loader_refuses_symlink_escape` | — | Open |
| SPEC-0005-R3 | WP-2.1 | Every model manifest shall declare an [ADR-0022](../adr/0022-permissive-license-gate.md) license block (`spdx`, `status`, `license_file`, `notice_file`); if `spdx` is missing, unrecognized, or in the forbidden set (`GPL*`, `AGPL*`, `LGPL*`, `CC-BY-NC*`, `CC-BY-ND*`, `CC-BY-SA*`, `research-only`), then validation shall fail closed with `InferError::LicenseRejected`, and `review_required` models shall load only when explicitly permitted by caller policy. | unit `manifest_rejects_forbidden_and_missing_licenses`; unit `review_required_license_needs_explicit_opt_in` | — | Open |
| SPEC-0005-R4 | WP-2.1 | Before creating any ONNX Runtime session or tokenizer, `seeky-infer` shall verify the byte length and lowercase SHA-256 of every file referenced by the selected component variant (including external `.onnx.data` files, tokenizer files, and `parity.jsonl`); if any file is missing or its size or digest mismatches, then loading shall fail with `InferError::MissingAsset` or `InferError::ChecksumMismatch` and load nothing. | unit `loader_verifies_all_variant_and_external_data_hashes`; unit `corrupt_weight_or_tokenizer_hash_is_rejected` | — | Open |
| SPEC-0005-R5 | WP-2.1 | `seeky-infer` shall read tensor names, dtypes, sequence limits, padding side and pad ID, query/passage prompt templates, pooling mode, L2 normalization, output dimension, and Matryoshka truncation dimensions exclusively from the validated manifest; it shall apply query prompts only in `embed_query`, passage prompts only in `embed_passages`, never include filename or path in embedding inputs, validate any requested truncation dimension against `truncatable_to`, and re-normalize to unit L2 length after truncation when `normalize == true`. | unit `prompts_applied_by_workload_only`; unit `pooling_modes_match_reference` (`in_graph`, `cls`, `mean`, `last_token`); property `matryoshka_truncation_preserves_unit_norm`; inspection: no hardcoded dim/tensor/prompt constants | S2, Q1 | Open |
| SPEC-0005-R6 | WP-2.1 | `seeky-infer` shall load the ONNX Runtime shared library only by explicit absolute path (`ort::init_from`), shall remove all PoC hardcoded model constants (`DIM`, `MODEL_ID`, `MODEL_REVISION`, `MODEL_PREPROCESSING`), all Gety installation discovery functions, and `prepend_path` / `prepare_cuda_paths` / `prepare_openvino_path`, and shall contain zero `std::env::set_var` or `remove_var` calls and zero `unsafe` blocks (closing audit A9 and SPEC-0001 §5.3). | inspection (`grep` for `unsafe`, `set_var`, `ai.gety`, `DIM`); unit `explicit_ort_path_missing_returns_typed_error`; `cargo clippy --workspace --all-targets -- -D warnings` | — | Open |
| SPEC-0005-R7 | WP-2.1 | For every active loaded model component, `seeky-infer` shall derive a deterministic, path-free `ActiveModelDescriptor` mapping 1:1 to `SPEC-0002` `ModelIdentity` and §9.5.7 `config_snapshot` (including canonical variant `sha256` and preprocessing recipe ID), a `SPEC-0006` `SpaceRecipe` for embedding roles, and a canonical JSON payload compatible with the `SPEC-0006` §4.2 `models` table. | unit `active_model_descriptor_matches_spec0002_snapshot`; unit `space_recipe_derives_from_manifest_and_parity_group`; unit `descriptor_is_path_independent` | — | Open |
| | | **`seeky-core` inference traits, errors, and privacy (WP-2.1)** | | | |
| SPEC-0005-R8 | WP-2.1 | `seeky-core` shall define the manifest structs, `TextEmbedder`, `CrossEncoderReranker`, `SparseEncoder`, `OcrTranscriber` (and `OcrEngine` trait slot), `ProviderKind`, `Workload`, `SessionConfig`, `GovernorHint`, `CancelToken`, `InferError`, and `InferEvent` (§4.2–§4.4) using only `std`, `serde`, and `thiserror` (SPEC-0001-R14); no `ort`, `tokenizers`, or runtime type shall appear in any public signature of `seeky-infer` (ADR-0019), and `seeky_core::TextEmbedder` shall supersede the PoC `seeky_infer::Embedder`. | `cargo tree -p seeky-core`; compile-time trait object assertions (`text_embedder_is_send_sync`); inspection of `seeky-infer/src/lib.rs` | — | Open |
| SPEC-0005-R9 | WP-2.1 | `seeky-infer` shall report all failures through the typed variants of `InferError` (no free-text catch-all variant), and no `InferError` `Display`/`Debug` string or `tracing` span/event emitted by `seeky-infer` shall contain query text, passage text, OCR output, image bytes, file names, user paths, or absolute asset/data directory paths. | unit `infer_errors_contain_no_sentinels` (every variant tested); unit `infer_spans_contain_no_sentinels` (capturing `tracing-subscriber` layer) | — | Open |
| SPEC-0005-R10 | WP-2.1 | Before returning embeddings, reranker scores, or sparse weights, `seeky-infer` shall verify output tensor shapes and check that every emitted float is finite; if an output has an unexpected shape or contains NaN or ±Inf, then it shall return `InferError::ShapeMismatch` or `InferError::NonFiniteOutput` without returning partial corrupt vectors. | unit `non_finite_tensor_yields_typed_error`; unit `wrong_output_shape_yields_typed_error` | — | Open |
| | | **ONNX Runtime sessions, concurrency, batching, and roles (WP-2.1)** | | | |
| SPEC-0005-R11 | WP-2.1 | For each loaded `TextEmbedder`, `seeky-infer` shall maintain separate ORT session pools for `Workload::Query` (batch-1 latency configuration, dedicated lock) and `Workload::Indexing` (throughput configuration, capped threads, separate lock); while an indexing batch is executing inside `embed_passages`, an `embed_query` call shall complete without waiting on the indexing session lock (closing the inference half of audit A7). | concurrency test `query_embed_completes_while_indexing_batch_is_blocked` (fake `SessionRunner` with barrier; no sleeps); benchmark gate S5 | S2, S5 | Open |
| SPEC-0005-R12 | WP-2.1 | When `embed_passages` receives a slice of passages, `seeky-infer` shall sort inputs by token length to minimize padding, partition them into batches bounded by both `max_batch_size` and `max_batch_tokens`, check `CancelToken` before each batch, restore the caller's original input order on return, and return `InferError::Cancelled` without running further batches when cancelled. | unit `indexing_batches_sort_by_length_and_restore_order`; unit `indexing_batches_respect_size_and_token_caps`; unit `indexing_cancellation_stops_between_batches`; property `batching_order_invariant` | I2, I3, S5 | Open |
| SPEC-0005-R13 | WP-2.1 | `CrossEncoderReranker::score_pairs` shall score `(query, passage)` pairs using the query-latency pool, enforce `RerankOptions` (`max_pairs`, `max_pair_tokens`, `micro_batch_size`), check `CancelToken` before every micro-batch (supporting ADR-0027 progressive reranking and S4 ≤ 5 ms cancellation), apply the manifest `output_activation`, return finite scores aligned 1:1 with input order, and fail open via typed `InferError` without poisoning the session. | unit `reranker_scores_pairs_in_micro_batches`; unit `reranker_cancels_between_micro_batches`; unit `reranker_respects_max_pairs_and_token_budget`; unit `reranker_error_leaves_session_reusable` | S4, S6 | Open |
| SPEC-0005-R14 | WP-2.1 | `SparseEncoder::encode_query` and `encode_passages` shall execute the manifest-configured sparse encoder graph, apply the declared activation (`log1p_relu`, `relu`, or `none`), discard terms with weight ≤ `min_weight` (default `0.0`), retain at most `top_k` terms per input, and return entries sorted by `token_id` ascending with finite positive weights. | unit `sparse_encoder_applies_activation_prunes_and_sorts`; property `sparse_output_is_sorted_positive_finite` | S2 | Open |
| SPEC-0005-R15 | WP-2.1 | Where a manifest declares `role == OcrTranscribe` ([ADR-0021](../adr/0021-no-generative-models-in-product.md)), `OcrTranscriber` shall run split ONNX graphs (`vision` encoder + `decoder` with KV cache) using strictly deterministic greedy decoding (`argmax`, temperature 0), inject only the manifest's fixed `fixed_transcription_prompt` (accepting no caller prompt parameter), enforce `max_new_tokens <= 1024` (or the smaller manifest cap) and a repetition-loop breaker, and check `CancelToken` at least every `cancel_check_interval` tokens (default 16). | unit `ocr_transcriber_is_deterministic_greedy`; unit `ocr_transcriber_stops_at_max_tokens_and_repetition`; unit `ocr_transcriber_cancels_within_interval`; inspection: no sampling or user-prompt API | O1, O2, O4 | Open |
| SPEC-0005-R16 | WP-2.1 | `seeky-infer` shall abstract execution providers through `ProviderKind` (`Cpu`, `OpenVino`, `Qnn`, `VitisAi`, `CoreMl`, opt-in-only `Cuda`); `ProviderPolicy::Auto` shall resolve to `Cpu` until SPEC-0012 validates an accelerator (WP-0.6 K3, audit A2); if any non-CPU provider fails session creation, parity-on-load, or inference, then `seeky-infer` shall fall back to `Cpu` and emit `InferEvent::ProviderFallback`; and `apply_governor_hint` shall update indexing thread/batch caps (`Default`, `FullSpeed`, `Paused`, ADR-0025) without changing the active model, parity group, or index generation. | unit `auto_provider_resolves_to_cpu_in_v1`; fault test `ep_failure_falls_back_to_cpu_and_emits_event`; unit `governor_hint_updates_indexing_caps_only` | S5, R3, K3 | Open |
| SPEC-0005-R17 | WP-2.1 | When a `(model_id, revision, variant_id, provider)` tuple is loaded for the first time on the current runtime/device fingerprint, `seeky-infer` shall run the component's `parity.jsonl` vectors through the session and verify outputs against `parity.load_check_tolerance`; if a non-CPU provider fails parity, then it shall be disabled for that model and fall back to `Cpu`; if `Cpu` fails parity, then loading shall fail with `InferError::ParityFailed`; and a variant with `parity_group: None` shall never be returned as write-eligible for an index generation (SPEC-0006-R32, audit A5). | unit `parity_on_load_passes_within_tolerance`; fault test `npu_parity_failure_falls_back_to_cpu`; fault test `cpu_parity_failure_refuses_load`; unit `variant_without_parity_group_cannot_write` | K3 | Open |
| SPEC-0005-R18 | WP-2.1 | Where a variant declares `shape_mode = StaticBuckets`, `seeky-infer` shall select the smallest declared sequence-length bucket `>= token_count` (truncating only at `tokenizer.max_tokens` and recording truncation counts in tracing spans), pad tensors cleanly to that bucket shape, and pass a versioned cache path under `<cache-dir>/ort/<model-hash>/<variant>/<provider>/` for ORT graph-optimization / EP-context caching. | unit `static_bucket_picks_smallest_fitting_length`; unit `static_bucket_reports_truncation_at_max_tokens`; unit `ort_cache_path_is_versioned_and_isolated` | R6, K3 | Open |
| SPEC-0005-R19 | WP-2.1 | With a test-only manifest wrapping the PoC `gety-embed-v0` artifact, `seeky-engine` shall pass the committed `SPEC-0002` `golden_hybrid_cpu` test (`hw-tests`) within the existing `1e-6` score tolerance while `golden_lexical` remains unchanged and hardware-free. | `golden_lexical`; `golden_hybrid_cpu` (`hw-tests`) | — | Open |
| | | **Multimodal and component readiness (WP-2.13, inference side)** | | | |
| SPEC-0005-R20 | WP-2.13 | A Model Manifest v1 declaring `modalities` containing `image` shall require a `vision` component with its own `io`, `image_preprocessing`, `variants[]`, and `parity` spec; every component in an embedding manifest shall inherit the manifest's `space_id` (mapping to `SPEC-0006` `SpaceRecipe::space_id`), and components shall validate and load independently. | unit `multimodal_manifest_validates_text_and_vision_components`; unit `image_modality_without_vision_component_is_rejected` | V4 | Open |
| SPEC-0005-R21 | WP-2.13 | `seeky-core` shall define the `VisionEmbedder: Send + Sync` capability trait accepting `ImageInput` (raw encoded bytes or decoded RGB8 buffer) and a `CancelToken`, returning finite normalized embeddings tagged with `(space_id, Modality::Image, parity_group)` alongside `ActiveModelDescriptor`, with zero image-codec or ORT types in `seeky-core`. | compile-time trait assertions; unit `vision_embedder_tags_image_modality_and_space` | V1, V5 | Open |
| SPEC-0005-R22 | WP-2.13 | While opening a model for text queries or text indexing, `seeky-infer` shall never open, stat-for-load, memory-map, or create an ORT session for a `vision` component, even when the manifest lists `modalities = ["text", "image"]` and the vision file is present or absent; a loaded `VisionEmbedder` shall expose explicit `unload()` / drop so vision sessions can be released under memory pressure without interrupting text queries (ADR-0023 decision 1.6). | unit with counting asset loader `text_query_never_opens_vision_component`; unit `text_loads_even_when_vision_pack_absent`; unit `vision_unload_keeps_text_session_serving` | V2, V4 | Open |
| SPEC-0005-R23 | WP-2.13 | `seeky-infer` shall execute image preprocessing in Rust strictly from the manifest's `ImagePreprocessingSpec` (`resize_policy`, `width`, `height`, `interpolation`, `color_space`, `rescale_factor`, `mean`, `std`, `layout`, `token_budget`), rejecting malformed or oversized images with typed `InferError::InvalidImage` without panicking; vision parity-on-load shall start from raw image bytes in `parity.jsonl` through this exact Rust pipeline (ADR-0023 decision 1.3, methodology §8.9). | unit `image_preprocess_matches_reference_tensor_values`; unit `malformed_or_oversized_image_yields_typed_error`; unit `vision_parity_runs_from_raw_image_bytes` | V1, V5 | Open |
| | | **Offline bake-off toolchain: `tools/model-export` v2 & `seeky-bench bakeoff` (WP-2.2)** | | | |
| SPEC-0005-R24 | WP-2.2 | `tools/model-export` v2 shall expose `export`, `quantize`, `parity`, `emit-manifest`, and `screen` subcommands requiring an external `--workspace` outside any Git worktree, using hash-locked ADR-0022-screened Python dependencies, fixed seeds, zero network calls during `quantize`/`parity`/`emit-manifest`, and bounded `--timeout-seconds` (atomic timeout artifact and exit code 124 on expiry). | Python `pytest`: `test_workspace_inside_git_is_rejected`, `test_offline_stages_make_no_network_calls`, `test_timeout_writes_atomic_artifact_and_exits_124` | — | Open |
| SPEC-0005-R25 | WP-2.2 | `tools/model-export export` shall export ONNX graphs for bi-encoder embedders, cross-encoder rerankers, sparse encoders, vision encoders, OCR detection/recognition models, and split-graph OCR transcription models (`vision` + `decoder` with KV cache), plus static-shape bucket graphs with an explicit `eager` attention switch (WP-0.6 K3), recording exporter version, opset, attention mode, and unsupported operators on failure. | Python `pytest` on tiny synthetic PyTorch modules: `test_export_encoder_and_static_bucket`, `test_export_split_ocr_graph`, `test_export_records_opset_and_attention_mode` | K1–K3 | Open |
| SPEC-0005-R26 | WP-2.2 | `tools/model-export quantize` shall generate `fp16`, `int8_dynamic`, `int8_static_qdq` (with configurable calibration method `entropy | percentile | minmax` from `dev`-split data only and sensitive-op exclusions), `int8_weight_only`, and `int4_matmul_nbits` variants (with external `.onnx.data` support) and ingest upstream `published_mixed` variants; it shall verify ORT session creation for each variant, delete partial artifacts on failure, and refuse `test`-split calibration data. | Python `pytest`: `test_quantize_matrix_and_external_data`, `test_quantize_rejects_test_split_calibration`, `test_failed_quantization_cleans_up_partial_files` | K1, K4, D2 | Open |
| SPEC-0005-R27 | WP-2.2 | `tools/model-export parity` shall compare every candidate variant (running NPU EP attempts in an isolated child process per WP-0.6 K3 crash hygiene) against the model's `fp32` reference on fixed `dev` inputs using all [methodology §8.4](../benchmarks/methodology.md#84-quantization-matrix-and-tolerance) and §8.9 metrics, assigning a deterministic non-null `parity_group` **only** when every applicable tolerance passes and emitting `parity_group: null` with structured failure reasons otherwise. | Python `pytest`: `test_embedder_parity_requires_cosine_recall_and_ndcg`, `test_reranker_parity_requires_tau_and_ndcg`, `test_ocr_parity_requires_cer_and_hallucination`, `test_npu_probe_crash_is_isolated_and_reported` | K1–K3 | Open |
| SPEC-0005-R28 | WP-2.2 | `tools/model-export emit-manifest` shall emit a deterministic schema-v1 manifest (`model.json`, §7 Q1) and `parity.jsonl` (including raw image byte fixtures for vision components) with verified SHA-256 digests, byte counts, license/notice metadata, and `parity_group` assignments; a cross-language contract test shall prove that an emitted manifest parses, validates, and passes parity-on-load in `seeky-infer` unmodified. | Python `pytest` `test_emit_manifest_deterministic_and_schema_valid`; Rust integration test `emitted_manifest_loads_in_seeky_infer` | D2, O3, V3 | Open |
| SPEC-0005-R29 | WP-2.2 | `tools/model-export screen` (Stage A) shall run reference-runtime candidates on the frozen `dev` screening set, cache outputs under `(candidate_id, revision, variant, input_sha256)`, write canonical SPEC-0003 six-column TREC runs, and invoke `seeky-bench` / `seeky-eval` to compute all retrieval metrics so no second metric implementation decides bake-off results (methodology §8.2). | Python `pytest`: `test_screen_cache_key_and_reuse`, `test_screen_emits_valid_spec0003_trec_run` | Q1, Q2, K2 | Open |
| SPEC-0005-R30 | WP-2.2 | `tools/seeky-bench` shall expose `seeky-bench bakeoff <area> --stage screen|deploy|confirm --candidates <file>` orchestrating Stage A (`seeky-eval` over cached runs), Stage B (deployed ORT variants via `Engine` on T1), and Stage C (confirmation-guarded `test` split enforcing SPEC-0003-R21), writing `results.json`, `summary.md`, the Pareto frontier table, and the [methodology §8.5](../benchmarks/methodology.md#85-deployment-cost-accounting) deployment-cost table (checking D2/O3/V3 limits and flagging §8.6 new-engine margins). | integration `bakeoff_screen_writes_pareto_and_summary`; integration `bakeoff_deploy_writes_cost_table`; integration `bakeoff_confirm_enforces_test_guard` | S2, S6, I3, R3, D2, Q1, Q2 | Open |

Status: `Open` → `Implemented (WP-2.x)` (code and tests merged) → `Verified`
(applicable benchmark gates passed with linked report).

## 4. Interfaces

Signatures are normative in shape; private helper names are not. All public
manifest and trait types live in `seeky-core` (`crates/seeky-core/src/infer.rs`
or submodule re-exported from `seeky-core`), keeping `seeky-core` restricted to
`std`, `serde`, and `thiserror` (SPEC-0001-R14). JSON serialization/parsing
(`serde_json`), SHA-256 verification (`sha2`), tokenization (`tokenizers`), and
ONNX Runtime bindings (`ort`) live in `seeky-infer` (all already present in
root `[workspace.dependencies]`; no new external crate required for WP-2.1).

### 4.1 Model Manifest v1 schema (`model.json`)

> **Format note (§7 Q1):** `docs/architecture/inference-and-models.md` §4 and
> `docs/architecture/distribution-and-provisioning.md` §4–§5 sketch `model.toml`.
> This draft specifies canonical JSON (`model.json`) as the normative schema so
> `seeky-infer`, `seeky-provision`, `seeky-store` (`models.manifest`), and
> `SPEC-0002` `config_snapshot` share one format with zero new Rust
> dependencies (`serde_json` is already in `[workspace.dependencies]`). See §7
> Q1 for the blocking H7 decision.

#### JSON Schema v1 (normative example — multimodal-capable embedding model)

```json
{
  "schema_version": 1,
  "id": "embed/example-multilingual/v1",
  "revision": "2026.11.r1",
  "role": "embedding",
  "modalities": ["text", "image"],
  "space_id": "example-multilingual/2026.11.r1",
  "default_channel": "text",
  "languages": ["pt", "en", "es", "fr", "de"],
  "license": {
    "spdx": "Apache-2.0",
    "status": "allowed",
    "license_file": "LICENSE.txt",
    "notice_file": "NOTICE.txt",
    "upstream_url": "https://example.invalid/models/example-multilingual",
    "use_policy_note": null
  },
  "components": [
    {
      "name": "text",
      "modality": "text",
      "io": {
        "inputs": [
          { "name": "input_ids", "dtype": "i64", "role": "input_ids" },
          { "name": "attention_mask", "dtype": "i64", "role": "attention_mask" }
        ],
        "outputs": [
          { "name": "sentence_embedding", "dtype": "f32", "role": "embeddings" }
        ],
        "pooling": "in_graph",
        "normalize": true,
        "metric": "cosine",
        "dimension": 768,
        "truncatable_to": [512, 256, 128],
        "output_activation": "none"
      },
      "tokenizer": {
        "revision": "tok-v1",
        "files": [
          { "path": "tokenizer.json", "bytes": 4201920, "sha256": "<64 lowercase hex>" }
        ],
        "padding_side": "right",
        "pad_id": 1,
        "bos_id": 0,
        "eos_id": 2,
        "max_tokens": 512,
        "add_special_tokens": true,
        "pair_format": null
      },
      "prompts": {
        "query": "query: ",
        "passage": "passage: ",
        "instruction": null,
        "fixed_transcription_prompt": null
      },
      "image_preprocessing": null,
      "decode": null,
      "variants": [
        {
          "variant_id": "fp32-cpu",
          "precision": "fp32",
          "providers": ["cpu"],
          "shape_mode": { "kind": "dynamic" },
          "files": [
            { "path": "text_fp32.onnx", "bytes": 130099079, "sha256": "<64 lowercase hex>" }
          ],
          "parity_group": "pg-v1-fp32ref",
          "ep_hints": {
            "graph_optimization": "all",
            "requires_eager_attention": false,
            "cacheable_compiled_blob": false,
            "min_ort_version": "1.22.0",
            "min_driver_version": null
          }
        },
        {
          "variant_id": "int8-qdq-openvino-npu",
          "precision": "int8_static_qdq",
          "providers": ["openvino"],
          "shape_mode": {
            "kind": "static_buckets",
            "batch_sizes": [1, 8],
            "seq_lengths": [64, 128, 256, 512]
          },
          "files": [
            { "path": "text_qdq_static.onnx", "bytes": 106210366, "sha256": "<64 lowercase hex>" }
          ],
          "parity_group": null,
          "ep_hints": {
            "graph_optimization": "all",
            "requires_eager_attention": true,
            "cacheable_compiled_blob": true,
            "min_ort_version": "1.22.0",
            "min_driver_version": "32.0.100.3800"
          }
        }
      ],
      "parity": {
        "vectors_file": { "path": "parity_text.jsonl", "bytes": 18432, "sha256": "<64 lowercase hex>" },
        "reference_precision": "fp32",
        "metric": "cosine",
        "load_check_tolerance": 0.99,
        "thresholds": {
          "min_mean_cosine": 0.99,
          "min_neighbor_recall_at_100": 0.98,
          "max_ndcg10_drop_points": 0.5,
          "min_kendall_tau_b": null,
          "max_cer_delta_points": null,
          "min_cross_modal_recall_at_10": null
        }
      }
    },
    {
      "name": "vision",
      "modality": "image",
      "io": {
        "inputs": [
          { "name": "pixel_values", "dtype": "f32", "role": "pixel_values" }
        ],
        "outputs": [
          { "name": "image_embedding", "dtype": "f32", "role": "embeddings" }
        ],
        "pooling": "in_graph",
        "normalize": true,
        "metric": "cosine",
        "dimension": 768,
        "truncatable_to": [512, 256, 128],
        "output_activation": "none"
      },
      "tokenizer": null,
      "prompts": null,
      "image_preprocessing": {
        "recipe_id": "img-shortest224-rgb-norm05-nchw-v1",
        "resize_policy": "shortest_edge",
        "width": 224,
        "height": 224,
        "interpolation": "bicubic",
        "color_space": "rgb",
        "rescale_factor": 0.00392156862745098,
        "mean": [0.5, 0.5, 0.5],
        "std": [0.5, 0.5, 0.5],
        "layout": "nchw",
        "token_budget": 280
      },
      "decode": null,
      "variants": [
        {
          "variant_id": "fp32-cpu",
          "precision": "fp32",
          "providers": ["cpu"],
          "shape_mode": { "kind": "dynamic" },
          "files": [
            { "path": "vision_fp32.onnx", "bytes": 195000000, "sha256": "<64 lowercase hex>" }
          ],
          "parity_group": "pg-v1-fp32ref",
          "ep_hints": null
        }
      ],
      "parity": {
        "vectors_file": { "path": "parity_vision.jsonl", "bytes": 65536, "sha256": "<64 lowercase hex>" },
        "reference_precision": "fp32",
        "metric": "cosine",
        "load_check_tolerance": 0.99,
        "thresholds": {
          "min_mean_cosine": 0.99,
          "min_neighbor_recall_at_100": 0.98,
          "max_ndcg10_drop_points": 0.5,
          "min_kendall_tau_b": null,
          "max_cer_delta_points": null,
          "min_cross_modal_recall_at_10": 0.98
        }
      }
    }
  ]
}
```

#### Rust manifest types (in `seeky-core`)

Every manifest struct derives `Clone, Debug, PartialEq, Serialize, Deserialize`
with `#[serde(deny_unknown_fields)]` and `#[serde(rename_all = "snake_case")]`.

```rust
pub const MODEL_MANIFEST_SCHEMA_VERSION: u16 = 1;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModelManifest {
    pub schema_version: u16,                         // must equal 1
    pub id: String,                                  // public model ID; never a path
    pub revision: String,                            // immutable revision label
    pub role: ModelRole,
    pub modalities: Vec<Modality>,                   // non-empty, unique, canonical order
    pub space_id: Option<String>,                    // required iff role == Embedding
    pub default_channel: Option<ChannelId>,          // "text" or "visual" for Embedding
    pub languages: Vec<String>,                      // e.g. ["pt", "en"] or ["multilingual"]
    pub license: LicenseInfo,
    pub components: Vec<ComponentSpec>,              // non-empty; unique component names
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ModelRole {
    Embedding,
    Rerank,
    Sparse,
    Snippet,
    OcrDetect,
    OcrRecognize,
    OcrTranscribe, // ADR-0021 gated deterministic transcriber only
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LicenseStatus { Allowed, ReviewRequired }

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LicenseInfo {
    pub spdx: String,
    pub status: LicenseStatus,
    pub license_file: String,                        // relative POSIX path
    pub notice_file: String,                         // relative POSIX path
    pub upstream_url: Option<String>,
    pub use_policy_note: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ComponentSpec {
    pub name: String,                                // e.g. "text", "vision", "cross_encoder", "decoder"
    pub modality: Modality,
    pub io: ComponentIo,
    pub tokenizer: Option<TokenizerSpec>,            // required when modality == Text
    pub prompts: Option<PromptTemplates>,
    pub image_preprocessing: Option<ImagePreprocessingSpec>, // required when modality == Image
    pub decode: Option<GreedyDecodeSpec>,            // allowed ONLY for role == OcrTranscribe
    pub variants: Vec<ModelVariant>,                 // non-empty; unique variant_id
    pub parity: ParitySpec,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactFile {
    pub path: String,                                // relative POSIX path (R2)
    pub bytes: u64,
    pub sha256: String,                              // 64 lowercase hex chars
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TensorDtype { I64, I32, F32, F16, Bool }

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TensorRole {
    InputIds, AttentionMask, TokenTypeIds, PositionIds,
    PixelValues, EncoderHiddenStates, PastKeyValues,
    Embeddings, LastHiddenState, Logits, SparseLogits,
    Boxes, RecognitionLogits, PresentKeyValues,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TensorSpec { pub name: String, pub dtype: TensorDtype, pub role: TensorRole }

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PoolingMode { InGraph, Cls, Mean, LastToken, None }

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OutputActivation { None, Sigmoid, Relu, Log1pRelu }

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ComponentIo {
    pub inputs: Vec<TensorSpec>,
    pub outputs: Vec<TensorSpec>,
    pub pooling: PoolingMode,
    pub normalize: bool,
    pub metric: Option<Metric>,                      // required for Embedding
    pub dimension: Option<u32>,                      // required for Embedding
    pub truncatable_to: Vec<u32>,                    // strictly descending, each < dimension
    pub output_activation: OutputActivation,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PaddingSide { Right, Left }

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TokenizerSpec {
    pub revision: String,                            // feeds SpaceRecipe::tokenizer_revision
    pub files: Vec<ArtifactFile>,                    // must include tokenizer.json
    pub padding_side: PaddingSide,
    pub pad_id: u32,
    pub bos_id: Option<u32>,
    pub eos_id: Option<u32>,
    pub max_tokens: u32,                             // > 0
    pub add_special_tokens: bool,
    pub pair_format: Option<PairFormat>,             // for Rerank / Snippet cross-encoders
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PairFormat { TokenizerPair, ConcatWithSeparator }

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PromptTemplates {
    pub query: Option<String>,
    pub passage: Option<String>,
    pub instruction: Option<String>,
    pub fixed_transcription_prompt: Option<String>,  // allowed ONLY for OcrTranscribe (ADR-0021)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResizePolicy { ShortestEdge, LongestEdge, Exact, Letterbox }

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Interpolation { Bilinear, Bicubic }

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ColorSpace { Rgb, Bgr }

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ImageLayout { Nchw, Nhwc }

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ImagePreprocessingSpec {
    pub recipe_id: String,                           // feeds SpaceRecipe::image_preprocessing
    pub resize_policy: ResizePolicy,
    pub width: u32,
    pub height: u32,
    pub interpolation: Interpolation,
    pub color_space: ColorSpace,
    pub rescale_factor: f32,                         // finite, > 0
    pub mean: [f32; 3],                              // finite
    pub std: [f32; 3],                               // finite, each > 0
    pub layout: ImageLayout,
    pub token_budget: Option<u32>,                   // visual soft-token budget if applicable
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GreedyDecodeSpec {
    pub strategy: GreedyStrategy,                    // only Greedy (ADR-0021)
    pub max_new_tokens: u32,                         // 1..=1024
    pub eos_token_ids: Vec<u32>,                     // non-empty
    pub repetition_window: u32,                      // e.g. 32 tokens
    pub cancel_check_interval: u32,                  // default 16 tokens
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GreedyStrategy { Greedy }

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Precision {
    Fp32, Fp16, Int8Dynamic, Int8StaticQdq, Int8WeightOnly, Int4MatmulNbits, PublishedMixed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderKind { Cpu, OpenVino, Qnn, VitisAi, CoreMl, Cuda }

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ShapeMode {
    Dynamic,
    StaticBuckets { batch_sizes: Vec<u32>, seq_lengths: Vec<u32> },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EpHints {
    pub graph_optimization: Option<String>,          // "disable" | "basic" | "extended" | "all"
    pub requires_eager_attention: bool,
    pub cacheable_compiled_blob: bool,
    pub min_ort_version: Option<String>,
    pub min_driver_version: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModelVariant {
    pub variant_id: String,                          // e.g. "int8-dynamic-cpu"
    pub precision: Precision,
    pub providers: Vec<ProviderKind>,                // non-empty, unique
    pub shape_mode: ShapeMode,
    pub files: Vec<ArtifactFile>,                    // non-empty; primary .onnx + optional .onnx.data
    pub parity_group: Option<String>,                // Some(...) iff variant passed §8.4 parity
    pub ep_hints: Option<EpHints>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ParityMetric { Cosine, KendallTauB, LogitDelta, ExactText, CerDelta }

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ParityThresholds {
    pub min_mean_cosine: Option<f64>,
    pub min_neighbor_recall_at_100: Option<f64>,
    pub max_ndcg10_drop_points: Option<f64>,
    pub min_kendall_tau_b: Option<f64>,
    pub max_cer_delta_points: Option<f64>,
    pub min_cross_modal_recall_at_10: Option<f64>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ParitySpec {
    pub vectors_file: ArtifactFile,                  // parity.jsonl
    pub reference_precision: Precision,
    pub metric: ParityMetric,
    pub load_check_tolerance: f64,                   // finite
    pub thresholds: ParityThresholds,
}
```

#### Parity vector file format (`parity.jsonl`)

Each line is a compact UTF-8 JSON object:

- Text embedding: `{"id":"p0","kind":"query"|"passage","text":"...","expected":[f32,...]}`
- Vision embedding: `{"id":"v0","kind":"image","image_base64":"...","format":"png"|"jpeg"|"rgb8","width":null,"height":null,"expected":[f32,...]}`
- Reranker: `{"id":"r0","kind":"pair","query":"...","passage":"...","expected_logit":f32}`
- Sparse encoder: `{"id":"s0","kind":"query"|"passage","text":"...","expected_terms":[[u32,f32],...]}`
- OCR transcription: `{"id":"o0","kind":"ocr_image","image_base64":"...","format":"png","expected_text":"..."}`

Vision and OCR parity records carry raw image bytes (base64-encoded PNG/JPEG),
never pre-computed float tensors, so Rust image decoding and preprocessing are
checked together with the ONNX graph (R23, ADR-0023 decision 1.3).

### 4.2 `seeky-core` inference traits and configuration types

```rust
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Workload { Query, Indexing }

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderPolicy {
    Auto,                      // CPU-only in WP-2.1; measured auto in SPEC-0012
    Explicit(ProviderKind),    // explicit override; still falls back to CPU on failure
}

/// Cooperative cancellation handle shared across stages and micro-batches.
/// Backed by `Arc<AtomicBool>` in `seeky-core` (no async runtime dependency).
#[derive(Clone, Debug, Default)]
pub struct CancelToken { /* Arc<AtomicBool> */ }
impl CancelToken {
    pub fn new() -> Self;
    pub fn cancel(&self);
    pub fn is_cancelled(&self) -> bool;
}

/// Runtime governor hint passed from `seeky-engine` (SPEC-0007 / ADR-0025).
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct GovernorHint {
    pub indexing_threads: usize,       // >= 1
    pub indexing_max_batch_size: usize,
    pub indexing_max_batch_tokens: usize,
    pub allow_discrete_gpu: bool,      // false in Default; true only in FullSpeed / opt-in
}

/// Session and pool configuration for one loaded component.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SessionConfig {
    pub provider_policy: ProviderPolicy,
    pub query_intra_op_threads: usize,    // provisional default: min(physical_cores, 8)
    pub indexing_intra_op_threads: usize, // provisional default: max(1, physical_cores / 2)
    pub inter_op_threads: usize,          // default: 1
    pub indexing_max_batch_size: usize,   // default: 32
    pub indexing_max_batch_tokens: usize, // default: 8192
    pub truncation_dimension: Option<u32>,// optional Matryoshka dimension
    pub allow_review_required_license: bool, // default: false
}

/// Public, path-free description of one loaded model component.
/// Maps 1:1 to `SPEC-0002` `ModelIdentity`, `config_snapshot`, and `SPEC-0006` `SpaceRecipe`.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ActiveModelDescriptor {
    pub role: ModelRole,
    pub id: String,
    pub revision: String,
    pub component: String,
    pub modality: Modality,
    pub variant_id: String,
    pub precision: Precision,
    pub provider: ProviderKind,
    pub dimension: Option<u32>,
    pub space_id: Option<String>,
    pub parity_group: Option<String>,
    pub tokenizer_revision: Option<String>,
    pub preprocessing: String,         // deterministic path-free recipe ID
    pub sha256: String,                // deterministic variant digest (64 lowercase hex)
}

impl ActiveModelDescriptor {
    /// SPEC-0002 §9.4.5 ModelIdentity ("embedding" -> "embedder", "rerank" -> "reranker").
    pub fn model_identity(&self) -> ModelIdentity;
    /// SPEC-0006 §4.3 SpaceRecipe (returns None for non-embedding roles or missing parity_group).
    pub fn space_recipe(&self, input_recipe_version: u32) -> Option<SpaceRecipe>;
}

/// Embedding output tagged with space provenance so callers never mix vector spaces.
#[derive(Clone, Debug)]
pub struct TaggedVector {
    pub space_id: String,
    pub parity_group: Option<String>,  // None => read/diagnostic only, refused by store writer
    pub modality: Modality,
    pub values: Vec<f32>,              // finite, length == active dimension
}

/// Text bi-encoder capability (supersedes PoC `seeky_infer::Embedder`).
pub trait TextEmbedder: Send + Sync {
    fn descriptor(&self) -> &ActiveModelDescriptor;
    fn dimension(&self) -> u32;
    /// Latency session (batch 1), applies `prompts.query`. Never blocks on indexing.
    fn embed_query(&self, text: &str) -> Result<TaggedVector, InferError>;
    /// Throughput session (sorted dynamic batches), applies `prompts.passage`.
    fn embed_passages(
        &self,
        passages: &[&str],
        cancel: &CancelToken,
    ) -> Result<Vec<TaggedVector>, InferError>;
    /// Apply governor hint to the indexing session pool only (ADR-0025).
    fn apply_governor_hint(&self, hint: GovernorHint) -> Result<(), InferError>;
}

/// Options for progressive cross-encoder reranking (ADR-0027).
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RerankOptions {
    pub max_pairs: usize,              // hard cap per call (depth decided by WP-4.8, floor >= 10)
    pub max_pair_tokens: usize,        // clamped to manifest tokenizer.max_tokens
    pub micro_batch_size: usize,       // default: 4 (enables S4 <= 5 ms cancellation)
}

/// Cross-encoder reranker capability (query-latency pool, cancellable, fail-open).
pub trait CrossEncoderReranker: Send + Sync {
    fn descriptor(&self) -> &ActiveModelDescriptor;
    fn score_pairs(
        &self,
        query: &str,
        passages: &[&str],
        options: RerankOptions,
        cancel: &CancelToken,
    ) -> Result<Vec<f32>, InferError>;
}

/// Learned sparse vector: sorted by `token_id` ascending, finite positive weights.
#[derive(Clone, Debug, PartialEq)]
pub struct SparseVector {
    pub entries: Vec<(u32, f32)>,
}

/// Learned sparse encoder capability (gated by WP-4.11).
pub trait SparseEncoder: Send + Sync {
    fn descriptor(&self) -> &ActiveModelDescriptor;
    fn encode_query(&self, text: &str) -> Result<SparseVector, InferError>;
    fn encode_passages(
        &self,
        passages: &[&str],
        cancel: &CancelToken,
    ) -> Result<Vec<SparseVector>, InferError>;
}

/// Image input passed across the `seeky-core` boundary without exposing codec crates.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EncodedImageFormat { Png, Jpeg, Webp }

pub enum ImageInput<'a> {
    Encoded { format: EncodedImageFormat, bytes: &'a [u8] },
    Rgb8 { width: u32, height: u32, bytes: &'a [u8] },
}

/// Optional vision embedding capability (WP-2.13, ADR-0023).
/// Loaded lazily ONLY for visual indexing or image queries; never on the text query path.
pub trait VisionEmbedder: Send + Sync {
    fn descriptor(&self) -> &ActiveModelDescriptor;
    fn dimension(&self) -> u32;
    fn embed_image_query(&self, image: ImageInput<'_>) -> Result<TaggedVector, InferError>;
    fn embed_images(
        &self,
        images: &[ImageInput<'_>],
        cancel: &CancelToken,
    ) -> Result<Vec<TaggedVector>, InferError>;
    /// Release underlying vision ORT sessions under memory pressure (ADR-0023 decision 1.6).
    fn unload(&self);
}

/// Gated split-graph OCR transcription runner (ADR-0019, ADR-0021).
/// Never accepts a caller prompt; always deterministic greedy decode.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OcrTranscription {
    pub text: String,
    pub tokens_generated: u32,
    pub stopped_at_limit: bool,
    pub stopped_by_repetition_guard: bool,
}

pub trait OcrTranscriber: Send + Sync {
    fn descriptor(&self) -> &ActiveModelDescriptor;
    fn transcribe_page(
        &self,
        image: ImageInput<'_>,
        cancel: &CancelToken,
    ) -> Result<OcrTranscription, InferError>;
}

/// High-level OCR trait slot implemented in SPEC-0009 (detection+recognition or transcriber).
pub trait OcrEngine: Send + Sync {
    fn descriptor(&self) -> &ActiveModelDescriptor;
    fn recognize_page(
        &self,
        image: ImageInput<'_>,
        cancel: &CancelToken,
    ) -> Result<String, InferError>;
}
```

### 4.3 `seeky-infer` runtime and session architecture

```rust
/// Configuration for initializing the process-wide ORT dynamic library and registry.
pub struct OrtRuntimeConfig {
    pub ort_library_path: PathBuf,     // explicit absolute path; never searched on PATH (R6)
    pub cache_dir: PathBuf,            // <data-dir>/cache/ort/ (R18)
}

pub struct ModelRegistry { /* verified manifests + runtime handle + event sink */ }

impl ModelRegistry {
    /// Initialize ORT via `ort::init_from` (idempotent; fails closed if path differs).
    pub fn init(config: OrtRuntimeConfig, events: Arc<dyn InferEventSink>) -> Result<Self, InferError>;
    /// Parse, validate, license-check, and register a manifest directory without loading any session.
    pub fn inspect_manifest(
        &self,
        model_dir: &Path,
        allow_review_required: bool,
    ) -> Result<ValidatedManifest, InferError>;
    /// Load ONLY the text component (never opens vision files, R22).
    pub fn load_text_embedder(
        &self,
        manifest: &ValidatedManifest,
        config: SessionConfig,
    ) -> Result<Arc<dyn TextEmbedder>, InferError>;
    /// Load ONLY the vision component lazily (R22).
    pub fn load_vision_embedder(
        &self,
        manifest: &ValidatedManifest,
        config: SessionConfig,
    ) -> Result<Arc<dyn VisionEmbedder>, InferError>;
    pub fn load_reranker(
        &self,
        manifest: &ValidatedManifest,
        config: SessionConfig,
    ) -> Result<Arc<dyn CrossEncoderReranker>, InferError>;
    pub fn load_sparse_encoder(
        &self,
        manifest: &ValidatedManifest,
        config: SessionConfig,
    ) -> Result<Arc<dyn SparseEncoder>, InferError>;
    pub fn load_ocr_transcriber(
        &self,
        manifest: &ValidatedManifest,
        config: SessionConfig,
    ) -> Result<Arc<dyn OcrTranscriber>, InferError>;
}
```

**Internal session isolation (`seeky-infer`):**

- `ort 2.0.0-rc.10` `Session::run(&mut self, ...)` requires `&mut self`.
  Therefore `OrtTextEmbedder` holds **two independent mutexes** (never one):
  `query_session: Mutex<Box<dyn SessionRunner>>` and
  `indexing_session: Mutex<Box<dyn SessionRunner>>`.
- `embed_query` acquires only `query_session`; `embed_passages` acquires only
  `indexing_session` per micro-batch (releasing it between batches so
  `apply_governor_hint` can reconfigure threads/batch bounds cleanly). Neither
  path ever touches the other's mutex (R11).
- `SessionRunner` is an internal crate-private trait implemented by
  `OrtSessionRunner` (wrapping real `ort::session::Session`) and by a
  deterministic `FakeSessionRunner` in `#[cfg(test)]` so every WP-2.1 and
  WP-2.13 test runs hardware-free without needing `onnxruntime.dll` /
  `libonnxruntime.so` on CI runners (§7 Q7).
- `VisionEmbedder` stores `Mutex<Option<VisionSessions>>`: `unload()` drops the
  ORT session handles immediately, freeing model RSS (V2), and a later vision
  call reloads lazily from the verified manifest if needed.

### 4.4 Errors and events (in `seeky-core`)

```rust
#[derive(Debug, thiserror::Error)]
pub enum InferError {
    #[error("invalid model manifest: {reason:?} at field {field}")]
    ManifestInvalid { reason: ManifestViolation, field: &'static str },
    #[error("invalid relative asset path in manifest")]
    InvalidAssetPath,
    #[error("model license rejected: {spdx}")]
    LicenseRejected { spdx: String },
    #[error("required model asset missing: {kind:?}")]
    MissingAsset { kind: AssetKind },
    #[error("asset checksum mismatch for {kind:?}")]
    ChecksumMismatch { kind: AssetKind },
    #[error("component '{component}' not declared in manifest")]
    ComponentNotFound { component: &'static str },
    #[error("no compatible variant for provider {provider:?}")]
    NoCompatibleVariant { provider: ProviderKind },
    #[error("truncation dimension {requested} not supported by model")]
    InvalidTruncationDimension { requested: u32 },
    #[error("execution provider {provider:?} unavailable")]
    ProviderUnavailable { provider: ProviderKind },
    #[error("parity check failed for provider {provider:?}: measured {measured:.4}, required {required:.4}")]
    ParityFailed { provider: ProviderKind, measured: f64, required: f64 },
    #[error("tokenizer error: {kind:?}")]
    Tokenizer { kind: TokenizerErrorKind },
    #[error("invalid image input: {reason:?}")]
    InvalidImage { reason: ImageErrorReason },
    #[error("tensor shape mismatch: expected {expected}, got {got}")]
    ShapeMismatch { expected: String, got: String },
    #[error("model produced non-finite floating-point output")]
    NonFiniteOutput,
    #[error("inference runtime error (code {code})")]
    Runtime { provider: ProviderKind, code: i32 },
    #[error("inference cancelled")]
    Cancelled,
    #[error("io error: {0:?}")]
    Io(std::io::ErrorKind),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum InferEvent {
    ProviderFallback {
        model_id: String,
        revision: String,
        component: String,
        from: ProviderKind,
        to: ProviderKind,
        reason: FallbackReason, // LoadFailed | ParityFailed | RuntimeFailed | Unsupported
    },
    ParityVerified {
        model_id: String,
        revision: String,
        component: String,
        variant_id: String,
        provider: ProviderKind,
        passed: bool,
    },
    VisionComponentUnloaded { model_id: String, revision: String },
}
```

`EngineError::Inference(#[from] seeky_infer::Error)` (SPEC-0002 §4.3) is
preserved by aliasing `pub type Error = seeky_core::InferError;` in
`seeky-infer` (replacing `Error::Message(String)` and raw `ort::Error`
strings that could leak paths).

### 4.5 Offline bake-off toolchain CLI (`tools/model-export` v2 & `tools/seeky-bench`)

#### `tools/model-export` v2 CLI

Extends the WP-0.6 package (`tools/model-export/src/seeky_model_export/`) while
retaining its external-workspace guard, pinned lockfiles, and bounded timeout
semantics (`--timeout-seconds`, exit code 124, atomic timeout JSON):

```text
python -m seeky_model_export.cli --workspace <external-dir> [--timeout-seconds <f>]
  export        --spec <candidate.json> [--static-buckets 64,128,256,512] [--attention eager|sdpa]
  quantize      --model-dir <dir> --matrix fp16,int8_dynamic,int8_static_qdq,int8_weight_only,int4_matmul_nbits
                [--calibration-data <dev-jsonl>] [--calibration-method entropy|percentile|minmax]
                [--exclude-ops LayerNorm,Softmax] [--ingest-published <onnx-path>]
  parity        --model-dir <dir> --reference <fp32-dir> --dataset <dev-sample> --role <role>
                [--provider cpu|openvino] [--isolate-child]
  emit-manifest --model-dir <dir> --parity-report <parity.json> --license-dir <dir> --out <out-dir>
  screen        --candidates <candidates.json> --dataset <dev-dataset> --cache <cache-dir>
                --seeky-bench <path-to-seeky-bench> --out <out-dir>
```

Output contract for `emit-manifest`:

```text
<out-dir>/
  model.json            schema v1 manifest (R1–R5, R28)
  parity_<comp>.jsonl   deterministic parity vectors per component (raw image bytes for vision)
  tokenizer.json        (and declared auxiliary tokenizer files)
  <comp>_<variant>.onnx (+ optional .onnx.data)
  LICENSE.txt
  NOTICE.txt
  export-provenance.json (offline build provenance: exporter, opset, torch/ort versions; not loaded at runtime)
```

Stage A screening cache layout (methodology §8.2):

```text
<cache-dir>/stage-a/<candidate-id>/<revision>/<variant>/<input-sha256>/
  vectors.npy | scores.jsonl | ocr.jsonl
  run.trec              canonical SPEC-0003 six-column TREC run (R29)
  cache-meta.json       candidate, revision, variant, input_sha256, runtime versions
```

#### `seeky-bench bakeoff` CLI (in `tools/seeky-bench`)

```text
seeky-bench bakeoff <area>
  --stage screen|deploy|confirm
  --candidates <candidates.json>
  --corpus <sdc-smoke|sdc-s|sdc-m|dataset-id>
  --output <dir>
  [--split dev|test]                  # test allowed ONLY with --stage confirm + SPEC-0003-R21 guard
  [--confirmation <manifest.json>]    # required for --stage confirm on test
  [--tier t0|t1|t1-emulated|t2]
```

`<area>` ∈ `{embedder, reranker, sparse, snippet, ocr, visual}`.

Artifacts written atomically to `--output`:

- `results.json` — versioned bake-off report extending `seeky-eval` metrics
  with Pareto frontier flags, §8.5 deployment-cost rows, budget checks
  (D2/O3/V3/S2/S6/I3/R3), and §8.6 new-engine margin checks.
- `summary.md` — Markdown report matching [`_report-template.md`](../benchmarks/_report-template.md),
  including the Pareto table and deployment-cost table.
- `pareto.json` and `deployment-costs.json` — machine-readable slices for ADR
  citations.

## 5. Behavior details

### 5.1 Fail-closed manifest validation

`ModelRegistry::inspect_manifest` validates in order and fails on the first
violation with no partial state:

1. **JSON parse & schema version:** UTF-8 JSON parsed with
   `deny_unknown_fields`; `schema_version == 1`.
2. **Identifiers:** `id`, `revision`, component `name`, `variant_id`, and
   `space_id` match `^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}$`, contain no `..`,
   no backslash, and no whitespace.
3. **Paths (R2):** every `ArtifactFile.path`, `license.license_file`, and
   `license.notice_file` is checked for relative POSIX form, then resolved
   under `model_dir` with canonical-path containment verification so symlinks
   cannot escape `model_dir`.
4. **License gate (R3, ADR-0022):**
   - Allowed SPDX set: `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`,
     `ISC`, `Zlib`, `Unicode-3.0`, `MPL-2.0`, `CC0-1.0`, `CC-BY-4.0`.
   - `status == Allowed` requires `spdx` in the allowed set.
   - `status == ReviewRequired` is rejected unless `spdx` is non-forbidden AND
     `allow_review_required == true`.
   - Forbidden prefixes/identifiers (`GPL`, `AGPL`, `LGPL`, `CC-BY-NC`,
     `CC-BY-ND`, `CC-BY-SA`, `research-only`, `proprietary`, empty) are always
     rejected regardless of caller flags.
5. **Role and modality invariants:**
   - `role == Embedding`: `space_id` is `Some`, `default_channel` is `Some`,
     every component declares `io.dimension = Some(d)` (`d >= 1`) and
     `io.metric = Some(_)`, and all components in the manifest share the same
     base `dimension` and `truncatable_to` list (if multimodal unified).
   - `modalities` contains `Image`: at least one component has
     `modality == Image` with `image_preprocessing = Some(_)`.
   - `modality == Text`: `tokenizer = Some(_)` with `max_tokens > 0` and
     `files` containing a `tokenizer.json` entry.
   - `decode` and `prompts.fixed_transcription_prompt`: allowed **only** when
     `role == OcrTranscribe`, and required for `OcrTranscribe` (`strategy ==
     Greedy`, `1 <= max_new_tokens <= 1024`, non-empty `eos_token_ids`).
   - `truncatable_to`: strictly descending, all `> 0` and `< dimension`.
   - Every numeric preprocessing parameter (`rescale_factor`, `mean`, `std`)
     and parity threshold is finite, with `rescale_factor > 0` and every
     `std[i] > 0`.
6. **File verification (R4):** deferred per component until that component is
   loaded so inspecting a multimodal manifest or loading the `text` component
   never touches `vision` files (R22).

### 5.2 Deterministic hashing for `config_snapshot` (SPEC-0002 v1.1) and `SpaceRecipe`

- **Variant `sha256`:** sort the active variant's `files` by `path` ascending.
  If there is one file, `sha256` is that file's verified 64-char lowercase hex
  SHA-256. If there are multiple files (e.g. `model.onnx` + `model.onnx.data`),
  `sha256` is the lowercase SHA-256 of the UTF-8 concatenation
  `"<path>:<sha256>\n"` for each sorted file.
- **Preprocessing recipe ID (`ActiveModelDescriptor::preprocessing`):**
  - Text component: canonical string built from `(tokenizer.revision,
    max_tokens, padding_side, pad_id, pooling, normalize, query_prompt_hash,
    passage_prompt_hash, dimension)` — stable across machines and containing
    no filesystem paths or raw prompt text if sensitive.
  - Vision component: `image_preprocessing.recipe_id` verbatim.
- **`ModelRole` → `SPEC-0002` `ModelIdentity::task` mapping:**
  `Embedding → "embedder"`, `Rerank → "reranker"`, `Sparse → "sparse"`,
  `Snippet → "snippet"`, `OcrDetect → "ocr-det"`, `OcrRecognize → "ocr-rec"`,
  `OcrTranscribe → "ocr-transcribe"`. This preserves byte compatibility with
  `SPEC-0002` §9.5.7 `"task": "embedder"` without renaming the manifest enum.
- **`SpaceRecipe` (SPEC-0006 §4.3):** constructed only when
  `role == Embedding` and `parity_group.is_some()`. A variant without a
  `parity_group` cannot write vectors to any `seeky-store` generation
  (SPEC-0006-R32, R17).

### 5.3 Pooling, Matryoshka truncation, and L2 normalization

1. Execute the ONNX graph and extract the declared output tensor (converting
   `f16` → `f32` when `dtype == F16`).
2. Check every element is finite (R10).
3. Apply `pooling`:
   - `InGraph`: expect rank-2 `[batch, dim]`.
   - `Cls`: expect rank-3 `[batch, seq, dim]`, take token 0.
   - `Mean`: expect rank-3 `[batch, seq, dim]`, compute attention-mask-weighted
     mean over valid tokens (`denom = max(sum_mask, 1.0)`).
   - `LastToken`: expect rank-3 `[batch, seq, dim]`, take the last unmasked
     token per row (respecting `padding_side`).
4. If `SessionConfig::truncation_dimension` is `Some(d)`: verify `d` is in
   `io.truncatable_to`, slice each row to `..d`.
5. If `io.normalize == true`: L2-normalize each row (`norm = sqrt(sum(v*v))`);
   if `norm <= 1e-12`, fail with `InferError::NonFiniteOutput` rather than
   silently emitting a zero vector that corrupts cosine search.

### 5.4 Batching, memory bounds, and governor cooperation

- **Query embedding (`embed_query`):** always batch 1, uses `query_session`,
  no length sorting, no batch queue. Thread count defaults to
  `min(physical_cores, 8)` (intra-op) and `1` (inter-op).
- **Indexing embedding (`embed_passages`):**
  1. Tokenize all inputs in the call using the manifest tokenizer (prepending
     `prompts.passage` if declared).
  2. Sort indices by `(token_len, original_index)` (stable sort).
  3. Pack consecutive sorted items into batches such that
     `batch.len() <= max_batch_size` and
     `batch.len() * max_len_in_batch <= max_batch_tokens` (a single item with
     `token_len <= max_tokens` always forms a batch of 1).
  4. Before each batch, check `cancel.is_cancelled()`; if true, return
     `Err(InferError::Cancelled)`.
  5. Acquire `indexing_session`, run the batch, release `indexing_session`,
     scatter outputs back to `original_index`.
- **Governor updates (`apply_governor_hint`):** updates atomic/config caps for
  `indexing_max_batch_size` and `indexing_max_batch_tokens` immediately; if
  `indexing_threads` changes, rebuilds only `indexing_session` lazily before
  the next indexing batch (never touching `query_session`, never changing the
  model or generation — ADR-0025, SPEC-0007-R7).
- **Cross-encoder reranker (ADR-0027):** truncates `passages` slice at
  `options.max_pairs`, encodes `(query, passage)` pairs truncated to
  `min(options.max_pair_tokens, tokenizer.max_tokens)`, executes in chunks of
  `options.micro_batch_size` (default 4) on the query-latency pool, checking
  `cancel.is_cancelled()` before every chunk so a new keystroke aborts within
  one micro-batch (S4 ≤ 5 ms budget).

### 5.5 Provider selection, parity-on-load, and CPU fallback

1. Resolve candidate provider order from `SessionConfig::provider_policy`:
   - `ProviderPolicy::Auto`: `[ProviderKind::Cpu]` in WP-2.1 (SPEC-0012 inserts
     measured, validated NPU providers ahead of CPU).
   - `ProviderPolicy::Explicit(p)`: `[p, ProviderKind::Cpu]` (or `[Cpu]` if
     `p == Cpu`).
2. Select the matching `ModelVariant` for the candidate provider (preferring
   variants with `parity_group.is_some()` and smallest verified byte size when
   multiple match).
3. Verify SHA-256 of all variant files and tokenizer files (R4).
4. Create the ORT session (never mutating `PATH`). If creation fails on a
   non-CPU provider, emit `InferEvent::ProviderFallback { reason: LoadFailed }`
   and fall through to `Cpu`.
5. Run `parity.jsonl` through the session if this
   `(model_id, revision, variant_id, provider, ort_version, device_fingerprint)`
   has not already been cached as verified.
   - Embedder: require `mean_cosine >= load_check_tolerance` and every single
     vector finite with cosine `>= load_check_tolerance - 0.02`.
   - Reranker: require `max_abs_logit_delta <= load_check_tolerance` (or
     Kendall τ-b `>= load_check_tolerance` when `metric == KendallTauB`).
   - OCR transcriber: require exact normalized text match (`ExactText`) or
     CER delta `<= load_check_tolerance`.
   - If parity fails on a non-CPU provider, emit
     `InferEvent::ProviderFallback { reason: ParityFailed }` and fall through
     to `Cpu`. If parity fails on `Cpu`, fail closed with
     `InferError::ParityFailed`.
6. Record the verified manifest state (`state = 'verified'`, `verified_at`) in
   the caller's `models` table record (`SPEC-0006` §4.2).

### 5.6 Graceful degradation and PoC migration

- **Lexical-first availability (ADR-0018):** if no model manifest is installed
  or the ORT library is absent, `Engine` starts with `TextEmbedder = None` and
  serves lexical and filename search normally (`SPEC-0002` `probe_query_embedding`
  returns `Unavailable`, `config_snapshot` reports `"models": []`).
- **Absent optional packs:** if a unified multimodal manifest is present but
  its `vision` variant files are not downloaded, `load_text_embedder` succeeds
  completely (R22) and `load_vision_embedder` returns
  `InferError::MissingAsset { kind: ModelWeights }`.
- **Clean migration from PoC:** WP-2.1 deletes `DIM`, `MODEL_ID`,
  `MODEL_REVISION`, `MODEL_PREPROCESSING`, `find_gety_model_root`,
  `gety_data_dir`, `gety_ort_dll`, `gety_openvino_dir`, `resolve_npu_dir`,
  `prepend_path`, `prepare_cuda_paths`, and `prepare_openvino_path`. Explicit
  development overrides (`SEEKY_ORT_LIB` for ORT DLL/dylib/so path,
  `SEEKY_MODEL_DIR` for a local manifest directory) are read only by
  `EngineConfig` / `seeky-bench` when explicitly configured, never by scanning
  `%APPDATA%\ai.gety`.

### 5.7 Privacy and tracing spans

`tracing` spans emitted by `seeky-infer`:

- `infer.manifest.validate`, `infer.model.load`, `infer.parity.verify`,
  `infer.embed.query`, `infer.embed.passages`, `infer.embed.batch`,
  `infer.rerank`, `infer.sparse.encode`, `infer.vision.preprocess`,
  `infer.vision.embed`, `infer.ocr.transcribe`.
- Allowed span fields: `model_id`, `revision`, `component`, `variant_id`,
  `provider`, `workload`, `batch_size`, `max_seq_len`, `bucket_len`,
  `truncated_count`, `tokens_generated`, `duration_ms`, `error_kind`.
- Forbidden in any span, event, or `InferError`: query text, passage text,
  OCR output, image bytes, file names, user paths, or absolute data/model
  directory paths (R9).

## 6. Acceptance

### 6.1 Tests

All Rust tests below are written **before** implementation, hermetic,
deterministic, and hardware-free by default (`cargo test --workspace`) using
temporary directories and `FakeSessionRunner` / synthetic fixtures in
`crates/seeky-infer/tests/fixtures/`. Hardware-dependent tests exercising real
`ort::Session` (on tiny <4 KB synthetic ONNX graphs or local models) sit behind
`--features hw-tests`. Python tests live in `tools/model-export/tests/` and run
offline with `pytest`.

| Test | Layer | Requirements |
|---|---|---|
| `manifest_v1_valid_round_trip`, `manifest_rejects_unknown_version_and_fields`, `malformed_manifest_never_panics` (proptest) | unit / property | R1 |
| `manifest_rejects_path_traversal_and_absolute_paths`, `loader_refuses_symlink_escape` | unit / fault | R2 |
| `manifest_rejects_forbidden_and_missing_licenses`, `review_required_license_needs_explicit_opt_in` | unit | R3 |
| `loader_verifies_all_variant_and_external_data_hashes`, `corrupt_weight_or_tokenizer_hash_is_rejected` | unit / fault | R4 |
| `prompts_applied_by_workload_only`, `pooling_modes_match_reference`, `matryoshka_truncation_preserves_unit_norm` (proptest) | unit / property | R5 |
| `explicit_ort_path_missing_returns_typed_error` + inspection (`unsafe`/`set_var`/`ai.gety`/`DIM` absent) | unit / inspection | R6 |
| `active_model_descriptor_matches_spec0002_snapshot`, `space_recipe_derives_from_manifest_and_parity_group`, `descriptor_is_path_independent` | unit | R7 |
| `text_embedder_is_send_sync` + `cargo tree -p seeky-core` + public API inspection | compile / inspection | R8 |
| `infer_errors_contain_no_sentinels`, `infer_spans_contain_no_sentinels` | unit | R9 |
| `non_finite_tensor_yields_typed_error`, `wrong_output_shape_yields_typed_error` | unit / fault | R10 |
| `query_embed_completes_while_indexing_batch_is_blocked` (barrier-synchronized, no sleeps) | concurrency | R11 |
| `indexing_batches_sort_by_length_and_restore_order`, `indexing_batches_respect_size_and_token_caps`, `indexing_cancellation_stops_between_batches`, `batching_order_invariant` (proptest) | unit / property | R12 |
| `reranker_scores_pairs_in_micro_batches`, `reranker_cancels_between_micro_batches`, `reranker_respects_max_pairs_and_token_budget`, `reranker_error_leaves_session_reusable` | unit / fault | R13 |
| `sparse_encoder_applies_activation_prunes_and_sorts`, `sparse_output_is_sorted_positive_finite` (proptest) | unit / property | R14 |
| `ocr_transcriber_is_deterministic_greedy`, `ocr_transcriber_stops_at_max_tokens_and_repetition`, `ocr_transcriber_cancels_within_interval` | unit | R15 |
| `auto_provider_resolves_to_cpu_in_v1`, `ep_failure_falls_back_to_cpu_and_emits_event`, `governor_hint_updates_indexing_caps_only` | unit / fault | R16 |
| `parity_on_load_passes_within_tolerance`, `npu_parity_failure_falls_back_to_cpu`, `cpu_parity_failure_refuses_load`, `variant_without_parity_group_cannot_write` | unit / fault | R17 |
| `static_bucket_picks_smallest_fitting_length`, `static_bucket_reports_truncation_at_max_tokens`, `ort_cache_path_is_versioned_and_isolated` | unit | R18 |
| `golden_lexical`, `golden_hybrid_cpu` (`hw-tests`, synthetic test-only manifest for PoC model) | integration | R19 |
| `multimodal_manifest_validates_text_and_vision_components`, `image_modality_without_vision_component_is_rejected` | unit | R20 |
| `vision_embedder_tags_image_modality_and_space` | unit | R21 |
| `text_query_never_opens_vision_component`, `text_loads_even_when_vision_pack_absent`, `vision_unload_keeps_text_session_serving` | unit / integration | R22 |
| `image_preprocess_matches_reference_tensor_values`, `malformed_or_oversized_image_yields_typed_error`, `vision_parity_runs_from_raw_image_bytes` | unit / fault | R23 |
| `test_workspace_inside_git_is_rejected`, `test_offline_stages_make_no_network_calls`, `test_timeout_writes_atomic_artifact_and_exits_124` | pytest | R24 |
| `test_export_encoder_and_static_bucket`, `test_export_split_ocr_graph`, `test_export_records_opset_and_attention_mode` | pytest | R25 |
| `test_quantize_matrix_and_external_data`, `test_quantize_rejects_test_split_calibration`, `test_failed_quantization_cleans_up_partial_files` | pytest | R26 |
| `test_embedder_parity_requires_cosine_recall_and_ndcg`, `test_reranker_parity_requires_tau_and_ndcg`, `test_ocr_parity_requires_cer_and_hallucination`, `test_npu_probe_crash_is_isolated_and_reported` | pytest | R27 |
| `test_emit_manifest_deterministic_and_schema_valid` (pytest) + `emitted_manifest_loads_in_seeky_infer` (Rust integration, tiny synthetic ONNX + `hw-tests` ORT CPU) | cross-language integration | R28 |
| `test_screen_cache_key_and_reuse`, `test_screen_emits_valid_spec0003_trec_run` | pytest | R29 |
| `bakeoff_screen_writes_pareto_and_summary`, `bakeoff_deploy_writes_cost_table`, `bakeoff_confirm_enforces_test_guard` | integration (`seeky-bench`) | R30 |

### 6.2 Benchmark gates

Budgets are provisional until locked by the WP-1.7 budgets ADR. WP-2.1, WP-2.2,
and WP-2.13 introduce no new default model; they establish the runtime and
toolchain contracts checked by the gates below (no regression versus B0 on
WP-2.1; model-selection gates run in WP-2.6, WP-3.8, WP-4.8, and Phase 10).

| Gate | Dataset/split | Tier | Threshold | Baseline report |
|---|---|---|---|---|
| S2 (Hybrid p95, including batch-1 query embedding) | `sdc-s` | T1 CPU-only | no regression vs B0 outside CI; target ≤ 120 ms (query embed ≤ 20 ms K1) | B0 (WP-1.7) |
| S4 (cancellation between reranker micro-batches / indexing batches) | `sdc-s` | T1 CPU-only | ≤ 5 ms | — |
| S5 (interference ratio under indexing, separate query/index sessions) | `sdc-s` | T1 CPU-only | ≤ 1.5 | B0 |
| S6 (progressive reranker refinement at default depth ≥ 10, ADR-0027) | `sdc-s` | T1 CPU-only | ≤ 1.5 s p95 (measured in WP-4.8) | WP-0.6 gate report |
| I3 (sustained embedding throughput) | `sdc-s` | T1 CPU-only | ≥ 56 passages/s (≤ 30 min for 100k passages) | WP-0.6 gate report |
| R3, R6 (peak RSS; cold load to semantic-capable) | `sdc-s` / `sdc-m` | T1 CPU-only | R3 ≤ 1.5 GB; R6 ≤ 3 s | B0 |
| D2 (default runtime + embedder + reranker download) | — | — | ≤ 250 MB (enforced by `seeky-bench bakeoff`) | WP-0.6 gate report |
| V4 (text Hybrid p95 with multimodal manifest present) | `sdc-s` | T1 CPU-only | S2 unchanged; zero vision bytes loaded | Phase 10 |

### 6.3 Inspection

- `seeky-core` depends only on `serde` and `thiserror` (SPEC-0001-R14); `ort`
  and `tokenizers` are direct dependencies only of `seeky-infer` (SPEC-0001-R13).
- Zero `unsafe` blocks and zero `std::env::set_var` / `remove_var` calls in
  `crates/seeky-infer/` (closes audit A9 and SPEC-0001 §5.3 entry).
- Zero hardcoded model dimensions, tensor names, prompts, pad IDs, or
  `ai.gety` discovery paths in `crates/` (P8, audit A10).
- No generative sampling API, no user-supplied prompt parameter on
  `OcrTranscriber`, and no non-OCR generative model role anywhere in the
  manifest or traits (ADR-0021).
- `cargo deny check`, `cargo clippy --workspace --all-targets -- -D warnings`
  (with and without `--features hw-tests`), `cargo test --workspace`, and
  `pytest tools/model-export/tests` all pass.

## 7. Risks and open questions

Blocking questions must be resolved by the maintainer at gate H7 before this
spec moves from `Draft` to `Accepted`.

| # | Question or risk | Options & proposed default | Who decides / when | Blocking acceptance? |
|---|---|---|---|---|
| Q1 | **Manifest file format on disk (`model.json` vs `model.toml`).** Document conflict: `inference-and-models.md` §4, `distribution-and-provisioning.md` §4–§5, and plan WP-2.2 show `model.toml`, whereas `GENERATION.json`, provisioning `manifest.json`, `SPEC-0006` `models.manifest`, and `SPEC-0002` `config_snapshot` are canonical JSON, and the Cargo workspace already has `serde_json` with no `toml` crate. | **Option A (Recommended):** standardize on `model.json` (zero new Rust dependencies, one canonical format across storage/provisioning/snapshots) and update the three doc references at acceptance. **Option B:** keep `model.toml` on disk, add `toml` (MIT/Apache-2.0) to `seeky-infer`, and convert to canonical JSON for hashing and SQLite storage. | Maintainer (H7) | **Yes** |
| Q2 | **Fate of PoC native `openvino` and `CUDA` code in `seeky-infer` during WP-2.1.** ADR-0019 decision 5 removes native OpenVINO unless WP-5.2 proves a material advantage over OpenVINO EP; WP-5.7 freezes PoC CUDA. Keeping both in the default build pulls `openvino`/`openvino-sys` into `seeky-infer` and complicates removing `prepend_path` (audit A9). | **Option A (Recommended):** delete PoC CUDA and `prepend_path` in WP-2.1, and gate the PoC native OpenVINO code behind an off-by-default Cargo feature `legacy-openvino` (loading `openvino_c.dll` by explicit path only, zero `PATH` mutation, excluded from `Auto` and default builds) until WP-5.2 decides its fate. **Option B:** remove native OpenVINO completely in WP-2.1 (would require re-adding a benchmark wrapper if WP-5.2 compares native IR). | Maintainer (H7) | **Yes** |
| Q3 | **Loading optional NPU EP shared libraries without `PATH` mutation (audit A9).** WP-2.1 only needs `ort::init_from(abs_path)` for CPU EP (zero `unsafe`). In Phase 5, Windows EP DLLs (`onnxruntime_providers_openvino.dll` + runtime deps) need deterministic DLL resolution without `std::env::set_var("PATH", ...)`. | **Option A (Recommended):** WP-2.1 ships pure CPU EP with zero `unsafe` in `seeky-infer`; SPEC-0012 resolves Phase 5 EP dependencies by co-locating EP libraries inside the versioned ORT runtime directory or using ORT's explicit EP registration / audited Windows `AddDllDirectory` (never `set_var`). **Option B:** land an audited `AddDllDirectory` loader helper in WP-2.1 ahead of Phase 5. | Maintainer (H7) | **Yes** |
| Q4 | **Image decoding dependency for WP-2.13 raw-byte vision parity (R23).** ADR-0023 requires vision parity vectors to start from raw image bytes. `seeky-infer` currently has no image-decoding crate. | **Option A (Recommended):** add `image` (MIT/Apache-2.0, `default-features = false, features = ["png", "jpeg", "webp"]`) to `seeky-infer` in WP-2.13 (license-checked via `cargo-deny`), implementing `Encoded` + `Rgb8` inputs and raw-byte parity immediately. **Option B:** accept `Rgb8` only in WP-2.13 with a minimal pure-Rust bilinear/bicubic kernel and add `image` only in Phase 10 (defers encoded raw-byte parity until SPEC-0016). | Maintainer (H7) | **Yes** |
| Q5 | **PoC `seeky_infer::Embedder` replacement and `golden_hybrid_cpu` continuity.** Removing hardcoded PoC constants (R6) affects `seeky-engine`'s `golden_hybrid_cpu` test (`hw-tests`). | **Option A (Recommended):** replace `seeky_infer::Embedder` with `seeky_core::TextEmbedder` across `seeky-infer`, `seeky-search`, and `seeky-engine` in WP-2.1, and keep `golden_hybrid_cpu` passing via a `#[cfg(test)]` manifest fixture wrapping the local PoC model until WP-2.6 selects the default embedder. **Option B:** keep a deprecated compatibility adapter in `seeky-infer` until WP-2.6. | Maintainer (H7) | **Yes** |
| Q6 | Provisional thread-count defaults (`query_intra_op_threads = min(physical_cores, 8)`, `indexing_intra_op_threads = max(1, physical_cores / 2)`, `inter_op_threads = 1`). | Accept as provisional defaults in WP-2.1; tune and lock via WP-2.6 (embedder bake-off) and WP-8.5 (energy/governor report). | Maintainer / WP-2.6 | No |
| Q7 | Hardware-free CI testing of `seeky-infer` without `onnxruntime.dll`/`libonnxruntime.so`. | Use crate-internal `SessionRunner` fake in default `cargo test --workspace` and run real `ort::Session` on <4 KB synthetic ONNX fixtures under `--features hw-tests`. | Implementer | No |
| Q8 | `SPEC-0006` §4.2 `models` table skeleton (`id, revision, manifest, state, verified_at`). | Keep the v2 skeleton unchanged in WP-2.1 (canonical manifest JSON in `manifest`, `state ∈ {"registered","verified","quarantined","retired"}`); no schema v3 migration needed. | Maintainer | No |
| R-a | Two ORT sessions per embedder (query + indexing) duplicate model weights in RAM unless ORT's `SessionOptions::AddInitializer` / shared-weights API or OS page-cache sharing reduces RSS; during a model swap (two embedders), RSS could pressure R3 (≤ 1.5 GB). | Measure added RSS of dual sessions in WP-2.1/WP-2.6 on T1-emulated; use ORT shared-allocator / weight-sharing options if dual sessions exceed 1.3× single-session RSS. | WP-2.1 / WP-2.6 | No |
| R-b | Static-QDQ quantization collapsed on MinMax calibration in WP-0.6 (§3.2). | `tools/model-export` v2 supports Entropy/Percentile calibration and sensitive-op exclusions, and never emits a `parity_group` when parity fails (R26, R27). | WP-2.2 | No |

### Document conflicts noted while drafting

Per `AGENTS.md` §2, conflicts are reported rather than silently resolved:

1. **Manifest filename (`model.toml` vs `model.json`):** `docs/architecture/inference-and-models.md` §4, `docs/architecture/distribution-and-provisioning.md` §4–§5, and `docs/plans/seeky-implementation-plan.md` WP-2.2 name `model.toml`, whereas this draft proposes canonical `model.json` (Q1). If Option A is accepted at H7, those three references should be updated in the acceptance commit.
2. **Trait names (`Embedder` / `Reranker` vs `TextEmbedder` / `VisionEmbedder` / `CrossEncoderReranker`):** `docs/architecture/inference-and-models.md` §1 and `ADR-0019` list `Embedder` and `Reranker`. Splitting `TextEmbedder` and optional `VisionEmbedder` enforces `ADR-0023` decision 1.6 (text query path never loads vision) at the type level; `inference-and-models.md` §1 can be noted as refined by this spec at acceptance.
3. **Task string (`"embedding"` vs `"embedder"`):** `inference-and-models.md` §4 uses `task = "embedding"`, while `SPEC-0002` §9.5.7 uses `"task": "embedder"` in `config_snapshot`. §5.2 defines the explicit deterministic mapping so both contracts stay consistent without breaking `SPEC-0002`.

## 8. Changelog

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-11-28 | Initial draft (Lane N): Model Manifest v1 schema and validation, `seeky-core` inference traits and privacy-safe `InferError`, `seeky-infer` dual-session ORT adapter closing audit A5/A7/A9/A10, ADR-0027 progressive reranking and ADR-0021 OCR greedy decoder hooks, WP-2.13 multimodal/component contracts and lazy vision residency, and WP-2.2 offline `tools/model-export` v2 + `seeky-bench bakeoff` toolchain |
