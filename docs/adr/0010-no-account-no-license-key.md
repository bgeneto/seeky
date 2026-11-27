# ADR-0010 — No account, activation, or license key

- **Status:** Accepted
- **Date:** 2026-11-26

## Decision

No account, sign-up, activation, subscription, entitlement check, or license
key. No telemetry, analytics, crash upload, or identity calls.

## Consequences

- No auth UI or entitlement client; asset downloads are public and read-only.
- The only outbound traffic is manifest/asset provisioning (ADR-0011).
