# ADR-0008 — No sidecar service or HTTP API

- **Status:** Accepted
- **Date:** 2026-11-26 (clarified 2026-11-27)

## Decision

All product backend behavior runs in the Rust engine inside the Tauri process.
No local web server, public REST API, MCP server, public CLI, or long-running
sidecar service.

Clarifications:

- `tools/seeky-bench` (internal evaluation/benchmark CLI built on the engine
  crates) is development tooling and is never shipped in installers.
- Running document extraction in a short-lived, same-binary worker process for
  crash isolation is not a sidecar service, but it requires its own ADR backed
  by fuzzing evidence before it is introduced.

## Consequences

- Less memory, no ports, fewer lifecycle failures, no IPC serialization of
  search/index operations. The desktop UI is the only product client.
