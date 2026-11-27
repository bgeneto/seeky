# AGENTS.md — Operating manual for AI agents (and humans)

Seeky is developed largely by AI coding agents. This file tells you what Seeky
is, which documents are binding, how to work, and what you must never do. Read
it fully before your first change. It applies to every agent and every human
contributor.

## 1. What Seeky is (30 seconds)

**Seeky is a cross-platform, CPU-first, local neural information retrieval
engine, delivered as a lightweight Tauri desktop application**, providing fast,
accurate, multilingual semantic search across the user's files without a GPU,
cloud services, or generative models.

It is **a search engine with a desktop interface, not a desktop app with a
search engine.** The engine comes first, is UI-independent, and is measured
headlessly.

Non-negotiable principles (full text: [`docs/product/vision.md`](docs/product/vision.md)):

| | Principle | One-line rule for you |
|---|---|---|
| P1 | CPU-first | Never make a GPU required; budgets are verified CPU-only |
| P2 | NPU-ready | Accelerate through ONNX Runtime execution providers, always with CPU parity and fallback |
| P3 | Local-first | No document content leaves the machine; no telemetry |
| P4 | Performance-first | State the latency/throughput/memory impact of every change; measure it |
| P5 | Multilingual-first | Portuguese and English first; never regress another language silently |
| P6 | Search-only | No chatbot, agents, MCP, connectors, or generated content; VLMs only as gated OCR transcribers (ADR-0021) |
| P7 | Benchmark-driven | No component chosen for popularity or leaderboard rank; bake-off + report |
| P8 | Model-agnostic core | No hardcoded model dimensions, paths, prompts, or tensor names |

## 2. Source of truth and precedence

When documents disagree, the higher one wins. **Do not silently pick one —
stop, report the conflict, and propose the fix** (usually an ADR or a doc
correction).

1. [`docs/product/vision.md`](docs/product/vision.md) — product constitution.
2. Accepted ADRs in [`docs/adr/`](docs/adr/README.md).
3. Accepted specs in [`docs/specs/`](docs/specs/README.md).
4. Architecture contracts in [`docs/architecture/`](docs/architecture/README.md).
5. [`docs/plans/seeky-implementation-plan.md`](docs/plans/seeky-implementation-plan.md) — phases, work packages, status.
6. [`docs/benchmarks/methodology.md`](docs/benchmarks/methodology.md) — budgets and gates (provisional until locked by ADR).
7. Code and code comments.

Not binding: [`docs/research/`](docs/research/README.md) (Gety reverse
engineering and source reports — context only) and
[`docs/archive/`](docs/archive/README.md) (superseded).

## 3. Repository map

```text
AGENTS.md / CLAUDE.md     this manual (CLAUDE.md imports it)
apps/seeky/               as-built PoC: Tauri 2 + React 19 + Rust (becomes apps/desktop in Phase 0)
  src/                    React/TypeScript UI
  src-tauri/src/          PoC engine + shell (lib.rs, indexer.rs, search.rs, inference.rs, db.rs, extract.rs)
  demo/                   five-file smoke corpus
docs/
  product/vision.md       principles, scope, product decisions
  adr/                    one decision per file (0001–0022 …)
  specs/                  SDD specs + template (written just-in-time per phase)
  architecture/           overview, indexing, retrieval-engine, inference-and-models, provisioning
  benchmarks/             methodology, candidates, report template, results/
  plans/                  the implementation plan (single active plan)
  validation/             as-built PoC runtime evidence and conformance audit
  research/               non-binding research (gety/ = reverse-engineering notes)
  archive/                superseded documents
  glossary.md             terminology
```

Target layout after Phase 0 (do not create ahead of its work package):
`crates/seeky-{core,extract,infer,store,search,engine,provision,eval}`,
`tools/{seeky-bench,model-export}`, `apps/desktop`, `bench/`. See
[`docs/architecture/overview.md`](docs/architecture/overview.md).

## 4. How to work: the SDD + BmDD loop

"BmDD" = Benchmark-Driven Development (never Behavior-Driven Development here).

1. **Pick a work package** (`WP-x.y`) from the plan whose dependencies are done.
   If your task is not a WP, it must be a bug fix, a behavior-preserving
   refactor, docs, or tooling.
2. **Read the spec.** Implement only **Accepted** specs. No spec yet? Write a
   Draft from [`docs/specs/_template.md`](docs/specs/_template.md) and stop for
   acceptance — do not implement a Draft.
3. **Declare the gate** before coding: which tests prove the requirement IDs,
   which budgets/quality gates (P*, I*, R*, D*, O*, Q*) the change can affect.
4. **Write failing tests first** (unit, property, integration, fuzz as the spec
   says). Reference requirement IDs in test names or doc comments
   (`// SPEC-0007-R4`).
5. **Implement the smallest change** that passes, inside the crates the WP names.
6. **Run the checks** (§5). All must pass.
7. **Prove it.** If quality or performance can change, run `seeky-bench` under
   the methodology and write a report from
   [`docs/benchmarks/_report-template.md`](docs/benchmarks/_report-template.md).
   Never hand-edit numbers. Never tune on the `test` split.
8. **Record it.** New/changed default or rule → ADR. Update spec status,
   `CHANGELOG.md` (user-visible changes), and the plan's status table.

Stop and ask the maintainer when: a spec is ambiguous, documents conflict, a
budget cannot be met, a dependency or model license is unclear, or a change
would touch more than the WP's named crates.

## 5. Commands

Current PoC (Windows; until Phase 0 creates the workspace):

```powershell
cd apps\seeky
npm install
npm run build                                  # TypeScript + Vite build
npm run tauri dev                              # run the desktop app
npm run format:check                           # Prettier (npm run format fixes)

cd src-tauri
cargo fmt --check                              # rustfmt (cargo fmt fixes)
cargo clippy --all-targets -- -D warnings
cargo test --lib                              # hardware-free by default
cargo test --lib --features hw-tests -- --test-threads=1   # needs local models/PDFium/CUDA/NPU
cargo check
```

After Phase 0 (workspace root):

```powershell
cargo fmt --all --check
npm --prefix apps/desktop run format:check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace                         # hardware-free by default
cargo deny check
cargo run -p seeky-bench -- eval --corpus sdc-smoke --split dev
```

Formatting is enforced: `npm install` enables the versioned pre-commit hook
(`.githooks/pre-commit`, check-only rustfmt + Prettier) and CI runs the same
checks. Run the formatters before committing; never commit with
`--no-verify`. Markdown is not Prettier-formatted yet.

Hardware-dependent tests (NPU, real models) are opt-in via a cargo feature and
must never be required for CI to pass. Until WP-0.4 makes `clippy -D warnings`
mandatory in CI, do not introduce new warnings and fix the ones in code you
touch.

## 6. Engineering rules

### Architecture

- Engine crates never depend on `tauri` or UI types; the shell never touches
  SQLite, models, or user files directly (ADR-0015).
- No sidecar service, local HTTP server, MCP server, or public CLI (ADR-0008).
  `tools/seeky-bench` is internal tooling and never ships.
- Search never waits for indexing: separate pools/sessions; no lock held across
  inference or user-file I/O; single store writer.
- Every swappable subsystem (models, lexical, filename, vector index, OCR) goes
  through its trait in `seeky-core`.
- One embedding vector space per index generation; never mix vectors (ADR-0019).
- The filename/path is never part of the embedding input.

### Rust

- Edition 2024; `clippy -D warnings`; `unsafe` only in audited modules with a
  `// SAFETY:` comment.
- Libraries use `thiserror`; `anyhow` only at binary edges. No `unwrap`/`expect`
  on user data or I/O paths; no panics on malformed files.
- Hot paths: no per-item allocation in inner loops, no needless clones, prefer
  slices and pre-sized buffers; justify with a microbenchmark when in doubt.
- `tracing` spans per pipeline stage; no `println!` in engine code.
- New dependency → check license (ADR-0022), maintenance, binary-size impact;
  mention it in the PR.

### TypeScript / UI

- Strict TypeScript; no business logic in the UI; all data through engine
  commands/channels.
- All user-facing strings in en + pt catalogs; no hardcoded text.
- Exactly two themes (light/dark). Minimal UI: no dashboards, chat, AI badges,
  or decorative metrics (ADR-0012).

### Models and benchmarks

- Behavior comes from the model manifest; never hardcode dimensions, prompts,
  pooling, padding, or output names.
- Shortlist from leaderboards, decide by bake-off on Seeky's protocol.
- Check the license **before** spending time on a candidate
  ([`docs/benchmarks/candidates.md`](docs/benchmarks/candidates.md)).
- Report confidence intervals; a difference inside the CI is a tie.
- Development tooling may use LLMs to draft evaluation data; humans verify; no
  generative feature ever ships (ADR-0021).
- ONNX Runtime is the only inference engine (ADR-0019). Compare models **as
  deployed** (ONNX variant + quantization + provider), following the bake-off
  funnel in [`docs/benchmarks/methodology.md`](docs/benchmarks/methodology.md)
  §8. A model that cannot run on ORT with parity is priced under the ADR-0019
  runtime-cost rule; a file format never implies a model class.
- Python is allowed only in `tools/` (offline export, dataset prep) — never in
  the product.

## 7. Never do this

- Add a generative LLM, chat, summarization, answer generation, agents, MCP,
  connectors, cloud sync, accounts, license keys, telemetry, or analytics; or
  a VLM used for anything but gated OCR transcription (ADR-0021).
- Add a second inference engine to the product without the ADR-0019
  runtime-cost rule.
- Make a GPU required, or make a GPU provider the default.
- Send document content, file names, or paths over the network, or write them
  to logs unredacted.
- Add GPL/AGPL/non-commercial code, models, or assets to shipped artifacts.
- Commit model weights, large datasets, private corpora, secrets, `.env`
  files, or personal paths (use `%APPDATA%`, `<repo>`, etc. in docs).
- Copy Gety source, decompiled code, binaries, or private weights. The research
  notes describe interfaces; implement independently (clean room, see
  [`NOTICE.md`](NOTICE.md)).
- Claim "faster", "better", or "SOTA" without a committed benchmark report.
- Tune on the `test` split, or change a locked budget without an ADR.
- Edit an Accepted ADR's decision (write a superseding ADR instead).
- Skip hooks, disable checks, or weaken lints to make CI green.

## 8. Definition of Done

- Implements an Accepted spec (or is an allowed non-spec change).
- Tests reference requirement IDs and pass; all checks in §5 pass.
- Benchmark report attached when quality/performance can change; budgets hold.
- ADR added/updated when a default or rule changes.
- Strings localized (en/pt) and both themes verified for UI changes.
- `CHANGELOG.md`, spec status, and the plan status table updated.
- No content, personal data, or secrets anywhere in the diff.

## 9. Commits and pull requests

- Conventional, imperative subjects with a scope:
  `feat(search): add MMR diversity stage`,
  `perf(store): binary first-pass vector scan`,
  `bench(embed): bake-off report for 2026-12 candidates`,
  `docs(adr): 0023 lock budgets v1`.
- One work package per PR where possible; reference `WP-x.y` and `SPEC-NNNN`.
- Fill in [`.github/pull_request_template.md`](.github/pull_request_template.md).
- Docs are written in English; UI strings ship in English and Portuguese.

## 10. Glossary

Terminology (passage, generation, two-speed indexing, Instant/Hybrid/Refined
stages, BmDD, SDC, tiers): [`docs/glossary.md`](docs/glossary.md).
