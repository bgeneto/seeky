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
  data/                generated BEIR corpus/queries/qrels and per-document
                       engine files; git-ignored and never committed
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

`seeky-bench --corpus <dataset-id>` resolves a manifest here; the repository
path never points into a user's home unless a private corpus is declared
explicitly.

## Pinned

| Dataset ID | Source | License (download-only) | Splits | Notes |
|---|---|---|---|---|
| `beir-scifact` | `mteb/scifact` mirror of BEIR SciFact | CC-BY-SA-4.0 per BEIR card | `dev` = source train claims, `test` = source test | English domain-shift sanity; document judgments only |
| `beir-nfcorpus` | `mteb/nfcorpus` mirror of BEIR NFCorpus | CC-BY-SA-4.0 per BEIR card | native `dev` and `test` | English biomedical sanity |
| `beir-fiqa` | `mteb/fiqa` mirror of BEIR FiQA | CC-BY-SA-4.0 per BEIR card | native `dev` and `test` | English finance sanity |
| `mldr-pt` | `Shitao/MLDR` `mldr-v1.0-pt` | MIT per MLDR card | native `dev` and `test` | Portuguese long documents; category `conceptual` |

The BEIR mirror re-packages the upstream BEIR release; the `BeIR/<name>`
dataset card at the pinned revision is the license/terms source recorded in
each manifest and lock. The MTEB mirror's own card does not declare a license
(it says `license: unknown`), so the BEIR card is the authoritative record.

`beir-scifact` uses SciFact's own train claims as `dev`: the source has no dev
qrels, and deriving dev from the test split would leak it. `mldr-pt` uses both
native splits unchanged.

`beir-fiqa` has 38 corpus rows with neither title nor text. They cannot be
indexed and would violate the loader's nonempty-text contract, so the
transform omits them and drops the three qrels that referenced them (dev 2,
test 1); the omission and drop counts are recorded in the lock's transform
notes and in `NOTICE.md`. No query loses all its judgments. Its manifest is
about 8.9 MB because §4.2 requires a local SHA-256 for each of the 57,600
per-document engine files; the lock keeps only the count and fingerprint, so
the committed metadata for all four datasets is about 11 MB.

## Not pinned (documented blockers)

No manifest is committed for these: a pin needs real upstream hashes, and an
invented hash is never acceptable. Each blocker is a source-property problem,
not a tooling gap.

| Dataset | Blocker |
|---|---|
| `beir-trec-covid` | 200 MB corpus with 171,540 documents. Per-document `local_file_sha256` (required by §4.2 for `files_root`) would add roughly 20–25 MB of manifest; deferred until the manifest format or a corpus-file mode is decided. Recipe is implemented. |
| `mldr-en` | English corpus alone is 985 MB compressed (plus 21 MB dev and 82 MB test). Deferred as too large for an unattended run; recipe is implemented and `mldr-pt` proves the mapping. |
| `miracl-*` | MIRACL publishes dev qrels only; test-a/test-b topics have no public qrels, so a `test` mapping cannot be produced without fabricating labels. Smallest corpus (Swahili) is 10 MB, but the missing test split is decisive. |
| `mmarco-pt`, `mmarco-pt-en`, `mmarco-en-pt` | The Portuguese collection is 3.4 GB and the English collection 3.1 GB; a cross-lingual pair needs two collections. MS MARCO terms are research-only, permitted for internal evaluation by ADR-0022. Pair construction is implemented and covered by synthetic tests. |
| `quati-pt` | License check passes: CC-BY-4.0 per the `unicamp-dl/quati` card. Blocked on size (1.17 GB minimum collection) and on the absence of test qrels: only validation qrels are published, so a `test` split would be a carve-out of dev. |

## Adding a dataset

1. Add a recipe under `tools/dataset-fetch/dataset_fetch/recipes/` and its
   tests; no third-party dependency is allowed without a license review and a
   hash-locked `requirements.lock`.
2. Record the source revision, immutable file URLs, upstream SHA-256 sizes,
   and the license/terms revision in the manifest with `local_file_sha256`
   empty, then run `prepare`. The tool fills the local hashes, writes the lock
   and notice, and computes the §4.2 fingerprint.
3. Run `verify` offline; commit only `manifest.json`, `dataset-lock.json`, and
   `NOTICE.md`.
