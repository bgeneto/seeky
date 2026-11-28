# ADR-0028 — Hosted-model drafting of evaluation data for synthetic corpora (amends 0021, 0026)

- **Status:** Accepted (maintainer, 2026-11-28)
- **Date:** 2026-11-28
- **Related:** [ADR-0021](0021-no-generative-models-in-product.md) decision 3,
  [ADR-0026](0026-model-verified-evaluation-judgments.md),
  [ADR-0022](0022-permissive-license-gate.md),
  [SPEC-0004](../specs/SPEC-0004-sdc-corpus-and-judgments.md) 0.4 (R21, §5.5,
  §6.3), [`query-drafting-brief.md`](../benchmarks/query-drafting-brief.md) v1,
  [`judgment-review-prompt.md`](../benchmarks/judgment-review-prompt.md) v1

## Context

ADR-0021 decision 3 lets development tooling use LLMs **offline** to draft
evaluation queries and relevance judgments, and SPEC-0004 §5.5 makes the
whole drafting workflow offline: no corpus text, prompt, query, or judgment
goes to a hosted service. ADR-0026 already relaxed the *verification* side:
a hosted model may review synthetic, redistributable corpora such as SDC,
because their text is public and contains no user data.

The drafting side was left offline, and the local drafter is too weak for the
semantic categories. In the first H6 pass on `sdc-smoke-v1`, most
Qwen3-0.6B drafts in `conceptual`, `cross_language`, and `exploratory`
failed review (10 of 15 rejected), which left those categories below the five
verified queries that SPEC-0004-R26 requires. Ten replacement queries with
full judgments were then drafted by a hosted model (`235269a`, under
`query-drafting-brief.md` v1); as SPEC-0004 stands they cannot be promoted.
The same gap will recur on the 732-query `sdc-v1` set, where the
Qwen3-0.6B drafts cover the same three categories.

ADR-0026's reasoning applies to drafting unchanged: SDC is synthetic,
generated from licensed templates, and already committed to a public
repository (ADR-0022). Sending its text to a hosted model reveals nothing
that is not public, and P3 (local-first) is about user documents, which are
not involved. A larger local model would also work, but costs a license
check, a drafter bake-off, and hours of machine time that compete with the
quiet window the WP-1.7 performance runs need.

## Decision

1. **A hosted model may draft.** For corpora that are synthetic and
   redistributable (SDC and its profiles), a hosted LLM may draft queries,
   candidate document judgments, and candidate passage judgments, besides the
   offline `qrels-drafter` and local models.
2. **Same provenance as any LLM draft.** A hosted draft carries
   `drafted_by: llm:<model-id>@<revision>`, where the revision is the
   provider's pinned snapshot ID (no alias that can move), and
   `llm_prompt_sha256` over a committed, versioned drafting instruction (today
   `query-drafting-brief.md`). A change to the instruction is a new version;
   a version a draft cites is never edited in place.
3. **Drafts stay candidates.** Nothing about verification changes: a hosted
   draft has no grade authority, is `state: draft` with empty `verified_by`,
   and a different reviewer (ADR-0026 decision 2: never the drafting
   identity) verifies it with the review prompt before promotion.
4. **Never for non-synthetic data.** Corpora built from real user documents,
   private files, or restricted datasets stay offline: any model that drafts
   for them runs locally (the ADR-0026 decision 5 boundary, now applied to
   drafting too).
5. **Applies to drafts already committed.** The `sdc-smoke-v1` records
   drafted under this rule before its acceptance (`235269a`) become eligible
   for review and promotion on the same terms.
6. **Unchanged.** Template-faithful categories keep the deterministic tool;
   the rubric, split freezing, pooling, publication, and harness eligibility
   checks are untouched; nothing a drafter produces ships in the product or
   runs on user data (ADR-0021 decisions 1 and 2).

## Consequences

- The SDC drafting workflow is no longer entirely offline. SPEC-0004 moves to
  0.5: R21, §5.5, and the §6.3 inspection describe the offline requirement as
  applying to non-synthetic corpora only. `qrels-drafter` stays offline
  (its network-boundary test is unchanged); a hosted drafter works outside
  that tool, from the drafting brief.
- `sdc-smoke-v1` can be completed by a second-model review of the hosted
  drafts, then `freeze-split` and `publish`, which unblocks WP-1.8 and the
  WP-1.2 smoke evaluation. The weak categories of `sdc-v1` can be redrafted
  the same way.
- Risks:
  - *Shared bias between drafter and reviewer.* Two models of one family may
    accept each other's mistakes. Mitigation: the reviewer must be a
    different model identity; a reviewer from a different model family is
    preferred for `test` drafts; benchmark reports name the drafter and the
    reviewer of each category.
  - *Model-written queries are more fluent and may echo corpus wording,*
    favouring lexical systems. Mitigation: the drafting brief requires
    natural, short queries and forbids copying corpus phrases; the reviewer
    rejects literal-copy queries.
  - *Exposure to the provider.* The corpus and queries are already public on
    GitHub, so a provider seeing them adds no new exposure; the bake-off
    candidates are encoders, not the drafting model.
  - *Reproducibility.* A hosted draft cannot be regenerated byte for byte.
    The committed records, the pinned snapshot ID, and the instruction hash
    are the audit trail; drafts are never regenerated in place after review.
- Forbidden: hosted drafting for any non-synthetic or private corpus; a
  moving model alias as a drafter identity; a model verifying its own draft;
  drafting without a committed, hashed instruction.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Keep drafting offline with Qwen3-0.6B | Most semantic-category drafts fail review; WP-1.4 and WP-1.8 stay blocked |
| A larger local drafting model | Valid but slower: license check, a new drafter bake-off, and machine time that delays the WP-1.7 quiet-window runs; still allowed under this ADR |
| Human drafting | No human drafters are available for hundreds of queries |
| Discard the semantic categories from the smoke set | Breaks SPEC-0004-R26 (five verified queries per category) and weakens the WP-1.8 gate |

## Evidence

- First H6 review of `sdc-smoke-v1`
  (`bench/qrels/sdc/reviews/sdc-smoke-v1.claude-opus-5-5.prompt-v1.jsonl`,
  `4a8c692`): 10 of the 15 Qwen3-0.6B queries in the three semantic
  categories rejected.
- Replacement drafts q46–q55 with full judgments (`235269a`), drafted under
  `query-drafting-brief.md` v1 and still `state: draft`.
