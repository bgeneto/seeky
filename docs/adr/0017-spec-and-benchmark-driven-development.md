# ADR-0017 — Spec-Driven + Benchmark-Driven Development

- **Status:** Accepted
- **Date:** 2026-11-27
- **Related:** [`../specs/README.md`](../specs/README.md), [`../benchmarks/methodology.md`](../benchmarks/methodology.md), [`../../AGENTS.md`](../../AGENTS.md)

## Context

Seeky is built largely by AI coding agents. Agents are fast but need precise,
checkable contracts; retrieval quality and latency cannot be judged by reading
code. Components must never be chosen for popularity or leaderboard position.

## Decision

1. **Spec-Driven Development (SDD).** Every non-trivial work package starts from
   an Accepted spec in `docs/specs/` with EARS-style requirements, interfaces,
   acceptance tests, and benchmark gates. Code without a spec is limited to
   bug fixes, refactors with no behavior change, and tooling.
2. **Benchmark-Driven Development** (abbreviated **BmDD** in this repository to
   avoid confusion with Behavior-Driven Development). Any change that can
   affect retrieval quality, latency, throughput, memory, disk, or download size
   must state its gate up front and attach a benchmark report produced by
   `seeky-bench` under the protocol in `docs/benchmarks/methodology.md`.
3. **Component selection by bake-off.** Models, index engines, OCR engines, and
   extractors are selected by a reproducible bake-off with a declared decision
   rule (constraint satisfaction on budgets, then quality), recorded in an ADR.
4. **Evidence over assertion.** "Faster", "better", or "SOTA" claims without a
   report are rejected in review.

## Consequences

- The evaluation harness and baseline measurement precede retrieval work.
- CI runs fast quality/latency smoke gates; full runs happen on reference
  hardware and are committed as reports.
- Specs and reports are first-class review artifacts for agent PRs.
