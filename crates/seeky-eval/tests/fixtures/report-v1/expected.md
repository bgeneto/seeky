# 2026-11-27 — quality: Fixture

| Field | Value |
|---|---|
| Work package / spec | WP-1.1 / SPEC-0003 |
| Hypothesis | Metrics render |
| Gate(s) | Q1 |
| Decision | NotApplicable |
| Commit | `0123456789abcdef0123456789abcdef01234567` |
| Config hash | `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` |
| Hardware tier | not measured |

## 1. Setup

- Dataset: `fixture`; split `dev`; configuration `default`.
- Corpus hash: `corpus-hash`; judgment set: `judgment-set`; fingerprint: `fingerprint`.
- System: `system`; provider: `cpu`.
- Command: `seeky-eval`.

## 2. Results

### Quality

| System | Weighted nDCG@10 | pt | en | cross-lingual | other | Recall@100 | MRR@10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| system | — | 1.000000 | 1.000000 | — | — | 1.000000 | 1.000000 |

| Category | nDCG@10 |
|---|---:|
| conceptual | 1.000000 |

### Performance

Not measured in this run.

### Pareto view

Not generated

## 3. Analysis


## 4. Decision and follow-ups

- Status: `NotApplicable`.
- Evidence only

## 5. Reproduction

- Run: `seeky-eval`.
- Commit: `0123456789abcdef0123456789abcdef01234567`.
- Config hash: `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`.
- Artifacts: run=`run.trec`, config_snapshot=`config.snapshot.json`, environment=`environment.json`, checksums=`checksums.sha256`.

