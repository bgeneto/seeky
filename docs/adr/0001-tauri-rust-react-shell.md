# ADR-0001 — Tauri 2 shell, Rust backend, React/TypeScript UI

- **Status:** Accepted (amended by [ADR-0015](0015-engine-first-architecture.md))
- **Date:** 2026-11-26

## Context

Seeky needs native filesystem and model-runtime access, a small footprint, and
no local server.

## Decision

Ship Seeky as a Tauri 2 desktop application. Backend logic is Rust; the UI is
React 19 + TypeScript + Vite. UI/backend contracts are Tauri commands, events,
and channels — never HTTP.

ADR-0015 amends this: the Tauri app is a **thin shell** over a UI-independent
engine workspace and contains no retrieval or indexing logic of its own.

## Consequences

- Rust changes require a rebuild; there is no hot-reload backend service.
- Small release footprint; one process for state, database, watcher, inference.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| Electron | Larger footprint, Node backend, weaker fit for native inference |
| Python backend + web UI | Second runtime and heavy packaging; retired (see `docs/archive/`) |
| Svelte UI | Viable; React kept because the PoC already uses it |
