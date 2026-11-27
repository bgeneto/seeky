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
3. Write tests first; reference requirement IDs.
4. Attach a benchmark report when quality or performance can change
   ([methodology](docs/benchmarks/methodology.md)).
5. Record decisions as ADRs in [`docs/adr/`](docs/adr/README.md).

Bug fixes, behavior-preserving refactors, docs, and tooling do not need a spec.

## Setup (PoC)

Install Node.js 20+, Rust stable with the MSVC toolchain, Visual Studio Build
Tools, WebView2, and Git LFS. The PoC also needs a local Gety installation for
model/runtime files until the provisioning phase lands.

```powershell
git lfs install
cd apps\seeky
npm install
npm run tauri dev
```

## Checks

```powershell
cd apps\seeky
npm run build
npm run format:check   # Prettier; `npm run format` fixes

cd src-tauri
cargo fmt --check      # rustfmt; `cargo fmt` fixes
cargo clippy --all-targets -- -D warnings
cargo test --lib
cargo check
```

`npm install` enables a pre-commit hook (`.githooks/pre-commit`) that checks
rustfmt and Prettier formatting without rewriting files; CI runs the same
checks on every pull request. Formatting rules live in `rustfmt.toml` and
`apps/seeky/.prettierrc.json`. Because `core.hooksPath` replaces
`.git/hooks`, `.githooks/` also carries the standard Git LFS hooks
(`pre-push`, `post-checkout`, `post-commit`, `post-merge`); without them
pushes would skip uploading LFS objects.

`cargo test --lib` is hardware-free. Tests that need local models, PDFium, CUDA,
or an NPU run with `cargo test --lib --features hw-tests -- --test-threads=1`
on a machine that has them. The workspace-level commands that replace these
after Phase 0 are listed in [`AGENTS.md`](AGENTS.md#5-commands).

## Commit style

Conventional, imperative subjects with a scope:

```text
feat(indexer): add durable job queue
perf(search): binary first-pass vector scan
bench(rerank): bake-off report for multilingual cross-encoders
docs(adr): 0023 lock budgets v1
```

## Licensing

Seeky is MIT-licensed; contributions are accepted under the same license. Any
new dependency, model, runtime, or dataset must pass the license gate
([ADR-0022](docs/adr/0022-permissive-license-gate.md)).

## Screenshots and privacy

Keep Seeky captures under `docs/assets/screenshots/seeky/`. Never commit
document content, personal paths, or private corpora; redact paths in Gety
captures under `docs/assets/screenshots/gety/`.
