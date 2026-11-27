# Seeky

**A Local Neural Information Retrieval Engine and Semantic Desktop Search Engine.**

Seeky is an open-source, local-first desktop application for semantic file
search. It indexes folders, ranks passages and documents with a multilingual
hybrid retrieval pipeline, and presents the best evidence without sending
document content to a cloud service.

![Seeky search results](docs/assets/screenshots/seeky/results.png)

## Product direction

Seeky is:

- **Open source** under the [MIT License](LICENSE).
- **Account-free** — no sign-up, activation, subscription, or commercial license
  key.
- **Slim** — the installer is small; runtimes, model weights, tokenizers, and
  native libraries are provisioned on first run from the **seeky** Cloudflare R2
  bucket, then cached for offline use.
- **Minimal** — search, results, preview, folders, and a small settings surface.
  No AI slop, dashboards, chat, or decorative metrics.
- **Bilingual UI from day one** — English and Portuguese, following the OS locale
  with English fallback.
- **Two themes only** — light and dark, following the OS by default.
- **Multilingual in retrieval** — user content may be in any language, regardless
  of UI language.
- **Hardware-aware** — CPU fallback, NVIDIA CUDA, AMD GPU, and Intel NPU paths
  selected and validated by benchmark.
- **SOTA-oriented** — model and ranking choices are benchmark-gated against a
  multilingual retrieval corpus.

The accepted decisions are recorded in
[`docs/product/seeky-product-decisions.md`](docs/product/seeky-product-decisions.md).

## Current status

Seeky 0.1 is a runnable PoC. The current validation build includes:

- Tauri **2.12.7**, Rust backend, React 19 + TypeScript + Vite frontend
- Local folder indexing with PDF, DOCX, XLSX, PPTX, HTML, text, and source-code extraction
- `gety-embed-v0` (384-d) via ONNX Runtime on CPU/CUDA and OpenVINO on Intel AI Boost
- BM25 + filename/path + dense retrieval fused with RRF
- Live filesystem watching with debounce, rename/delete handling, per-folder pause
- Incremental reindexing using size + nanosecond-mtime signatures
- Index health, progress, cancellation, and stale-document pruning
- SQLite + FTS5 persistence; no external vector service
- A dark, English-only PoC UI

The current PoC still uses a local Gety installation for model/runtime files and
ships a temporary bundled OpenVINO IR. The **target product** removes that
dependency and downloads all required assets on first run.

See [`docs/validation/seeky-poc-validation.md`](docs/validation/seeky-poc-validation.md)
for build commands and observed runtime evidence.

## Retrieval target

The target pipeline is hierarchical and multilingual:

1. Passage and document candidate generation with BM25, filename/path, and dense retrieval.
2. Multilingual cross-encoder passage ranking.
3. Document-level score aggregation.
4. Hierarchical document → passage retrieval.
5. Per-document candidate limits.
6. Near-duplicate detection and collapsing.
7. Cross-document diversity.
8. Length-bias correction and calibrated fusion.

See [`docs/architecture/retrieval-engine.md`](docs/architecture/retrieval-engine.md)
for the ranking contract and acceptance gates.

## Quick start (current PoC)

### Prerequisites

- Windows 10/11 x64 (current validated target)
- Node.js 20+ and npm
- Rust stable with the MSVC toolchain and Visual Studio Build Tools
- WebView2
- A local Gety installation for the current CPU/CUDA models, tokenizer, ONNX
  Runtime, PDFium, and OpenVINO runtime
- NVIDIA CUDA libraries for CUDA inference, or an Intel NPU driver for NPU inference

The target slim setup will remove the Gety prerequisite. Until then, the paths
above are required for local validation.

### Run from source

```powershell
cd apps\seeky
npm install
npm run tauri dev
```

Production-style build:

```powershell
npm run tauri -- build --no-bundle
# binary: src-tauri\target\release\seeky.exe
```

Keep `resources\` next to `seeky.exe` for the current PoC. The target product
will resolve downloaded assets from the app data directory instead.

### Smoke test

1. Add `apps\seeky\demo` as a folder.
2. Click **Index** once.
3. Search for `contract renewal notice`.
4. Edit, create, rename, or delete a file in that folder; the watcher updates the
   index after a short debounce.

## Repository layout

```text
.
├─ apps/
│  └─ seeky/                    Tauri + React + Rust application
│     ├─ demo/                  five-file smoke-test corpus
│     ├─ src/                   React/TypeScript UI
│     └─ src-tauri/             Rust backend, resources, tests
├─ docs/
│  ├─ plans/                    Active implementation plan
│  ├─ product/                  Product decisions and scope
│  ├─ architecture/             Retrieval, model, and provisioning design
│  ├─ research/                 Gety reverse-engineering research
│  ├─ audits/                   Verification reports and evidence ledger
│  ├─ decisions/                Seeky architecture decision records
│  ├─ validation/               Build and runtime evidence
│  ├─ assets/screenshots/       Seeky and Gety UI captures
│  └─ archive/                  Superseded historical planning documents
├─ models/                      Machine-local model path reference
├─ sql/                         Schema references
├─ LICENSE                      MIT
├─ NOTICE.md                    Third-party, clean-room, and privacy notes
└─ README.md
```

## Documentation

- **Product decisions:** [`docs/product/seeky-product-decisions.md`](docs/product/seeky-product-decisions.md)
- **Product scope:** [`docs/product/seeky-scope.md`](docs/product/seeky-scope.md)
- **Active plan:** [`docs/plans/seeky-implementation-plan.md`](docs/plans/seeky-implementation-plan.md)
- **Retrieval architecture:** [`docs/architecture/retrieval-engine.md`](docs/architecture/retrieval-engine.md)
- **Model strategy:** [`docs/architecture/model-strategy.md`](docs/architecture/model-strategy.md)
- **Slim provisioning:** [`docs/architecture/distribution-and-provisioning.md`](docs/architecture/distribution-and-provisioning.md)
- **Architecture decisions:** [`docs/decisions/seeky-adrs.md`](docs/decisions/seeky-adrs.md)
- **Validation evidence:** [`docs/validation/seeky-poc-validation.md`](docs/validation/seeky-poc-validation.md)
- **Research:** [`docs/research/README.md`](docs/research/README.md)
- **Audits:** [`docs/audits/README.md`](docs/audits/README.md)
- **Archive:** [`docs/archive/README.md`](docs/archive/README.md)
- **Contributing:** [`CONTRIBUTING.md`](CONTRIBUTING.md)
- **Changelog:** [`CHANGELOG.md`](CHANGELOG.md)

## Non-goals

Seeky deliberately excludes cloud sync, accounts, multiuser support, external
connectors, MCP, a public REST API or CLI, AI-client integrations, generative
chat, plugin marketplaces, and theme customization. It is a precise local search
tool, not a RAG platform or agent backend.

Optional answer generation remains out of scope unless the product scope is
explicitly changed.

## Verified baseline

- 8/8 Rust tests pass (CPU/CUDA/NPU embeddings, extraction, incremental indexing,
  watcher event mapping).
- Release binary: 11.5 MB; current temporary OpenVINO IR: 118.6 MB `model.bin`.
- Final recorded NPU UI search: `5 results · 26 ms`.
- Portable `exe + resources` copy resolves the bundled OpenVINO IR and searches
  successfully.

## License

Seeky source code is [MIT-licensed](LICENSE). Third-party libraries, runtimes, and
model weights retain their own licenses. See [`NOTICE.md`](NOTICE.md).

No account or license key is required to use Seeky. The MIT license is a
software license, not an activation requirement.

The current PoC reads Gety's installed model files locally and does not
redistribute Gety binaries. The temporary OpenVINO IR is tracked with Git LFS and
will be replaced by first-run R2 provisioning in the slim distribution.
