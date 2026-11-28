# ADR-0027 — Progressive reranking with its own latency budget

- **Status:** Proposed
- **Date:** 2026-11-27
- **Related:** [ADR-0019](0019-single-inference-engine.md),
  [ADR-0016](0016-cpu-first-npu-ready-execution.md),
  [WP-0.6 gate report](../benchmarks/results/2026-11-27-ort-gate/summary.md),
  [methodology](../benchmarks/methodology.md) §5.1 (S3) and §8.7 (K1),
  [retrieval engine](../architecture/retrieval-engine.md) §6.1 and §8,
  plan WP-2.3 and WP-4.8

## Context

The WP-0.6 gate fired K1 for the reranker role. The K1 target, derived from
S3 headroom, is a depth-50 p95 of at most 250 ms on T1, CPU-only. Measured on
the T1-emulated profile with ONNX Runtime:

| Cross-encoder | Variant | Depth-50 p50 | Depth-50 p95 |
|---|---|---:|---:|
| gte-multilingual-reranker-base (proxy) | fp32 | 8,457 ms | 9,934 ms |
| hs-rerank-1 (amendment 3) | published ONNX | 2,285 ms | 4,966 ms |

The fastest measured cross-encoder misses the target by 20× at p95. Fifty
pairs of about 180 tokens are about 9,000 tokens of encoder work per query,
so the gap comes from the budget, not the runtime. No engine named in WP-2.3
plausibly closes a 20× gap (report §3.1; the vendor-claimed 5.5× for native
OpenVINO would not). K3 also fired, so NPU offload cannot carry the default
on this stack.

At gate H5 (2026-11-27) the maintainer accepted the report's recommendation:
revisit the reranker budget or depth by ADR before any engine bake-off,
instead of starting WP-2.3 for the reranker. ADR-0019 stands for the embedder
role (amendment 2 shows ORT meets the embedder targets with compact models)
and for OCR (the isolated O2 reading decides).

The vision (§5.1) keeps the reranker in the default first-run download, and
the retrieval engine already delivers results progressively (Instant, Hybrid,
Refined) with cancellation between stages and a fail-open reranker. The user
sees Hybrid results within S2; reranking reorders them afterwards.

## Decision

1. **Reranking is a progressive refinement, not part of S3.** The Refined
   stage is delivered in two steps: S3 (≤ 400 ms p95) covers diversity and
   snippets over the Hybrid ordering; reranked results replace them when the
   cross-encoder finishes. The reranker stays in the default download (vision
   §5.1) and stays fail-open and cancellable on every keystroke.
2. **New provisional budget S6:** reranked refinement at the default depth,
   p95 ≤ 1.5 s on T1, CPU-only, warm, measured from query submission. It
   follows the methodology §5 rules: provisional until the budgets ADR locks
   it.
3. **Depth follows the budget.** The default depth (documents × passages per
   document) is no longer fixed at 50 pairs. WP-4.8 sets it to the largest
   depth whose p95 meets S6 for the bake-off winner, with a floor of 10 pairs.
   Adaptive depth by query class (retrieval engine §6.1) still applies below
   that cap.
4. **K1 for the reranker** is re-derived from S6: the role passes when its
   best ORT CPU variant meets S6 at a depth of at least 10 pairs. The WP-0.6
   measurements are not reinterpreted; the check runs in WP-4.8 with
   `seeky-bench`. WP-2.3 starts for the reranker only if no ORT-runnable
   candidate meets it there.
5. **Reranking must earn its cost.** WP-4.8 keeps a cross-encoder in the
   default only if it beats the Hybrid ordering on the quality gate (Q6) by
   more than the confidence interval at the chosen depth. Otherwise the
   default ships without a reranker, by a new ADR that also amends vision
   §5.1.

## Consequences

- The UI shows Hybrid results first and reorders in place when reranking
  lands; the reorder must not move the item under the pointer or keyboard
  focus (WP-4.8 integration and the UI spec).
- Methodology §5.1 gains S6, and the §8.7 K1 reranker target changes to point
  at it, in the commit that accepts this ADR. The retrieval engine §8 table
  splits the Refined stage the same way.
- A shallower depth lowers the reranker's quality ceiling; Q6 decides whether
  what remains is worth shipping.
- Forbidden: blocking the Hybrid results on the reranker, holding a lock
  across reranker inference, and making an NPU or GPU required to meet S6.
- The reranker's share of D2 is unchanged by this ADR; the K4 finding (the
  proxies alone exceed D2) belongs to the bake-offs.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Keep 250 ms at depth 50 and start WP-2.3 | No candidate engine plausibly closes a 20× gap; spends a bake-off on a foregone result |
| Keep the budget, cut depth only | At about 100 ms per pair at p95 (hs-rerank-1), 250 ms allows two or three pairs, too few to change a ranking |
| Make reranking an opt-in pack outside the default | Conflicts with vision §5.1; decision 5 reaches it only if Q6 shows no gain |
| NPU-only reranking | K3 fired on this NPU stack; ADR-0016 forbids an accelerator-only default |
| Distill a smaller reranker now | A post-1.0 mitigation in the plan's risk table; needs the SDC judgments first |

## Evidence

- [`docs/benchmarks/results/2026-11-27-ort-gate/summary.md`](../benchmarks/results/2026-11-27-ort-gate/summary.md)
  §2 (reranker rows), §3.1, §4.
- S6's 1.5 s is a proposal, not a measurement: at the hs-rerank-1 published
  ONNX p95 per pair, it allows roughly 15 pairs. WP-4.8 verifies it.
