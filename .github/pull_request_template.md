## Summary

<!-- What changed and why, in two or three sentences. -->

## Traceability

- Work package: WP-x.y
- Spec: SPEC-NNNN (requirement IDs: R…)
- ADRs touched/added:
- WP status after this change (plan §15.3): Not started / In progress / Done
- Commits carry the `Refs: WP-x.y, SPEC-NNNN` trailer

## Gates

<!-- Which budgets/quality gates can this change affect? (S*, I*, R*, D*, O*, V*, Q*) -->

- [ ] No quality/performance impact (explain why), **or**
- [ ] Benchmark report attached: `docs/benchmarks/results/...`

## Checklist

- [ ] Implements an **Accepted** spec (or is a bug fix / behavior-preserving refactor / docs / tooling)
- [ ] Tests written first, reference requirement IDs, and meet AGENTS.md §6 Tests (regression test for a fix, hermetic, hardware-free by default)
- [ ] Green, logical commits with semantic messages and `Refs:` trailers; nothing of mine left uncommitted (AGENTS.md §9)
- [ ] rustfmt + Prettier, clippy `-D warnings`, tests, `cargo deny`, TypeScript build, smoke eval pass
- [ ] Crate boundaries respected (no engine crate depends on `tauri`)
- [ ] New dependencies license-checked (ADR-0022)
- [ ] No hardcoded model dimensions/paths/prompts (ADR-0019)
- [ ] UI strings localized (en/pt) and both themes checked (if UI changed)
- [ ] No document content, personal paths, or secrets in code, logs, or docs
- [ ] Recorded in the same commit (AGENTS.md §4 step 8): plan §15.3 row with evidence (and §15.2, §16), spec requirement status and index, ADR index, conformance audit rows, `CHANGELOG.md`; AGENTS.md §3/§5 and `CONTRIBUTING.md` if paths or commands changed
