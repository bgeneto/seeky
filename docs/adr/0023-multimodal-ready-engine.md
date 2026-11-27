# ADR-0023 — Multimodal-ready engine; visual retrieval as an optional, gated pack

- **Status:** Proposed
- **Date:** 2026-11-27
- **Related:** [ADR-0003](0003-hybrid-retrieval-rrf.md), [ADR-0013](0013-hierarchical-multilingual-retrieval.md), [ADR-0018](0018-lexical-first-availability.md), [ADR-0019](0019-single-inference-engine.md), [ADR-0021](0021-no-generative-models-in-product.md), [ADR-0022](0022-permissive-license-gate.md); SPEC-0004, SPEC-0005, SPEC-0006, SPEC-0016 (planned); [candidates §1 and §14](../benchmarks/candidates.md); [methodology §5.6, §7, §8.9](../benchmarks/methodology.md); plan WP-2.6, WP-2.13, Phase 10

## Context

Seeky's goal is meaning-based search across the user's files
([vision](../product/vision.md) §1). Until now, image semantic search was
listed as deferred post-1.0, and the architecture was text-only: retrieval
units are text passages, the model manifest has no notion of modality, and an
index generation holds exactly one embedding space (ADR-0019 decision 7). Adding
images after the schema, generations, manifest, traits, and fusion are
implemented would be an expensive retrofit; making those contracts
modality-aware now costs little and changes no text behavior.

Compact multimodal embedding models with permissive weights and ONNX exports
now exist. Facts as of 2026-11-27 (vendor-reported, not reproduced; details
and sources in [candidates §14](../benchmarks/candidates.md)):

- `google/embeddinggemma-2` (released 2026-10-06) maps text, images, audio, and
  video into one 768-d space (Matryoshka 512/256/128). Text component 270M
  (backbone 130M + embedder 140M, 262k-token vocabulary); vision encoder 170M.
  Images enter the shared backbone as 70–1120 soft tokens (default 280). ONNX
  exports: text 314 MB (q8) / 175 MB (q4); vision 195 MB / 109 MB. License:
  Apache-2.0 plus the Gemma Prohibited Use Policy.
- SigLIP 2 (Apache-2.0) is a two-tower model with independent text and vision
  towers and a 64-token text context.
- No candidate publishes Portuguese text-to-image results.

What those facts mean for Seeky:

- The q8 text graph of the unified candidate alone exceeds D2 (≤ 250 MB for
  runtime + embedder + reranker); its q4 variant has a worst-case cosine of
  0.975 against fp32 (vendor-reported).
- In a unified model that feeds images through the shared backbone, embedding
  one image costs roughly one long passage plus the vision encoder.
- A shared space does not make text–text and text–image cosine scores
  comparable (the *modality gap*). Cross-modal ranking needs rank fusion or
  per-modality calibration in both unified and specialized designs; Seeky
  already fuses rankings ([ADR-0003](0003-hybrid-retrieval-rrf.md)).
- Only one capability strictly requires a shared space: an image query that
  retrieves text documents.
- One shared space couples upgrade cycles: changing the text model re-embeds
  every image, and vice versa.
- For the primary users ([vision](../product/vision.md) §3), most visual value
  (scans, screenshots, slides with text) is already delivered by OCR. Visual
  embeddings add photos, illustrations, diagrams, and charts without useful
  text, plus image-as-query search. The reference product studied in
  `docs/research/` ships no visual embeddings.

## Decision

1. **Modality-aware contracts from Phase 2** (plan WP-2.13), with no visual
   model in the default path:
   1. **Retrieval units.** A file may have several representations: text
      passages (extracted or OCR, as today) and **visual units** (an image
      file, a slide, an embedded figure, or a page region), each with a
      modality, a locator, and a content hash. Text passages remain the only
      input to BM25, the cross-encoder, and snippets.
   2. **Embedding channels.** An embedding channel is one embedding space: one
      model, revision, dimension, and input recipe. Each channel has its own
      index-generation lineage, so ADR-0019 decision 7 (one vector space per
      generation; vectors never mixed) holds unchanged. The text channel's
      generation keeps owning the lexical, filename, and text-vector indexes;
      a visual channel's generation owns only visual vectors. Rebuilding one
      channel never rebuilds another. A unified multimodal model is **one**
      channel whose generation holds both text and image vectors.
   3. **Manifest.** Models declare their modalities; an embedding-space ID
      shared by every component that produces comparable vectors; one ONNX
      graph per component (for example `text` and `vision`) with its own
      variants and parity vectors; and image preprocessing (resize policy,
      normalization, visual token budget). Preprocessing is implemented in Rust
      from the manifest; parity vectors for image components start from raw
      image bytes.
   4. **Traits.** Image embedding is a declared capability of an embedder in
      `seeky-core`; nothing model-specific leaves `seeky-infer`.
   5. **Fusion.** Each channel and query modality is one more first-stage
      retriever feeding the existing fusion. Raw similarity scores from
      different modalities are never compared or summed, even inside one
      shared space; cross-modal ranking uses rank fusion or per-modality
      calibration selected by bake-off.
   6. **Residency.** The text query path never loads a vision encoder. Vision
      components load only for visual indexing and image queries and are
      released under memory pressure.
2. **Visual retrieval is an optional asset pack**, like OCR: outside the
   default download (D2), installed only when the user enables image search,
   indexed in the lowest-priority lane under the resource governor, and never
   delaying text semantic coverage. Its first scope is text-to-image and
   image-to-image search over common still-image formats and over selected
   visual units of documents (slides, embedded figures, pages with little
   extractable text). Document pages are never all rendered and embedded.
3. **Text first, no handicap.** The default text embedder is chosen by the
   embedding bake-off (WP-2.6) on text quality and text budgets.
   Multimodal-capable models compete there as ordinary text candidates. Their
   visual capability is only a tie-breaker: among candidates that tie on the
   weighted primary score (inside the CI) and meet every text budget, D2
   included, prefer one whose space also serves images
   ([methodology §7](../benchmarks/methodology.md)). Visual capability never
   compensates for a text-quality loss outside the CI or a missed text budget.
4. **The visual architecture is decided by bake-off** (plan Phase 10;
   [methodology §8.9](../benchmarks/methodology.md)) between:
   **(A)** text-only — OCR + filename + text channel, no pack;
   **(B)** unified — one channel for text and images;
   **(C)** specialized — the text channel plus a separate visual channel.
   The pack ships only if it passes gate Q8 and budgets V1–V5; the outcome is
   recorded in an ADR that cites the report.
5. **Out of scope** until a superseding ADR: generated captions, tags, or
   descriptions of images (generative content,
   [ADR-0021](0021-no-generative-models-in-product.md)); a multimodal
   reranker; audio and video embeddings; embedding every page of every
   document as an image; late-interaction (multi-vector) visual document
   retrieval as a product tier.
6. Vision encoders used for embeddings are non-generative encoders, permitted
   under ADR-0021 decision 1. They pass the license gate
   ([ADR-0022](0022-permissive-license-gate.md)) like any model; a use-policy
   pass-through such as the Gemma Prohibited Use Policy is "review required".

## Consequences

- Phase 2 gains WP-2.13 (contracts only). SPEC-0005 and SPEC-0006 cover
  modalities, channels, and visual units; text-only behavior and budgets are
  unchanged, and tests verify that the text path loads no vision session.
- The [vision](../product/vision.md) moves image semantic search from
  "deferred" to "optional visual pack after the text gates"; audio and video
  stay deferred.
- Plan Phase 10 (off the 1.0 critical path; the maintainer decides 1.0 vs 1.1),
  SPEC-0016 (planned), [candidates §14](../benchmarks/candidates.md), and
  methodology additions (visual corpus slice, query categories, public sets,
  metrics, budgets V1–V5, gate Q8, the tie-breaker, §8.9).
- Provisioning gains a visual-pack asset class. When Phase 10 starts,
  SPEC-0014 adds an image-search setting, locally generated thumbnails,
  image-as-query input, and a modality filter, with en/pt strings and both
  themes.
- **Forbidden:** loading a vision encoder on the text query path; comparing
  raw scores across modalities; shipping the visual pack in the default
  download; generating captions or descriptions; selecting the default text
  embedder for its visual capability outside the tie-break rule.
- Cost now: a few schema fields, manifest keys, and trait methods, before any
  visual model is chosen.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| "Multimodal-first" as a product principle, with a unified model mandatory | Couples the most important component (text retrieval) to a secondary capability; a shared space still needs per-modality calibration; current unified candidates strain D2 and indexing throughput |
| Keep the architecture text-only and retrofit images later | Retrofitting schema, generations, manifest, and fusion after implementation is expensive; preparing the contracts now is cheap |
| Make images searchable through generated captions | Generative content in the index (ADR-0021); hallucinated captions would create false matches |
| Embed every document page as an image | Indexing time and index size on CPU; OCR text plus selective visual units cover most of the value |
| Late-interaction visual document retrieval (ColPali class) | Multi-vector storage and query cost beyond CPU budgets; kept as an offline quality ceiling |
| Multimodal reranker | Per-query cost on every candidate pair; no evidence of gain; secondary to embeddings |
| Audio and video embeddings | Outside the core user jobs; heavy encoders; speech transcription would fall under the ADR-0021 transcription rule |

## Evidence

None yet (Proposed). Vendor-reported facts and their sources are recorded in
[candidates §14](../benchmarks/candidates.md). The decision on the visual
architecture and model will cite the Phase 10 bake-off report in
[`../benchmarks/results/`](../benchmarks/results/README.md).
