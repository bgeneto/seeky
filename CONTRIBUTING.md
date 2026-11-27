# Contributing

Thanks for helping build Seeky. Humans and AI agents follow the same rules,
described in full in [`AGENTS.md`](AGENTS.md). This page is the short version.

## Workflow

Seeky uses **Spec-Driven Development** plus **Benchmark-Driven Development
(BmDD)** ([ADR-0017](docs/adr/0017-spec-and-benchmark-driven-development.md)):

1. Pick a work package from the
   [implementation plan](docs/plans/seeky-implementation-plan.md).
2. Implement against an **Accepted** spec in [`docs/specs/`](docs/specs/README.md);
   write one first if it does not exist.
3. Write tests first; reference requirement IDs. A bug fix needs a regression
   test, a refactor keeps existing tests unchanged, and tests are hermetic and
   hardware-free by default (full rules: [`AGENTS.md`](AGENTS.md) §6 Tests).
4. Attach a benchmark report when quality or performance can change
   ([methodology](docs/benchmarks/methodology.md)).
5. Record decisions as ADRs in [`docs/adr/`](docs/adr/README.md).
6. Record progress in the same commit as the work: the work package's row in
   the plan's [§15.3](docs/plans/seeky-implementation-plan.md#153-work-packages),
   the spec's requirement status, and `CHANGELOG.md` (full checklist:
   [`AGENTS.md`](AGENTS.md#4-how-to-work-the-sdd--bmdd-loop) §4 step 8).

Bug fixes, behavior-preserving refactors, docs, and tooling do not need a spec
or a plan row, but still get a `CHANGELOG.md` entry when someone would notice.

## Setup (PoC)

Install Node.js 20+, Rust stable with the MSVC toolchain, Visual Studio Build
Tools, WebView2, and Git LFS. The PoC also needs a local Gety installation for
model/runtime files until the provisioning phase lands.

```powershell
git lfs install
cargo install cargo-deny --locked   # crate-boundary checks
cd apps\desktop
npm install
npm run tauri dev
```

## Checks

```powershell
# workspace root
cargo fmt --all --check   # rustfmt; `cargo fmt --all` fixes
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy --workspace --all-targets --features hw-tests -- -D warnings
cargo test --workspace
cargo deny check             # bans, licenses, advisories, sources

cd apps\desktop
npm run build
npm run format:check      # Prettier; `npm run format` fixes
```

`npm install` enables a pre-commit hook (`.githooks/pre-commit`) that checks
rustfmt and Prettier formatting without rewriting files; CI runs the same
checks on every pull request. Formatting rules live in `rustfmt.toml` and
`apps/desktop/.prettierrc.json`. Because `core.hooksPath` replaces
`.git/hooks`, `.githooks/` also carries the standard Git LFS hooks
(`pre-push`, `post-checkout`, `post-commit`, `post-merge`); without them
pushes would skip uploading LFS objects.

`cargo test --workspace` is hardware-free. Tests that need local models,
PDFium, CUDA, or an NPU run with
`cargo test --workspace --features hw-tests -- --test-threads=1` on a machine
that has them. The full command list is in [`AGENTS.md`](AGENTS.md#5-commands).

Every pull request also runs clippy with and without `hw-tests`, hardware-free
tests on Windows and Linux, all `cargo-deny` checks, the TypeScript build, and
`cargo check --workspace --all-targets` on Windows, Linux, and macOS. CI checks
out Git LFS assets when compiling the shell, creates `apps/desktop/dist` for
`tauri::generate_context!`, and installs Tauri's WebKitGTK dependencies on Linux.

## Commit style

Commit each logically complete step as soon as all checks pass, tests
together with the code they cover, and push; never leave finished work
uncommitted or commit a red tree. Stage explicit paths of your own changes,
never `git add -A`, and keep one logical change per commit (full rules:
[`AGENTS.md`](AGENTS.md) §9).

Conventional, imperative subjects with a scope (at most 72 characters), and
a body that explains what changed and why:

```text
feat(indexer): add durable job queue
perf(search): binary first-pass vector scan
bench(rerank): bake-off report for multilingual cross-encoders
docs(adr): 0023 lock budgets v1
```

Commits that belong to a work package or spec end with a trailer such as
`Refs: WP-0.2, SPEC-0001`, so `git log --grep "WP-0.2"` lists the whole
work package ([`AGENTS.md`](AGENTS.md) §9).

## Licensing

Seeky is MIT-licensed; contributions are accepted under the same license. Any
new dependency, model, runtime, or dataset must pass the license gate
([ADR-0022](docs/adr/0022-permissive-license-gate.md)).

## Screenshots and privacy

Keep Seeky captures under `docs/assets/screenshots/seeky/`. Never commit
document content, personal paths, or private corpora; redact paths in Gety
captures under `docs/assets/screenshots/gety/`.
