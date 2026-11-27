# SPEC-0004 — Seeky Desktop Corpus and relevance judgments

| Field | Value |
|---|---|
| Status | Accepted (maintainer pre-approval in /goal) |
| Version | 0.1 (text corpus v1; the WP-10.1 visual slice requires a later spec version) |
| Owner | Maintainer |
| Phase / work packages | Phase 1 — WP-1.3, WP-1.4; Phase 10 — WP-10.1 (later version) |
| Crates touched | None. Offline generator under `tools/sdc-generator/`; data under `bench/`; consumed by `seeky-eval` (SPEC-0003) |
| Governing docs | [vision](../product/vision.md) §2 (P3, P5–P8); [methodology](../benchmarks/methodology.md) §2, §6, §8.2 and §10; [ADR-0019](../adr/0019-single-inference-engine.md); [ADR-0021](../adr/0021-no-generative-models-in-product.md); [ADR-0022](../adr/0022-permissive-license-gate.md); [ADR-0023](../adr/0023-multimodal-ready-engine.md); [ADR-0024](../adr/0024-source-code-indexing-opt-in.md); [SPEC-0001](SPEC-0001-workspace-and-crate-boundaries.md); [SPEC-0002](SPEC-0002-engine-api.md) |
| Benchmark gates | Supplies datasets for Q1–Q7 and the WP-1.8 smoke gate. This version defines no visual Q8 data and changes no latency or resource budget |

## 1. Problem and goal

Public passage-retrieval datasets do not reproduce the desktop-search jobs
Seeky must serve: forgotten filenames, identifiers buried in office files,
multilingual folders, long documents, duplicate versions, boilerplate, scanned
copies, and mixed semantic/metadata intent. Seeky therefore needs its own
reproducible corpus before it can choose models or ranking components without
overfitting to a public leaderboard or to a developer's files.

This specification defines the Seeky Desktop Corpus (SDC), its deterministic
generator, and its query and graded-judgment formats. The generated files must
exercise the real extractors through the headless `Engine` API, while canonical
text and passage locators remain independent of any engine chunking recipe.
Every source must be pinned and licensed for its intended redistribution mode.
Every item used for a gate must be traceable to its author or drafting model
and to human verification; an LLM is an offline drafting aid, never an
authority (ADR-0021).

Done for WP-1.3 is a reproducible `sdc-smoke` corpus committed within the size
cap, plus on-demand `sdc-s` and `sdc-m` profiles whose bulk output is not
committed. Done for WP-1.4 is a versioned set of at least 600 queries across
nine categories, with document- and passage-level judgments drafted and then
human-verified before benchmark use. The WP-10.1 visual slice is deliberately
not part of version 0.1.

## 2. Scope

- **In:** source acquisition and license manifests; canonical document and
  passage representations; deterministic PDF, office, text, e-mail, and scanned
  rendering; exact/near-duplicate, version, rename/move, and boilerplate
  fixtures; `sdc-smoke`, `sdc-s`, and `sdc-m` profiles; nine text query
  categories; deterministic dev/test assignment; graded document and passage
  qrels; snippet evidence spans; duplicate-cluster labels; pooling and
  provenance; draft-to-verified workflow; validation of all committed SDC data.
- **Out:** public datasets and their download scripts (SPEC-0003/WP-1.5);
  metric and statistical definitions, TREC export, and test-split enforcement
  in `seeky-bench` (SPEC-0003); engine extractors and chunking (SPEC-0008);
  model weights or any inference in corpus generation; real-scan transcription
  procurement for OCR Stage A (WP-2.11 extends the truth data); visual units,
  visual queries, image-as-query data, and visual judgments (WP-10.1, later
  SPEC-0004 version); private user corpora; any product runtime or UI feature.

## 3. Requirements (EARS)

All requirements are open. The WP column is the implementation owner.

| ID | WP | Requirement | Verification | Status |
|---|---|---|---|---|
| SPEC-0004-R1 | WP-1.3 | The generator shall obtain every non-synthetic source item from a pinned source URL whose upstream revision, expected byte length, media type, and SHA-256 are recorded in a source manifest, and shall reject a missing pin or a digest mismatch. | `source_item_requires_complete_pin`; `source_download_rejects_sha256_mismatch` | Implemented (WP-1.3) |
| SPEC-0004-R2 | WP-1.3 | The generator shall record a license identifier, license-text URL and digest, redistribution class, and attribution/notice for every source item; if an item is ineligible for the committed permissive core, then it shall exclude that item from `sdc-smoke` and either reject it or isolate it in the separately licensed extension defined in §5.2. | `source_manifest_requires_license_and_notice`; `core_rejects_ineligible_or_missing_license`; inspection of notices | Implemented (WP-1.3) |
| SPEC-0004-R3 | WP-1.3 | When the source cache, profile, seed, generator version, and locked renderer environment are identical, the generator shall produce a byte-identical output tree, including file bytes, IDs, timestamps, JSONL ordering, and `corpus_hash`, without reading the wall clock, host name, user name, or absolute checkout path. | `same_seed_rebuild_is_byte_identical`; `manifest_contains_no_host_specific_data`; cross-platform golden hash check | Implemented (WP-1.3) |
| SPEC-0004-R4 | WP-1.3 | The generator shall emit the layout and versioned JSON/JSONL interfaces in §4.3, with POSIX relative paths, lowercase hexadecimal SHA-256 hashes, stable content references, and a manifest that detects any changed, missing, or additional output file. | `corpus_layout_matches_schema`; `manifest_detects_added_changed_and_missing_files`; `ids_and_target_hashes_survive_regeneration` | Implemented (WP-1.3) |
| SPEC-0004-R5 | WP-1.3 | The generator shall provide `sdc-smoke`, `sdc-s`, and `sdc-m` profiles with the limits in §4.4; the repository shall commit only the generated `sdc-smoke` corpus, and `sdc-s` and `sdc-m` shall be generated on demand without committing their bulk documents or sidecar JSONL. | `smoke_profile_meets_file_and_size_caps`; `scale_profiles_meet_document_and_passage_ranges`; repository-size inspection | Implemented (WP-1.3) |
| SPEC-0004-R6 | WP-1.3 | The generator shall use only public-domain or appropriately licensed sources or newly synthesized office content, and synthetic content shall use fictitious entities, reserved example identifiers, and no personal documents, credentials, real contact details, or secrets. | source review; `synthetic_content_uses_reserved_example_domains`; secret/personal-data scan | Implemented (WP-1.3) |
| SPEC-0004-R7 | WP-1.3 | The generator shall render the canonical block model into text PDF, DOCX, XLSX, PPTX, ODT, RTF, HTML, EPUB, EML, Markdown, TXT, and source-code fixtures, preserving canonical text references and structural locators for each renderer. | parameterized `renderer_round_trip_preserves_text_and_locators` for every format; extractor golden tests | Implemented (WP-1.3) |
| SPEC-0004-R8 | WP-1.3 | Where a scanned variant is requested, the generator shall render deterministic page images and image-only PDFs at the declared dpi, noise, skew, and compression settings, with no hidden text layer, and shall emit page-aligned known-text ground truth for extraction and OCR evaluation. | `scanned_pdf_has_no_text_layer`; `scan_recipe_is_deterministic`; `scan_truth_matches_canonical_pages` | Implemented (WP-1.3) |
| SPEC-0004-R9 | WP-1.3 | When duplicate injection is enabled, the generator shall create the configured exact-byte, exact-text, scanned, and near-duplicate relationships, assign cluster labels independently of file paths, and include renamed and moved copies without changing their stable document identities. | `duplicate_injection_counts_and_clusters_match_profile`; `renamed_and_moved_copies_keep_identity`; duplicate property tests | Implemented (WP-1.3) |
| SPEC-0004-R10 | WP-1.3 | When version injection is enabled, the generator shall create ordered version groups with explicit changed passages, `version_number`, and `is_latest` metadata, while assigning a distinct document ID to each version. | `version_groups_are_ordered_and_changed_spans_are_valid`; `each_version_has_distinct_document_id` | Implemented (WP-1.3) |
| SPEC-0004-R11 | WP-1.3 | When boilerplate injection is enabled, the generator shall insert the configured shared headers, footers, disclaimers, and navigation blocks and shall mark every injected passage and its source family without marking unique body text as boilerplate. | `boilerplate_counts_and_families_match_profile`; property test `only_injected_spans_are_boilerplate` | Implemented (WP-1.3) |
| SPEC-0004-R12 | WP-1.3 | Where a profile contains source code, the generator shall label it `file_class = "source_code"`, place it under a disjoint code root, and emit `default` and `code_enabled` roots such that `default` excludes all source code and `code_enabled` includes it, consistent with ADR-0024 and the conflict recorded in §7. | `default_root_contains_no_source_code`; `code_enabled_root_adds_only_code`; `code_queries_require_code_enabled_configuration` | Implemented (WP-1.3) |
| SPEC-0004-R13 | WP-1.3 | If a source manifest, cached source, profile, canonical document, or output sidecar is malformed, then the generator shall stop with a typed, location-bearing error and no panic, shall not silently skip the item, and shall leave any pre-existing output tree unchanged. | malformed-input matrix; `failed_build_is_atomic`; fuzz targets for JSON/JSONL and source-cache readers | Implemented (WP-1.3) |
| SPEC-0004-R14 | WP-1.3 | The generator shall be development-only tooling under `tools/sdc-generator/`, with the command interface in §4.1; only `fetch` may use the network, and `build`, `verify`, and judgment validation shall work with networking disabled. | `build_and_verify_never_access_network`; command smoke tests; dependency/license inspection | Implemented (WP-1.3) |
| SPEC-0004-R15 | WP-1.4 | The query set shall represent exactly the nine category values in §4.5 in the query schema, and each query shall carry language, target-language, split, evaluation-configuration, and provenance fields; mixed metadata queries shall additionally carry structured filters rather than encoding them only in prose. | `query_schema_accepts_all_nine_categories`; `mixed_metadata_queries_have_structured_filters`; malformed-query tests | Open |
| SPEC-0004-R16 | WP-1.4 | The full `sdc-v1` judgment set shall contain at least 600 distinct queries, at least 300 in each of `dev` and `test`, and at least 30 queries per category per split, assigned by the frozen stratified procedure in §5.4 before any system output is inspected. | `full_query_set_meets_category_and_split_minima`; `split_assignment_is_stratified_deterministic_and_predates_pools` | Open |
| SPEC-0004-R17 | WP-1.4 | The full query set shall contain at least 100 Portuguese and 100 English monolingual queries overall and at least 40 of each per split, at least 30 cross-language queries per split, at least 20 queries each for Spanish, French, and German overall, and at least 10 non-Latin non-regression queries. | `language_and_cross_lingual_slices_meet_minima`; `non_latin_queries_are_non_regression_only` | Open |
| SPEC-0004-R18 | WP-1.4 | Document judgments shall use the graded schema in §4.6 with integer relevance 0–3 and the rubric in §5.5, and shall allow a known-item target, its explicitly judged duplicates, and multiple relevant exploratory documents without collapsing them into an assumed single answer. | `document_qrels_validate_grades_and_references`; `known_item_duplicates_and_multiple_relevant_docs_are_representable` | Open |
| SPEC-0004-R19 | WP-1.4 | Passage judgments shall reference stable canonical passage IDs and use integer relevance 0–3; where snippet evidence is supplied, its UTF-8 half-open offsets shall lie inside the referenced canonical passage and delimit the exact supporting text. | `passage_qrels_validate_grades_and_target_hashes`; `snippet_spans_are_ordered_in_bounds_and_exact` | Open |
| SPEC-0004-R20 | WP-1.4 | Every query, document judgment, and passage judgment shall carry `drafted_by`, `verified_by`, and `state` provenance; an LLM-drafted item shall also carry immutable model/revision and prompt-hash fields, and an adjudicated item shall identify the human adjudicator and at least two distinct participating human reviewers. | `provenance_is_complete_for_human_and_llm_drafts`; `adjudication_requires_distinct_humans_and_adjudicator` | Open |
| SPEC-0004-R21 | WP-1.4 | When an LLM drafts queries or candidate judgments, the drafting tool shall run offline as development tooling, and a human shall verify the query intent and every relevance grade against the referenced corpus text before the item can enter a benchmark-eligible split. | workflow inspection; `llm_draft_cannot_be_promoted_without_human_verification`; network-boundary test of drafting tool | Open |
| SPEC-0004-R22 | WP-1.4 | If an item is unverified or lacks required provenance, then the publisher shall refuse its promotion and the SDC loader shall reject any benchmark set containing it; rejected and draft records may retain an intended split only in the quarantined draft area and shall never enter `test`. | `draft_judgment_set_is_not_benchmark_eligible`; `unverified_item_never_enters_test`; `promotion_rejects_missing_provenance` | Open |
| SPEC-0004-R23 | WP-1.4 | Once a judgment set has been used on `test`, the publisher shall keep its query membership and split assignments immutable and shall write corrections or additional judgments under a new judgment-set version rather than moving, deleting, or silently rewriting test history. | `frozen_test_membership_and_splits_are_immutable`; `correction_creates_new_judgment_set_version`; audit-trail inspection | Open |
| SPEC-0004-R24 | WP-1.4 | For each system under test, the pooling workflow shall union document and passage candidates through depth 20, include known targets and manually discovered candidates, and require every pooled candidate to have an explicit verified or adjudicated judgment before the judgment set is frozen; the `test` pooling panel shall be predeclared before the first test exposure and later candidates shall not expand it under the same judgment-set version. | `pool_is_depth_20_union_of_all_systems`; `known_targets_and_manual_candidates_are_pooled`; `frozen_pool_has_no_unjudged_candidate`; `test_pool_panel_precedes_exposure` | Open |
| SPEC-0004-R25 | WP-1.4 | The judgment schema shall distinguish an explicit grade 0 from an absent judgment and shall bind each judged target to its document or passage text SHA-256 so that stale judgments fail validation instead of silently attaching to changed content. | `explicit_zero_is_distinct_from_unjudged`; `changed_target_text_invalidates_qrel` | Open |
| SPEC-0004-R26 | WP-1.4 | The committed `sdc-smoke-v1` set shall provide at least five human-verified `dev` queries per category with document and passage judgments and no benchmark-eligible `test` split; its eight non-code categories shall support the default WP-1.8 run and its code category shall require a separate code-enabled run. | `smoke_queries_cover_every_category_five_times`; `smoke_has_no_test_split`; `smoke_default_and_code_runs_use_disjoint_configurations` | Open |
| SPEC-0004-R27 | WP-1.4 | Where `sdc-m` reuses the `sdc-s` query and judgment lineage, it shall preserve every judged target byte-for-byte and shall complete a new depth-20 pool top-up for candidates introduced at that scale before a new `test` gate is frozen. | `medium_profile_preserves_small_judged_targets`; `medium_test_freeze_requires_scale_specific_pool_topup` | Open |

Status: `Open` → `Implemented` (code/data and tests merged, tagged with the WP)
→ `Verified` (applicable benchmark gate passed with a linked report). The
implementing commit updates only the relevant rows; the spec header and index
remain maintainer-controlled lifecycle records.

## 4. Interfaces

### 4.1 Tool location and commands

The implementation is a Python 3.12 package in `tools/sdc-generator/`,
installed only into an isolated development environment. It is dataset-prep
tooling, is never imported by an engine crate, and never ships. Its renderer,
font, and other dependency assets are hash-locked and license-checked as
required by §7.

After installation, commands run from the repository root:

```text
python -m sdc_generator fetch \
  --sources bench/corpora/sdc/sources \
  --cache <source-cache>

python -m sdc_generator build \
  --profile bench/corpora/sdc/profiles/sdc-smoke.json \
  --seed sdc-smoke-v1 \
  --sources bench/corpora/sdc/sources \
  --cache <source-cache> \
  --output bench/corpora/sdc/sdc-smoke

python -m sdc_generator verify \
  --output bench/corpora/sdc/sdc-smoke

python -m sdc_generator judgments validate \
  --set bench/qrels/sdc/sdc-v1 \
  --corpus bench/corpora/sdc/sdc-s

python -m sdc_generator judgments validate \
  --set bench/qrels/sdc/drafts/sdc-v1 \
  --corpus bench/corpora/sdc/sdc-s \
  --allow-draft

python -m sdc_generator judgments freeze-split \
  --draft bench/qrels/sdc/drafts/sdc-v1

python -m sdc_generator judgments publish \
  --draft bench/qrels/sdc/drafts/sdc-v1 \
  --output bench/qrels/sdc/sdc-v1
```

`fetch` downloads only public source and license URLs into a content-addressed
cache. `build` never downloads; a cache miss is an error. `verify` recalculates
all output hashes and validates cross-references. `judgments validate` checks
the schemas, cardinalities, target hashes, pool coverage, and provenance. It
rejects a frozen set containing drafts. `--allow-draft` is valid only under
`bench/qrels/sdc/drafts/` and never makes the set benchmark-eligible.
`judgments freeze-split` requires human-verified query provenance, validates the
query minima, and records immutable query hashes before any run pool is added.
`judgments publish` requires a split-frozen draft, omits records explicitly
marked `rejected`, fails if any other record is unverified or lacks provenance,
freezes all file hashes, and refuses to overwrite an existing frozen set.

All commands exit nonzero on the first structural error and print a machine-
readable error on stderr as
`{"code":"...","file":"...","line":123,"field":"...","message":"..."}`.
Paths in diagnostics are repository-relative or cache-relative, never absolute.
Successful `build`, `verify`, and `publish` also print the resulting SHA-256.

### 4.2 Source manifests and profiles

`bench/corpora/sdc/sources/<source-set>.json` is UTF-8 JSON with this shape:

```json
{
  "schema_version": 1,
  "source_set_id": "public-text-v1",
  "redistribution_class": "permissive-core",
  "items": [
    {
      "source_item_id": "stable-source-specific-id",
      "origin": "external",
      "url": "https://example.invalid/immutable/source-revision",
      "byte_length": 12345,
      "media_type": "text/plain",
      "sha256": "<64 lowercase hex characters>",
      "license": {
        "id": "CC-BY-4.0",
        "text_url": "https://example.invalid/immutable/license",
        "text_sha256": "<64 lowercase hex characters>",
        "attribution": "<required attribution or empty for public domain>",
        "notice_path": "notices/<source-item-id>.txt"
      }
    }
  ]
}
```

The example host is reserved and is not an actual source. Real manifests may
use a versioned release URL plus an immutable content hash; a mutable URL is
acceptable only if `sha256` pins the content and the manifest records the
upstream revision in `source_item_id`. Redirects do not relax the digest check.

For an `origin = "synthetic"` item, `url`, `byte_length`, `media_type`, and
`sha256` are replaced by `template_id` and `template_sha256`, which pin a
committed synthetic template. Its license is the repository's MIT license or
another declared permissive license. The generator records the resulting
canonical source bytes in each corpus row's `source_sha256`. Every other item
uses `origin = "external"` and the complete external pin shown above.

`redistribution_class` is one of:

| Value | Meaning |
|---|---|
| `permissive-core` | Public domain, CC0, CC-BY-4.0, or an ADR-0022-compatible permissive license; eligible for committed `sdc-smoke` with required notices |
| `sharealike-extension` | CC-BY-SA encyclopedia text, isolated as in §5.2 and never mixed into the MIT-licensed core output or its notices |
| `local-only` | Research-only or otherwise non-redistributable input; never an SDC source and rejected here (such datasets belong to SPEC-0003) |

License IDs use SPDX where one exists and otherwise a stable `LicenseRef-*`
value reviewed by the maintainer. `LicenseRef-Public-Domain` requires the
public-domain basis in `attribution`. Missing, unclear, NC, ND, or research-only
terms are errors in SDC, not warnings. Every renderer dependency, embedded
font, and other non-source asset is pinned and licensed in an equivalent
`assets` array; its license is not inherited from the document source.

A profile in `bench/corpora/sdc/profiles/<scale>.json` contains:

```json
{
  "schema_version": 1,
  "corpus_id": "sdc-smoke",
  "source_set_ids": ["public-text-v1", "synthetic-office-v1"],
  "default_seed": "sdc-smoke-v1",
  "extends": null,
  "target_documents": 200,
  "target_passages": 2400,
  "max_committed_bytes": 67108864,
  "renderers": ["pdf", "scanned-pdf", "scanned-image", "docx", "xlsx", "pptx", "odt", "rtf", "html", "epub", "eml", "md", "txt", "code"],
  "injection": {
    "exact_byte_copies": 12,
    "exact_text_copies": 8,
    "scanned_variants": 12,
    "near_duplicate_documents": 12,
    "version_groups": 8,
    "boilerplate_documents": 32
  },
  "scan_recipes": ["clean-300dpi", "noise-skew-jpeg-300dpi"],
  "clock_start": "2018-01-01T00:00:00Z",
  "clock_end": "2025-12-31T23:59:59Z"
}
```

For smoke, `target_documents` and every `injection` value are exact required
counts; `target_passages` is a planning target rather than a required exact
count. `sdc-s` and `sdc-m` profiles use the same fields with
positive counts for every mechanism. `extends` is `null` for smoke and `sdc-s`,
and is `"sdc-s"` for `sdc-m`. Every random or generated timestamp is derived
from the seed inside the profile's closed UTC interval.

### 4.3 Corpus output and JSONL records

The committed and generated trees have this layout:

```text
bench/corpora/sdc/
  sources/                         pinned JSON manifests + notices
  profiles/                        scale and renderer recipes
  sdc-smoke/                       only committed generated corpus
    manifest.json
    corpus.jsonl                   BEIR-compatible canonical documents
    passages.jsonl                 canonical gold passages, not engine chunks
    extraction-truth.jsonl         text/OCR truth by locator
    duplicate-clusters.jsonl
    versions.jsonl                 version membership and changed passages
    files/
      documents/                   default indexing root
      code/                        disjoint opt-in code indexing root
  sdc-s/                           generated locally; bulk not committed
  sdc-m/                           generated locally; bulk not committed

bench/qrels/sdc/
  drafts/<judgment-set-id>/        quarantined, not benchmark-eligible
  <judgment-set-id>/
    judgment-set.json
    queries.dev.jsonl
    queries.test.jsonl             omitted for sdc-smoke-v1
    qrels.dev.documents.jsonl
    qrels.test.documents.jsonl
    qrels.dev.passages.jsonl
    qrels.test.passages.jsonl
    pools.dev.jsonl
    pools.test.jsonl
    reviewers.json                 pseudonymous reviewer IDs and roles only
```

JSON is UTF-8 with LF newlines. Manifest JSON uses sorted keys and two-space
indentation. JSONL uses one compact object per line, sorted by the stable ID of
its primary record, with no blank lines or comments. For a hash over a JSON
object, canonical JSON instead means sorted keys, compact separators, no
insignificant whitespace, and no trailing newline. No record contains an
absolute path. A parser rejects unknown schema versions, duplicate primary
keys, invalid UTF-8, trailing data, and unknown enum values. Sort keys are
`_id` for corpus/passages/queries, `(document_id, canonical locator JSON)` for
extraction truth, `cluster_id` for duplicate clusters, `version_group_id` for
versions, `(query_id, document_id)` for document qrels, `(query_id, document_id,
passage_id)` for passage qrels, and `(query_id, document_id, passage_id, origin,
run_id)` for pools, with null represented by an empty sort string.

Each `corpus.jsonl` row is compatible with the BEIR document fields and adds
SDC metadata:

```json
{
  "_id": "doc-<stable-id>",
  "title": "<canonical title>",
  "text": "<canonical UTF-8 text>",
  "metadata": {
    "relative_path": "files/documents/<relative-file>",
    "media_type": "application/pdf",
    "format": "pdf",
    "languages": ["pt"],
    "file_class": "document",
    "source_set_id": "synthetic-office-v1",
    "source_item_id": "<stable-source-item>",
    "source_sha256": "<source bytes SHA-256>",
    "content_sha256": "<rendered file bytes SHA-256>",
    "text_sha256": "<canonical text SHA-256>",
    "byte_count": 12345,
    "modified_at": "2024-01-02T03:04:05Z",
    "render_recipe_id": "<profile-renderer-and-options>",
    "duplicate_cluster_ids": [],
    "version_group_id": null,
    "version_number": null,
    "is_latest": null,
    "boilerplate_family_ids": []
  }
}
```

`relative_path` is relative to the corpus root and uses `/`. `format` is one of
the §4.2 renderer IDs; scanned images use `scanned-image`, and scanned PDFs use
`scanned-pdf`. `languages` contains BCP-47 tags. `file_class` is `document` or
`source_code`. `content_sha256` hashes the exact bytes at `relative_path`;
`text_sha256` hashes the exact `text` string encoded as UTF-8. Synthetic
`modified_at` values support metadata queries and do not describe generation
time. Version fields are either all null or all populated for a versioned
record. The loader must not derive relevance or identity from a path or title.

Each `passages.jsonl` row is:

```json
{
  "_id": "doc-<stable-id>:p:<stable-block-id>",
  "document_id": "doc-<stable-id>",
  "text": "<exact substring of the canonical document text>",
  "start_utf8": 120,
  "end_utf8": 640,
  "text_sha256": "<passage text SHA-256>",
  "kind": "paragraph",
  "locator": {"page": 1, "block_id": "b-0004"},
  "boilerplate_family_id": null
}
```

Canonical text is NFC with LF line endings; case, punctuation, and diacritics
are preserved. Offsets are zero-based UTF-8 byte offsets into the document's
`text`, with an exclusive end. `passages[doc]` is ordered by `(start_utf8,
end_utf8, _id)`, may overlap only for a heading/context unit explicitly marked
`kind = "context"`, and never crosses a document boundary. `kind` is
`heading`, `paragraph`, `list_item`, `table_cell`, `code`, `page`, or `context`.
`boilerplate_family_id` is null for unique body text. Locator coordinates are
one-based where applicable; supported keys are `page`, `slide`, `sheet`, `row`,
`column`, `line_start`, `line_end`, `figure`, and `block_id`. These gold
passages are stable across engine chunking configurations.

`extraction-truth.jsonl` contains one row per document locator unit:

```json
{
  "document_id": "doc-<stable-id>",
  "locator": {"page": 1},
  "text": "<expected extracted text for this unit>",
  "text_sha256": "<truth text SHA-256>",
  "truth_origin": "generator-known"
}
```

`truth_origin` is `generator-known` for all rendered variants. A later real-
scan extension uses `human-verified` and the §4.6 provenance object. Reading
order follows canonical block order. OCR comparisons apply only NFC and LF
normalization unless a benchmark explicitly declares an additional
normalization; diacritic-sensitive truth is never destructively overwritten.

`duplicate-clusters.jsonl` contains:

```json
{
  "cluster_id": "dup-<stable-id>",
  "kind": "exact_byte",
  "canonical_document_id": "doc-<stable-id>",
  "member_document_ids": ["doc-<stable-id>", "doc-<stable-copy-id>"]
}
```

`kind` is `exact_byte`, `exact_text`, `near_duplicate`, `version`, or
`scanned_variant`. A document may occur in clusters of different kinds but at
most once in one cluster. Every member's `duplicate_cluster_ids` contains the
cluster ID. Boilerplate identity is represented by `boilerplate_family_id` on
passages, not by pretending that otherwise distinct documents are duplicates.

`versions.jsonl` contains one row per version group:

```json
{
  "version_group_id": "ver-<stable-id>",
  "members": [
    {
      "document_id": "doc-<stable-version-id>",
      "version_number": 1,
      "is_latest": false,
      "changed_passages": []
    },
    {
      "document_id": "doc-<stable-next-version-id>",
      "version_number": 2,
      "is_latest": true,
      "changed_passages": [
        {
          "change": "modified",
          "from_passage_id": "doc-<stable-version-id>:p:<old-block-id>",
          "to_passage_id": "doc-<stable-next-version-id>:p:<new-block-id>"
        }
      ]
    }
  ]
}
```

Version numbers are consecutive positive integers and exactly one member has
`is_latest = true`. The first version has an empty `changed_passages`; later
versions use `added`, `removed`, or `modified`. Added entries have a null
`from_passage_id`, removed entries a null `to_passage_id`, and modified entries
populate both. Referenced passages must exist in the respective adjacent
versions. The same group is also represented by a `version` duplicate cluster
whose `cluster_id` equals `version_group_id`, and by the version fields in every
member's corpus metadata.

`manifest.json` contains `schema_version`, `corpus_id`, `profile_sha256`,
`source_set_sha256`, `seed`, `generator_version`, `renderer_lock_sha256`,
`document_count`, `passage_count`, `default_roots`, `code_enabled_roots`,
`files`, `sidecars`, and `corpus_hash`. `default_roots` is
`["files/documents"]`; `code_enabled_roots` is
`["files/documents", "files/code"]`. The default SDC loader omits every
`source_code` row and selects only `configuration = "default"` queries; the
code-enabled loader includes both file classes and all nine query categories.
`files` is a path-sorted array of
`{path, byte_count, sha256}` for every rendered file. `sidecars` maps the five
JSONL filenames to their SHA-256. `corpus_hash` is SHA-256 over the canonical
JSON object `{files, sidecars, default_roots, code_enabled_roots}` and excludes
`manifest.json` itself, avoiding a self-hash cycle. `profile_sha256` and
`renderer_lock_sha256` hash their exact respective files. `source_set_sha256`
hashes the canonical JSON array of `{source_set_id, file_sha256}`, sorted by
`source_set_id`, where `file_sha256` hashes the exact source manifest bytes.

### 4.4 Scale profiles and deterministic derivation

| Profile | Rendered files | Canonical passages | Storage and use |
|---|---:|---:|---|
| `sdc-smoke` | Exactly 200, including code root | At least 2,000 | Committed; the generated tree plus its `sdc-smoke-v1` judgments is at most **67,108,864 bytes (64 MiB)**; CI/dev only |
| `sdc-s` | 9,500–10,500 | 90,000–110,000 | Generated, never committed in bulk; full `sdc-v1` judgments |
| `sdc-m` | 95,000–105,000 | 900,000–1,100,000 | Generated, never committed in bulk; extends `sdc-s` with distractors |

Rendered-file counts include all document and code files, not JSONL or notices.
The smoke corpus includes every required renderer, at least one file in each of
the nine query categories' target populations, and the exact injection counts
in §4.2. Large profiles target the same proportions within ±1 percentage point
per mechanism and record exact realized counts in `manifest.json`.

For every stochastic choice, the generator derives a value independently of
iteration order:

```text
D = SHA-256(UTF8("SDC1\0" + seed + "\0" + purpose + "\0" + stable_key))
x = unsigned_big_endian_u64(D[0..8])
u = x / 2^64
```

Seeds, purposes, and stable keys are nonempty ASCII strings containing no NUL.
For an inclusive integer range `[lo, hi]`, use
`lo + floor(u * (hi - lo + 1))`. For a seeded ordering, sort by the full digest
`D` and break the astronomically unlikely digest tie by `stable_key`. For a
multi-block random stream, hash the tuple above plus `"\0" + counter`, where
`counter` is an unsigned decimal integer beginning at 0. The generator never
uses a language-runtime global PRNG, dictionary iteration order, filesystem
enumeration order, or wall-clock randomness.

Document IDs derive from source item, renderer role, injection role, and
occurrence index, not from checkout paths or output timestamps. Renaming or
moving a rendered copy therefore does not change its ID. `sdc-m` uses the same
seed and core recipes as `sdc-s`; candidate ordering by the derivation above
makes the small corpus an exact prefix/subset, and every document and passage
judged in `sdc-s` is copied unchanged into `sdc-m`.

### 4.5 Query records

Each `queries.<split>.jsonl` row is:

```json
{
  "_id": "q-sdc-v1-000001",
  "text": "<query text>",
  "language": "pt-BR",
  "target_languages": ["en"],
  "language_slice": "cross_lingual",
  "category": "cross_language",
  "configuration": "default",
  "split": "dev",
  "filters": null,
  "provenance": {
    "drafted_by": "human:reviewer-a",
    "verified_by": ["human:reviewer-a"],
    "state": "verified",
    "adjudicated_by": null
  }
}
```

`language` and `target_languages` are BCP-47. `language_slice` is `pt`, `en`,
`cross_lingual`, `other`, or `non_latin_non_regression`; it is assigned by the
human verifier from the query/target language pair and is not inferred from a
folder name. `configuration` is `default` or `code_enabled`. `split` is `dev`
or `test`; in a quarantined draft it means the intended split and confers no
eligibility. `filters` is null except for `mixed_semantic_metadata`, where it
is an object with at least one of:

```json
{
  "extensions": ["pdf", "docx"],
  "modified_after": "2022-01-01T00:00:00Z",
  "modified_before": "2024-12-31T23:59:59Z",
  "folder_prefix": "files/documents/<relative-folder>/",
  "min_bytes": 1000,
  "max_bytes": 1000000
}
```

Bounds are inclusive except `modified_before`, which is exclusive. Folder
prefixes are corpus-relative and never user paths. A filter does not replace
relevance judgment: matching metadata is necessary but not sufficient for a
positive grade.

The nine category IDs and required intent coverage are:

| Category | Required fixture/intent |
|---|---|
| `known_item` | A specific known document, including a forgotten-name target and duplicate versions |
| `conceptual` | Semantic topic intent without requiring exact query terms in the target |
| `exact_identifier` | A UUID, invoice number, error code, or other exact synthetic identifier |
| `cross_language` | Portuguese query to English evidence and English query to Portuguese evidence, in both directions |
| `needle_in_haystack` | One canonical passage inside a long document, with document and passage judgments |
| `exploratory` | Broad intent with multiple relevant documents and subtopic labels for diversity evaluation |
| `mixed_semantic_metadata` | Semantic intent plus at least one structured type/date/folder/size constraint |
| `code_search` | Implementation intent in the opt-in code root; always `configuration = "code_enabled"` |
| `filename_partial` | Prefix, substring, extension, or typo intent over a filename, including an accented filename |

An exploratory query adds `subtopic_labels` to relevant document judgments, as
defined below. A cross-language query need not be the only query whose
`language_slice` is `cross_lingual`; category and language slice are separate
reporting dimensions.

### 4.6 Judgment and provenance records

A row in `qrels.<split>.documents.jsonl` is:

```json
{
  "judgment_set_id": "sdc-v1",
  "query_id": "q-sdc-v1-000001",
  "document_id": "doc-<stable-id>",
  "document_text_sha256": "<canonical document text SHA-256>",
  "grade": 3,
  "evidence_passage_ids": ["doc-<stable-id>:p:<stable-block-id>"],
  "subtopic_labels": [],
  "provenance": {
    "drafted_by": "llm:<model-id>@<immutable-revision>",
    "llm_prompt_sha256": "<prompt template and input SHA-256>",
    "verified_by": ["human:reviewer-a"],
    "state": "verified",
    "adjudicated_by": null
  }
}
```

A row in `qrels.<split>.passages.jsonl` is:

```json
{
  "judgment_set_id": "sdc-v1",
  "query_id": "q-sdc-v1-000001",
  "document_id": "doc-<stable-id>",
  "passage_id": "doc-<stable-id>:p:<stable-block-id>",
  "passage_text_sha256": "<canonical passage text SHA-256>",
  "grade": 3,
  "evidence_spans": [
    {"start_utf8": 42, "end_utf8": 158}
  ],
  "provenance": {
    "drafted_by": "human:reviewer-b",
    "verified_by": ["human:reviewer-b"],
    "state": "verified",
    "adjudicated_by": null
  }
}
```

`grade` is an integer in `0..=3`; Boolean, float, and out-of-range grades are
invalid. `evidence_passage_ids` is empty for grade 0 and nonempty for document
grades 2 and 3. Every evidence passage must belong to the document and have its
own positive passage judgment for the same query. `subtopic_labels` is empty
outside `exploratory`; for exploratory grade 2/3 documents it contains one or
more stable, query-local ASCII snake-case labels. Passage `evidence_spans` may
be empty; when present, spans are ordered, nonoverlapping, nonzero-length UTF-8
offsets relative to the passage text, not to the whole document. The referenced
passage and document hashes must match the corpus exactly.

Provenance fields have these rules:

| Field | Rule |
|---|---|
| `drafted_by` | `human:<reviewer-id>` or `llm:<model-id>@<immutable-revision>`; never empty |
| `llm_prompt_sha256` | Required exactly for an LLM draft; hashes the versioned prompt template and actual input, which remain local drafting artifacts |
| `verified_by` | Array of distinct `human:<reviewer-id>` values; empty only for `draft` or `rejected` |
| `state` | `draft`, `verified`, `adjudicated`, or `rejected` |
| `adjudicated_by` | Null except for `adjudicated`, where it names a human in `verified_by`; at least two distinct humans participate |

A reviewer ID is a maintainer-issued pseudonym listed in `reviewers.json`, not
an e-mail address, account name, legal name, or personal path. Human-authored
queries are preferred. LLM-drafted queries and judgments follow the same schema
and carry no assumption of correctness.

`pools.<split>.jsonl` rows are:

```json
{
  "query_id": "q-sdc-v1-000001",
  "document_id": "doc-<stable-id>",
  "passage_id": "doc-<stable-id>:p:<stable-block-id>",
  "origin": "run",
  "run_id": "<committed-report-run-id>",
  "system_id": "<system-and-config-id>",
  "rank": 7,
  "corpus_hash": "<manifest corpus_hash>"
}
```

`origin` is `run`, `known_target`, or `manual`; for non-run origins, `run_id`,
`system_id`, and `rank` are null. For run origins, rank is an integer in
`1..=20`. Passage ID is null only for a document-only system. The judgment union
key is `(query_id, document_id, passage_id)`. Repeated discoveries are separate
rows with the uniqueness constraint `(query_id, document_id, passage_id,
origin, run_id)`, and the frozen pool retains every origin row.

### 4.7 Judgment-set manifest and draft quarantine

`judgment-set.json` contains:

```json
{
  "schema_version": 1,
  "judgment_set_id": "sdc-v1",
  "state": "draft",
  "split_seed": "sdc-v1-split-v1",
  "compatible_corpus_hashes": ["<sdc-s corpus_hash>"],
  "query_counts": {"dev": 0, "test": 0},
  "query_file_sha256": {},
  "file_sha256": {},
  "test_pool_system_ids": [],
  "supersedes": null,
  "test_exposure": "unexposed"
}
```

`state` is `draft`, `split_frozen`, or `frozen`. Draft and split-frozen sets
live below `bench/qrels/sdc/drafts/` and use combined files named
`queries.draft.jsonl`, `qrels.draft.documents.jsonl`,
`qrels.draft.passages.jsonl`, and `pools.draft.jsonl`; each record still
carries its intended split. In `draft`, all of these files are mutable. Moving
to `split_frozen` records the query file digest in `query_file_sha256` and
makes query membership and split assignments immutable while pools and qrels
remain drafts. Only a `frozen` set is published with the split filenames from
§4.3 and accepted by the SDC loader. `file_sha256` maps every published JSONL
filename to its digest. Publishing a set with test queries requires a nonempty
`test_pool_system_ids`, frozen to the predeclared baseline/reference systems
whose depth-20 outputs form the initial test pool; smoke uses an empty array.
Later candidate systems are evaluated against that frozen pool and do not
trigger new test pooling in the same judgment-set version.

`test_exposure` is `unexposed`, `exposed`, or `not-applicable`; publishing sets
`unexposed` (or `not-applicable` for smoke). The first benchmark run using
`test` atomically changes only this bookkeeping field to `exposed` and records
the same transition in its report. This field is outside `file_sha256`; every
other manifest field and all published JSONL remain immutable. Later
corrections use a new `judgment_set_id` and `supersedes`; they never reuse the
old directory.

## 5. Behavior details

### 5.1 Build pipeline, rendering, and failures

1. Parse and validate every source and asset manifest before creating output.
2. `fetch` writes to a temporary cache object, verifies length and SHA-256, and
   atomically renames it to `<cache>/sha256/<digest>`. A failed download leaves
   no usable object. No query, judgment, private path, or user document is ever
   sent by this command.
3. `build` reads only pinned cache objects, profiles, locked assets, and the
   seed. It creates canonical block models, applies injections, renders into a
   temporary sibling directory, emits sidecars, verifies the complete manifest,
   and atomically renames the directory. Existing output is replaced only after
   a complete verified build; failure leaves it untouched.
4. ZIP-based formats sort entries and use fixed entry timestamps and no host
   metadata. PDFs use deterministic IDs and no current-date fields. Rasterizers
   use pinned fonts and versions. Generated file permissions, path separators,
   JSON key ordering, and newlines do not depend on the host OS.
5. Every rendered document retains a mapping from canonical block IDs to output
   locators. Renderer round-trip tests compare extracted blocks to canonical
   truth rather than merely checking that a file opens. Formats supported by
   the Phase 0 engine are read through the `Engine` API. ODT, RTF, EPUB, and EML
   use an independent, permissively licensed reader in WP-1.3 because their
   engine extractors arrive only with WP-3.4; WP-3.4 must then add the same
   golden round-trip through the engine. Image-only scanned PDFs contain no
   text objects or OCR layer; their canonical page truth remains in
   `extraction-truth.jsonl`.

Errors use stable codes including `SOURCE_PIN_MISSING`, `SOURCE_HASH_MISMATCH`,
`LICENSE_INELIGIBLE`, `LICENSE_NOTICE_MISSING`, `CACHE_MISS`, `SCHEMA_INVALID`,
`RENDER_FAILED`, `OUTPUT_HASH_MISMATCH`, `QREL_TARGET_STALE`,
`PROVENANCE_INCOMPLETE`, `POOL_INCOMPLETE`, and `TEST_NOT_ELIGIBLE`. There is no
partial corpus or partially frozen judgment set.

### 5.2 Licensing and the sharealike extension

The permissive core and `sdc-smoke` contain only source material and generated
derivatives whose redistribution is compatible with the repository's MIT code
distribution and ADR-0022, including required attribution. Notices travel with
the corpus and identify the source items and render variants; they are not
collapsed into a generic URL list.

CC-BY-SA encyclopedia material, if used, is generated under
`bench/corpora/sdc/extensions/cc-by-sa/` with a separate corpus manifest,
query/qrels compatibility declaration, complete license text, attribution, and
sharealike notice. It is never committed into `sdc-smoke`, merged into the core
`corpus_hash`, uploaded as part of the application or model asset bundle, or
silently relicensed. A benchmark that includes it must name the extension and
its corpus hash separately. Any separate publication of that extension must
preserve its sharealike terms and requires maintainer license review.

### 5.3 Adversarial injection

- **Exact byte copies** share `content_sha256` but have distinct paths and
  document IDs. **Exact text copies** share canonical `text_sha256` but may use
  different formats or bytes. **Scanned variants** link the text original and
  scanned derivative through a `scanned_variant` cluster.
- **Near duplicates** change a bounded set of canonical blocks while retaining
  a cluster label; the profile records the edit recipe. Similarity is not
  inferred from filenames. **Versions** form an ordered chain, record changed
  passage IDs in the version metadata sidecar, and may change the latest target
  without changing older IDs.
- **Boilerplate** comes from a profile-defined family of synthetic canonical
  blocks. Injection counts refer to receiving documents, not repeated blocks;
  each inserted block is exactly identified in `passages.jsonl`. Unique target
  evidence remains outside boilerplate spans.
- Random injection never changes a judged source target without also changing
  its target hash and forcing re-judgment. Query and judgment files are inputs
  to validation, never sources of randomness for corpus mutation.

### 5.4 Query authoring and split assignment

Queries are authored from canonical source content before any compared system
is run. The author records intent, category, languages, and any metadata
filters; an LLM may propose additional text, but a human must make the intent
coherent and answerable from the corpus. Known-item and needle queries identify
at least one candidate target for pooling, not an automatic relevance grade.

After query drafting, queries are grouped by `(category, language_slice,
configuration)`. Every nonempty stratum shall contain an even number of
queries; an odd stratum is a drafting error and is corrected by adding or
removing a draft before split freeze, never by weakening a minimum. Within each
stratum, sort query IDs by the §4.4 digest using purpose `query-split-order`
and `split_seed`, then form adjacent pairs. For each pair, derive another
digest with purpose `query-split-direction` and the lexicographically smaller
query ID as stable key: `u < 0.5` puts the first query in `dev` and the second
in `test`, otherwise the assignments are reversed. Thus every stratum, category,
language slice, and the complete set is exactly balanced between splits.

Query-level human verification may occur before or after this intended
assignment, but it must be complete before `judgments freeze-split` so that
provenance edits cannot invalidate frozen query hashes. That command validates
all minima and freezes the seed, query membership, intended splits, and query
hashes before run pooling starts. Human verification and pooling do
not reassign a split; removing a query after split freeze requires a new
judgment-set draft and split seed. No retrieval score, model preference, or
perceived difficulty may move a query between splits.

The non-Latin sample is reported separately for non-regression and does not
enter the weighted primary score. Code-search queries are likewise separate
from the default configuration, as required by ADR-0024; see resolved question
1 in §7.

### 5.5 Relevance rubric and human verification

| Grade | Document meaning | Passage meaning |
|---|---|---|
| 0 | Explicitly judged not to satisfy the intent, including a metadata mismatch | No useful evidence for the intent |
| 1 | Topically related or marginally useful, but does not satisfy the main intent | Background or indirect evidence only |
| 2 | Relevant and useful, but incomplete, superseded where recency matters, or only partly satisfies the intent | Substantial supporting evidence that is incomplete or indirect |
| 3 | Directly satisfies the intent; for known item, the intended item or an explicitly relevant copy/version | Contains the exact target, answer-bearing text, or decisive evidence |

Relevance is judged against the query intent and structured filters, not query
term overlap. Unjudged means absent, not grade 0. Duplicate copies may all be
relevant; duplicate-cluster labels, rather than arbitrary zero grades, allow
deduplication metrics to distinguish redundancy from relevance. Exploratory
queries may have many grade 2/3 documents and use subtopic labels for diversity
metrics. For recency-sensitive known-item/version queries, the verifier records
whether an older version is grade 1/2 or remains fully valid; the generator
does not infer it.

Human verification displays the query, canonical document/passage text, and
locator. The verifier confirms or changes the draft grade and evidence and then
sets `verified_by` and `state`. A disagreement may be adjudicated by a second
human; `adjudicated` records the final grade, both participants, and the
adjudicator. Rejected records stay in drafts and are never published. At least
10% of test items should receive independent second review as a quality check;
disagreements entering a frozen set must be adjudicated.

The LLM drafting workflow is entirely offline: no corpus text, prompt, query,
or judgment is sent to a hosted service. Model ID, immutable revision, and
prompt/input hash are provenance only; the model and its outputs never become
a product component or a generated answer feature.

### 5.6 Pooling, publication, and scale changes

For `dev`, pool the top 20 documents and passages from every system under test
on the same corpus hash. For `test`, do this only for the predeclared baseline/
reference panel recorded in `test_pool_system_ids`, before the first candidate
confirmation run. Both splits also include known targets and manual discoveries.
Duplicate discoveries share one judgment target. Every pooled target receives
an explicit grade, including grade 0, before freezing. Judgment coverage and
remaining unjudged corpus counts are validation outputs so that later reports
can disclose pooling limitations rather than treating missing data as verified
nonrelevance.

Publishing validates all minima, cross-references, target hashes, provenance,
and pool coverage, then writes split files and their hashes atomically. A
frozen `dev` set may be extended only under a new version as well, preventing
silent baseline drift. Once `test` is exposed, even a corrected typo in a query
or judgment creates a new judgment-set ID linked by `supersedes`; reports name
the exact version used.

`sdc-m` retains the `sdc-s` targets and their text hashes. Its added distractors
may enter depth-20 pools and therefore require new judgments. Those judgments
are drafted and human-verified in a new judgment-set version before its `test`
split is exposed. Reusing small-scale judgments without this top-up is invalid
for a medium-scale gate.

## 6. Acceptance

### 6.1 Tests to write first

Generator tests live beside `tools/sdc-generator/`; cross-format integration
tests invoke the real engine extractors through temporary directories for the
formats supported by the current engine and use independent readers for ODT,
RTF, EPUB, and EML until WP-3.4. Tests are hardware-free except those that
explicitly require PDFium or an OCR model. Judgment loader tests live with the
SPEC-0003 SDC loader. Every test names or
comments its requirement IDs.

| Test | Requirement IDs |
|---|---|
| `source_item_requires_complete_pin` | R1 |
| `source_download_rejects_sha256_mismatch` | R1 |
| `source_manifest_requires_license_and_notice` | R2 |
| `core_rejects_ineligible_or_missing_license` | R2 |
| `same_seed_rebuild_is_byte_identical` on two checkout paths and all CI OSes | R3 |
| `different_seed_changes_corpus_hash_without_host_nondeterminism` | R3, R4 |
| `manifest_contains_no_host_specific_data` | R3, R6 |
| `corpus_layout_matches_schema` | R4 |
| `manifest_detects_added_changed_and_missing_files` | R4, R13 |
| `ids_and_target_hashes_survive_regeneration` | R4, R9, R25 |
| `smoke_profile_meets_file_and_size_caps` | R5 |
| `scale_profiles_meet_document_and_passage_ranges` (use reduced test fixtures for unit tests; full generation is an integration gate) | R5 |
| `synthetic_content_uses_reserved_example_domains` plus personal-data/secret scanning | R6 |
| Parameterized `renderer_round_trip_preserves_text_and_locators` for all formats | R7 |
| `scanned_pdf_has_no_text_layer` | R8 |
| `scan_recipe_is_deterministic` | R3, R8 |
| `scan_truth_matches_canonical_pages` | R8 |
| `duplicate_injection_counts_and_clusters_match_profile` | R9 |
| `renamed_and_moved_copies_keep_identity` | R9 |
| Duplicate property: cluster membership is symmetric, nonduplicated within a cluster, and path-independent | R9 |
| `version_groups_are_ordered_and_changed_spans_are_valid` | R10 |
| `each_version_has_distinct_document_id` | R10 |
| `boilerplate_counts_and_families_match_profile` | R11 |
| Property `only_injected_spans_are_boilerplate` | R11 |
| `default_root_contains_no_source_code` | R12 |
| `code_enabled_root_adds_only_code` | R12 |
| `code_queries_require_code_enabled_configuration` | R12, R15, R26 |
| Malformed-input matrix: bad UTF-8/JSON/JSONL, unknown versions/enums, duplicate IDs, dangling paths, bad hashes; typed errors and no panics | R13, R15, R18–R20, R25 |
| `failed_build_is_atomic` with injected read/write/render failures | R13 |
| `build_and_verify_never_access_network` with network denied | R14 |
| Command smoke tests for `build`, `verify`, draft validation, and publication | R14, R22 |
| `query_schema_accepts_all_nine_categories` | R15 |
| `mixed_metadata_queries_have_structured_filters` | R15 |
| `full_query_set_meets_category_and_split_minima` | R16 |
| `split_assignment_is_stratified_deterministic_and_predates_pools` | R16 |
| `odd_split_stratum_is_rejected_before_freeze` | R16 |
| `split_freeze_precedes_pool_rows_and_blocks_query_reassignment` | R16, R23 |
| `language_and_cross_lingual_slices_meet_minima` | R17 |
| `non_latin_queries_are_non_regression_only` | R17 |
| `document_qrels_validate_grades_and_references` | R18 |
| `known_item_duplicates_and_multiple_relevant_docs_are_representable` | R18 |
| `passage_qrels_validate_grades_and_target_hashes` | R19, R25 |
| `snippet_spans_are_ordered_in_bounds_and_exact` | R19 |
| `provenance_is_complete_for_human_and_llm_drafts` | R20 |
| `adjudication_requires_distinct_humans_and_adjudicator` | R20 |
| `llm_draft_cannot_be_promoted_without_human_verification` | R21, R22 |
| `draft_judgment_set_is_not_benchmark_eligible` | R22 |
| `unverified_item_never_enters_test` | R22 |
| `promotion_rejects_missing_provenance` | R20–R22 |
| `frozen_test_membership_and_splits_are_immutable` | R23 |
| `correction_creates_new_judgment_set_version` | R23 |
| `pool_is_depth_20_union_of_all_systems` | R24 |
| `known_targets_and_manual_candidates_are_pooled` | R24 |
| `frozen_pool_has_no_unjudged_candidate` | R24 |
| `test_pool_panel_precedes_exposure` | R23, R24 |
| `explicit_zero_is_distinct_from_unjudged` | R25 |
| `changed_target_text_invalidates_qrel` | R25 |
| `smoke_queries_cover_every_category_five_times` | R26 |
| `smoke_has_no_test_split` | R26 |
| `smoke_default_and_code_runs_use_disjoint_configurations` | R12, R26 |
| `medium_profile_preserves_small_judged_targets` | R27 |
| `medium_test_freeze_requires_scale_specific_pool_topup` | R24, R27 |
| Fuzz source/profile/corpus/query/qrel/pool readers with arbitrary bytes; no panic, no partial output, bounded diagnostics | R13, R25 |

No unit test asserts ranking quality. Quality is measured only by
`seeky-bench` under SPEC-0003 and the methodology.

### 6.2 Benchmark and data gates

| Gate | Dataset/split | Tier | Threshold | Baseline report |
|---|---|---|---|---|
| Corpus reproducibility | `sdc-smoke` | Windows, Linux, macOS CI | Same seed and lockfile produce identical `corpus_hash`; committed tree and smoke judgments total ≤ 64 MiB | Golden hash introduced with WP-1.3 |
| Scale generation | `sdc-s`; `sdc-m` when first consumed | Generation host | WP-1.3 generates and validates all of `sdc-s`; the `sdc-m` recipe is validated on a reduced test profile until its full materialization. Counts, passages, injections, and hashes validate; bulk output is absent from Git | WP-1.3 `sdc-s` generation log; later `sdc-m` generation log |
| Judgment readiness | `sdc-v1` dev/test | Offline | All §4.5–§4.7 invariants and minima pass; no unverified item is eligible | Frozen judgment-set manifest |
| WP-1.8 quality smoke | `sdc-smoke-v1` dev, default configuration | Hardware-free CI | nDCG@10 drop ≤ 1.0 point versus `main`, plus ranking invariants; calculation and baseline storage are SPEC-0003 | `main` baseline established by WP-1.8 |
| Code-enabled non-regression | `sdc-smoke-v1` dev, `code_search` | Hardware-free CI/manual | Reported separately; never substituted for the default smoke score | Established with code-enabled benchmark configuration |

SDC definition alone proves neither retrieval quality nor performance and must
not be used to claim that a model or ranking stage improved.

### 6.3 Inspection

- Every source item, font, and renderer asset has a pinned revision/digest,
  license, and notice appropriate to its redistribution class (R1, R2, R6).
- `sdc-smoke` contains no source cache, model weight, private document,
  personal path, real personal data, secret, or unverified judgment (R3, R6,
  R22).
- `sdc-s` and `sdc-m` bulk output is untracked; committed regeneration
  instructions contain no user-specific paths (R5).
- No engine crate depends on `tools/sdc-generator/`; the tool has no product
  runtime component or telemetry, no network call outside `fetch`, and no
  hosted-service call in the LLM drafting workflow (R14, R21).
- Default benchmark roots exclude source code; code search is reported only
  under `code_enabled` (R12, R15, R26).
- Frozen judgment sets have complete human provenance, stable target hashes,
  immutable test membership, and a visible `supersedes` chain for corrections
  (R20–R25).
- This version contains no visual query category, visual unit, generated image
  caption, or visual relevance claim. WP-10.1 requires a later accepted spec
  version and ADR-0023 conformance.

## 7. Risks and open questions

### Resolved blocking questions (H1)

Questions 1–3 are resolved by maintainer pre-approval in /goal. The
recommendations below are accepted and normative; the methodology and plan
corrections they name landed in the same commit.

| # | Question and conflict | Recommendation | Decides | By when |
|---|---|---|---|---|
| 1 | **Code search versus the default corpus.** Methodology §2.1 lists source code and §2.2 includes code search among nine text categories, while ADR-0024 says benchmark corpora and budgets measure the documents-only default and code-enabled configurations separately. This directly affects R12, R15, R26, Q2 category reporting, and the WP-1.8 smoke score. | Follow the higher-precedence ADR: include code only in a disjoint opt-in root; compute default Q1/Q2 and WP-1.8 over the eight non-code categories; report code search and its Q2 comparison only between code-enabled configurations. Correct methodology §2.2/§3.1 and the WP-1.8 wording to state this explicitly. | Maintainer | Before SPEC-0004 and SPEC-0003 acceptance (H1) |
| 2 | **The WP-1.8 dependency graph omits verified smoke judgments.** R26 assigns the smoke qrels to WP-1.4, and methodology §2.2 requires every gate judgment to be human-verified, but plan WP-1.8 depends only on WP-1.2 and WP-1.3. Starting the quality gate on generator-assumed or unverified labels would violate the higher-precedence protocol. | Keep R26 in WP-1.4, but deliver and human-verify its small `sdc-smoke-v1` subset before the full 600-query campaign. Change WP-1.8's dependency to `1.2, 1.3, 1.4 (sdc-smoke-v1 verified)`; no full WP-1.4 completion is needed to start WP-1.8. | Maintainer | Before H1 and scheduling WP-1.8 |
| 3 | **Generator language and renderer/font dependency set.** The plan permits Python only in `tools/`, while the implementation lane needs a fixed location and deterministic cross-platform renderers. Font and renderer licenses must not be assumed compatible merely because output is evaluation data. | Use Python 3.12 in `tools/sdc-generator/` with a hash-locked, license-checked dependency set and no product dependency. Pin renderer and font binaries/resources; allow only ADR-0022-compatible assets in committed smoke. If deterministic rendering needs an asset outside that gate (for example an unreviewed font license), stop for a maintainer license decision rather than bundling it. Choose Rust only if the maintainer rejects Python; keep the JSONL contracts unchanged either way. | Maintainer, with license review | Before acceptance and WP-1.3 dependency selection |

### Non-blocking questions and risks

| # | Item | Recommendation / mitigation | Decides | By when |
|---|---|---|---|---|
| 4 | The exact initial public source list and Portuguese/English balance are not selected by this document. | Prefer public-domain Portuguese classics and government works, CC-BY papers, and synthetic office documents; record the final pinned manifests in the WP-1.3 PR and review license before implementation effort. | WP-1.3 implementer + maintainer reviewer | WP-1.3 review |
| 5 | CC-BY-SA material can contaminate redistribution if merged into the core. | Keep the optional sharealike extension physically and cryptographically separate as in §5.2; do not publish it until maintainer review. Core acceptance does not depend on this extension. | Maintainer/license reviewer | Before any extension publication |
| 6 | A 600-query pool can still have sparse passage judgments or newly returned unjudged documents at `sdc-m`. | Require depth-20 top-up and report judgment coverage; never describe absent judgments as human-verified nonrelevance. Consider additional adjudication where metrics disagree. | WP-1.4 reviewer | Before each frozen gate |
| 7 | LLM drafts may encode implausible queries or relevance bias. | Prefer human-authored queries, independently review at least 10% of test items, adjudicate disagreements, and retain model/revision/prompt hashes. No draft enters a benchmark split unverified. | Human judgment lead | WP-1.4/H6 |
| 8 | Generated scans do not capture all real scanner and camera failure modes. | Treat generated scans as deterministic v1 fixtures; add a licensed real-scan subset with human-verified transcriptions before OCR bake-off claims under methodology §8.8. Do not make WP-1.3 depend on an unplanned transcription campaign. | WP-2.11 owner + maintainer | Before OCR Stage A conclusions |
| 9 | Exact byte reproducibility across renderer upgrades can unnecessarily freeze bug fixes. | Version the generator and renderer lock; intentional output changes create a new corpus version and require revalidation of stale judgment hashes, never an in-place silent golden update. | Maintainer | WP-1.3 and every renderer upgrade |
| 10 | The 64 MiB smoke cap may pressure scanned and long-document fixtures as formats grow. | Keep smoke small and targeted; put additional bulk in generated profiles. Any cap change requires a spec changelog and repository-size measurement, not silent removal of coverage. | Maintainer | Before changing the cap |

## 8. Changelog

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-11-27 | WP-1.3 implemented R14: offline `judgments validate`, `freeze-split`, and `publish` with the canonical `bench/qrels/sdc/drafts` quarantine, schema/target-hash/provenance/minima/pool checks, immutable query digests, and atomic publication; R15-R27 remain with WP-1.4 |
| 0.1 | 2026-11-27 | Accepted (maintainer pre-approval in /goal); resolved H1 questions 1-3 with the draft recommendations: documents-only default benchmarks, verified smoke judgments for WP-1.8, and isolated Python 3.12 tooling |
| 0.1 | 2026-11-27 | WP-1.3 implemented R1-R13: deterministic licensed generator, all renderers/scans, injections, code root, atomic build/verify, committed `sdc-smoke`; R14 remains open for judgment commands and the external-source scope is still v1-synthetic-only |
| 0.1 | 2026-11-27 | Initial Draft for WP-1.3/WP-1.4: deterministic licensed SDC generation, scale profiles, adversarial fixtures, nine query categories, graded document/passage judgments, provenance, human verification, pooling, and split/version protection. Visual WP-10.1 deferred to a later version |
