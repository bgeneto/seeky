# Benchmarks

Seeky is built with **Benchmark-Driven Development (BmDD)**: quality and
performance claims are accepted only with a reproducible report
([ADR-0017](../adr/0017-spec-and-benchmark-driven-development.md)).

| Document | Purpose |
|---|---|
| [`methodology.md`](methodology.md) | Protocol: datasets, metrics, hardware tiers, budgets, statistics, decision rules |
| [`candidates.md`](candidates.md) | Candidate registry for every bake-off (models, OCR, extractors, index engines, fusion, chunking) |
| [`judgment-review-prompt.md`](judgment-review-prompt.md) | Versioned instruction for a model reviewer of SDC queries and judgments (ADR-0026) |
| [`_report-template.md`](_report-template.md) | Required structure of every benchmark report |
| [`results/`](results/README.md) | Committed reports, one folder per run |

Inputs that are not documentation live outside `docs/`:

```text
bench/
  datasets/      dataset manifests + download scripts (pinned URLs and SHA-256)
  corpora/sdc/   Seeky Desktop Corpus generator; sdc-smoke subset committed for CI
  qrels/         relevance judgments (committed)
  configs/       pipeline configurations under test
tools/seeky-bench/   the harness (index, eval, perf, compare, report)
```

These directories are created in Phase 0–1 of the
[implementation plan](../plans/seeky-implementation-plan.md).

## Workflow

1. State the hypothesis and gate in the spec or work package (metric, slice,
   threshold, budget).
2. Run the baseline and the candidate with `seeky-bench` on the same split,
   tier, and commit.
3. Write the report from the template; include CIs and the decision.
4. If the result changes a default, write or update the ADR that cites it.
