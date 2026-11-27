# ADR-0012 — Two themes, minimal UI, English/Portuguese UI

- **Status:** Accepted
- **Date:** 2026-11-26

## Decision

Exactly two themes (light and dark; OS default with optional override), a
minimal search-first UI, and English (`en`) + Portuguese (`pt`) locale catalogs
from the start, with OS-locale detection and English fallback.

## Consequences

- All user-facing strings live in locale catalogs; CI checks catalog parity.
- Backend/model internals live behind an advanced diagnostics surface.
- No theme editor, custom palettes, dashboards, chat panels, or AI badges.
