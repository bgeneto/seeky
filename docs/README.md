# Documentation

This directory contains the Seeky product, engineering, research, and validation
documentation.

## Start here

| Document | Purpose |
|---|---|
| [`plans/seeky-implementation-plan.md`](plans/seeky-implementation-plan.md) | Active implementation plan, milestones, architecture, targets |
| [`product/seeky-scope.md`](product/seeky-scope.md) | Product scope and explicit non-goals |
| [`decisions/seeky-adrs.md`](decisions/seeky-adrs.md) | Architecture decisions for the shipped Rust/Tauri implementation |
| [`validation/seeky-poc-validation.md`](validation/seeky-poc-validation.md) | Build, test, runtime, watcher, and backend evidence |

## Reference material

- [`research/`](research/README.md) — Gety reverse-engineering research and model notes.
- [`audits/`](audits/README.md) — report verification, evidence ledger, source report.
- [`assets/screenshots/`](assets/README.md) — Seeky and Gety UI captures.
- [`archive/`](archive/README.md) — retired planning documents kept for history.

## Documentation rules

1. The active implementation plan is the source of truth for engineering scope.
2. Implementation changes update the plan when they affect milestones or contracts.
3. Runtime claims require evidence in `validation/` or `audits/`.
4. Historical plans are archived, marked superseded, and never referenced as the
   current build contract.
5. Do not put local document content or unredacted personal data in documentation.
