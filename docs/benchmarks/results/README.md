# Benchmark results

One folder per run, named `YYYY-MM-DD-<area>-<slug>/`, containing:

```text
summary.md       human report following ../_report-template.md
results.json     machine-readable metrics, environment, and config
config.json      pipeline/engine configuration used
plots/           optional Pareto or latency plots
```

Rules:

- Reports are produced by `tools/seeky-bench` under
  [`../methodology.md`](../methodology.md); hand-edited numbers are not accepted.
- Never commit document content, file names, or paths from private corpora.
- Raw outputs larger than a few MB are regenerated from the recorded commands
  instead of being committed.
- Reports that change a default are cited by an ADR in [`../../adr/`](../../adr/README.md).

The first planned report is the **B0 baseline** of the as-built PoC (plan
work package WP-1.7).
