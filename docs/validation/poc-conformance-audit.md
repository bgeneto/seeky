# PoC Conformance Audit

| Field | Value |
|---|---|
| Date | 2026-11-27 |
| Scope | `apps/seeky` 0.1.0 PoC (Rust backend, React UI, Tauri configuration) against the Accepted ADRs, the [implementation plan](../plans/seeky-implementation-plan.md), and [`AGENTS.md`](../../AGENTS.md) engineering rules |
| Method | Code reading; `cargo fmt --check`, `cargo clippy --all-targets`, `cargo test --lib`, `npm run build` on the development workstation (tier T2) |
| Status | Phase 0 pre-flight fixes applied; open deviations tracked below with the work package (WP) that closes each one |

The PoC predates the current ADRs, so deviations are expected. This audit makes
them explicit so that WP-0.2 ("extract crates with no behavior change") freezes
known behavior deliberately, and so the golden test is captured after the
pre-flight bug fixes rather than before.

Maintenance: the commit that closes a deviation (§3) or a finding (§4) updates
its row in the same commit ([`AGENTS.md`](../../AGENTS.md) §4 step 8). In §3,
"Closed by" becomes `**Closed** (WP-x.y)`; in §4, `Open → WP-x.y` becomes
`**Fixed** (WP-x.y)` with the test that proves it. No new rows are added: new
deviations found after Phase 0 go to the plan or a spec. When every row is
closed, the Status field above becomes `Closed`.

## 1. Build health

| Check | Before pre-flight | After pre-flight |
|---|---|---|
| `cargo fmt --check` | Fails (41 hunks) | Passes |
| `cargo clippy --all-targets -- -D warnings` | Does not compile: 1 error (`invalid_regex`) and 11 warnings | Passes, with and without `--features hw-tests` |
| `cargo test --lib` | 8 passed on T2 only: 5 tests need local Gety model files, PDFium, CUDA, or an Intel NPU and fail elsewhere | Hardware-free by default: 4 passed, 5 ignored |
| `cargo test --lib --features hw-tests -- --test-threads=1` | — | 9 passed on T2 (with local assets) |
| `npm run build` | — | Passes |

## 2. Conforming

- RRF fusion with `k = 60` over lexical, dense, and filename rankings
  ([ADR-0003](../adr/0003-hybrid-retrieval-rrf.md)).
- Live watcher with a 600 ms debounce, per-root pause/resume, and
  size + nanosecond-mtime skipping ([ADR-0005](../adr/0005-incremental-watcher.md)).
- Tauri capabilities limited to `core:default` and `dialog:default`
  ([ADR-0006](../adr/0006-narrow-webview-capabilities.md); CSP is a deviation, §3).
- No sidecar, HTTP server, MCP, or public CLI ([ADR-0008](../adr/0008-no-sidecar-no-http-api.md)).
- MIT license; no account or license key ([ADR-0009](../adr/0009-mit-license.md),
  [ADR-0010](../adr/0010-no-account-no-license-key.md)).
- Rust edition 2024; no HTTP client dependency and no telemetry.

## 3. Known deviations already scheduled in the plan

| Area | Deviation | Rule | Closed by |
|---|---|---|---|
| Structure | Engine logic and Tauri commands live in one crate (`lib.rs`) | [ADR-0015](../adr/0015-engine-first-architecture.md) | WP-0.1–WP-0.3 |
| Models | `DIM = 384`, output tensor names, max tokens, and pad id hardcoded; model found by scanning a Gety installation | [ADR-0019](../adr/0019-single-inference-engine.md) | WP-2.1 |
| Runtimes | Two engines: ONNX Runtime and the native OpenVINO API | ADR-0019 | WP-0.6, WP-5.2 |
| Distribution | Runtime, model, and PDFium read from a Gety installation; OpenVINO IR bundled through Git LFS | [ADR-0011](../adr/0011-slim-first-run-provisioning.md), [ADR-0007](../adr/0007-temporary-lfs-model-asset.md) | WP-6.4 |
| Vector search | Exact scan of every vector decoded from SQLite on each query, while holding the database lock | [ADR-0020](../adr/0020-pluggable-index-backends.md) | WP-2.9 |
| Ranking | Chunk-level fusion only: no document layer, dedupe, diversity, or reranking | [ADR-0013](../adr/0013-hierarchical-multilingual-retrieval.md) | Phase 4 |
| Indexing | One pass per file (extract, embed, store); no durable queue or resource governor | [indexing](../architecture/indexing.md) | WP-3.1, WP-3.2 |
| UI | Dark theme only; English strings hardcoded | [ADR-0012](../adr/0012-two-themes-minimal-ui-en-pt.md) | WP-7.1, WP-7.2 |
| Webview | Content Security Policy is `null` | ADR-0006 | WP-7.9 |
| Libraries | `anyhow` in library code; no `tracing` spans | AGENTS.md §6 | WP-0.2 |

## 4. Findings of this audit

| # | Finding | Rule | Status |
|---|---|---|---|
| A1 | HTML extraction always failed: the script/style pattern used a backreference, which the `regex` crate rejects, so every `.html`/`.htm` file errored | Bug | **Fixed**; test `extracts_html_text_without_scripts_and_styles` added |
| A2 | Auto backend resolved CUDA → NPU → CPU (GPU first) | [ADR-0016](../adr/0016-cpu-first-npu-ready-execution.md) | **Fixed**: Auto resolves NPU → CPU; CUDA only when chosen explicitly. The NPU is still not "validated" in the ADR-0016 sense (see A5, A11) until WP-5.1/WP-5.2 |
| A3 | Tests needing local assets or hardware were not opt-in | AGENTS.md §5 | **Fixed**: `hw-tests` cargo feature |
| A4 | Regexes compiled per file, and per text run in DOCX/PPTX entity decoding | AGENTS.md §6 (hot paths) | **Fixed**: compiled once |
| A5 | Switching backend does not re-embed: CPU uint8, CUDA fp16, and NPU vectors mix in one index with no parity check | ADR-0019 (one vector space; parity) | Open → WP-2.1 (manifest, parity on load), WP-3.7 (index generations) |
| A6 | `start_index` initializes the embedding engine first: without a model nothing is indexed, not even lexically | [ADR-0018](../adr/0018-lexical-first-availability.md) | Open → WP-3.2, WP-6.3 |
| A7 | One `Mutex<Engine>` and one `Mutex<Connection>`: query embedding waits for the indexer's per-file embedding call (all chunks of a file), search waits for database writes, and the first search can wait for model load or NPU compilation | AGENTS.md §6 (search never waits for indexing); interference budget P5 | Open → WP-2.1 (separate latency session), WP-2.4 (WAL readers, single writer), WP-3.1 |
| A8 | `open_local_file` accepts any path from the webview and opens it with the OS default handler (including executables), with CSP `null` | ADR-0006 (narrow webview capabilities) | Open → WP-0.3 (open by document ID, defined in SPEC-0002), WP-7.9 |
| A9 | `unsafe { std::env::set_var("PATH", …) }` without a `// SAFETY:` comment, in a multithreaded process | AGENTS.md §6 | Open → WP-0.2 (document or remove), WP-2.1 (load provider libraries by explicit path) |
| A10 | No `query:`/`passage:` prefixes for an E5-derived model, and no measurement of the choice | [research note](../research/gety/models-and-inference.md) | Open → WP-1.7 (B0 ablation) |
| A11 | Silent truncation: the NPU path truncates at 256 tokens while chunks are 1,200 characters, often longer | [inference and models §3](../architecture/inference-and-models.md) | Open → WP-2.10 (chunking), WP-5.2 (shape buckets) |

## 5. Implications for Phase 0

- The WP-0.2 golden test is captured on the post-pre-flight code.
- WP-0.2 preserves the open deviations on purpose; they are closed by the
  listed work packages, not patched in the PoC.
- SPEC-0002 must define file opening by document ID (A8) and must not expose
  raw paths as a command input.
