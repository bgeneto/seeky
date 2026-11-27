# ADR-0007 — Temporary Git LFS model asset during the PoC

- **Status:** Accepted (transitional; ends when ADR-0011 provisioning ships)
- **Date:** 2026-11-26

## Decision

Track the temporary bundled OpenVINO `model.bin` (118.6 MB) with Git LFS while
first-run provisioning does not exist.

## Consequences

- Contributors need Git LFS only for the PoC NPU path.
- The provisioning phase removes the bundled IR. New model weights are never
  committed to the repository; they are published as provisioned assets.
