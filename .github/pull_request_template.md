## Summary

<!-- What changed and why, in two or three sentences. -->

## Traceability

- Work package: WP-x.y
- Spec: SPEC-NNNN (requirement IDs: R…)
- ADRs touched/added:

## Gates

<!-- Which budgets/quality gates can this change affect? (P*, I*, R*, D*, O*, Q*) -->

- [ ] No quality/performance impact (explain why), **or**
- [ ] Benchmark report attached: `docs/benchmarks/results/...`

## Checklist

- [ ] Implements an **Accepted** spec (or is a bug fix / behavior-preserving refactor / docs / tooling)
- [ ] Tests written first and reference requirement IDs
- [ ] rustfmt + Prettier, clippy `-D warnings`, tests, `cargo deny`, TypeScript build, smoke eval pass
- [ ] Crate boundaries respected (no engine crate depends on `tauri`)
- [ ] New dependencies license-checked (ADR-0022)
- [ ] No hardcoded model dimensions/paths/prompts (ADR-0019)
- [ ] UI strings localized (en/pt) and both themes checked (if UI changed)
- [ ] No document content, personal paths, or secrets in code, logs, or docs
- [ ] `CHANGELOG.md`, spec status, and plan status table updated
