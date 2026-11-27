# ADR-0026 — Model-verified evaluation judgments (amends 0021)

- **Status:** Accepted
- **Date:** 2026-11-27
- **Related:** [ADR-0021](0021-no-generative-models-in-product.md) decision 3,
  [ADR-0017](0017-spec-and-benchmark-driven-development.md),
  [SPEC-0004](../specs/SPEC-0004-sdc-corpus-and-judgments.md) 0.4 (R20–R22,
  §4.6, §5.5), [SPEC-0003](../specs/SPEC-0003-evaluation-harness.md) R30

## Context

ADR-0021 decision 3 lets development tooling use LLMs offline to draft
evaluation queries and relevance judgments "that humans then verify".
SPEC-0004 turned that into gate H6: every published query and judgment needs
a `human:<id>` in `verified_by`, and the drafting workflow sends nothing to a
hosted service.

Human verification of every record is the bottleneck of Phase 1: WP-1.4
(≥ 600 queries with document and passage judgments), the `sdc-smoke-v1` set
that WP-1.8 needs, and WP-10.1 later. The first smoke review packet (45
queries) showed that most defects are mechanical — unexpanded duplicate
clusters, hard negatives that contain the literal target, ambiguous
known-item and filename targets — which a capable model reviewer with corpus
access finds faster and more consistently than a person reading a packet.

The SDC corpus is fully synthetic, generated from licensed templates, and
committed to a public repository (ADR-0022). Sending its text to a hosted
model reveals nothing that is not already public, and involves no user data,
so P3 (local-first) is not at stake.

The maintainer decided on 2026-11-27 that a model may replace the human
verifier for every judgment set, without a mandatory human sample.

## Decision

1. **A model may verify.** `verified_by` accepts `llm:<model-id>@<revision>`
   reviewers besides `human:<id>`. A verified or adjudicated record needs at
   least one reviewer of either kind. For a hosted model the revision is the
   provider's pinned model snapshot ID (for example
   `llm:claude-opus-5-5@claude-opus-5-5`); an alias that can move to another
   snapshot is not allowed.
2. **No self-verification.** A model reviewer never verifies a record whose
   `drafted_by` is the same `llm:` identity. Tool- and human-drafted records,
   and records drafted by a different model, may be model-verified.
3. **Adjudication** needs two distinct reviewers of either kind; the
   adjudicator is one of them.
4. **No mandatory human sample.** Neither `dev` nor `test` requires a human
   reviewer. A human may still verify, re-verify, or adjudicate any record,
   and the 10% second-review recommendation of SPEC-0004 §5.5 may be met by a
   second model or a human.
5. **Hosted verifiers only on synthetic, public corpora.** A hosted model may
   read corpus text, queries, and judgments only for corpora that are
   synthetic and redistributable (SDC and its profiles). Corpora built from
   real user documents, private files, or restricted datasets stay offline:
   any model that reads them runs locally.
6. **Fixed review instruction.** A model reviewer follows the versioned
   prompt in [`judgment-review-prompt.md`](../benchmarks/judgment-review-prompt.md);
   a change to it is a new prompt version. Benchmark reports on a
   model-verified set name the reviewer identity and the prompt version.
7. **Unchanged.** The rubric, the evidence rules, split freezing, pooling,
   publication, and the eligibility checks of the harness stay as they are; a
   model reviewer is held to the same rubric as a human. Nothing produced by a
   reviewer ships in the product or runs on user data; ADR-0021 decisions 1
   and 2 are untouched.

## Consequences

- Gate H6 becomes "a reviewer verifies": the maintainer or a model. WP-1.4,
  the `sdc-smoke-v1` set, and WP-1.8 are no longer blocked on manual review.
- `tools/sdc-generator` (`judgments validate`, `freeze-split`, `publish`),
  `seeky-eval` qrels loading, and the `seeky-bench` smoke gate accept
  `llm:` reviewers.
- Risk: an LLM judge can share biases with the systems under test (lexical
  overlap, preference for model-written text). Mitigations: the bake-off
  candidates are encoders, not the reviewer model; benchmark reports name the
  reviewer identity of the judgment set; a human or a second model can
  re-verify a sample at any time, and a disagreement is adjudicated.
- Forbidden: a model verifying its own draft; a moving model alias as a
  reviewer identity; sending non-synthetic or private corpus text to a hosted
  model.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Keep human verification of every record (status quo) | Blocks Phase 1 on hundreds of manual reviews; most defects found are mechanical |
| Model verification plus a mandatory 10% human sample of `test` | Considered and offered; the maintainer chose full model review |
| Let the drafting model also verify | Self-verification adds no independent check |

## Evidence

The sdc-smoke-v1 pre-screen of 2026-11-27 (45 queries): 10 accepted as
drafted; the rest failed on duplicate expansion, literal-target hard
negatives, ambiguous targets, and weak LLM-drafted queries, all detectable
from the corpus files.
