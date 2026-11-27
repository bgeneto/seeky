# Documentation map

## Precedence

When two documents disagree, the higher one wins and the lower one is
corrected:

1. [`product/vision.md`](product/vision.md) — vision, non-negotiable principles, scope, product decisions
2. [`adr/`](adr/README.md) — Accepted architecture decision records
3. [`specs/`](specs/README.md) — Accepted specifications (Spec-Driven Development)
4. [`architecture/`](architecture/README.md) — target architecture contracts
5. [`plans/seeky-implementation-plan.md`](plans/seeky-implementation-plan.md) — phases, work packages, status
6. [`benchmarks/methodology.md`](benchmarks/methodology.md) — budgets, gates, evaluation protocol

## Directory guide

| Directory | Contents | Binding? |
|---|---|---|
| [`product/`](product/vision.md) | Product constitution | Yes |
| [`adr/`](adr/README.md) | One decision per file, MADR-style | Yes (Accepted) |
| [`specs/`](specs/README.md) | Spec process, template, planned specs | Yes (Accepted) |
| [`architecture/`](architecture/README.md) | Overview, indexing, retrieval engine, inference and models, provisioning | Yes |
| [`plans/`](plans/README.md) | The single active implementation plan | Yes |
| [`benchmarks/`](benchmarks/README.md) | Methodology, candidate registry, report template, results | Yes (protocol); results are evidence |
| [`validation/`](validation/seeky-poc-validation.md) | As-built PoC runtime evidence; [conformance audit](validation/poc-conformance-audit.md) against the ADRs | Evidence |
| [`glossary.md`](glossary.md) | Terminology | Reference |
| [`research/`](research/README.md) | Gety reverse-engineering notes, supplied reports | No — context only |
| [`archive/`](archive/README.md) | Superseded documents | No |
| [`assets/`](assets/README.md) | Screenshots | — |

## Documentation rules

1. One canonical place per topic; link instead of copying.
2. Product or architecture changes go through an ADR; numeric defaults go
   through a benchmark report.
3. Runtime and performance claims require evidence in `benchmarks/results/` or
   `validation/`.
4. Superseded documents move to `archive/` with a pointer to their replacement.
5. Docs are in English. No document content, personal paths, or secrets.
