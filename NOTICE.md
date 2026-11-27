# Notice and scope

Seeky source code is licensed under the **MIT License** (see [`LICENSE`](LICENSE)).
Seeky is an independent local search engine. Its design was informed by
clean-room reverse engineering of the installed Gety desktop application; the
research notes live in [`docs/research/gety/`](docs/research/gety/README.md).

This repository does **not** contain Gety source code, Gety binaries, private
keys, or Gety's encrypted OCR weights.

## Distribution model

The target product ships as a small installer. Inference runtimes, model
weights, tokenizers, and optional asset packs are downloaded from the public
`seeky` Cloudflare R2 bucket, verified, cached, and used offline afterward.
Filename and lexical search work before any download. No account, activation,
or license key is required.

The 0.1.0 PoC still reads model/runtime files from a local Gety installation
and bundles a temporary OpenVINO export; both are removed by the provisioning
phase of the [implementation plan](docs/plans/seeky-implementation-plan.md).

## What was inspected (research phase)

- Installed Gety binaries under `%LOCALAPPDATA%\Gety`.
- Public strings, PE metadata, SQLite schema and aggregate counts, runtime logs,
  WebView2 cache, and local model files.
- No document content was read; the SQLite database was inspected read-only for
  schema and aggregate counts.

## Licensing

- **Gety application:** proprietary. Do not redistribute its binaries.
- **`gety-embed-v0`:** MIT per the Hugging Face model card of
  `gety-ai/gety-embed-v0` (base model `intfloat/multilingual-e5-small`, MIT).
  Verified 2026-11-27: the LFS-tracked `model.bin` is byte-identical to the
  published `openvino/model.bin`. It is a benchmark baseline only.
- **`gety-ocr-v0`:** encrypted/private. Not used or redistributed by Seeky.
- **OpenVINO IR (PoC):** temporarily tracked with Git LFS under
  `apps/seeky/src-tauri/resources/models/`; removed when provisioning ships.
- **Models, runtimes, and libraries adopted by Seeky:** must pass the
  permissive-license gate ([ADR-0022](docs/adr/0022-permissive-license-gate.md));
  every provisioned asset carries its own license and notice files.
- **Evaluation datasets:** downloaded by scripts for internal benchmarking; data
  with research-only terms is never redistributed in this repository.
- **Screenshots:** `docs/assets/screenshots/gety/` are user-provided and may
  contain local file names; review before publishing.
  `docs/assets/screenshots/seeky/` are captured from the demo corpus.

## Clean-room guidance

The research describes interfaces, schemas, and algorithms. Implement them
independently. Do not copy Gety source, decompiled code, private model weights,
API keys, or user data. SQL under `docs/research/gety/sql/` reconstructs the
observed schema shape for documentation; it is not Gety source.

## Privacy

Documentation avoids personal document content and personal paths; local paths
are written as `%APPDATA%`, `%LOCALAPPDATA%`, `%USERPROFILE%`, or `<repo>`.
Seeky itself sends no document content anywhere and has no telemetry.
