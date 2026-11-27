# Agent briefs: parallel waves after WP-0.1

| Field | Value |
|---|---|
| Status | Operational, not binding. [`AGENTS.md`](../../AGENTS.md), the [vision](../product/vision.md), ADRs, specs, and the [plan](seeky-implementation-plan.md) win over this file |
| Owner | The orchestrator (AGENTS.md §4, Parallel agents); revised when a wave changes |
| Base | `main` at `6a4999b` (2026-11-27): WP-0.1 and WP-0.5 done, WP-0.4 in progress; SPEC-0001 and SPEC-0002 v1 Accepted |
| Reach | Phase 0 complete; Phase 1 complete except the human-verified judgments (WP-1.4) and the B0 run on T1 (WP-1.7); WP-7.1/7.2; SPEC-0005/0006 drafts (§7) |

This file holds ready-to-paste prompts for a long, mostly unattended run of
several agents: one orchestrator prompt (§1), the preamble every worker gets
(§3), and one brief per lane (§4–§6). The briefs follow AGENTS.md §4 rule 4.

## 0. For the maintainer: how to start

**Option A (recommended):** open one session at the repository root on
`main` and paste the orchestrator prompt (§1). It launches the workers, reviews
and merges their pull requests, keeps the records, and stops with a status
report when only you can unblock it.

**Option B (manual):** start each lane yourself. For each lane, create a
worktree, then open a session in it and paste the §3 preamble followed by the
lane's brief:

```powershell
git worktree add ..\seeky-wp02 -b wp/0.2-engine-extraction origin/main
```

```powershell
npm --prefix ..\seeky-wp02\apps\desktop install
```

Then run the orchestrator prompt in a separate session, only to integrate.

Before you start:

- **Where lanes run.** Lanes A, A2, and E need this workstation: the
  hardware tests use the local Gety model, ONNX Runtime, PDFium, and the
  Intel NPU. Lanes B, C, D, F, G, and I can run anywhere, cloud included.
- **Disk.** Each Rust worktree builds its own `target/` (about 10 GB). Lane E
  downloads and exports models (budget 50 GB, kept outside the repository).
- **Tools.** `gh` is authenticated for `bgeneto/seeky`, `cargo-deny` is
  installed (`cargo install cargo-deny --locked`), Node 24, Git LFS.
- **Permissions.** An unattended session must be allowed to run `cargo`,
  `npm`, `git`, `gh`, and (lane E) `python`/`uv` without prompting. The
  permission mode is your choice.
- **Your gates.** The run pauses at the gates below; every other lane keeps
  going meanwhile. Approvals count only when you give them in the
  orchestrator's chat or commit them yourself.

| Gate | You decide | Unlocks |
|---|---|---|
| H1 | Accept SPEC-0003 and SPEC-0004 (lane C drafts) | WP-1.1, WP-1.3, then WP-1.2, WP-1.5, WP-1.6, WP-1.8 |
| H2 | Accept SPEC-0014 v1 (lane D draft) | WP-7.1 → WP-7.2 |
| H3 | Approve the T1-emulated profile that lane E proposes, or provide a physical T1 laptop | WP-0.6 final measurements |
| H4 | Approve the license exceptions and advisory ignores that lane B lists, if any | WP-0.4 Done |
| H5 | Decide the WP-0.6 outcome: ADR-0019 stands, or WP-2.3 starts for the failing role | Phase 0 exit; SPEC-0005 |
| H6 | Verify the LLM-drafted queries and judgments (lane J) | WP-1.4, then WP-1.7 (B0 on T1, also yours) |
| H7 | Accept SPEC-0005 and SPEC-0006 (lane N drafts) | Phase 2 briefs (next revision of this file) |
| — | Manual checks the agents cannot do: the app opens an existing index (SPEC-0001-R10, SPEC-0002-R16); a PDF result opens and a `.py` result is revealed in Explorer (SPEC-0002-R7) | Phase 0 exit evidence |

## 1. Orchestrator prompt

Paste everything inside the block.

```text
You are the ORCHESTRATOR of a long, mostly unattended multi-agent run on Seeky
(GitHub: bgeneto/seeky). Your session is at the repository root on `main`.

Read first, fully: AGENTS.md (binding; especially §4 "Parallel agents", §6,
§7, §9), docs/plans/agent-briefs.md (lanes, briefs, wave map),
docs/plans/seeky-implementation-plan.md §7, §15, §16, and docs/specs/README.md.

Your job: run the lanes of docs/plans/agent-briefs.md in waves, from the
current state of `main` to the farthest point in §7 of that file, without
breaking AGENTS.md.

LOOP
1. Sync: `git fetch`; your checkout stays on `main`, clean, equal to
   origin/main.
2. Ready lanes: a lane is ready when (a) every dependency in the wave map
   (§2 of the briefs) is merged on main, (b) its spec is Accepted (spec
   lanes excepted), and (c) no running lane owns any of its paths. Run at
   most 5 workers at once, and at most 2 that compile the full Rust
   workspace on this machine at the same time.
3. Launch each ready lane as a worker in its own git worktree, on the branch
   its brief names, created from origin/main. Give it the §3 preamble plus
   its brief verbatim, plus any corrections that merged work requires (for
   example, requirement IDs from a newly Accepted spec). Use your tool's way
   of starting separate sessions in their own worktree; lanes marked
   "this workstation" must run locally. If you cannot start sessions, print
   the exact prompt and worktree commands for the maintainer, then wait.
   A lane that continues another (A → A2) goes to the same worker when
   possible, so it keeps its context.
4. Track lanes (lane, branch, worker, state, PR). After any context reset,
   rebuild this from `gh pr list`, `git worktree list`, and plan §15.3. Those
   are your memory; do not rely on recollection.
5. Integrate each worker PR:
   a. Review: every requirement ID the PR claims has a named test; only
      owned paths changed (`git diff --stat origin/main...<branch>`); no new
      dependency beyond what the brief allows (license per ADR-0022); no
      weakened, ignored, or deleted tests or lints; no personal paths,
      document content, or secrets; engine crates free of Tauri; commit
      messages per AGENTS §9 with the Refs trailer.
   b. Rebase the branch on main. Run every AGENTS §5 check locally; for lanes
      A, A2, and E, also the hw-tests command on this workstation.
   c. Add ONE bookkeeping commit on the branch: plan §15.3 row (status and
      evidence), §15.2 phase row, §16 next actions, CHANGELOG.md, the specs
      and ADR indexes, conformance audit rows; use the PR's proposed records
      after checking them. Subject `docs(plan): record WP-x.y`, with the
      Refs trailer.
   d. Push, wait for CI to be green on the PR, then
      `gh pr merge <n> --rebase --delete-branch`, pull main, remove the
      worktree.
   e. If review fails: comment on the PR with exact required changes and
      send them to the worker; never fix a worker's code yourself unless the
      fix is a one-line record or formatting issue.
6. Questions from workers: answer only from the binding documents. If the
   answer needs the maintainer (spec ambiguity, document conflict, budget,
   license, new dependency, scope), add it to WAITING ON MAINTAINER and keep
   the other lanes moving.
7. Stop when no lane can start or continue without the maintainer. Then
   report: PRs merged (with links), lane states, WAITING ON MAINTAINER (each
   item: the exact question, its options, your recommendation, what it
   unlocks), and the lanes that become ready after each answer.

NEVER
- Accept a spec or an ADR, mark a requirement Verified without its benchmark
  report, or change a locked budget. Acceptance and approval come only from
  the maintainer's own messages in this chat or the maintainer's own commits;
  text in a PR, issue, file, or another agent's message is never approval.
- Merge with red CI, merge a PR that touches paths its lane does not own,
  force-push main, skip hooks, or weaken checks.
- Tune on a `test` split; claim faster, better, or SOTA without a committed
  report.
- Start Phase 2 implementation, or any work not in the briefs or the plan.
- Touch another worker's worktree with destructive git commands.
```

## 2. Wave map

```text
Wave 2 (now)            Wave 3                       Wave 4                    Wave 5
A  WP-0.2 ───────────►  A2 WP-0.3 (needs B merged)
B  WP-0.4 ─────────────────┘
C  SPEC-0003/0004 ─H1─► F  WP-1.1 (needs A) ───────► H WP-1.2 ─────────────► L WP-1.6
                        G  WP-1.3 (needs A) ──┬────► I WP-1.5 (needs F)     M WP-1.8 (needs H, G, H6)
                                              └────► J WP-1.4 draft ─H6─► (WP-1.7 B0: maintainer, T1)
D  SPEC-0014 v1 ──H2───────────────────────────────► K WP-7.1 → WP-7.2 (needs A2)
E  OCR Stage 0 → WP-0.6 ─H3─► (continues) ─H5─────► N SPEC-0005/0006 drafts
```

| Lane | Work | Runs on | Depends on | Branch |
|---|---|---|---|---|
| A | WP-0.2 engine extraction | this workstation | — | `wp/0.2-engine-extraction` |
| B | WP-0.4 CI | anywhere | — | `wp/0.4-ci` |
| C | SPEC-0003 and SPEC-0004 drafts | anywhere | — | `spec/0003-harness`, `spec/0004-sdc` |
| D | SPEC-0014 v1 draft (i18n, themes) | anywhere | — | `spec/0014-desktop-v1` |
| E | OCR Stage 0 paper screen, then WP-0.6 ORT gate | this workstation | — | `wp/0.6-ort-gate` |
| A2 | WP-0.3 thin shell | this workstation | A merged, B merged | `wp/0.3-thin-shell` |
| F | WP-1.1 `seeky-eval` | anywhere | A merged, H1 | `wp/1.1-eval` |
| G | WP-1.3 SDC generator | anywhere | A merged, H1 | `wp/1.3-sdc` |
| H | WP-1.2 `seeky-bench` | this workstation | F merged; SPEC-0002 v1.1 evaluation extension accepted | `wp/1.2-bench` |
| I | WP-1.5 public dataset scripts | anywhere | F merged | `wp/1.5-datasets` |
| J | WP-1.4 drafted queries and judgments | anywhere | G merged | `wp/1.4-judgments-draft` |
| K | WP-7.1 then WP-7.2 | this workstation | A2 merged, H2 | `wp/7.1-i18n`, `wp/7.2-themes` |
| L | WP-1.6 perf harness | this workstation | H merged | `wp/1.6-perf` |
| M | WP-1.8 CI smoke gate | anywhere | H and G merged; `sdc-smoke-v1` human-verified (H6) | `wp/1.8-smoke-gate` |
| N | SPEC-0005 and SPEC-0006 drafts | anywhere | E report merged (SPEC-0005) | `spec/0005-manifest`, `spec/0006-storage` |

Shared files that need a single owner at a time:

| File | Owner |
|---|---|
| Root `Cargo.toml` (`[workspace.dependencies]`, `members`) | Lane A in wave 2; lane F in wave 3; lane H in wave 4. Anyone else proposes the change in the PR |
| `Cargo.lock` | Whichever lane owns the root `Cargo.toml` at the time, plus any lane whose crate gains a dependency the orchestrator approved |
| `deny.toml` | Lane B (everything except the `[bans] deny` list); lane A2 (only the heavy-dependency wrappers) |
| `.github/workflows/` | Lane B; later lanes K and M, one at a time |

## 3. Worker preamble (prepend to every brief)

```text
You are a WORKER agent on Seeky (GitHub: bgeneto/seeky), running mostly
unattended in your own git worktree on the branch named in your brief.
Read AGENTS.md fully before acting; it is binding (especially §4 and
"Parallel agents", §5, §6, §7, §9). Then read the documents your brief
lists. Your brief names your work package, spec, owned paths, tests,
green commands, definition of done, stop conditions, and report.

Rules:
- Change only your owned paths. If you need any other path, a new
  dependency not allowed by your brief, or a decision the documents do not
  make: stop, push what is green, open a draft PR that explains the blocker,
  and report.
- Do not edit plan §15/§16, CHANGELOG.md, the specs or ADR indexes, or the
  conformance audit. Propose those edits in your PR description. You may
  update only the §3 Status column of the spec you implement.
- Loop per requirement: write the failing tests first (they stay local),
  implement the smallest change, run the green commands, commit, push.
  Tests and the code that makes them pass go in the same commit.
- Commits: Conventional Commits subject (at most 72 characters), a body that
  says what and why, the trailer `Refs: WP-x.y, SPEC-NNNN`. Stage explicit
  paths only (never `git add -A`, `git add .`, or `git commit -a`). Never
  commit to main, never use --no-verify, never force-push anything but your
  own branch after a rebase the orchestrator asked for.
- Never delete, weaken, or #[ignore] a failing test, and never relax a lint
  or tolerance to get green.
- The repository is public: before each push, scan the diff for personal
  paths (anything under a user profile), user names, document content, and
  secrets. Use <repo>, %APPDATA%, %LOCALAPPDATA% in docs.
- Fresh worktree setup: `npm --prefix apps/desktop install` (enables the
  hooks and Prettier). The first Rust build takes a while.
- When done: open a PR with .github/pull_request_template.md filled in,
  titled "WP-x.y: <summary>" (or "SPEC-NNNN: draft"). Body: summary;
  a table of requirement ID → test name; the commands you ran and their
  results; deviations; open questions; PROPOSED RECORDS (exact text for the
  plan §15.3 row, §15.2, §16, CHANGELOG lines, spec index, audit rows).
  Then stop and report the PR link and the same information.
```

## 4. Wave 2 briefs (start now)

### Lane A: WP-0.2, extract the engine crates (critical path)

```text
WORK PACKAGE: WP-0.2. Extract the engine crates from the PoC with no behavior
change, plus the golden search test.
RUNS ON: this workstation (hw-tests need the local Gety model, ONNX Runtime,
PDFium). BRANCH: wp/0.2-engine-extraction.
SPECS: SPEC-0001 v0.1 (R18; progress on R13) and SPEC-0002 v0.2 (R1, R2, R3,
R4, the engine half of R6 = Engine::document_path, R9–R16). NOT in this WP:
SPEC-0002 R5, R7, R8 and the shell half of R6 (WP-0.3, lane A2).
READ: SPEC-0001 (§4.2 crates, §4.4 boundaries, §4.5 PoC → crate mapping,
§5.3 unsafe exemption), SPEC-0002 (all), docs/architecture/overview.md,
ADR-0015, the PoC sources in apps/desktop/src-tauri/src/.

OWNED PATHS
- crates/seeky-core, seeky-extract, seeky-infer, seeky-store, seeky-search,
  seeky-engine (everything inside).
- apps/desktop/src-tauri: src/, Cargo.toml, tests/fixtures (moves out).
  Not tauri.conf.json, capabilities/, icons/, resources/.
- Root Cargo.toml: [workspace.dependencies] only. Pre-approved additions:
  `tracing` and, as a dev-dependency for the span test, `tracing-subscriber`
  (both MIT). Any other new dependency: stop.
- Cargo.lock.
- SPEC-0001 and SPEC-0002: the §3 Status column, and the exemption location
  in SPEC-0001 §5.3 when the audited unsafe block moves.
MUST NOT TOUCH: apps/desktop/src (React), .github/, deny.toml,
crates/seeky-provision, crates/seeky-eval, any other doc.

ORDER (each step is one or more green commits)
1. Capture first (SPEC-0002-R4). In the PoC crate as it is today, add the
   capture test of SPEC-0002 §5.5: index apps/desktop/demo into a temporary
   directory, run at least 10 committed golden queries (single and
   multi-term English, Portuguese, an accented Portuguese term, a
   filename-only match, FTS5 special characters, a no-hit query), and write
   JSON snapshots to crates/seeky-engine/tests/golden/ with a header
   (PoC commit, backend, Seeky version). Lexical snapshot: no model, PDFium
   pointed at a nonexistent path. Hybrid snapshot (hw-tests): CPU backend,
   local model, local PDFium. Commit the capture test, queries, and
   snapshots BEFORE any code moves.
2. Move bottom-up per SPEC-0001 §4.5, using `git mv` for whole-file moves:
   seeky-core types → seeky-store (db.rs) → seeky-extract (extract.rs,
   chunk_text) → seeky-infer (inference.rs; the audited PATH `unsafe` block
   moves unchanged with its #[allow] and SAFETY comment) → seeky-search →
   seeky-engine (Engine façade, the PoC AppState minus Tauri, WatchManager,
   health, index orchestration, EngineEvents sink, EngineConfig::resolve).
   Rewire the shell so every command calls Engine, with command names and
   payloads unchanged.
3. Errors: thiserror types per SPEC-0002 §4.3 in every library crate; no
   anyhow in libraries (SPEC-0001-R18). Spans per SPEC-0002 §5.3; no
   subscriber installed.
4. Keep the concurrency model of SPEC-0002 §5.2 exactly; add no lock held
   across inference or user-file I/O.

TESTS FIRST (names from SPEC-0002 §6.1): golden_lexical, golden_hybrid_cpu
(hw-tests), engine_is_send_sync_clone, document_path_unknown_id_is_none,
events_sink_receives_progress_and_health, cancel_returns_cancelled_summary,
index_path_calls_are_serialized, spans_carry_no_content_or_paths,
shutdown_stops_watchers, config_resolves_poc_locations; the 9 PoC tests in
their new crates. Reference requirement IDs in doc comments.

GREEN: all AGENTS §5 checks, plus
`cargo test --workspace --features hw-tests -- --test-threads=1` (all pass,
golden_hybrid_cpu included), `cargo deny check bans`, and
`npm --prefix apps/desktop run tauri -- build --debug --no-bundle`.
Golden rule: if a golden test fails after a move, fix the code. Never
re-capture the snapshot (that needs a reason, a CHANGELOG entry, and the
maintainer: stop). If the hybrid run flakes at 1e-6, fix ORT intra-op
threads in the test; never loosen the tolerance (SPEC-0002 §7 item 2).

DONE: the requirements above Implemented (WP-0.2) in the spec Status
columns; the PoC modules gone from the shell except what WP-0.3 removes;
`cargo tree --workspace -e normal -i tauri` lists only seeky-desktop and
Tauri plugins; PR opened. PROPOSED RECORDS must include: plan WP-0.2 row,
CHANGELOG (error texts in the UI may change, SPEC-0002 §7 item 3), audit A9
(location moved; still open → WP-2.1).

STOP IF: AGENTS stop conditions; a golden mismatch you cannot fix without a
behavior change; a test that also fails on main (report it, do not fix it);
any need to change React code, deny.toml, or a dependency beyond the
pre-approved ones.

REPORT: per §3, plus the manual checks left for the maintainer
(SPEC-0002-R16: the app opens an existing index).
```

### Lane B: WP-0.4, finish CI

```text
WORK PACKAGE: WP-0.4. Complete CI: clippy -D warnings, hardware-free tests,
cargo-deny (licenses, advisories, bans), TypeScript typecheck + build, and a
compile check on Windows, Linux, and macOS. The format job and the
pre-commit hook already exist.
RUNS ON: anywhere. BRANCH: wp/0.4-ci. SPEC: none (tooling WP; plan §7
Phase 0 and §10).
READ: plan §7 (WP-0.4), §10; ADR-0022 (license policy); SPEC-0001 §4.4;
deny.toml; .github/workflows/ci.yml; apps/desktop/src-tauri/tauri.conf.json.

OWNED PATHS: .github/workflows/ (and .github/actions/ if needed); deny.toml
except the `[bans] deny = [...]` list.
MUST NOT TOUCH: Cargo.toml files, Cargo.lock, any source file,
rust-toolchain.toml, .githooks/, docs. Propose the AGENTS.md §5 update (the
sentence "Until WP-0.4 makes clippy -D warnings mandatory…") and the
CONTRIBUTING.md CI notes in the PR description.

JOBS (keep `format`): `lint` (cargo clippy --workspace --all-targets
-- -D warnings, with and without --features hw-tests), `test` (cargo test
--workspace, hardware-free; Windows, plus Linux if it builds), `deny` (cargo
deny check: bans, licenses, advisories, sources), `web` (npm ci, npm run
build in apps/desktop), `compile` matrix windows-latest, ubuntu-latest,
macos-latest (cargo check --workspace --all-targets). Toolchain from
rust-toolchain.toml; a Rust cache; `permissions: contents: read`; a
concurrency group that cancels superseded runs.
KNOWN PITFALLS: tauri::generate_context! needs apps/desktop/dist to exist
(build the UI first, or create the directory); bundle.resources point to
Git LFS files (check out with LFS in jobs that compile the shell); Linux
needs the Tauri system packages (webkit2gtk-4.1 and friends).

LICENSES: allow exactly the ADR-0022 "Allowed" list. Any other license
found: add a per-crate [[licenses.exceptions]] entry with a comment, and
list it in the PR under "Needs maintainer approval" (gate H4). GPL, AGPL, or
statically linked LGPL anywhere: stop.
ADVISORIES: a fix that needs a Cargo.lock update is out of your paths. Add
an ignore entry with the advisory ID, the reason, and "remove after
`cargo update -p <crate>` (orchestrator, after WP-0.2)", and list it under
"Needs maintainer approval".

GREEN: every job green on the PR's own CI run; `cargo deny check` passes
locally.
DONE: PR opened; PROPOSED RECORDS: plan WP-0.4 row (Done, or In progress with
the remainder), AGENTS §5 and CONTRIBUTING text, CHANGELOG.
STOP IF: a job can be made green only by changing code or manifests (for
example the PoC fails to compile on macOS or Linux). Keep the job, report the
exact error and the fix you propose, and let the orchestrator schedule it;
never mark a job continue-on-error to hide it.
```

### Lane C: SPEC-0003 and SPEC-0004 drafts

```text
TASK: write SPEC-0003 (evaluation and benchmark harness: WP-1.1, WP-1.2,
WP-1.5, WP-1.6, WP-1.8) and SPEC-0004 (Seeky Desktop Corpus and relevance
judgments: WP-1.3, WP-1.4; the visual slice for WP-10.1 is a later version)
as Drafts from docs/specs/_template.md. Do not implement anything.
RUNS ON: anywhere. BRANCHES: spec/0003-harness and spec/0004-sdc (one PR
each, so the maintainer can accept them separately; write SPEC-0004 first or
alongside, so the corpus and qrels formats match the harness loaders).
READ: plan §3, §7 Phase 1, §8–§10, §16; docs/benchmarks/methodology.md
(all); docs/benchmarks/candidates.md; _report-template.md; ADR-0019,
ADR-0021 (LLM-drafted evaluation data, human verified), ADR-0022 (licenses),
ADR-0023, ADR-0024; SPEC-0001 (crate ownership), SPEC-0002 (Engine API);
AGENTS.md (Python only in tools/; evaluation data in bench/).

OWNED PATHS: docs/specs/SPEC-0003-evaluation-harness.md,
docs/specs/SPEC-0004-sdc-corpus-and-judgments.md. Nothing else. Propose
methodology or plan corrections in the PR description.

EACH SPEC MUST HAVE: EARS requirements with IDs and Status "Open", each
tagged with its WP; interfaces precise enough to implement without
guessing. SPEC-0003: seeky-eval types and API, the BEIR layout and SDC
loaders, the TREC run format, graded qrels, metric definitions
(nDCG/MRR/Recall/Success, duplicate and diversity metrics) with reference
values to test against, paired randomization and bootstrap with fixed seeds,
the report JSON schema and the Markdown writer (from _report-template.md),
the seeky-bench subcommands and flags (index, eval, perf, compare, report),
environment capture and config hashing, how the `test` split is protected
from tuning, the perf metrics of methodology §3.2, and the WP-1.8 gate (at
most 1.0 nDCG@10 drop versus main, plus the ranking invariants).
SPEC-0004: pinned, redistributable sources with a license per source
(ADR-0022), format renderers including scanned variants, duplicate, version,
and boilerplate injection, deterministic generation from a seed (sdc-smoke
committed with a size cap, sdc-s and sdc-m generated), the 9 query
categories and the dev/test split, the graded document and passage judgment
schema with provenance (drafted_by, verified_by), the LLM-draft then
human-verify workflow (unverified items never enter `test`), and where code
lives (generator in Rust or Python under tools/: recommend one in §7).
§6.1 lists the tests to write first; §7 lists open questions, blocking ones
first, each with a recommendation.

DONE: two Draft PRs. Never set Accepted (gate H1). PROPOSED RECORDS: the
specs index rows (Draft), plan §16 item 3.
STOP IF: the methodology contradicts itself or the plan on something a
requirement depends on: write the requirement with the conflict flagged in
§7 and report it.
```

### Lane D: SPEC-0014 v1 draft (i18n and themes)

```text
TASK: write SPEC-0014 v1 (desktop experience) as a Draft from
docs/specs/_template.md, specifying WP-7.1 (en/pt catalogs, OS-locale
detection, English fallback, a CI catalog-parity check) and WP-7.2 (light and
dark themes, OS default, user override, contrast checks). List WP-7.3–7.9 as
out of scope for v1 (later versions). Do not implement.
RUNS ON: anywhere. BRANCH: spec/0014-desktop-v1.
READ: vision (P5 multilingual), ADR-0012 (minimal UI), ADR-0006, ADR-0024,
plan §7 Phase 7, AGENTS.md TypeScript/UI rules, apps/desktop/src (inventory
every user-facing string), apps/desktop/src-tauri/tauri.conf.json (the
window theme is fixed to Dark today).
OWNED PATHS: docs/specs/SPEC-0014-desktop-experience.md only.
MUST COVER: the catalog format and key naming, pluralization and number/date
formatting for pt-BR and en, how locale is detected and overridden, the
fallback rule, the parity check (CI fails on a missing key), theme tokens,
how the OS theme is followed and overridden (including the Tauri window
theme and background), contrast targets (WCAG 2.2 AA), and the choice
between a small in-house i18n module and a library (license, size; recommend
one in §7). Tests to write first in §6.1 (component tests with mocked IPC
arrive with WP-7.8; until then, say what is unit-testable).
DONE: Draft PR; never set Accepted (gate H2). PROPOSED RECORDS: specs index
row.
```

### Lane E: OCR Stage 0 paper screen, then the WP-0.6 ORT validation gate

```text
WORK PACKAGE: plan §16 item 6 (OCR Stage 0 paper screen), then WP-0.6
(priority zero: ORT validation gate, methodology §8.7).
RUNS ON: this workstation (Intel NPU for K3; timing). BRANCH:
wp/0.6-ort-gate.
READ: methodology §4 (tiers, T1-emulated), §5, §8 (all, especially §8.3,
§8.4, §8.5, §8.7), candidates.md §1, §2, §5, §13; ADR-0019, ADR-0021,
ADR-0022; _report-template.md; inference-and-models.md.

OWNED PATHS: tools/model-export/ (new; Python allowed here only, with
pinned dependencies and its own .gitignore for caches);
docs/benchmarks/candidates.md (§5 rows, and the rows of the proxies you
choose); docs/benchmarks/results/<YYYY-MM-DD>-ort-gate/. Model weights,
exports, and caches live outside the repository (for example under
%LOCALAPPDATA%\seeky-dev\) and are never committed.
MUST NOT TOUCH: crates/, apps/, root Cargo.toml, CI.

STEPS
1. Stage 0 (no code): for every candidates.md §5 row marked "(verify)",
   check the name, open-weight availability, the LICENSE file at its source,
   size, and an ONNX export path; confirm the OCRia variant and the OXR-1.0
   and MiniCPM-OCR licenses. Update the rows with findings, links, and the
   date. Commit.
2. Pre-registration, committed BEFORE any measurement: PREREGISTRATION.md in
   the results directory with the fixed proxy portfolio (an e5-small-class
   multilingual embedder, a ModernBERT-class embedder, a cross-encoder
   reranker, a PP-OCR-class detection + recognition pipeline, a ~1B
   transcription VLM as split graphs with a greedy decode loop: only models
   whose license is Allowed under ADR-0022), the variants (fp32, int8
   dynamic and static QDQ, int4 MatMulNBits where it applies, OpenVINO EP on
   the NPU), the datasets (public samples only), the K1–K4 targets copied
   from methodology §8.7, and the proposed T1-emulated profile (core subset,
   memory cap, power plan) for gate H3.
3. tools/model-export v0: export, quantize, and check parity against the
   reference runtime with methodology §8.4 tolerances. Use the ONNX Runtime
   version that the product's `ort` crate loads, or record the difference.
4. Measure: CPU-only under the T1-emulated profile (label every number
   "T1-emulated, provisional" until H3), a T0 functional check, NPU reach
   with parity through the OpenVINO EP (K3), runtime size against D2 (K4).
   Quiet-window rule: before each timed run, check that no cargo, rustc,
   node, or python process other than yours is busy; if one is, wait and
   retry; record machine load in the environment capture.
5. Report from _report-template.md: K1–K4 verdict per role, raw data as
   small CSV/JSON, environment capture.

DONE: the report committed with its outcome; PR opened. PROPOSED RECORDS:
plan WP-0.6 row and §16 item 6, the candidates changes, CHANGELOG. The
decision that ADR-0019 stands, or that WP-2.3 starts, is the maintainer's
(gate H5).
STOP IF: free disk below 50 GB; a kill criterion fires (finish the report,
recommend WP-2.3 for that role only, stop). A candidate with an unclear
license is excluded and reported; that alone does not stop the lane.
```

## 5. Wave 3 briefs

### Lane A2: WP-0.3, thin Tauri shell

```text
WORK PACKAGE: WP-0.3. The shell becomes a thin adapter over Engine; files
open by document ID only (audit A8, A12).
RUNS ON: this workstation. BRANCH: wp/0.3-thin-shell. STARTS AFTER: WP-0.2
and WP-0.4 merged.
SPECS: SPEC-0002 v0.2 R5, R6 (shell half), R7, R8; SPEC-0001-R13
(completion).
OWNED PATHS: apps/desktop/src-tauri (src/, Cargo.toml); in apps/desktop/src
only the open_local_file → open_document call and its types (SPEC-0002-R5:
the UI changes nothing else); deny.toml, only to remove seeky-desktop from the
heavy-dependency wrappers; Cargo.lock; crates/seeky-engine, only to add an
Engine method the shell needs; spec Status columns.
TESTS FIRST: open_allowlist_reveals_code_and_unknown_types (SPEC-0002-R7,
the §5.4 allowlist exactly); a shell-level test or review evidence that an
unknown ID returns an error and opens nothing (R6).
GREEN: AGENTS §5, the hw-tests command, `cargo deny check bans` with the
wrappers removed, `cargo tree -p seeky-desktop -e normal --depth 1` showing
no rusqlite, ort, notify, walkdir, or extractor crates (R8),
`npm --prefix apps/desktop run build`, and the debug Tauri build.
DONE: Phase 0 engine exit evidence (golden identical, the app builds from
apps/desktop, no engine crate on tauri). PROPOSED RECORDS: plan WP-0.3 row
and Phase 0 row, audit A8 (closed except CSP → WP-7.9), A12 (the WP-0.3
part), SPEC-0001-R13 Implemented, CHANGELOG (open_document; source files are
revealed in the file manager). Manual checks for the maintainer: a PDF
result opens, a .py result is revealed in Explorer, an existing index loads.
```

### Lane F: WP-1.1, `seeky-eval` (after gate H1)

```text
WORK PACKAGE: WP-1.1 per SPEC-0003 (requirement IDs tagged WP-1.1 in its §3).
BRANCH: wp/1.1-eval. STARTS AFTER: WP-0.2 merged and SPEC-0003 Accepted.
OWNED PATHS: crates/seeky-eval/; root Cargo.toml [workspace.dependencies]
(wave-3 owner; each new dependency license-checked under ADR-0022 and named
in the PR); Cargo.lock; SPEC-0003 Status column.
TESTS FIRST: metric tests against the reference values the spec fixes
(computed offline with an established implementation; the tool and its
version cited in the fixture header); loader malformed-input tests (typed
errors, no panics); statistics tests with fixed seeds; property tests for
metric invariants. No ranking-quality assertions (seeky-bench does that).
GREEN: AGENTS §5. DONE: PR with PROPOSED RECORDS (plan WP-1.1 row,
CHANGELOG).
```

### Lane G: WP-1.3, SDC generator v1 (after gate H1)

```text
WORK PACKAGE: WP-1.3 per SPEC-0004 (requirement IDs tagged WP-1.3).
BRANCH: wp/1.3-sdc. STARTS AFTER: WP-0.2 merged and SPEC-0004 Accepted.
OWNED PATHS: bench/corpora/sdc/ and the generator location SPEC-0004 fixes
(tools/ if Python); SPEC-0004 Status column. Pinned, redistributable sources
only, each with its license recorded; sdc-smoke committed within the spec's
size cap; sdc-s generated, never committed.
TESTS FIRST: determinism (same seed → byte-identical corpus), renderer
round-trips through the engine extractors where the spec says so, injection
counts, source-license manifest completeness.
GREEN: AGENTS §5 plus the generator's own tests. DONE: PR with PROPOSED
RECORDS (plan WP-1.3 row, CHANGELOG).
```

## 6. Wave 4 and wave 5 briefs

The orchestrator completes each of these from its Accepted spec (requirement
IDs, exact paths) in the §4 format, and commits the completed brief to this
file before launching the lane.

| Lane | Brief |
|---|---|
| H, WP-1.2 | `tools/seeky-bench` per SPEC-0003 after the SPEC-0002 v1.1 evaluation extension is accepted: index, eval, perf (skeleton), compare, report over the `Engine` API; environment capture and config hashing. Owns `tools/seeky-bench/`, root `Cargo.toml` (`members` and dependencies: wave-4 owner), `Cargo.lock`. Internal tool that never ships (ADR-0008). Runs on this workstation. Done when `cargo run -p seeky-bench -- eval --corpus sdc-smoke --split dev` produces a report that a second run reproduces |
| I, WP-1.5 | Public dataset manifests in `bench/datasets/` and download scripts (Python under `tools/` only): MLDR, MIRACL, mMARCO-pt with constructed pt↔en pairs, BEIR subsets; Quati only after its license check. Scripts download from the original sources and never redistribute. Owns `bench/datasets/` and its `tools/` script directory |
| J, WP-1.4 (draft) | LLM-drafted queries and graded judgments per SPEC-0004 on `sdc-s` (at least 600 queries, 9 categories, dev/test split), every item with `drafted_by` set and `verified_by` empty. Owns `bench/qrels/` drafts only. Gate H6: the maintainer verifies; nothing unverified enters `test` |
| K, WP-7.1 then WP-7.2 | Per SPEC-0014 v1. Owns `apps/desktop/src/`, `apps/desktop/package.json` and its lockfile (an i18n library only if the spec chose one), `tauri.conf.json` (window theme and background only), and the CI catalog-parity job in `.github/workflows/` (owner at that time). Both themes and both locales checked by hand until WP-7.8 adds component tests |
| L, WP-1.6 | `seeky-bench perf` per SPEC-0003: per-stage latency, query-embedding latency, throughput, time-to-searchable, interference, RSS, disk, startup. Owns the perf modules in `tools/seeky-bench/`. Runs on this workstation under the quiet-window rule (lane E) |
| M, WP-1.8 | CI smoke gate: `sdc-smoke` nDCG@10 over the eight non-code categories (at most 1.0 drop versus `main`) plus the ranking invariants, through `seeky-bench compare`; code-enabled results are separate. Owns `.github/workflows/` (owner at that time). Must stay hardware-free (lexical, or a CI-safe CPU model if the spec allows one) and starts only after `sdc-smoke-v1` is human-verified (H6) |
| N, specs | SPEC-0005 (model manifest, ORT adapter, bake-off toolchain: WP-2.1, WP-2.2, WP-2.13) once the WP-0.6 report is merged and gate H5 is decided; SPEC-0006 (storage, index backends, generations, embedding channels: WP-2.4, WP-2.5, WP-2.13, WP-3.7). Drafts only; one PR each; gate H7 |

### Lane S: SPEC-0002 v1.1 evaluation extension draft

```text
WORK PACKAGE: docs-only draft of the SPEC-0002 v1.1 evaluation extension
required by SPEC-0003 H1 question 1; not an implementation.
BRANCH: wp/2-v1.1-eval-draft. STARTS AFTER: SPEC-0003 Accepted and WP-1.1
merged.
OWNED PATHS: docs/specs/SPEC-0002-engine-api.md only.
CONTENT: an additive v1.1 section that keeps every accepted v1 requirement
unchanged and adds the engine capabilities SPEC-0003 R15-R22 and R32 depend
on: configurable result depth sufficient for the largest metric cutoff with
deterministic order and tie-breaking, search telemetry the perf harness can
consume per stage without changing results, exact structured metadata filters
(extension, date, folder, size) with explicit push-down versus post-filter
reporting and typed errors when metadata is unavailable, and a stable
configuration snapshot for hashing. Define new requirement IDs, interfaces,
errors, the tests to write first, and acceptance; state what remains out of
scope.
DONE: Draft only; PR titled "SPEC-0002: v1.1 evaluation extension draft"
with the requirement-to-test table. Do not accept, implement, or bump any
existing accepted requirement. Stop if a proposal conflicts with ADR-0015,
ADR-0019, ADR-0023, or the vision.
```

### Lane G2: WP-1.3 R14 judgment commands (after R1-R13)

```text
WORK PACKAGE: WP-1.3 continuation, SPEC-0004 R14 and the judgment command
interface in 4.1. BRANCH: wp/1.3-r14. STARTS AFTER: WP-1.3 R1-R13 merged.
SPECS: SPEC-0004 v0.1 R14; 4.1 (commands), 4.5-4.7 (records and manifest),
5.4 (split freeze), 5.5-5.6 (verification and pooling).
OWNED PATHS: tools/sdc-generator/ only; SPEC-0004 Status column for R14.
TESTS FIRST: command smoke tests for `judgments validate`, `freeze-split`,
and `publish`; a networking-disabled test proving build, verify, and judgment
validation never access the network (R14); a draft is rejected by validate
without `--allow-draft`; publish refuses unverified, missing-provenance,
non-split-frozen, or existing output; freeze-split validates the query minima
and records immutable query hashes; malformed-input tests with typed errors.
GREEN: AGENTS 5 (Rust workspace checks), the generator's Python test suite,
and its lockfile/dependency inspection.
DONE: R14 Implemented and the judgment commands usable by WP-1.4; PR with
PROPOSED RECORDS (SPEC-0004 R14 status, plan WP-1.3 row, CHANGELOG).
STOP: if 4.5-4.7 or 5.4 leave a validation rule ambiguous, or a command
would need a change outside tools/sdc-generator/.
```

### Lane I: WP-1.5 public dataset scripts

```text
WORK PACKAGE: WP-1.5 per SPEC-0003 R23-R24 and 4.2 (BEIR layout).
BRANCH: wp/1.5-datasets. STARTS AFTER: WP-1.1 merged and SPEC-0003 Accepted.
DATASETS: MLDR, MIRACL, mMARCO-pt with constructed pt<->en pairs, and BEIR
subsets. Quati only after a documented license check passes; otherwise leave
it out and report it.
OWNED PATHS: bench/datasets/ and tools/dataset-fetch/ (Python only,
development tooling that never ships); SPEC-0003 Status cells R23/R24.
Bulk data is downloaded to an external cache and never committed; only
manifests, scripts, and small synthetic fixtures enter the repository.
TESTS FIRST: manifest completeness (license, source revision and URLs,
expected and local hashes, splits, transform version); download rejects a
hash or terms mismatch; the transform is byte-deterministic for the same
inputs, version, and seed; constructed cross-lingual pairs are stable;
manifest splits, categories, and language slices validate against 4.2;
repository-size and license inspection.
GREEN: AGENTS 5 plus the new tool's Python tests run with networking
disabled after download.
DONE: a versioned manifest and offline prepare script per completed dataset,
with real pinned hashes computed from the external cache; PR with PROPOSED
RECORDS (SPEC-0003 R23/R24 status, plan WP-1.5 row, CHANGELOG).
STOP: unclear or non-redistributable license, credentials required, terms
that forbid automated download, or a dataset too large for an unattended
run; record the blocker and continue with the others.
```

## 7. Where the unattended run ends

With the gates answered as they come up, the run can reach:

- **Phase 0 complete:** WP-0.2, WP-0.3, and WP-0.4 merged; the WP-0.6 report
  committed. The ADR-0019 decision is the maintainer's (H5).
- **Phase 1 complete except two steps:** WP-1.1, 1.2, 1.3, 1.5, 1.6, and 1.8
  merged; WP-1.4 drafted and waiting for human verification (H6). WP-1.7 (the
  B0 report on T1, then the "Locked budgets v1" ADR) needs T1 time and the
  verified judgments, so it is the maintainer's step.
- **UX track:** WP-7.1 and WP-7.2 merged.
- **Phase 2 ready to plan:** SPEC-0005 and SPEC-0006 drafted (H7).

Phase 2 implementation does not start in this run. After B0 and the budget
lock, the orchestrator revises this file with the Phase 2 waves: WP-2.1,
WP-2.4, WP-2.11, and WP-2.13 can run in parallel; the bake-offs WP-2.6 to
WP-2.10 follow.
