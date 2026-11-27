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
```

Only `fetch` may open a network connection. `build` and `verify` read pinned
cache objects and committed files; a missing cache object is `CACHE_MISS`, not
a download. A failed build writes only into a sibling `.<name>.tmp` directory
and leaves an existing corpus untouched.

Successful `build` and `verify` print the corpus SHA-256 (`corpus_hash`).
Structural errors are one JSON object on stderr:

```json
{"code":"SCHEMA_INVALID","file":"sources/x.json","line":12,"field":"sha256","message":"..."}
```

Paths in diagnostics are repository- or cache-relative.

## Corpus data

`bench/corpora/sdc/` owns the manifests, profiles, renderer lock, notices, and
the committed `sdc-smoke` tree. `sdc-s` and `sdc-m` are generated on demand and
are not committed. See [its README](../../bench/corpora/sdc/README.md).

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

- `judgments` commands and query/qrels data belong to WP-1.4; the CLI does not
  implement them yet.
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
