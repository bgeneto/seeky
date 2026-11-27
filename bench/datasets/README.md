# Public evaluation datasets (SPEC-0003 R23–R24)

Each subdirectory is one dataset prepared by `tools/dataset-fetch/`:

```text
<dataset-id>/
  manifest.json        SPEC-0003 §4.2 BEIR manifest: source revision and
                       hashes, license and terms, dev/test mappings, query
                       defaults, transform version and seed, local file hashes
  dataset-lock.json    pinned upstream sizes and hashes, terms digest, parsed
                       counts, language/category slices, dataset fingerprint
  NOTICE.md            provenance, license, download-only notice, reproduction
  data/                generated BEIR corpus/queries/qrels and optional
                       per-document engine files; git-ignored and never committed
```

Bulk data lives in an external cache (for example
`%LOCALAPPDATA%\seeky-dev\datasets`) and in the git-ignored `data/`
directories. Nothing here is redistributed; every dataset is
`redistribution: "download-only"` under ADR-0022.

```text
python -m dataset_fetch prepare --dataset <dataset-id> --cache <cache>
python -m dataset_fetch verify  --dataset <dataset-id>
python -m dataset_fetch check   --dataset <dataset-id>
```

`seeky-bench --corpus <dataset-id>` resolves a manifest here (for datasets with
`files_root` materialized). Large datasets pinned with `files_root: null` run in
SPEC-0003 §4.2 cached-TREC-run mode (Stage A / `seeky-eval::load_beir`), keeping
each committed `manifest.json` around 2–4 KB instead of listing millions of
per-document file hashes.

## Pinned

| Dataset ID | Source | License (download-only) | Mode | Splits | Notes |
|---|---|---|---|---|---|
| `beir-scifact` | `mteb/scifact` mirror of BEIR SciFact | CC-BY-SA-4.0 per BEIR card | `files_root` | `dev` = source train claims, `test` = source test | English domain-shift sanity; document judgments only |
| `beir-nfcorpus` | `mteb/nfcorpus` mirror of BEIR NFCorpus | CC-BY-SA-4.0 per BEIR card | `files_root` | native `dev` and `test` | English biomedical sanity |
| `beir-fiqa` | `mteb/fiqa` mirror of BEIR FiQA | CC-BY-SA-4.0 per BEIR card | `files_root` | native `dev` and `test` | English finance sanity |
| `beir-trec-covid` | `mteb/trec-covid` mirror of BEIR TREC-COVID | CC-BY-SA-4.0 per BEIR card | `files_root: null` | deterministic 50/50 carve-out of source test (25 / 25) | 171,331 docs; 2 TREC `-1` non-relevant grades mapped to `0` |
| `mldr-pt` | `Shitao/MLDR` `mldr-v1.0-pt` | MIT per MLDR card | `files_root` | native `dev` and `test` | Portuguese long documents; category `conceptual` |
| `mldr-en` | `Shitao/MLDR` `mldr-v1.0-en` | MIT per MLDR card | `files_root: null` | native `dev` (200) and `test` (800) | 200,000 English long documents; category `conceptual` |
| `mmarco-pt` | `unicamp-dl/mmarco` (`portuguese` + `dev.small`) | MS-MARCO-Research | `files_root: null` | deterministic 50/50 carve-out of `dev.small` (3,490 / 3,490) | 8,841,823 Portuguese passages |
| `mmarco-pt-en` | `unicamp-dl/mmarco` (`pt` queries → `en` collection) | MS-MARCO-Research | `files_root: null` | deterministic 50/50 carve-out of `dev.small` (3,490 / 3,490) | Constructed `pt→en` cross-lingual pairs (`<id>-xl-pt-en`), 8,841,823 English passages |
| `mmarco-en-pt` | `unicamp-dl/mmarco` (`en` queries → `pt` collection) | MS-MARCO-Research | `files_root: null` | deterministic 50/50 carve-out of `dev.small` (3,490 / 3,490) | Constructed `en→pt` cross-lingual pairs (`<id>-xl-en-pt`), 8,841,823 Portuguese passages |
| `miracl-es` | `miracl/miracl` + `miracl/miracl-corpus` (`v1.0-es`) | Apache-2.0 | `files_root: null` | deterministic 50/50 carve-out of `dev` (324 / 324) | 10,373,953 Spanish Wikipedia passages (`other` slice); recipes also implemented for `miracl-fr`, `miracl-de`, `miracl-en` |
| `quati-pt` | `unicamp-dl/quati` (`quati_1M`) | CC-BY-4.0 | `files_root: null` | deterministic 50/50 carve-out of judged topics (25 / 25) | 1,000,000 native Brazilian Portuguese passages |

### Notes on source normalization and splits

- **BEIR license cards:** the `mteb/<name>` mirrors re-package upstream BEIR
  releases without declaring a license in their own cards, so the pinned
  `BeIR/<name>` dataset card is the authoritative license/terms record.
- **`beir-scifact`** uses SciFact's own train claims as `dev` (the source has
  no dev qrels). **`mldr-pt`** and **`mldr-en`** use both native splits
  unchanged.
- **`beir-fiqa`** has 38 corpus rows with neither title nor text; the transform
  omits them and drops the three qrels referencing them (dev 2, test 1),
  recorded in the lock and `NOTICE.md`. Its manifest is ~8.9 MB because it
  materializes 57,600 per-document engine files under `files_root`.
- **`beir-trec-covid`** publishes only 50 test topics (no public dev/train
  qrels) and contains two TREC `-1` (explicit non-relevant) grades; the recipe
  maps `-1 → 0` (matching `trec_eval`), partitions the 50 topics 50/50
  deterministically by SHA-256 without tuning, and records both facts in the
  lock.
- **Deterministic 50/50 carve-out for single-split sources** (`mmarco-*`,
  `miracl-*`, `quati-pt`, `beir-trec-covid`): when upstream publishes only a
  single judged split (no public `test` qrels, or test-only in TREC-COVID), the
  recipe orders query IDs by `SHA-256(seed NUL purpose NUL query_id)` and
  partitions them 50/50 into disjoint `dev` and `test` splits without tuning.
  Public datasets remain cross-checks; the SDC `test` split is always the
  deciding dataset for product defaults (`docs/benchmarks/methodology.md` §2.3).
- **Additional MIRACL languages (`miracl-fr`, `miracl-de`, `miracl-en`):** the
  multi-shard recipe in `tools/dataset-fetch/dataset_fetch/recipes/miracl.py`
  already supports all four languages; `miracl-es` is pinned as the committed
  non-pt sanity set and the others can be pinned on demand using the same
  manifest pattern.

## Adding a dataset

1. Add a recipe under `tools/dataset-fetch/dataset_fetch/recipes/` and its
   tests; no third-party dependency is allowed without a license review and a
   hash-locked `requirements.lock`.
2. Record the source revision, immutable file URLs, upstream SHA-256 digests,
   and the license/terms revision in `manifest.json` with `local_file_sha256`
   empty (use `"files_root": null` for large Stage A datasets), then run
   `prepare`. The tool fills the local hashes, writes the lock and notice, and
   computes the §4.2 fingerprint.
3. Run `verify` offline; commit only `manifest.json`, `dataset-lock.json`, and
   `NOTICE.md`.
