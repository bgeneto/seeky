# Contributing

## Setup

Install Node.js 20+, Rust stable with the MSVC toolchain, Visual Studio Build
Tools, WebView2, Git LFS, and a local Gety installation for model/runtime files.

```powershell
git lfs install
cd apps\seeky
npm install
```

## Development

```powershell
cd apps\seeky
npm run tauri dev
```

## Checks

```powershell
cd apps\seeky
npm run build

cd src-tauri
cargo test --lib -- --test-threads=1
cargo check
```

Inference tests require the local Gety models and the appropriate hardware.
Frontend build and pure Rust tests must pass without optional hardware.

## Architecture rules

- Backend logic stays in Rust inside the Tauri process.
- Do not add a sidecar service, local HTTP API, or a second backend runtime.
- Keep the webview capability surface minimal; add explicit Rust commands for
  filesystem actions.
- Do not add accounts, activation, license-key checks, or telemetry.
- Do not add outbound network calls except the approved first-run/update asset
  fetch from the seeky R2 bucket.
- Keep CPU/CUDA/AMD/NPU embeddings compatible; a backend switch must not require
  reindexing for the same model.
- Do not bundle large model/runtime assets in the installer; provision and verify
  them through the asset pipeline.
- Keep UI strings in locale catalogs and support only the light/dark themes.
- Update `docs/plans/seeky-implementation-plan.md` when a milestone or contract
  changes.
- Add runtime evidence under `docs/validation/` or `docs/audits/`.
- Add retrieval evaluation evidence before changing ranking behavior.
- Update `CHANGELOG.md` for user-visible changes.

## License

Seeky is MIT-licensed. Contributions are accepted under the same license.
Third-party libraries and model weights keep their own licenses; do not add an
asset without recording its license and redistribution terms.

## Commit style

Use short imperative subjects, for example:

```text
feat(indexer): add watcher debounce and per-folder pause
fix(search): include filename matches in RRF
docs(plan): define reranker evaluation gate
```

## Screenshots

Keep current Seeky captures under `docs/assets/screenshots/seeky/`. Redact local
paths before adding Gety captures under `docs/assets/screenshots/gety/`.
