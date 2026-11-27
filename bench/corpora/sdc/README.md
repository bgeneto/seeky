# Seeky Desktop Corpus (SDC)

Data layout and regeneration for SPEC-0004. Only `sdc-smoke` is committed;
`sdc-s` and `sdc-m` are generated locally and must stay untracked.

```text
bench/corpora/sdc/
  renderers.lock.json     pinned renderer implementation, assets, and scan recipes
  sources/                pinned source manifests, synthetic templates, notices
  profiles/               sdc-smoke.json, sdc-s.json, sdc-m.json
  sdc-smoke/              committed generated corpus (200 files, < 64 MiB)
  logs/                   generation evidence for scale profiles
  sdc-s/                  generated on demand, gitignored
  sdc-m/                  generated on demand, gitignored
```

## Regenerating the committed smoke corpus

From the repository root:

```powershell
$env:PYTHONPATH = "tools/sdc-generator"
python -m sdc_generator build `
  --profile bench/corpora/sdc/profiles/sdc-smoke.json `
  --seed sdc-smoke-v1 `
  --sources bench/corpora/sdc/sources `
  --cache <source-cache> `
  --output bench/corpora/sdc/sdc-smoke
python -m sdc_generator verify --output bench/corpora/sdc/sdc-smoke
```

The build is byte-identical for the same seed, profile, source cache, and
renderer lock. It needs no network: every source in v1 is a committed synthetic
template. `fetch` exists for future external source sets.

## Scale profiles

```powershell
python -m sdc_generator build `
  --profile bench/corpora/sdc/profiles/sdc-s.json `
  --seed sdc-s-v1 `
  --sources bench/corpora/sdc/sources `
  --cache <source-cache> `
  --output bench/corpora/sdc/sdc-s
python -m sdc_generator verify --output bench/corpora/sdc/sdc-s
```

`sdc-m` extends `sdc-s` with distractors; only its reduced recipe is validated
until the profile is materialized for a benchmark gate.

## Sources and licensing

`redistribution_class = permissive-core` requires public domain, CC0, CC-BY-4.0,
or an ADR-0022-compatible permissive license, a complete pin, and a notice.
Ineligible sources (sharealike, non-commercial, no-derivatives, research-only)
are rejected. The committed v1 corpus uses only the MIT-licensed synthetic
templates listed in `sources/synthetic-office-v1.json`; every company, person
role, identifier, and address is fictitious, and e-mails use reserved example
domains. See `sources/notices/` for attribution and `renderers.lock.json` for
the renderer/font asset licenses.

## What is committed

`sdc-smoke/` (rendered files and sidecars), the source manifests/templates,
profiles, renderer lock, notices, and `logs/`. Never commit `sdc-s/`, `sdc-m/`,
the source cache, model weights, or personal documents.

## Verified scale run

`sdc-s` was materialized on 2026-11-27 with seed `sdc-s-v1` from the committed
synthetic sources, and `python -m sdc_generator verify` passed on the result:
10,000 rendered files, 109,689 canonical passages, 112.5 MB, corpus hash
`1d65b8ff04091850b8deefa34f5658bee0b87ec4ff29667f002f6cec88ac2ef0`. The tree
stays git-ignored; this records the SPEC-0004 R5 scale proof.
