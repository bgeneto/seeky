# Notice and scope

Seeky source code is licensed under the **MIT License** (see [`LICENSE`](LICENSE)).
Seeky is an independent local search implementation informed by reverse
engineering of the installed Gety application. The repository contains research
notes, a clean-room Rust/Tauri implementation, UI captures, and a temporary
OpenVINO export used during PoC validation.

It does **not** contain Gety source code, Gety binaries, private keys, or Gety's
encrypted OCR weights.

## Distribution model

The target product ships as a slim application. Runtimes, model weights, and
native libraries are downloaded on first run from the public seeky Cloudflare R2
bucket, verified, cached, and used offline afterward. No account, activation, or
commercial license key is required.

The current PoC still uses a local Gety installation and a temporary bundled
OpenVINO IR. Those are transitional and are removed by the slim-setup milestone.

## What was inspected

- Installed Gety binaries under `C:\Users\bernh\AppData\Local\Gety`.
- Public strings, PE metadata, SQLite schema/counts, runtime logs, WebView2
  cache, and local model files.
- No document content was read; the SQLite database was inspected read-only for
  schema and aggregate counts.

## Licensing

- **Gety application:** proprietary. Do not redistribute its binaries.
- **`gety-embed-v0`:** the Hugging Face model card declares MIT. Verify the
  license before redistributing model files.
- **`gety-ocr-v0`:** the installed payload is encrypted/private. It is not used
  or redistributed by Seeky.
- **Qwen3-Embedding-0.6B / Qwen3-Reranker-0.6B:** Apache-2.0 per their model
  cards; not bundled in this repository.
- **OpenVINO IR (current PoC):** temporarily tracked with Git LFS under
  `apps/seeky/src-tauri/resources/models/`. The target slim build downloads it
  from R2 and removes the bundled copy. Verify the model license before
  publishing or redistributing it.
- **Downloaded runtimes and models:** each R2 asset carries license/notice
  metadata. Third-party terms must be reviewed before publication.
- **Screenshots:** `docs/assets/screenshots/gety/` are user-provided and may
  contain local paths or file names. Review and redact before publishing.
  `docs/assets/screenshots/seeky/` are captured from the demo corpus.

## Clean-room guidance

The research describes interfaces, schemas, and algorithms. Implement them
independently. Do not copy Gety source, decompiled code, private model weights,
API keys, or user data. SQL under `sql/` reconstructs observed schema shape for
interoperability/documentation; it is not copied Gety source.

## Privacy

Documentation avoids personal document content and full user paths except where
the user supplied them in screenshots or a machine path is required to locate a
model. Redact paths before publishing this repository.
