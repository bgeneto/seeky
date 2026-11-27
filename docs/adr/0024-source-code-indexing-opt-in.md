# ADR-0024 — Source-code indexing is opt-in; source files are never opened directly

- **Status:** Accepted
- **Date:** 2026-11-27
- **Related:** [ADR-0006](0006-narrow-webview-capabilities.md), [ADR-0018](0018-lexical-first-availability.md), [ADR-0012](0012-two-themes-minimal-ui-en-pt.md); [SPEC-0002](../specs/SPEC-0002-engine-api.md) §5.4; SPEC-0008, SPEC-0014 (planned); [conformance audit](../validation/poc-conformance-audit.md) A8, A12

## Context

Seeky's primary users search documents: PDFs, Office files, notes, and
spreadsheets ([vision](../product/vision.md) §3). The PoC indexes source code
by default (C, C++, Python, JavaScript, Rust, shell scripts, and more). For most
users this:

- spends CPU time, disk, and embedding throughput (budgets I1–I5, R1–R6) on
  files they rarely search with Seeky;
- adds near-duplicate, boilerplate-heavy passages that compete with documents
  in the ranking;
- is a security risk when a result is opened: the PoC opens files with the OS
  default handler, and some handlers execute source files instead of showing
  them (for example `.js` with Windows Script Host, `.py` with the Python
  launcher, `.bat`/`.cmd`, `.ps1` with some configurations) — audit A8.

Developers who want their code searchable can still turn it on.

## Decision

1. **Two file classes.** Supported files are either *documents* (indexed by
   default) or *source code* (indexed only when the user opts in). Source code
   means programming, scripting, shell, and query-language source files, for
   example `c h cpp hpp cc cxx cs java kt go rs py pyw js jsx mjs cjs ts tsx rb
   php pl lua r jl swift scala dart sh bash zsh ps1 psm1 bat cmd vbs sql f for
   f77 f90 f95 f03 asm`. Markup and data formats (Markdown, HTML, XML, JSON,
   JSONL, YAML, TOML, CSV) are documents. The authoritative, versioned list
   lives in the extraction spec (SPEC-0008); changing it is a spec change.
2. **Off by default.** While the "Index source code" setting is off (the
   default), the engine shall not index source files at all: no metadata,
   filename, lexical, passage, or vector entries, and no extraction or
   embedding work.
3. **Toggling.** When the setting is turned on, the engine indexes source files
   in the existing roots through the normal pipeline, at background priority.
   When it is turned off, the engine removes every source-file entry from the
   index. The setting is global (not per folder) until a later ADR says
   otherwise.
4. **Never opened directly.** Whether or not code indexing is on, the desktop
   shell never opens a source file with the OS default handler; it reveals the
   file in the system file manager. The same applies to any file whose type is
   not in the document open allowlist ([SPEC-0002](../specs/SPEC-0002-engine-api.md)
   §5.4).

## Consequences

- WP-0.3 implements decision 4 (SPEC-0002 R7).
- Decisions 1–3 need the engine setting and the UI control: SPEC-0008
  (WP-3.4, file classes and the setting in the pipeline) and SPEC-0014
  (WP-7.6, the settings control with en/pt strings and both themes). Until
  then the PoC keeps indexing source code by default; this is recorded as
  audit finding A12.
- Benchmark corpora and budgets measure the default configuration, so
  documents only; a code-enabled configuration is measured separately when it
  matters.
- **Forbidden:** indexing source files while the setting is off; opening a
  source file, or a file outside the open allowlist, with the OS default
  handler.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Keep indexing code by default | Costs indexing budget and ranking quality for most users; execution risk on open |
| Drop source code support entirely | Developers lose a useful capability; the cost is only paid when they opt in |
| Per-folder code toggle | More UI and state for a rare need; a later ADR can add it |
| Open code files in a built-in viewer | A text preview already exists; a full viewer is outside the minimal UI (ADR-0012) |

## Evidence

Maintainer decision, 2026-11-27, during the SPEC-0002 v1 review (resolving its
open-allowlist question). No benchmark report: this ADR sets a default and a
safety rule, not a component.
