# SPEC-0003 reference fixtures v1

Generated 2026-11-27 for SPEC-0003 §5.8. Synthetic IDs only; no corpus content.

- `qrels.tsv`, `run.trec`: standard-metric inputs, `metrics-v1` (§5.8 A).
- `expected.json`: one machine-readable file holding the `metrics-v1`,
  `duplicates-v1` (§5.8 B), `diversity-v1` (§5.8 C) and `statistics-v1`
  (§5.3) blocks, so no second copy of the numbers can drift.
- `../report-v1/expected.md`: deterministic Markdown golden (§4.7, §5.8).

## Provenance and tool versions

- nDCG/MRR/Recall/Success: `pytrec-eval-terrier==0.5.11` under Python 3.15.0,
  measures `ndcg_cut.10`, `recip_rank`, `recall.10`, `success.1`. nDCG uses the
  trec_eval linear-gain convention; queries without positive judgments score 0.
- Diversity: `ir-measures==0.4.3` and `pyndeval==0.0.8`, α = 0.5, k = 10,
  cross-checked against the §5.2 formula.
- Duplicate rate and statistics: computed from the SPEC-0003 §4.4/§5.3
  formulas with seed `seeky-eval-reference-v1` (see `src/stats.rs`).
- Markdown golden: produced by `render_markdown` in `src/report.rs`.

## Reproduction of the expected values

Standard metrics, over the committed `qrels.tsv` and `run.trec`:

```python
import pytrec_eval
run = pytrec_eval.parse_run("run.trec")
qrels = pytrec_eval.parse_qrel("qrels.tsv")
evaluator = pytrec_eval.RelevanceEvaluator(
    qrels, {"ndcg_cut.10", "recip_rank", "recall.10", "success.1"}
)
print(evaluator.evaluate(run))
```

Diversity, over the §5.8 C records transcribed in
`src/metrics.rs::diversity_fixture` (qrels `dA=3[x] dB=2[x] dC=2[y] dD=1[z]
dE=3[y,z]`, run `dA,dB,dC,dD`, α = 0.5, k = 10):

```python
import ir_measures
from pyndeval import AlphaNDCG

qrels = {
    "qexp": {"dA": 3, "dB": 2, "dC": 2, "dD": 1, "dE": 3},
}
run = {"qexp": {"dA": 3.0, "dB": 2.0, "dC": 1.0, "dD": 0.5}}
# pyndeval additionally consumes the per-document subtopic labels.
print(ir_measures.calc_aggregate([AlphaNDCG(alpha=0.5, cutoff=10)], qrels, run))
```

Statistics (§5.3 eight-query differences, 10,000 resamples, seed
`seeky-eval-reference-v1`) and duplicate rate (§5.8 B, no external tool) are
recomputed by `committed_reference_fixtures_match_expected_json` and
`randomization_and_bootstrap_match_fixed_seed_reference`, which read
`expected.json` directly.

## Consumers

`src/metrics.rs::committed_reference_fixtures_match_expected_json` parses the
committed `qrels.tsv`/`run.trec` through the public loaders and compares every
`expected.json` block against the computed metrics;
`src/stats.rs::randomization_and_bootstrap_match_fixed_seed_reference` reads the
`statistics-v1` block; `src/report.rs::markdown_report_matches_golden` uses the
report golden. The named requirement tests in the same modules carry the
requirement IDs.
