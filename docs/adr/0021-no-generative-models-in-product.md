# ADR-0021 — No generative models in the shipped product

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Seeky is search-only: no chatbot, agents, MCP, connectors, or generative RAG.
Generative models also cost latency, memory, and energy that the CPU-first
budget cannot afford.

## Decision

1. **No generative features.** The product never generates content for the
   user or about the user's documents: no chat, answers, summaries, agents,
   LLM query rewriting, HyDE, or generated snippets. Retrieval components are
   encoders (bi-encoders, cross-encoders, sparse encoders, token classifiers).
2. **Transcription-model rule (OCR).** An OCR model may use an
   encoder-decoder or vision-language (autoregressive) architecture **only as a
   transcriber** of text that is visibly present on a page, when all of these
   hold:
   - decoding is deterministic (greedy, temperature 0) with a bounded output
     length, and the prompt is a fixed transcription instruction — never user
     input;
   - it runs locally and passes the OCR bake-off, including the
     **hallucination gate** (text emitted that is not on the page), because
     hallucinated text would pollute the index with false matches;
   - it complies with CPU-first tiers ([ADR-0016](0016-cpu-first-npu-ready-execution.md))
     and the runtime-cost rule ([ADR-0019](0019-single-inference-engine.md)).
3. Development tooling may use LLMs offline (for example to draft evaluation
   queries or relevance judgments that humans then verify). Nothing produced
   that way ships in the product binary or runs on user data.

## Consequences

- The "optional answer layer" from earlier plans is removed from the roadmap.
- OCR candidates include discriminative pipelines (detection + recognition),
  OS-native OCR, and transcription VLMs; the OCR bake-off decides with data
  which tier (CPU default, opt-in GPU pack) each one can serve, if any.
