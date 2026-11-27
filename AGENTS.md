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
Cargo.toml                workspace root (members: crates/*, apps/desktop/src-tauri)
crates/                   engine crates seeky-{core,extract,infer,store,search,engine,provision,eval} (stubs until WP-0.2)
apps/desktop/             Tauri 2 + React 19 shell; still holds the PoC engine until WP-0.2/WP-0.3
  src/                    React/TypeScript UI
  src-tauri/src/          PoC engine + shell (lib.rs, indexer.rs, search.rs, inference.rs, db.rs, extract.rs)
  demo/                   five-file smoke corpus
docs/
  product/vision.md       principles, scope, product decisions
  adr/                    one decision per file (0001–0023 …)
  specs/                  SDD specs + template (written just-in-time per phase)
  architecture/           overview, indexing, retrieval-engine, inference-and-models, provisioning
  benchmarks/             methodology, candidates, report template, results/
  plans/                  the implementation plan (single active plan) + agent briefs for the current waves
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
   which budgets/quality gates (S*, I*, R*, D*, O*, V*, Q*) the change can affect.
4. **Write failing tests first** (unit, property, integration, fuzz as the spec
   says). Reference requirement IDs in test names or doc comments
   (`// SPEC-0007-R4`). What each kind of change must test, and how: §6 Tests.
5. **Implement the smallest change** that passes, inside the crates the WP names.
6. **Run the checks** (§5). All must pass.
7. **Prove it.** If quality or performance can change, run `seeky-bench` under
   the methodology and write a report from
   [`docs/benchmarks/_report-template.md`](docs/benchmarks/_report-template.md).
   Never hand-edit numbers. Never tune on the `test` split.
8. **Record it — in the same commit as the work**, so `main` never claims more
   or less than it contains. Check every item; skip only those that do not
   apply:
   - **Plan** [§15.3](docs/plans/seeky-implementation-plan.md#153-work-packages):
     set the WP's status using the values in §15.1. **Done** lists the
     evidence (spec and version, test or report paths, ADR). **In progress**
     says what is done and what remains, precisely enough for the next session
     to resume. Update the phase row (§15.2) and remove finished items from
     the next actions (§16).
   - **Spec**: set each requirement you implemented to `Implemented` in the
     spec's §3 Status column; when all are, move the spec header and the
     [specs index](docs/specs/README.md#index) to Implemented (Verified once
     its benchmark gates pass with a linked report); add a spec changelog row.
   - **ADR**: a new or changed default or rule gets an ADR; keep the
     [ADR index](docs/adr/README.md) status in step.
   - **Audit**: mark any deviation or finding the change closes in
     [`docs/validation/poc-conformance-audit.md`](docs/validation/poc-conformance-audit.md)
     as Closed/Fixed with the WP and the proving test.
   - **`CHANGELOG.md`**: an entry under `Unreleased` for anything a user,
     contributor, or agent would notice (behavior, defaults, formats, product
     decisions, process rules); pure internal refactors need none.
   - **This file and `CONTRIBUTING.md`**: if the change moves directories,
     renames apps or crates, or changes a command, update §3 and §5 here and
     the setup and checks in `CONTRIBUTING.md`.
   - **Commit and push** per §9: green, only your own changes, a semantic
     message ending with a `Refs: WP-x.y, SPEC-NNNN` trailer.

   Changes outside any WP (bug fixes, refactors, docs, tooling) have no plan
   row; they still record `CHANGELOG.md` and the audit when those apply.

Stop and ask the maintainer when: a spec is ambiguous, documents conflict, a
budget cannot be met, a dependency or model license is unclear, or a change
would touch more than the WP's named crates.

### Parallel agents

When several agents work at the same time, one **orchestrator** (a lead
session or the maintainer) assigns and integrates the work, and **workers**
implement it. These rules add to the loop above; where they differ from §9,
they win for workers.

1. **One worktree, one branch, one work package.** Each worker runs in its
   own git worktree on its own branch (for example `wp/0.2-engine-extraction`)
   and delivers one work package per pull request. Workers never commit to
   `main` and never share a working tree with another agent; they commit and
   push to their branch (§9) and open a PR. The orchestrator merges after CI
   is green and the PR is reviewed.
2. **Owned paths.** Every assignment lists the paths the worker may change,
   taken from the crate ownership in
   [SPEC-0001](docs/specs/SPEC-0001-workspace-and-crate-boundaries.md) §4.2 and
   the WP's crates. Two concurrent assignments never own the same path. A
   worker that needs a change outside its paths (another crate, the root
   `Cargo.toml` or `deny.toml`, CI, a shared doc) stops and reports it instead
   of making it.
3. **Shared records belong to the orchestrator.** Workers do not edit plan
   §15 and §16, `CHANGELOG.md`, the specs and ADR indexes, or the conformance
   audit; parallel edits to those files always conflict. A worker updates only
   the §3 Status column of the spec it implements and proposes the remaining
   step 8 records in its PR description. Before merging, the orchestrator
   rebases the branch on `main` and adds one commit with those records, so
   `main` still never claims more or less than it contains.
4. **Every worker starts from a brief** that names:
   - the work package, the Accepted spec and version, and the requirement IDs;
   - the owned paths, and paths it must not touch;
   - the tests to write first (§4 step 4, §6 Tests);
   - the commands that define green: §5 plus any WP-specific gate;
   - the definition of done: §8 without the orchestrator's records;
   - the stop conditions: the list above, plus any change outside the owned
     paths, a new dependency, or a failing check the worker did not cause;
   - the report it returns: what changed, test evidence, open questions, and
     the proposed records.

   Ready-made briefs for the current waves, the orchestrator prompt, and the
   maintainer gates are in [`docs/plans/agent-briefs.md`](docs/plans/agent-briefs.md)
   (operational, not binding; this file and the plan win).

## 5. Commands

From the workspace root (Windows; the toolchain is pinned in `rust-toolchain.toml`):

```powershell
cargo fmt --all --check                        # rustfmt (cargo fmt --all fixes)
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy --workspace --all-targets --features hw-tests -- -D warnings
cargo test --workspace                         # hardware-free by default
cargo test --workspace --features hw-tests -- --test-threads=1   # needs local models/PDFium/CUDA/NPU
cargo deny check                               # bans, licenses, advisories, sources

cd apps\desktop
npm install                                    # also enables the Git hooks
npm run build                                  # TypeScript + Vite build
npm run format:check                           # Prettier (npm run format fixes)
npm run tauri dev                              # run the desktop app
```

From Phase 1 on: `cargo run -p seeky-bench -- eval --corpus sdc-smoke --split dev`.

Formatting is enforced: `npm install` enables the versioned pre-commit hook
(`.githooks/pre-commit`, check-only rustfmt + Prettier) and CI runs the same
checks. Run the formatters before committing; never commit with
`--no-verify`. Markdown is not Prettier-formatted yet.

Hardware-dependent tests (NPU, real models) are opt-in via a cargo feature and
must never be required for CI to pass. CI runs clippy `-D warnings` with and
without `hw-tests`, hardware-free tests on Windows and Linux, `cargo deny
check`, the TypeScript build, and compile checks on Windows, Linux, and macOS.

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
- One embedding vector space per index generation, and one generation lineage
  per embedding channel; never mix vectors, and never compare raw scores across
  modalities (ADR-0019, ADR-0023).
- The text query path never loads a vision encoder; image search is an optional
  pack (ADR-0023).
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

### Tests

What every change must carry:

| Change | Required tests |
|---|---|
| Spec requirement | The tests in the spec's §6.1, written first, named or commented with the requirement ID (`// SPEC-0007-R4`) |
| Bug fix | A regression test that fails before the fix and passes after it, in the same commit |
| Behavior-preserving refactor | Existing tests (and the golden test, once WP-0.2 adds it) pass unchanged; code without coverage first gets a characterization test, in its own commit |
| Code that reads user files or external input (extractors, parsers, manifests, file system) | Error and malformed-input tests: no panic, a typed error, partial results only where the spec allows |
| Ranking, fusion, dedupe, chunking | Property tests for the invariants (plan §9), besides examples |
| Hot-path change that claims or risks a speed difference | A microbenchmark next to the code (quality and budget claims still need `seeky-bench`, §4 step 7) |
| UI | Component tests with mocked IPC once WP-7.8 lands; until then, a manual check in both themes and both locales |
| Docs only | None |

Pick the cheapest layer that proves the behavior: unit for pure logic,
integration through the `Engine` API for cross-crate behavior, property for
invariants, golden for ranked output and extraction blocks, fuzz for parsers
(tooling in plan §9).

- **Location**: Rust unit tests in a `#[cfg(test)] mod tests` beside the code;
  cross-crate and lifecycle tests in `crates/<crate>/tests/`; frontend tests
  next to the component. Until Phase 0, PoC tests stay in their modules.
- **Names** state the behavior (`renamed_file_keeps_embeddings`), never
  `test1` or `it_works`.
- **Hermetic and deterministic**: no network; no files outside a per-test
  temporary directory; no user or home paths; fixed seeds; no sleeps as
  synchronization; no dependence on test order; safe under parallel
  `cargo test`.
- **Hardware-free by default**: anything needing local models, PDFium, CUDA,
  or an NPU goes behind `hw-tests` (§5), and its logic also gets a
  hardware-free test where possible (for example with a fake `Embedder`).
- **Fixtures**: small, synthetic or redistributable (ADR-0022), committed
  beside the tests (`tests/fixtures/`); no personal documents, private
  corpora, or model weights. Evaluation corpora and qrels live in `bench/`;
  unit tests never assert ranking quality — `seeky-bench` does.
- **Fast**: the hardware-free suite stays fast enough to run before every
  commit; a test that needs more than a few seconds is an integration test
  and says why.
- **Behavior, not internals**: assert observable results, not private
  details a refactor could change without changing behavior.
- **Never** delete, weaken, `#[ignore]`, or rerun-until-green a failing test to
  get a commit through. A flaky test is fixed, or quarantined with
  `#[ignore = "<reason>, <WP or issue>"]` in a commit that says why.

**Green** means every check in §5 passes locally. It is the precondition for
every commit (§9).

### Models and benchmarks

- Behavior comes from the model manifest; never hardcode dimensions, prompts,
  pooling, padding, or output names.
- Shortlist from leaderboards, decide by bake-off on Seeky's protocol.
- Check the license **before** spending time on a candidate
  ([`docs/benchmarks/candidates.md`](docs/benchmarks/candidates.md)).
- Report confidence intervals; a difference inside the CI is a tie.
- A multimodal model competes in the text embedding bake-off on text merit;
  its image capability is only a tie-breaker (ADR-0023).
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

- Add a generative LLM, chat, summarization, answer generation, image
  captioning, agents, MCP, connectors, cloud sync, accounts, license keys,
  telemetry, or analytics; or
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
- Tests cover the change as §6 Tests requires, reference requirement IDs, and
  pass; all checks in §5 pass.
- Committed in green, logical commits with semantic messages and pushed; no
  uncommitted work of yours left in the tree (§9).
- Benchmark report attached when quality/performance can change; budgets hold.
- ADR added/updated when a default or rule changes.
- Strings localized (en/pt) and both themes verified for UI changes.
- Recorded in the same commit per §4 step 8: plan §15.3 row with evidence,
  spec requirement status and index, ADR index, audit rows, `CHANGELOG.md`.
- No content, personal data, or secrets anywhere in the diff.

## 9. Commits and pull requests

### When to commit

- **Commit every logically complete step as soon as it is green** (§6 Tests):
  one requirement or behavior with its tests, one bug fix with its regression
  test, one refactor, or one docs change. A work package is a series of small
  commits, each leaving `main` green; never let finished work pile up.
- Tests and the code that makes them pass go in the **same commit**; never
  commit red. The failing-first tests of §4 step 4 stay local until they pass.
- **Never end a session, hand off, or switch tasks with uncommitted work of
  your own.** If a step cannot be made green, do not commit it: tell the
  maintainer what is pending and record the remainder in plan §15.3.
- **Push right after committing** (to `main`, or to the branch of an open PR).
  The repository is public: before each push, scan the diff for personal
  paths, document content, and secrets (§7).

### What to stage

- Stage explicit paths of your own changes (`git add <path>`); never
  `git add -A`, `git add .`, or `git commit -a`. Several agents may share one
  working tree.
- Read `git status` and `git diff --cached` before every commit and commit
  only what you changed. Changes you did not make stay unstaged and
  untouched; mention them. When someone else's edits share a file with yours,
  stage only your hunks (build the staged version from `HEAD` plus your edits,
  for example with a patch and `git apply --cached`); if that is not possible,
  ask the maintainer.
- One logical change per commit: never mix a refactor with a behavior change,
  formatting with logic, or two work packages.

### Messages

- **Subject**: Conventional Commits, `type(scope): imperative summary`, at
  most 72 characters, no trailing period. Types: `feat`, `fix`, `perf`,
  `refactor`, `test`, `docs`, `build`, `ci`, `bench`, `style`, `chore`. The
  scope is the crate, app, or area (`search`, `store`, `ui`, `adr`, `plan`):
  `feat(search): add MMR diversity stage`,
  `perf(store): binary first-pass vector scan`,
  `bench(embed): bake-off report for 2026-12 candidates`,
  `docs(adr): 0023 lock budgets v1`.
- **Body**, required unless the subject says everything: what changed and
  why, wrapped at 72 columns; the motivation and effects (user-visible
  behavior, gates affected, follow-ups), not a replay of the diff.
- **Trailer**: every commit that belongs to a work package or spec ends with
  one (before any `Co-Authored-By` line), so `git log --grep "WP-0.2"` finds
  the whole history of a WP:

  ```text
  Refs: WP-0.2, SPEC-0001
  ```

### Pull requests

- One work package per PR where possible; reference `WP-x.y` and `SPEC-NNNN`.
- Fill in [`.github/pull_request_template.md`](.github/pull_request_template.md).
  Committing directly to `main` skips nothing: run through §8 and that
  template's checklist before each commit.
- Docs are written in English; UI strings ship in English and Portuguese.

## 10. Glossary

Terminology (passage, generation, two-speed indexing, Instant/Hybrid/Refined
stages, BmDD, SDC, tiers): [`docs/glossary.md`](docs/glossary.md).
