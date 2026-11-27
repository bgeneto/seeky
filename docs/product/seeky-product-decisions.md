# Seeky Product Decisions


Date: 2026-11-26

This document records durable product decisions. The implementation plan and
architecture documents define how the decisions are delivered.

## Classification

Seeky is a **Local Neural Information Retrieval Engine**, also described as a
**Semantic Desktop Search Engine**. It is not a chatbot, agent platform, RAG
service, or document management system.

## Open source

- Seeky source code is licensed under the **MIT License**.
- MIT is chosen because it is permissive, familiar, and compatible with the
  permissive dependencies and model licenses used by the project.
- Third-party libraries and model weights remain under their own licenses.
- Model downloads and installers must include the relevant notices and license
  metadata; the Seeky MIT license does not relicense third-party assets.
- Contributions are accepted under the project license.

## No account or license key

- No account, sign-up, activation, subscription, or commercial license key is
  required.
- No user identity is needed to use any feature.
- The application does not phone home for entitlement checks.
- Model/runtime downloads are public read-only assets; they do not require user
  credentials.

## Slim setup and first-run provisioning

Seeky ships as a slim application. Required runtimes, model weights, tokenizers,
and supporting native libraries are downloaded on first run from the **Seeky**
Cloudflare R2 bucket (`seeky` identifier, as required by R2) and cached locally.

- The user installs a small desktop package; large runtimes and weights are not
  embedded in the installer.
- First run detects platform, installed GPU/NPU capabilities, locale, and
  available disk space.
- A signed/checksummed manifest selects the smallest compatible asset set.
- Downloads are resumable, retried, integrity-checked, and installed atomically.
- After provisioning, Seeky runs fully offline.
- No account or license key is needed for provisioning.
- If provisioning cannot complete, Seeky shows an actionable error and remains
  usable for retry; it does not silently fall back to a degraded search model.
- The current PoC's local Gety dependency and bundled OpenVINO IR are
  transitional. The target product does not require the Gety application to be
  installed.

R2 layout, asset classes, security, and first-run flow are defined in
[`../architecture/distribution-and-provisioning.md`](../architecture/distribution-and-provisioning.md).

## UI themes

- Seeky has exactly two themes: **light** and **dark**.
- The default follows the operating system appearance.
- A user override may be stored, but there is no theme editor, custom palette,
  theme marketplace, or per-panel theme.
- Both themes must meet accessible contrast and focus requirements.

## Minimal UI

Seeky is deliberately minimal: search, results, preview, folders, and a small
settings surface.

- No dashboards, onboarding carousels, AI badges, generated summaries, chat
  panels, or decorative metrics.
- No more than the controls needed to complete the core jobs.
- Backend/model internals are hidden behind an advanced or diagnostics surface;
  the default is automatic selection.
- Empty states and errors explain the next action in one sentence.
- The UI does not imitate an AI assistant. It behaves like a precise desktop
  search tool.

## Multilingual UI

- The UI is internationalized from the start.
- Initial locales: **English (`en`)** and **Portuguese (`pt`)**.
- The default follows the operating-system locale when supported; otherwise the
  fallback is English.
- Locale detection maps regional variants (for example `pt-BR`, `pt-PT`) to the
  available base locale.
- All user-facing strings live in locale catalogs. No feature is gated by
  locale.
- Missing translation keys fall back to English and are reported in development.

## SOTA multilingual retrieval

The retrieval pipeline must be state-of-the-art and high-performance with the
best small multilingual models available, not merely a demo embedding model.

- **Content multilingualism is mandatory.** User files may be in any language,
  even when the UI is English or Portuguese.
- Embedding and reranking models must be multilingual and evaluated on mixed
  language corpora.
- Model selection is benchmark-gated across quality, CPU latency, GPU/NPU
  latency, memory, and download size.
- CPU must remain practical; CUDA, AMD, and NPU must use accelerated execution
  paths when available.
- The current `gety-embed-v0` integration is a compatibility baseline, not a
  claim that the final model choice is SOTA.
- Candidate models, backend policy, and evaluation gates are defined in
  [`../architecture/model-strategy.md`](../architecture/model-strategy.md) and
  [`../architecture/retrieval-engine.md`](../architecture/retrieval-engine.md).

## Required retrieval mechanisms

The semantic search engine must implement and evaluate the following mechanisms
as one coherent pipeline, not as optional marketing checkboxes:

1. **Passage-level ranking** — rank the best passages for the query before and
   after document selection.
2. **Document-level score aggregation** — combine passage, title, filename,
   coverage, and consensus signals into a document score.
3. **Hierarchical document retrieval** — retrieve documents first, then rank
   their passages, and optionally feed document context back into passage
   ranking.
4. **Per-document candidate limits** — cap passages/documents per source so one
   long or repetitive file cannot monopolize results.
5. **Cross-document diversity** — penalize redundant sources and ensure the
   result set covers distinct documents and aspects.
6. **Near-duplicate detection** — collapse repeated files, versions, boilerplate,
   and duplicated passages before presentation.
7. **Length bias correction** — normalize passage/document length effects in
   BM25, dense fusion, and reranker scores.

Detailed scoring, defaults, and acceptance criteria are defined in
[`../architecture/retrieval-engine.md`](../architecture/retrieval-engine.md).

## Privacy and offline behavior

- Search, indexing, inference, and preview are local.
- No document content is sent to Cloudflare R2 or any other service.
- R2 is used only for public runtime/model assets.
- No telemetry or usage analytics.
- The application works offline after first-run provisioning.

## Non-goals

- Cloud sync, accounts, teams, multiuser access.
- Connectors, plugin marketplace, MCP, public REST API, public CLI.
- Chat, agents, generated answers, or generative UI.
- Theme customization, plugin themes, or a settings-heavy dashboard.

## Related documents

- [English scope summary](seeky-scope.md)
- [Original Portuguese scope source](seeky-scope-pt-br.md)
- [Implementation plan](../plans/seeky-implementation-plan.md)
- [Architecture decisions](../decisions/seeky-adrs.md)
- [Retrieval engine](../architecture/retrieval-engine.md)
- [Distribution and provisioning](../architecture/distribution-and-provisioning.md)
- [Model strategy](../architecture/model-strategy.md)
