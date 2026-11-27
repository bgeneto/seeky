# SDC generator (development tooling)

Deterministic generator for the Seeky Desktop Corpus defined by
[SPEC-0004](../../docs/specs/SPEC-0004-sdc-corpus-and-judgments.md). This is
offline dataset-prep tooling: it is never imported by an engine crate, never
ships with the product, and uses only the Python 3.12 standard library.

## Requirements and setup

- Python 3.12 or newer (the development host currently uses CPython 3.15).
- No third-party packages, no build step, no virtualenv required.
- `requirements.lock` records that the runtime dependency set is empty and
  therefore hash-locked by construction.

Run from `tools/sdc-generator/`:

```powershell
python -m unittest discover -s tests -v
```

From the repository root, put the tool on the path:

```powershell
$env:PYTHONPATH = "tools/sdc-generator"
python -m sdc_generator build --help
```

## Commands

```text
python -m sdc_generator fetch --sources <sources> --cache <cache>
python -m sdc_generator build --profile <profile.json> --seed <seed> \
  --sources <sources> --cache <cache> --output <corpus-dir>
python -m sdc_generator verify --output <corpus-dir>
python -m sdc_generator judgments validate --set <set-dir> \
  --corpus <corpus-dir> [--allow-draft]
python -m sdc_generator judgments freeze-split --draft <draft-dir>
python -m sdc_generator judgments publish --draft <draft-dir> \
  --output <frozen-dir>
```

Only `fetch` may open a network connection. `build`, `verify`, and every
`judgments` command read pinned cache objects, committed files, or local draft
data; a missing cache object is `CACHE_MISS`, not a download. A failed build
writes only into a sibling `.<name>.tmp` directory and leaves an existing
corpus untouched; `publish` likewise refuses an existing output directory and
writes atomically.

Successful `build` and `verify` print the corpus SHA-256 (`corpus_hash`);
`publish` prints the SHA-256 of the exact `judgment-set.json` bytes.
`validate` and `freeze-split` print a compact JSON summary. Structural errors
are one JSON object on stderr:

```json
{"code":"SCHEMA_INVALID","file":"sources/x.json","line":12,"field":"sha256","message":"..."}
```

Paths in diagnostics are repository- or cache-relative.

## Corpus data

`bench/corpora/sdc/` owns the manifests, profiles, renderer lock, notices, and
the committed `sdc-smoke` tree. `sdc-s` and `sdc-m` are generated on demand and
are not committed. See [its README](../../bench/corpora/sdc/README.md).

## Judgment sets

Draft and split-frozen sets live below `bench/qrels/sdc/drafts/<set-id>/` and
use the combined `queries.draft.jsonl`, `qrels.draft.documents.jsonl`,
`qrels.draft.passages.jsonl`, and `pools.draft.jsonl` files from SPEC-0004
§4.7. They are never benchmark-eligible:

- `judgments validate --allow-draft` checks schemas, ordering, provenance,
  target hashes against `--corpus`, and pool rows. The flag is refused outside
  a `drafts` directory and is never needed for a frozen set.
- `judgments freeze-split` requires state `draft`, every non-rejected query to
  be human-verified or adjudicated, no pool rows, and the SPEC-0004 query
  minima. It verifies the stratified assignment from §5.4 and records the exact
  future `dev`/`test` query-file digests in `query_file_sha256`.
- `judgments publish` requires state `split_frozen`, an unchanged query digest,
  complete provenance on every non-rejected record, and complete pool coverage.
  It omits `rejected` records, refuses a nonempty or incompatible test pool
  panel, writes the §4.3 split files atomically, and records `file_sha256`.
  The output directory must not exist.

Draft provenance is `human:<id>`, `llm:<model>@<revision>` with
`llm_prompt_sha256`, or `tool:<id>@<version>` with `tool_config_sha256`. A tool
or LLM draft is candidate data only: it has no authority over a relevance grade,
and `publish` refuses any record without human verification. A tool drafts only
`known_item`, `exact_identifier`, `needle_in_haystack`,
`mixed_semantic_metadata`, `filename_partial`, and `code_search` records, never
a `cross_lingual` slice (SPEC-0004 §4.6).

The minima applied by `freeze-split` and `publish` follow the set named by the
spec: `sdc-smoke-*` sets use the R26 smoke minima (at least five dev queries
per category, no test split); every other set, including a correction with a new
judgment-set ID, uses the full R16/R17 minima. `reviewers.json` is optional in
a draft; when present, recognized reviewer IDs are checked against every human
provenance value. Its only required content is pseudonymous IDs and roles.

## Determinism rules

- Values derive from `SHA-256("SDC1\0" + seed + "\0" + purpose + "\0" + key)`
  (SPEC-0004 §4.4), never from a wall clock, host, user, or global PRNG.
- No zlib-dependent output: ZIP containers are stored with fixed timestamps and
  Unix permissions; scans are bilevel PNGs whose deflate stream is written as
  stored blocks; JPEG is deliberately not used in v1.
- PDFs use base-14 Helvetica by name, fixed object order, and a seeded `/ID`.
  No current-date fields.
- Timestamps are whole UTC seconds inside the profile's closed interval.
- Output paths are POSIX-relative; no absolute path enters the corpus.

## Renderer coverage and gaps

Implemented and round-tripped through independent readers: DOCX, XLSX, PPTX,
ODT, RTF, HTML, EPUB, EML, MD, TXT, code (`py`, `rs`, `js`, `ts`, `go`, `sql`),
text PDF, image-only scanned PDF, and scanned PNG.

Formats supported by the Phase 0 engine are additionally checked against the
real extractors through a small harness:

```powershell
cargo build --manifest-path tools/sdc-generator/engine-roundtrip/Cargo.toml
# then run the engine round-trip test with PDFium available
python -m unittest tests.test_renderers -v
```

Known gaps for later work packages:

- Query and qrels *data* belong to WP-1.4; these commands validate and publish
  it but draft none of it.
- Scanned fixtures use 150 dpi bilevel PNG with deterministic speckle/skew.
  JPEG compression artifacts require a deterministic JPEG encoder and are
  deferred; WP-2.11 can extend the real-scan slice.
- ODT, RTF, EPUB, and EML have no engine extractor until WP-3.4; the independent
  readers in `sdc_generator/readers.py` are the required interim oracle.
- This version uses only committed synthetic templates (MIT). External
  public-domain/CC-BY source sets are supported by the manifest and `fetch`
  code and are exercised with local fixtures, but no external sources are
  pinned in v1; adding them needs maintainer license review (§7 question 4).
- Full `sdc-m` materialization is not generated; its profile and the prefix
  logic are validated at reduced scale.
