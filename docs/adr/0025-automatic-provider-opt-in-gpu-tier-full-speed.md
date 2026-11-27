# ADR-0025 — Automatic provider selection, opt-in GPU quality tier, and full-speed indexing

- **Status:** Accepted
- **Date:** 2026-11-27
- **Amends:** [ADR-0016](0016-cpu-first-npu-ready-execution.md) §3–§4 (refines; does not reverse)
- **Related:** [ADR-0019](0019-single-inference-engine.md), [ADR-0023](0023-multimodal-ready-engine.md) (generations and embedding channels), [ADR-0011](0011-slim-first-run-provisioning.md), [ADR-0012](0012-two-themes-minimal-ui-en-pt.md), SPEC-0007 (governor), SPEC-0012 (providers), [SPEC-0014](../specs/SPEC-0014-desktop-experience.md) (v2 UI), [methodology](../benchmarks/methodology.md) §5 and §8.6

## Context

Many users own a discrete or integrated GPU. Small models (for example the
0.6B Qwen3 embedder and reranker in
[candidates](../benchmarks/candidates.md) §1–§2) miss the CPU budgets (kill
criterion K1: ≥ 56 passages/s, batch-1 query p95 ≤ 20 ms, reranking 50 pairs
p95 ≤ 250 ms) yet run quickly on such a GPU. The question is whether Seeky
should switch to them automatically when it detects a GPU.

Two different decisions hide in that question:

1. **Which execution provider runs a given model.** Same model, same vectors
   within the manifest parity tolerance; only speed and energy change. Cheap
   to change, reversible at any moment.
2. **Which model runs.** A different embedder means a different vector space,
   a new index generation, a reindex, a larger download, and different ranked
   output. A different reranker changes ranked output and download, but not
   the index.

GPU presence is volatile on laptops: hybrid graphics power the discrete GPU
down on battery, driver updates break runtimes, external GPUs are unplugged.
A desktop search engine also runs in the background, where a discrete GPU
costs battery, fan noise, and VRAM that the user's own applications need.
GPU runtimes (CUDA, TensorRT) add hundreds of megabytes to gigabytes of
download (ADR-0016, budget D2).

The user also needs a way to say "index as fast as you can, now", for example
after adding a large folder. The resource governor already throttles
background indexing (architecture [indexing](../architecture/indexing.md)
§2.6, [overview](../architecture/overview.md) §4) but offers no explicit
override.

## Decision

**The provider is chosen automatically; the model is never chosen
automatically.**

1. **Automatic provider selection (`Auto`, the default).** For each workload
   (`query`: batch-1 latency; `indexing`: throughput), the engine selects the
   fastest provider that is (a) already provisioned, (b) validated by
   parity-on-load for the active model, and (c) allowed by the power policy
   (item 3). The order is **measured, never fixed**: no static
   "GPU → NPU → CPU" ranking. Measurements are taken locally on first use per
   model × provider × device × driver version, cached, and redone when any of
   those change. Any load, parity, or runtime failure falls back to CPU for
   that workload without user action (ADR-0016 §4).
2. **Manual override.** Settings offer `Auto`, `CPU`, and each validated
   provider present on the machine. An explicit choice is honored for all
   workloads; if that provider fails, the engine falls back to CPU and the UI
   says so. Choosing `CPU` disables every accelerator.
3. **Power policy.** In the default governor mode, background indexing never
   uses a discrete GPU, and on battery it prefers the most energy-efficient
   validated provider (NPU, then CPU). A discrete GPU serves background work
   only in full-speed mode (item 4) or when the user installed the GPU
   quality tier (item 6), and then only on AC power unless full speed was
   requested. Query-time selection follows item 1 in every power state.
4. **Full-speed indexing.** A user action that tells the governor to index as
   fast as the machine allows:
   - lifts the background CPU-share cap and priority, uses larger batches, and
     allows the fastest validated provider for indexing, including a
     provisioned discrete GPU;
   - is **temporary**: it ends when the current backlog is drained, when the
     app restarts, or when the user turns it off; it is never a persistent
     setting;
   - keeps search first: queries still preempt indexing and budget S5
     (interference ratio ≤ 1.5) still holds;
   - may start on battery because the user asked, and the UI shows that the
     machine is on battery; if AC power is lost while it runs, the governor
     returns to the default mode;
   - never changes the model, never downloads anything, and never triggers a
     reindex.
5. **No automatic GPU downloads.** Detecting GPU hardware is local and may
   produce at most one dismissible, non-repeating offer of the GPU quality
   tier. No GPU runtime or model is downloaded without the user's explicit
   choice (ADR-0011, ADR-0016 §3). Detection results are never sent off the
   machine (P3).
6. **Opt-in GPU quality tier.** An optional asset pack that swaps in larger
   models for users with a capable GPU, installed only by explicit choice in
   Settings with its download size and reindex cost shown first. It is
   delivered in two independent steps:
   - **Reranker tier first.** A larger reranker changes no index. When the
     GPU is unavailable, the engine uses the default CPU reranker for that
     query, silently and without data loss. Eligible when the bake-off shows
     the methodology §8.6 retrieval-model margin over the CPU default on the
     reference GPU, and the full deployment cost is accounted for.
   - **Embedder tier later**, only if all hold: (a) the bake-off shows the
     §8.6 margin over the CPU default embedder; (b) the tier's model meets
     S2 for **query** embedding on T1 CPU-only, so search keeps working
     without the GPU; (c) it builds its own index generation under ADR-0023
     rules, with the CPU-default generation kept or rebuilt only by explicit
     user choice. If the GPU disappears, indexing of the tier generation
     pauses and the UI says why; the engine never reindexes silently and
     never mixes vectors from different models.
7. **Budgets.** All locked budgets (S*, I*, R*, D*) remain defined and
   verified in the default mode on T1 CPU-only. Full-speed mode and the GPU
   tier are measured and reported separately; they never relax a budget.
8. **Scope.** Items 1–5 are part of the 1.0 engine (governor WP-3.1,
   providers WP-5.1, UI WP-7.4/WP-7.6). The GPU quality tier (item 6) stays in
   the vision's post-1.0 "opt-in GPU asset packs" until a scope decision moves
   it.

## Consequences

- Provider choice becomes a per-workload, measured, power-aware decision in
  `seeky-infer` (SPEC-0012); the governor (SPEC-0007) owns the modes
  `default`, `full_speed`, and `paused`.
- The UI gains a full-speed control next to the semantic-indexing status
  (SPEC-0014 v2, WP-7.4) and a provider override in Settings (WP-7.6). Labels
  describe indexing, not "AI" (ADR-0012).
- Large decoder models remain ceilings for the CPU default (ADR-0016
  consequence unchanged); they can ship only inside the opt-in tier.
- Ranked output can differ between users only when one of them opted in to
  the quality tier; bug reports and diagnostics must state the active tier
  and generation.
- **Forbidden:** switching the model, downloading a runtime, or starting a
  reindex because hardware was detected; a fixed provider order; a discrete
  GPU in default-mode background indexing; a persistent "always full speed"
  setting; relaxing a budget for full-speed or GPU-tier runs.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| GPU detected → larger models automatically | Couples a volatile hardware signal to the index's vector space; silent multi-GB downloads; silent reindex; results change with power state |
| Fixed provider order (GPU → NPU → CPU) | Batch-1 query latency on a GPU is often worse than CPU for small models; ignores energy; must be measured per workload |
| Always use the GPU for background indexing when present | Battery, fan noise, and VRAM contention in a background service; contradicts CPU-first and low-power NPU design |
| Persistent "always full speed" setting | Forgotten settings keep laptops at full load; a temporary action covers the real need |
| No GPU path at all | Leaves real quality on the table for users who choose it; ADR-0016 already allows opt-in packs |

## Evidence

No benchmark report yet. Item 6 is gated on a future bake-off on the
reference GPU (report in `docs/benchmarks/results/`); items 1–4 are verified
by SPEC-0007 and SPEC-0012 tests and by the S5 interference gate.
