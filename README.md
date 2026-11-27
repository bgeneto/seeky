# Seeky

**A high-performance, local-first semantic file search engine. No cloud, no chatbots, no agents. Just search.**

Seeky is a Tauri 2 desktop application that indexes local files, embeds their
chunks with `gety-embed-v0`, and retrieves with a hybrid of BM25, filename/path
matching, dense cosine similarity, and reciprocal rank fusion. Everything runs
locally on CPU, NVIDIA CUDA, or an Intel NPU.

![Seeky search results](docs/assets/screenshots/seeky/results.png)

## Status

Seeky 0.1 is a runnable proof of concept. The current baseline includes:

- Tauri **2.12.7**, Rust backend, React 19 + TypeScript + Vite frontend
- Local folder indexing with PDF, DOCX, XLSX, PPTX, HTML, text, and source-code extraction
- `gety-embed-v0` (384-d) via ONNX Runtime on CPU/CUDA and OpenVINO on Intel AI Boost
- BM25 + filename/path + dense retrieval fused with RRF
- Live filesystem watching with debounce, rename/delete handling, per-folder pause
- Incremental reindexing using size + nanosecond-mtime signatures
- Index health, progress, cancellation, and stale-document pruning
- SQLite + FTS5 persistence; no external vector service
- Offline operation with no telemetry, connectors, MCP server, REST API, or chat

See [`docs/validation/seeky-poc-validation.md`](docs/validation/seeky-poc-validation.md)
for build commands and observed runtime evidence.

## Quick start

### Prerequisites

- Windows 10/11 x64 (current validated target)
- Node.js 20+ and npm
- Rust stable with the MSVC toolchain and Visual Studio Build Tools
- WebView2
- A local Gety installation for the CPU/CUDA model files, tokenizer, ONNX
  Runtime, PDFium, and OpenVINO runtime
- NVIDIA CUDA libraries for CUDA inference, or an Intel NPU driver for NPU inference

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

Keep `resources\` next to `seeky.exe`. The release build copies the bundled NPU
IR to `src-tauri\target\release\resources\models\gety-embed-v0\openvino`.

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
│  ├─ product/                  Product scope and constraints
│  ├─ research/                 Gety reverse-engineering research
│  ├─ audits/                   Verification reports and evidence ledger
│  ├─ decisions/                Seeky architecture decision records
│  ├─ validation/               Build and runtime evidence
│  ├─ assets/screenshots/       Seeky and Gety UI captures
│  └─ archive/                  Superseded historical planning documents
├─ models/                      Machine-local Gety model path example
├─ sql/                         Gety schema reference and minimal schema
├─ NOTICE.md                    Licensing, clean-room, and privacy notes
└─ README.md
```

## Documentation

- **Active plan:** [`docs/plans/seeky-implementation-plan.md`](docs/plans/seeky-implementation-plan.md)
- **Product scope:** [`docs/product/seeky-scope.md`](docs/product/seeky-scope.md)
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
chat, and plugin marketplaces. The product is a fast local search tool, not a
RAG platform or agent backend.

Optional answer generation remains out of scope until retrieval quality,
evaluation, and packaging are complete.

## Verified baseline

- 8/8 Rust tests pass (CPU/CUDA/NPU embeddings, extraction, incremental indexing,
  watcher event mapping).
- Release binary: 11.5 MB; bundled OpenVINO IR: 118.6 MB `model.bin`.
- Final recorded NPU UI search: `5 results · 26 ms`.
- Portable `exe + resources` copy resolves the bundled OpenVINO IR and searches
  successfully.

## Licensing

Seeky reads Gety's installed model files locally and does not redistribute Gety
binaries. Model and screenshot licensing details are in [`NOTICE.md`](NOTICE.md).
The bundled OpenVINO IR is tracked with Git LFS; verify the model license before
publishing or redistributing it.
