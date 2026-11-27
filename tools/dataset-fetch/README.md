# dataset-fetch — public evaluation dataset preparation (development tooling)

Offline preparation and verification of the public datasets that
`seeky-bench` evaluates on, per SPEC-0003 R23–R24 and §4.2.

This package never ships in the product, never imports an engine crate, never
computes retrieval metrics, and never redistributes dataset content. It is
standard-library-only Python 3.12+ (`requirements.lock` is intentionally
empty). Bulk data stays in an external download cache and in `data/`
directories that git ignores; only `manifest.json`, `dataset-lock.json`,
`NOTICE.md`, and scripts are committed.

## Layout

```text
bench/datasets/<dataset-id>/
  manifest.json        SPEC-0003 §4.2 BEIR manifest (source, license, splits,
                       transform, local file hashes, corpus layout)
  dataset-lock.json    pinned source files and sizes, terms digest, prepared
                       fingerprints, counts, and language/category slices
  NOTICE.md            provenance, license, download-only notice, reproduction
  data/                generated BEIR files (untracked, regenerated)
```

The download cache is external, for example
`%LOCALAPPDATA%\seeky-dev\datasets\<dataset-id>\downloads`. Set `--cache`
explicitly or `SEEKY_DATASET_CACHE`.

## Usage

From the repository root:

```text
python -m dataset_fetch prepare --dataset beir-scifact --cache <cache>
python -m dataset_fetch verify  --dataset beir-scifact
python -m dataset_fetch check   --dataset beir-scifact
python -m dataset_fetch list
```

`prepare` downloads only the manifest's `source.urls` into the cache (unless
`--offline`), verifies every upstream SHA-256 and the pinned terms digest,
decompresses, normalizes text to NFC/LF, writes the BEIR `dev`/`test` files,
the per-document engine files, `dataset-lock.json`, `NOTICE.md`, and the
manifest's `local_file_sha256`. It refuses to overwrite an existing `data/`
directory unless `--overwrite` is given, so a failed run cannot silently
replace a pinned corpus.

`verify` performs no network access and fails on any manifest, source, terms,
local hash, split, category, language, transform, or fingerprint mismatch. It
also re-derives the dataset fingerprint from the manifest and local files and
compares it with `dataset-lock.json`.

`check` validates the committed manifest and lock without touching `data/`.

## License policy

Every dataset is `visibility: "public"`, `redistribution: "download-only"`,
and its `license.id` must be on the ADR-0022 internal-evaluation allowlist.
CC-BY-SA and research-only terms are allowed only because the content is
downloaded by this script and never redistributed; no dataset content is
committed. `license.terms_url` must point at an immutable revision and its
SHA-256 is pinned in the lock and in `manifest.json#terms_sha256`.

Because the Rust loader ignores unknown manifest fields, `terms_sha256` is
excluded from the SPEC-0003 §4.2 fingerprint, exactly like the typed Rust
`BeirManifest` struct does. The lock records it alongside the fingerprint.

## Determinism

For the same source bytes, `transform.version`, and `transform.seed`, the
prepared files, their hashes, the manifest `local_file_sha256`, the lock, and
the dataset fingerprint are byte-identical. Identifiers are preserved from the
source (the only exception is the declared cross-lingual prefix/suffix in
§4.2). Documents and queries are written in identifier order, qrels in
`(query, document)` order, JSON keys sorted, JSONL compact, LF endings.

## Supported dataset ids

| Identifier | Source | Notes |
|---|---|---|
| `beir-scifact` | BeIR/mteb SciFact mirror | `files_root`; `dev` = SciFact train claims, `test` = SciFact test |
| `beir-nfcorpus` | BeIR/mteb NFCorpus mirror | `files_root`; native `dev` and `test` qrels |
| `beir-fiqa` | BeIR/mteb FiQA mirror | `files_root`; native `dev` and `test` qrels |
| `beir-trec-covid` | BeIR/mteb TREC-COVID mirror | `files_root: null` (Stage A); deterministic 50/50 carve-out of test qrels; TREC `-1` mapped to `0` |
| `mldr-pt` | Shitao/MLDR (`mldr-v1.0-pt`) | `files_root`; native Portuguese `dev` and `test` |
| `mldr-en` | Shitao/MLDR (`mldr-v1.0-en`) | `files_root: null` (Stage A); native English `dev` and `test` |
| `miracl-es`, `miracl-fr`, `miracl-de`, `miracl-en` | miracl/miracl + miracl-corpus | `files_root: null` (Stage A); deterministic 50/50 carve-out of dev qrels; `miracl-es` pinned |
| `mmarco-pt`, `mmarco-pt-en`, `mmarco-en-pt` | unicamp-dl/mmarco | `files_root: null` (Stage A); `dev.small` deterministic 50/50 carve-out + constructed `pt↔en` pairs; all three pinned |
| `quati-pt` | unicamp-dl/quati (`quati_1M`) | `files_root: null` (Stage A); CC-BY-4.0; deterministic 50/50 carve-out of judged topics; pinned |

Every committed dataset has real upstream and local SHA-256 digests verified
offline against its external cache; bulk `data/` directories stay untracked.
