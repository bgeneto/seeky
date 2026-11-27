# SPEC-0001 — Workspace and crate boundaries

| Field | Value |
|---|---|
| Status | Implemented |
| Version | 0.1 |
| Owner | Maintainer |
| Phase / work packages | Phase 0 — WP-0.1 (boundaries also bind WP-0.2 and WP-0.3) |
| Crates touched | new: `seeky-core`, `seeky-extract`, `seeky-infer`, `seeky-store`, `seeky-search`, `seeky-engine`, `seeky-provision`, `seeky-eval`; renamed: `apps/seeky` → `apps/desktop` |
| Governing docs | [vision](../product/vision.md) §2 (P4, P8); [ADR-0015](../adr/0015-engine-first-architecture.md); [ADR-0008](../adr/0008-no-sidecar-no-http-api.md); [ADR-0019](../adr/0019-single-inference-engine.md); [ADR-0022](../adr/0022-permissive-license-gate.md); [architecture overview](../architecture/overview.md) §2; [AGENTS.md](../../AGENTS.md) §6 |
| Benchmark gates | None. Behavior must not change (guarded by the WP-0.2 golden test, [SPEC-0002](SPEC-0002-engine-api.md) R3) |

## 1. Problem and goal

The PoC is one Tauri crate (`apps/seeky/src-tauri`): commands, watcher,
indexing, inference, storage, and ranking share one crate, so the engine cannot
be built, tested, or benchmarked without the UI
([ADR-0015](../adr/0015-engine-first-architecture.md); audit deviation
"Structure"). Agents also lack review boundaries: any change can touch
anything.

This spec fixes the Cargo workspace that every later work package builds on:
the crates and what each owns, the allowed dependency direction, shared lints,
profiles and toolchain, and the rename of the app to `apps/desktop`. WP-0.1
creates the skeleton and empty crate stubs; WP-0.2 moves PoC code into the
crates along the mapping in §4.5 without changing behavior
([SPEC-0002](SPEC-0002-engine-api.md)).

Done means: `cargo build/test/clippy --workspace` work from the repository
root, the app runs from `apps/desktop` exactly as before, and a forbidden
dependency (for example `tauri` in an engine crate) fails a check instead of
relying on review.

## 2. Scope

- **In:** root virtual workspace; eight engine crate stubs; shared
  `[workspace.package]`, `[workspace.dependencies]`, and `[workspace.lints]`;
  profiles; `rust-toolchain.toml`; `clippy.toml`; the dependency-direction
  rules and their `cargo-deny` bans; the `hw-tests` feature convention; the
  rename `apps/seeky` → `apps/desktop` with every path reference updated; the
  PoC module → crate mapping used by WP-0.2.
- **Out:** moving PoC code (WP-0.2, SPEC-0002); the `Engine` API (SPEC-0002);
  CI jobs beyond keeping the existing `format` job working (WP-0.4 adds clippy,
  tests, `cargo-deny`, the OS matrix); `tools/seeky-bench` (Phase 1, SPEC-0003)
  and `tools/model-export` (WP-0.6); `bench/` (Phase 1).

## 3. Requirements (EARS)

| ID | Requirement | Verification | Status |
|---|---|---|---|
| SPEC-0001-R1 | The repository root shall contain a virtual Cargo workspace (`resolver = "3"`) whose members are `crates/*` and `apps/desktop/src-tauri`, with one `Cargo.lock` and one `target/` at the root. | inspection; `cargo metadata --no-deps` lists exactly these members | Implemented (WP-0.1) |
| SPEC-0001-R2 | Every member shall inherit `edition`, `rust-version`, `license`, `version`, and `repository` from `[workspace.package]`. | inspection of each `Cargo.toml` | Implemented (WP-0.1) |
| SPEC-0001-R3 | Every external dependency used by more than one member shall be declared once in `[workspace.dependencies]` and referenced with `workspace = true`. | inspection; `cargo tree --workspace --duplicates` shows no duplicate caused by divergent member requirements | Implemented (WP-0.1) |
| SPEC-0001-R4 | The workspace shall contain the crates `seeky-core`, `seeky-extract`, `seeky-infer`, `seeky-store`, `seeky-search`, `seeky-engine`, `seeky-provision`, and `seeky-eval`, each with a crate-level doc comment that states its responsibility as in §4.2. | inspection; `cargo doc --workspace --no-deps` | Implemented (WP-0.1) |
| SPEC-0001-R5 | Every member shall set `[lints] workspace = true`, and `cargo clippy --workspace --all-targets -- -D warnings` shall pass with the lint set in §4.3. | command | Implemented (WP-0.1) |
| SPEC-0001-R6 | If code needs `unsafe`, then it shall carry an item-level `#[allow(unsafe_code)]`, a `// SAFETY:` comment, and an entry in §5.3; no other `unsafe` shall exist. | `grep -rn "allow(unsafe_code)"` matches §5.3 exactly | Implemented (WP-0.1) |
| SPEC-0001-R7 | The repository shall pin the Rust toolchain in `rust-toolchain.toml` (channel `1.99.1`, components `rustfmt` and `clippy`), and CI shall use that file rather than a floating `stable`. | inspection of the file and `.github/workflows/ci.yml` | Implemented (WP-0.1) |
| SPEC-0001-R8 | The root `Cargo.toml` shall define the `release` profile with the PoC values (`codegen-units = 1`, `lto = true`, `opt-level = 3`, `panic = "abort"`, `strip = true`) and a `profiling` profile that inherits `release` with `debug = "line-tables-only"` and `strip = false`. | inspection; `cargo build --profile profiling -p seeky-desktop` | Implemented (WP-0.1) |
| SPEC-0001-R9 | The app shall move from `apps/seeky` to `apps/desktop` with `git mv`, so that `git log --follow` on a moved file shows its pre-rename history. | `git log --follow apps/desktop/src-tauri/src/lib.rs` | Implemented (WP-0.1) |
| SPEC-0001-R10 | When the app is renamed, the product name (`Seeky`), the bundle identifier (`ai.seeky.desktop`), the version, the release executable name (`seeky`), and the app-data directory (and therefore the existing `seeky.db`) shall stay unchanged. | inspection of `tauri.conf.json` and `Cargo.toml`; manual run: an index built before the rename is listed after it | Implemented (WP-0.1) |
| SPEC-0001-R11 | The workspace shall follow the internal dependency matrix in §4.4, enforced by `cargo-deny` `bans` entries with `wrappers` in `deny.toml`. | `cargo deny check bans` passes; a scratch commit that adds `seeky-store` to `seeky-extract` fails it | Implemented (WP-0.1) |
| SPEC-0001-R12 | No engine crate shall depend, directly or transitively, on `tauri` or any `tauri-*` crate. | `cargo tree --workspace -e normal -i tauri` lists only `seeky-desktop` and Tauri plugins; `cargo deny check bans` | Implemented (WP-0.1) |
| SPEC-0001-R13 | The heavy external dependencies in §4.4 shall be direct dependencies only of their owning crate (for example `rusqlite` only in `seeky-store`, `ort` only in `seeky-infer`). | `cargo deny check bans` | Implemented (WP-0.2) |
| SPEC-0001-R14 | `seeky-core` shall depend only on `serde` and `thiserror` (plus `std`). | inspection of `crates/seeky-core/Cargo.toml` | Implemented (WP-0.1) |
| SPEC-0001-R15 | Every member shall declare a `hw-tests` feature (empty where unused, forwarding to dependencies where they have hardware tests), so that `cargo test --workspace` is hardware-free and `cargo test --workspace --features hw-tests -- --test-threads=1` runs every hardware test. | both commands; ignored-test count without the feature equals the hardware-test count | Implemented (WP-0.1) |
| SPEC-0001-R16 | When the rename lands, every reference to `apps/seeky` (pre-commit hook, CI workflow, `.gitignore`, `.prettierignore`, `AGENTS.md`, `CONTRIBUTING.md`, READMEs, docs) shall point to `apps/desktop`, except historical records (CHANGELOG entries, the conformance audit, `docs/archive/`). | `git grep -n "apps/seeky"` returns only the exceptions; the docs link check passes | Implemented (WP-0.1) |
| SPEC-0001-R17 | When WP-0.1 is complete, the full PoC test suite (9 tests: 4 hardware-free, 5 `hw-tests`) shall pass unchanged from the workspace root, and `npm run build` and `npm run tauri dev` shall work from `apps/desktop`. | commands; `cargo test --workspace` reports 4 passed, 5 ignored | Implemented (WP-0.1) |
| SPEC-0001-R18 | From WP-0.2 on, library crates shall not depend on `anyhow`; only `seeky-desktop` and `tools/*` binaries may. | `cargo tree --workspace -e normal -i anyhow --depth 1` lists no library crate | Implemented (WP-0.2) |

## 4. Interfaces

### 4.1 Root files

```text
Cargo.toml              virtual workspace: members, package, dependencies, lints, profiles
Cargo.lock              single lockfile (moved from apps/seeky/src-tauri)
rust-toolchain.toml     channel = "1.99.1", components = ["rustfmt", "clippy"], profile = "minimal"
clippy.toml             allow-unwrap-in-tests = true, allow-expect-in-tests = true
deny.toml               [bans] for §4.4 (WP-0.4 adds [licenses] and [advisories] and runs it in CI)
rustfmt.toml            unchanged
crates/seeky-*/         Cargo.toml + src/lib.rs
apps/desktop/           renamed from apps/seeky (frontend + src-tauri member)
```

`[workspace.package]`: `version = "0.1.0"`, `edition = "2024"`,
`rust-version = "1.99"`, `license = "MIT"`,
`repository = "https://github.com/bgeneto/seeky"`. The workspace version is the
single product version; `tauri.conf.json` keeps the same value.

### 4.2 Crates and responsibilities

| Crate | Owns | Phase 0 content |
|---|---|---|
| `seeky-core` | Domain types and IDs, configuration types, error types shared across crates, subsystem traits | Stub in WP-0.1; API types from SPEC-0002 in WP-0.2 |
| `seeky-extract` | Format extraction, normalization, language ID, chunking, OCR adapter | Stub; PoC `extract.rs` and `chunk_text` in WP-0.2 |
| `seeky-infer` | ONNX Runtime sessions, execution-provider selection, tokenizers, model discovery/registry, embedder implementations | Stub; PoC `inference.rs` in WP-0.2 |
| `seeky-store` | SQLite schema and migrations, metadata, lexical (FTS5) and filename queries, vector storage | Stub; PoC `db.rs` in WP-0.2 |
| `seeky-search` | Query parsing, candidate generation, fusion, ranking, snippets | Stub; PoC `search.rs` in WP-0.2 |
| `seeky-engine` | `Engine` façade: roots, scanning, watcher, indexing orchestration, health, status | Stub; PoC `indexer.rs` and the non-Tauri parts of `lib.rs` in WP-0.2 |
| `seeky-provision` | Asset manifest, download, verification, asset cache | Empty stub until Phase 6 |
| `seeky-eval` | Datasets, qrels, metrics, statistics, report writer | Empty stub until Phase 1 |
| `seeky-desktop` (`apps/desktop/src-tauri`) | Tauri commands and event forwarding only | Whole PoC in WP-0.1; commands + wiring after WP-0.3 |

The Rust package of the shell is renamed `seeky` → `seeky-desktop`; its
`[[bin]]` stays `seeky` (R10).

### 4.3 Shared lints

```toml
[workspace.lints.rust]
unsafe_code = "deny"            # item-level exemptions only (R6, §5.3)

[workspace.lints.clippy]
# Correctness and hygiene (AGENTS.md §6)
dbg_macro = "deny"
todo = "deny"
unimplemented = "deny"
unwrap_used = "deny"            # tests exempt via clippy.toml
print_stdout = "deny"           # engine code logs through `tracing`
print_stderr = "deny"
# Pedantic subset: cheap, low-noise, performance- or clarity-relevant
cloned_instead_of_copied = "warn"
explicit_iter_loop = "warn"
flat_map_option = "warn"
implicit_clone = "warn"
inefficient_to_string = "warn"
manual_let_else = "warn"
needless_pass_by_value = "warn"
redundant_closure_for_method_calls = "warn"
semicolon_if_nothing_returned = "warn"
uninlined_format_args = "warn"
unnested_or_patterns = "warn"
```

`-D warnings` turns every `warn` into an error in CI. `expect` is allowed only
for invariants that cannot fail on user data (for example compiling a constant
regex); review rejects `expect` on I/O or user input. A binary that must print
(the future `seeky-bench`) allows `print_stdout` at its crate root. Adding a
lint is a normal PR; removing one needs a spec changelog entry.

### 4.4 Dependency matrix

Internal direct dependencies (anything not listed is forbidden):

| Crate | May depend on |
|---|---|
| `seeky-core` | — |
| `seeky-extract` | `seeky-core` |
| `seeky-infer` | `seeky-core` |
| `seeky-store` | `seeky-core` |
| `seeky-search` | `seeky-core`, `seeky-store`, `seeky-infer` |
| `seeky-engine` | `seeky-core`, `seeky-extract`, `seeky-infer`, `seeky-store`, `seeky-search`, `seeky-provision` |
| `seeky-provision` | `seeky-core` |
| `seeky-eval` | `seeky-core` |
| `seeky-desktop` | `seeky-engine` only (the engine re-exports the API types it returns) |
| `tools/seeky-bench` (Phase 1) | `seeky-engine`, `seeky-eval` |

Owners of heavy external dependencies (direct dependency allowed only here):

| Dependency | Owner |
|---|---|
| `tauri`, `tauri-plugin-*` | `seeky-desktop` |
| `rusqlite` | `seeky-store` |
| `ort`, `openvino`, `openvino-sys`, `tokenizers`, `half` | `seeky-infer` |
| `pdfium-render`, `calamine`, `zip` | `seeky-extract` |
| `notify`, `walkdir` | `seeky-engine` |

`deny.toml` expresses both tables as `[[bans.deny]]` entries with `wrappers`
(for example `{ crate = "tauri", wrappers = ["seeky-desktop", <tauri plugins>] }`
and `{ crate = "seeky-store", wrappers = ["seeky-search", "seeky-engine"] }`).
Third-party crates that legitimately depend on an owned crate (for example
`calamine` on `zip`) are added to that entry's `wrappers`.
`walkdir` is not banned, because Tauri's build crates and `notify` depend on
it; its ownership is checked in review.

### 4.5 PoC module → crate mapping (executed by WP-0.2)

| PoC item (`apps/seeky/src-tauri/src/`) | Destination |
|---|---|
| `extract.rs` | `seeky-extract` |
| `indexer.rs`: `chunk_text`, `CHUNK_CHARS`, overlap | `seeky-extract` (chunking) |
| `indexer.rs`: scan, ignore rules, `index_root`, `index_file`, `IndexContext`, progress/summary types | `seeky-engine` (types in `seeky-core`) |
| `inference.rs` (backends, embedding, Gety model/runtime discovery, `available_backends`) | `seeky-infer` (`Backend`, `EngineInfo` in `seeky-core`) |
| `db.rs` | `seeky-store` (`Root`, `Counts`, `DocumentView`, `FileSignature` in `seeky-core`) |
| `search.rs` (RRF fusion, dense scan, snippets) | `seeky-search` (`SearchHit` in `seeky-core`) |
| `lib.rs`: `AppState`, `WatchManager`, watch batching, health, status, backend selection, index orchestration | `seeky-engine` |
| `lib.rs`: `#[tauri::command]` functions, `run()`, event emission, path resolution from Tauri (`app_data_dir`, `resource_dir`) | `seeky-desktop` |
| `tests/fixtures/*` | the crate whose tests use them (`seeky-extract`) |

## 5. Behavior details

### 5.1 WP-0.1 sequence

1. Add the root `Cargo.toml`, `rust-toolchain.toml`, `clippy.toml`, and the
   eight stub crates; make `apps/seeky/src-tauri` a member; move `Cargo.lock`
   and the `[profile.*]` sections to the root (Cargo ignores member profiles).
2. `git mv apps/seeky apps/desktop`; rename the package to `seeky-desktop`
   with `[[bin]] name = "seeky"`; update every path reference (R16), including
   `RUST_MANIFEST` and `WEB_DIR` in `.githooks/pre-commit` and the CI workflow
   (which then runs `cargo fmt --all --check` from the root).
3. Add `deny.toml` `[bans]`; fix any lint the new set raises in the PoC code
   with behavior-preserving changes only.
4. Run every check in §6; capture nothing else (the golden snapshot belongs to
   WP-0.2).

### 5.2 Feature flags

`hw-tests` is the only cross-crate feature in Phase 0. A crate's feature
forwards to the crates whose hardware tests it runs (for example
`seeky-engine/hw-tests = ["seeky-infer/hw-tests", "seeky-extract/hw-tests"]`).
The shell keeps no hardware tests after WP-0.2.

### 5.3 Audited `unsafe`

| Location (after WP-0.2) | Code | Justification | Removal |
|---|---|---|---|
| `crates/seeky-infer/src/inference.rs`, runtime library path setup (`prepend_path`, reached from PoC `prepare_cuda_paths` and `prepare_openvino_path`) | `std::env::set_var("PATH", …)` | Needed for the PoC to locate CUDA/OpenVINO libraries from a Gety installation. `set_var` is unsound if another thread reads the environment concurrently; the `// SAFETY:` comment must state this residual risk (audit A9) | WP-2.1 loads provider libraries by explicit path and deletes this code |
| `tools/seeky-bench/src/perf/platform.rs`, Windows `current_rss_bytes`, `total_memory_bytes`, `process_affinity` (WP-1.6) | `K32GetProcessMemoryInfo`, `GlobalMemoryStatusEx`, and `GetProcessAffinityMask` through `windows-sys` | SPEC-0003 R27/R28 need process RSS, installed memory, and the pinned CPU set on Windows; each call writes only into a live, zero-initialized local whose size it is given, on the always-valid current-process pseudo-handle. Internal tool, never shipped | None planned; remove if a reviewed process-metrics crate replaces it |

### 5.4 What does not change

Rust source behavior, the SQLite schema, the Tauri configuration other than
paths, the React UI, the model resource location relative to the shell crate,
and the Git LFS tracking of `model.bin` (moved with `git mv`).

## 6. Acceptance

### 6.1 Tests

No new behavior, so no new unit tests. The existing tests are the guard:

| Check | Requirement IDs |
|---|---|
| `cargo test --workspace` → 4 passed, 5 ignored | R1, R15, R17 |
| `cargo test --workspace --features hw-tests -- --test-threads=1` → 9 passed (T2 with local assets) | R15, R17 |
| `cargo clippy --workspace --all-targets -- -D warnings`, also with `--features hw-tests` | R5, R6 |
| `cargo fmt --all --check`; `npm run format:check` and `npm run build` in `apps/desktop` | R16, R17 |
| `cargo deny check bans`, plus one deliberate violation on a scratch branch that must fail | R11, R12, R13 |

### 6.2 Benchmark gates

None: no runtime behavior changes. Indexing and search timings are not
measured in Phase 0 beyond the golden test.

### 6.3 Inspection

- Each `Cargo.toml` inherits package fields and lints (R2, R5).
- `git grep -n "apps/seeky"` returns only historical records (R16).
- `git log --follow` shows pre-rename history (R9).
- The app opens an index created before the rename (R10).
- `cargo tree` confirms R12, R14, R18.

## 7. Risks and open questions

| # | Item | Decides | When | Blocking |
|---|---|---|---|---|
| 1 | `panic = "abort"` prevents in-process panic isolation of extractors (WP-3.5 needs `catch_unwind`, which requires `panic = "unwind"`, or a worker process). Kept for now to avoid a behavior change | Maintainer, with WP-3.5 | Phase 3 | No |
| 2 | Toolchain bump policy: proposal is a deliberate PR per stable minor release, with all checks green | Maintainer | Before WP-0.4 | No |
| 3 | The pedantic lint subset may surface many findings in PoC code; WP-0.1 fixes them only where the fix is mechanical, otherwise a lint moves to a follow-up with a changelog entry here | Implementer | WP-0.1 | No |
| 4 | Tauri build tooling and the root `target/`: `tauri dev/build` must resolve the workspace target directory; verified by R17 | Implementer | WP-0.1 | No |

## 8. Changelog

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-11-27 | Initial draft |
| 0.1 | 2026-11-27 | Accepted by the maintainer |
| 0.1 | 2026-11-27 | WP-0.1 implemented R1–R12 and R14–R17. §4.4: `walkdir` ownership is checked in review instead of `cargo-deny` (Tauri build crates depend on it). R13 stays open until the shell drops the PoC's heavy dependencies |
| 0.1 | 2026-11-27 | WP-0.2 implemented R13 and R18; §5.3 names `crates/seeky-infer/src/inference.rs` as the audited unsafe location. All requirements are implemented |
