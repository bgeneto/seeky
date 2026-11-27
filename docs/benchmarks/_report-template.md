# <YYYY-MM-DD> — <area>: <short title>

| Field | Value |
|---|---|
| Work package / spec | WP-x.y / SPEC-NNNN |
| Hypothesis | What should improve, by how much, where |
| Gate(s) | Budget/quality IDs from `methodology.md` (e.g. S2, Q2, Q6) |
| Decision | Adopt / Reject / Inconclusive (and the ADR updated) |
| Commit | `<sha>` (dirty tree not allowed) |
| Config hash | `<hash of RankingConfig/EngineConfig>` |
| Hardware tier | T0 / T1 / T1-emulated / T2 — plus captured environment |

## 1. Setup

- Datasets and versions (with checksums), split used (`dev` or `test`).
- Systems compared (baseline first), model IDs and file hashes, providers.
- Exact `seeky-bench` command lines.

## 2. Results

### Quality

| System | Weighted nDCG@10 | pt | en | cross-lingual | other | Recall@100 | MRR@10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | | | | | | | |
| candidate | | | | | | | |

Per-category table, paired differences with 95 % CIs and p-values.

### Performance

| System | S1 p95 | S2 p95 | S3 p95 | passages/s | RSS idle | RSS peak | disk/1M | download |
|---|---:|---:|---:|---:|---:|---:|---:|---:|

### Pareto view

Quality × latency (and memory/download where relevant). Include the plot file.

## 3. Analysis

What changed, why, failure cases (with query IDs, not private content),
threats to validity.

## 4. Decision and follow-ups

Decision per the rule in `methodology.md` §7, the ADR created/updated, and any
follow-up work packages.

## 5. Reproduction

Steps and artifact locations; raw outputs not committed are described here.
