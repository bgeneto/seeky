# SPEC-0007 — Indexing pipeline: jobs, two-speed lanes, cache, reconcile, governor

| Field | Value |
|---|---|
| Status | Draft (partial: §5.1 governor modes only) |
| Version | 0.1 |
| Owner | Maintainer |
| Phase / work packages | Phase 3 — WP-3.1, WP-3.2, WP-3.3, WP-3.6 |
| Crates touched | `seeky-engine` (scheduler, governor), `seeky-infer` (provider choice per workload, with SPEC-0012), `seeky-core` (types) |
| Governing docs | [vision](../product/vision.md) P1, P2, P4; [ADR-0016](../adr/0016-cpu-first-npu-ready-execution.md); [ADR-0025](../adr/0025-automatic-provider-opt-in-gpu-tier-full-speed.md); [architecture/indexing](../architecture/indexing.md) §2.6; [architecture/overview](../architecture/overview.md) §4 |
| Benchmark gates | S5, I1–I3, R3 (from `docs/benchmarks/methodology.md` §5) |

> **Partial draft.** Specs are written just-in-time (specs README). This
> version records only the governor modes decided in ADR-0025, so the
> decision is not lost before Phase 3. The job queue, two-speed lanes,
> embedding cache, and reconcile sections are written at the start of
> Phase 3, and this spec cannot be Accepted before they are complete.

## 1. Problem and goal

Background indexing must stay invisible: the query pool always wins, the
machine stays cool and quiet, and battery is respected. Sometimes the user
wants the opposite for a while, for example right after adding a large
folder. The resource governor therefore needs explicit modes: a default,
background-friendly mode; a temporary full-speed mode the user starts; and
pause. None of them may change the model or the index generation.

## 2. Scope

- **In (this draft):** governor modes `default`, `full_speed`, `paused`;
  their transitions; the power policy for indexing providers; the engine
  API surface the UI needs (SPEC-0014 v2, WP-7.4).
- **To be written in Phase 3:** durable job queue, two-speed lanes
  (lexical/semantic), content-addressed embedding cache, startup reconcile,
  memory ceiling, visual-lane scheduling.
- **Out:** provider measurement and parity-on-load (SPEC-0012); the opt-in
  GPU quality tier and its generations (ADR-0025 item 6, post-1.0; SPEC-0006
  for generations); UI layout and strings (SPEC-0014 v2).

## 3. Requirements (EARS)

Draft requirements for §5.1 only; IDs are stable and later sections
continue the numbering.

| ID | Requirement | Verification | Status |
|---|---|---|---|
| SPEC-0007-R1 | The governor shall run in exactly one of the modes `default`, `full_speed`, or `paused`, and shall start every engine session in `default`, or in `paused` when the user paused indexing before the last shutdown. | unit `governor_starts_in_default_or_persisted_pause`; `full_speed_is_never_restored_after_restart` | Open |
| SPEC-0007-R2 | While in `default`, the governor shall run indexing at background priority under the configured CPU-share cap, shall not select a discrete GPU for indexing, and, on battery, shall prefer the most energy-efficient validated provider or pause semantic indexing as configured. | unit with fake power source and fake providers `default_mode_never_selects_discrete_gpu`, `battery_prefers_efficient_provider` | Open |
| SPEC-0007-R3 | When the user requests full speed, the governor shall lift the background priority and CPU-share cap, allow larger batches, and allow the fastest validated provisioned provider for indexing, including a discrete GPU. | unit `full_speed_allows_fastest_validated_provider`; integration with fake `Embedder` timing | Open |
| SPEC-0007-R4 | When the semantic and lexical backlogs are drained, the user turns full speed off, or the engine restarts, the governor shall return from `full_speed` to `default`. | unit `full_speed_ends_when_backlog_drains`, `full_speed_toggle_off_returns_default` | Open |
| SPEC-0007-R5 | If AC power is lost while in `full_speed`, then the governor shall return to `default` and emit a mode-change event with reason `power_lost`. | unit with fake power source `ac_loss_ends_full_speed` | Open |
| SPEC-0007-R6 | While in any mode, the governor shall let interactive queries preempt indexing so that S5 holds. | benchmark gate S5 in both `default` and `full_speed` | Open |
| SPEC-0007-R7 | The governor shall never change the active model, start a download, or start a reindex as a consequence of a mode change or of detected hardware. | unit `mode_change_keeps_model_and_generation`; inspection | Open |
| SPEC-0007-R8 | When the mode changes, the engine shall emit a typed event carrying the new mode, the reason (`user`, `backlog_drained`, `power_lost`, `restart`), and whether the machine is on battery, so the UI never parses strings. | unit `mode_events_are_typed` | Open |

## 4. Interfaces

Sketch for review; finalized with SPEC-0002 v2 in Phase 3.

```rust
pub enum GovernorMode { Default, FullSpeed, Paused }

pub enum ModeChangeReason { User, BacklogDrained, PowerLost, Restart }

pub struct GovernorStatus {
    pub mode: GovernorMode,
    pub on_battery: bool,
    pub indexing_provider: ProviderId, // as selected for the indexing workload
}

// Engine API additions (SPEC-0002 v2):
// fn set_governor_mode(&self, mode: GovernorMode) -> Result<GovernorStatus, EngineError>;
// fn governor_status(&self) -> GovernorStatus;
// event: GovernorModeChanged { status: GovernorStatus, reason: ModeChangeReason }
```

Config keys (defaults owned by the WP-8.5 energy report): CPU-share cap in
`default`; battery behavior (`prefer_efficient` | `pause_semantic`).
`full_speed` has no persisted key by design.

## 5. Behavior details

### 5.1 Governor modes

```text
            user: full speed                backlog drained / user off /
  default ───────────────────► full_speed ── AC lost / restart ──► default
     ▲  │                          │
     │  └──── user: pause ───► paused ◄──── user: pause ────┘
     └──────── user: resume ──────┘
```

- `paused` stops semantic and visual lanes; the lexical lane keeps files
  lexically searchable unless the user also paused watching (folder-level
  pause is a separate control, WP-7.4).
- Starting `full_speed` on battery is allowed; the status reports
  `on_battery = true` so the UI can say so.
- Provider choice per workload follows ADR-0025 items 1–3 through the
  SPEC-0012 provider layer; the governor only passes the mode and the power
  state as constraints.

### 5.2–5.6 Job queue, lanes, cache, reconcile, memory ceiling

To be written at the start of Phase 3.

## 6. Acceptance

### 6.1 Tests

The tests named in §3, with fake power source, fake providers, and a fake
`Embedder`; hardware-free.

### 6.2 Benchmark gates

| Gate | Dataset/split | Tier | Threshold | Baseline report |
|---|---|---|---|---|
| S5 (default and full speed) | `sdc-s` | T1 CPU-only | ≤ 1.5 | — |
| I3 (default mode only) | `sdc-s` | T1 CPU-only | ≤ 30 min | — |

Full-speed throughput is reported separately and never relaxes I3.

### 6.3 Inspection

No code path selects a model, downloads an asset, or starts a reindex from a
governor mode change or hardware detection (R7).

## 7. Risks and open questions

| Question | Owner / deadline | Blocking? |
|---|---|---|
| Default CPU-share cap and battery behavior values | WP-8.5 energy report | No (defaults provisional) |
| Whether `paused` persists across restarts (R1 assumes yes) | Maintainer, Phase 3 start | No |
| Remaining sections §5.2–§5.6 | Phase 3 spec author | Yes |

## 8. Changelog

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-11-27 | Partial draft: governor modes and full-speed indexing from ADR-0025; other sections pending Phase 3 |
