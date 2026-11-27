# Specifications

Seeky uses **Spec-Driven Development** ([ADR-0017](../adr/0017-spec-and-benchmark-driven-development.md)).
A spec turns architecture into a checkable contract for one work package (or a
coherent group of them). AI agents implement **Accepted** specs only.

## Lifecycle

```text
Draft ──► Review ──► Accepted ──► Implemented ──► Verified
  │                     │
  └──► Rejected         └──► Superseded (by SPEC-XXXX)
```

| Status | Meaning | Who moves it |
|---|---|---|
| Draft | Being written; may be incomplete | Spec author (human or agent) |
| Review | Complete; open for comments | Spec author |
| Accepted | Binding contract; implementation may start | Maintainer (human) |
| Implemented | Code merged; acceptance tests pass | Implementer |
| Verified | Benchmark gates passed on reference hardware; report linked | Benchmark runner + maintainer |
| Superseded / Rejected | Kept for history | Maintainer |

Rules:

1. One spec per file: `SPEC-NNNN-<slug>.md`, numbered in order, never reused.
2. A spec may refine, never contradict, [`../product/vision.md`](../product/vision.md),
   Accepted ADRs, and [`../architecture/`](../architecture/README.md). If it must,
   write an ADR first.
3. Requirements use **EARS** syntax and carry stable IDs (`SPEC-0007-R12`) that
   tests and PRs reference.
4. Every requirement is verifiable: by a test, a benchmark gate, or an
   inspection step named in the spec.
5. Changing an Accepted spec: edit with a changelog entry at the bottom; if the
   change alters behavior already implemented, bump the spec version and list
   the migration.

## EARS cheat sheet

| Pattern | Template |
|---|---|
| Ubiquitous | The `<system>` shall `<response>`. |
| Event-driven | When `<trigger>`, the `<system>` shall `<response>`. |
| State-driven | While `<state>`, the `<system>` shall `<response>`. |
| Unwanted behavior | If `<condition>`, then the `<system>` shall `<response>`. |
| Optional feature | Where `<feature is present>`, the `<system>` shall `<response>`. |

Example: *When a watched file is renamed and its content is unchanged, the
engine shall update its path without computing any new embedding.*
(verified by an integration test and gate I5).

## Planned specs

Specs are written just-in-time, as the first task of their phase (see the
[implementation plan](../plans/seeky-implementation-plan.md)).

| Spec | Title | Phase | Work packages |
|---|---|---|---|
| SPEC-0001 | Workspace and crate boundaries | 0 | WP-0.1 |
| SPEC-0002 | Engine API (v1 headless; v2 progressive search) | 0, 4 | WP-0.2, WP-0.3, WP-4.3 |
| SPEC-0003 | Evaluation and benchmark harness | 1 | WP-1.1, WP-1.2, WP-1.5, WP-1.6 |
| SPEC-0004 | Seeky Desktop Corpus and relevance judgments (incl. the visual slice) | 1, 10 | WP-1.3, WP-1.4, WP-10.1 |
| SPEC-0005 | Model manifest (incl. modalities and components), ONNX Runtime adapter, and bake-off toolchain | 2 | WP-2.1, WP-2.2, WP-2.13 |
| SPEC-0006 | Storage, index backends, index generations, and embedding channels | 2, 3 | WP-2.4, WP-2.5, WP-2.13, WP-3.7 |
| SPEC-0007 | Indexing pipeline: jobs, two-speed lanes, cache, reconcile, governor | 3 | WP-3.1, WP-3.2, WP-3.3, WP-3.6 |
| SPEC-0008 | Document extraction, language ID, and chunking | 3 | WP-3.4, WP-3.5, WP-3.9 |
| SPEC-0009 | OCR asset pack (CPU default tier, optional GPU pack) | 2, 3 | WP-2.11, WP-3.8 |
| SPEC-0010 | Ranking pipeline: query analysis to diversity | 4 | WP-4.1, WP-4.2, WP-4.4–WP-4.9 |
| SPEC-0011 | Snippet engine | 4 | WP-4.10 |
| SPEC-0012 | Execution providers and NPU acceleration | 5 | WP-5.1–WP-5.6 |
| SPEC-0013 | Provisioning and asset manifest | 6 | WP-6.1–WP-6.5 |
| SPEC-0014 | Desktop experience: shell, i18n, themes, progressive UI | 7 | WP-7.1–WP-7.9 |
| SPEC-0015 | Release, packaging, and signing | 9 | WP-9.1, WP-9.2 |
| SPEC-0016 | Visual retrieval pack: visual units, channels, fusion, image queries ([ADR-0023](../adr/0023-multimodal-ready-engine.md)) | 10 | WP-10.3–WP-10.7 |

Template: [`_template.md`](_template.md).
