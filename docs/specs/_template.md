# SPEC-NNNN — <Title>

| Field | Value |
|---|---|
| Status | Draft |
| Version | 0.1 |
| Owner | <maintainer> |
| Phase / work packages | Phase N — WP-N.x, WP-N.y |
| Crates touched | `seeky-…` |
| Governing docs | vision §…, ADR-…, architecture/…md §… |
| Benchmark gates | e.g. S2, I1, Q2 (from `docs/benchmarks/methodology.md`) |

## 1. Problem and goal

Two or three paragraphs: what is missing, why it matters for the principles,
what "done" looks like for the user and for the engine.

## 2. Scope

- **In:** …
- **Out:** … (and where it is handled instead)

## 3. Requirements (EARS)

| ID | Requirement | Verification | Status |
|---|---|---|---|
| SPEC-NNNN-R1 | The engine shall … | unit test `crate::module::tests::name` | Open |
| SPEC-NNNN-R2 | When …, the engine shall … | integration test | Open |
| SPEC-NNNN-R3 | If …, then the engine shall … | fault-injection test | Open |
| SPEC-NNNN-R4 | While indexing, the engine shall keep S2 within budget | benchmark gate S5 | Open |

Status: `Open` → `Implemented` (code and its test merged; the WP is named, for
example `Implemented (WP-3.2)`) → `Verified` (benchmark gate passed; report
linked). The commit that implements or verifies a requirement updates its row;
the header status and the [specs index](README.md#index) follow (README rule 6).

## 4. Interfaces

Rust signatures, data types, schema/migration DDL, IPC payloads, config keys
(with defaults and their benchmark owner), file formats. Keep it precise enough
that two independent implementers would produce compatible code.

## 5. Behavior details

State machines, algorithms, edge cases, error taxonomy, concurrency and
cancellation rules, crash-consistency rules.

## 6. Acceptance

### 6.1 Tests

List of tests to write **before** implementation (unit, property, integration,
fuzz), each mapped to requirement IDs.

### 6.2 Benchmark gates

| Gate | Dataset/split | Tier | Threshold | Baseline report |
|---|---|---|---|---|

### 6.3 Inspection

Anything verified by review (for example "no engine crate depends on `tauri`").

## 7. Risks and open questions

Each open question names who decides and by when; a spec cannot be Accepted
with blocking open questions.

## 8. Changelog

| Version | Date | Change |
|---|---|---|
| 0.1 | YYYY-MM-DD | Initial draft |
