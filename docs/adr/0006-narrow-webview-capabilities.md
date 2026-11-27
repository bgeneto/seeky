# ADR-0006 — Narrow webview capabilities and Rust-side file opening

- **Status:** Accepted
- **Date:** 2026-11-26

## Decision

Grant the webview only Tauri `core` and `dialog` capabilities. File opening and
any filesystem action go through dedicated Rust commands. No broad filesystem
or opener path scope.

## Consequences

- Smaller UI attack surface; Windows verbatim paths handled in one place.
- Every new file action is an explicit, tested Rust command.
- A restrictive Content Security Policy must replace the PoC's `csp: null`
  before 1.0.
