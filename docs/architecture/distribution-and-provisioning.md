# Distribution and First-Run Provisioning


Product decision: slim setup with first-run downloads from Cloudflare R2

## 1. Decision

Seeky ships as a small desktop application. Runtime libraries, model weights,
tokenizers, and native document libraries are downloaded on first run from the
public **seeky** Cloudflare R2 bucket, verified, and cached locally.

- No account, license key, or sign-in is required.
- No large model or runtime is embedded in the installer.
- After provisioning, the application works fully offline.
- Only public runtime/model assets are downloaded. Document content never leaves
  the machine.

The current PoC still reads model files from a local Gety installation and ships
a temporary bundled OpenVINO IR for validation. That is transitional and must be
removed from the shipped product once provisioning is implemented.

## 2. Bucket and endpoints

| Item | Value |
|---|---|
| Provider | Cloudflare R2 |
| Bucket | `seeky` (R2 bucket identifiers must be lowercase; product name: Seeky) |
| Access | Public read-only assets |
| User authentication | None |
| Client credentials | None embedded |
| Transport | HTTPS with integrity verification |

The exact public base URL is supplied through a build-time configuration and can
be overridden for development/testing:

```text
SEEKY_ASSET_BASE_URL
```

A production build should use a Cloudflare custom domain or the public R2
endpoint with immutable versioned keys. The application must not require R2
credentials to read public assets.

## 3. Object layout

```text
channels/
  stable/manifest.json
  beta/manifest.json

artifacts/
  win-x64/
    cpu/ort/<version>/...
    cuda/ort/<version>/...
    amd/directml/<version>/...
    npu/openvino/<version>/...
    pdfium/<version>/pdfium.dll
  linux-x64/...
  macos-arm64/...

models/
  embedding/<family>/<revision>/
    tokenizer.json
    model_uint8.onnx
    model_fp16.onnx
    openvino/model.xml
    openvino/model.bin
  reranker/<family>/<revision>/
    tokenizer.json
    model_uint8.onnx
    model_fp16.onnx

licenses/
  <asset-id>/LICENSE.txt
  <asset-id>/NOTICE.txt
```

Keys are immutable once published. A new revision gets a new path and a new
manifest entry; clients never overwrite a known-good artifact in place.

## 4. Manifest

The manifest is a small JSON document validated against a Rust serde schema.

Required fields:

- schema version;
- channel and release timestamp;
- minimum app version;
- target platform (`os`, `arch`);
- asset ID, kind, version, URL, byte size, SHA-256;
- execution backend (`cpu`, `cuda`, `directml`, `openvino-npu`);
- embedding dimension and tokenizer revision where applicable;
- license and attribution paths;
- compatibility notes and minimum driver/runtime versions;
- optional Ed25519 signature over the canonical manifest payload.

Example shape:

```json
{
  "schema": 1,
  "channel": "stable",
  "generated_at": "2026-11-26T00:00:00Z",
  "minimum_app_version": "0.2.0",
  "platform": { "os": "windows", "arch": "x86_64" },
  "assets": [
    {
      "id": "embedding-primary-cpu",
      "kind": "embedding-model",
      "version": "2026.11",
      "url": "models/embedding/example/2026.11/model_uint8.onnx",
      "size": 123456789,
      "sha256": "…",
      "backend": "cpu",
      "license": "licenses/embedding-example/LICENSE.txt"
    }
  ]
}
```

## 5. First-run flow

1. Show a single provisioning screen with progress and disk usage.
2. Detect OS, architecture, GPU vendor, NPU availability, RAM, and free disk.
3. Fetch the stable manifest with conditional caching and ETag support.
4. Select the smallest compatible asset set:
   - CPU is always provisioned as a fallback.
   - CUDA assets only when an NVIDIA runtime is detected.
   - DirectML assets for supported AMD/Intel GPUs.
   - OpenVINO/NPU assets only when an Intel NPU runtime is detected.
5. Check whether all required files already exist with valid checksums.
6. Download missing assets to temporary files:
   - HTTP range/resume where supported;
   - bounded retries with exponential backoff;
   - no parallel downloads beyond a measured safe limit;
   - progress by bytes, not fake percentages.
7. Verify SHA-256 and optional signature.
8. Move verified files into the immutable versioned cache atomically.
9. Write a `provisioned.json` state file.
10. Start the indexing/search engine.
11. Permit offline use thereafter.

If the network is unavailable, the app remains on the provisioning screen with
retry, offline explanation, and a manual import option for air-gapped use.

## 6. Local storage

```text
%APPDATA%\ai.seeky.desktop\
  seeky.db
  provisioned.json
  runtime\<asset-id>\<version>\
  models\<asset-id>\<revision>\
  cache\manifests\
  logs\
```

- `provisioned.json` records manifest ID, asset IDs, versions, hashes, and
  installation timestamps.
- The last known-good asset set is retained until a new set is fully verified.
- A failed update never deletes the working set.
- A user-facing **Repair assets** action may re-verify and re-download missing
  files; it is not a general settings dashboard.

## 7. Security

- HTTPS only; reject plaintext or redirected non-HTTPS downloads.
- Verify SHA-256 for every file before use.
- Verify the manifest signature when production signing is enabled.
- Prevent path traversal and absolute paths from manifest keys.
- Never load native libraries from a user-selected or unverified directory.
- Keep downloaded runtime DLLs in the app-controlled cache only.
- Do not embed R2 write credentials or account secrets in the client.
- Public bucket listing is unnecessary; only manifest-referenced keys are used.
- Add a release checklist for third-party runtime CVEs and model licenses.

## 8. Licensing and attribution

- Seeky code is MIT-licensed.
- Every downloaded artifact has its own license metadata in the manifest.
- The UI exposes a minimal **Third-party notices** view or document link.
- Model and runtime notices are cached locally with the asset.
- Assets with non-commercial or incompatible licenses are not eligible.
- A model or runtime cannot be added to the bucket until its redistribution
  terms are reviewed and recorded.

## 9. Asset selection policy

The first-run installer should not download every backend.

- Always: CPU embedding, tokenizer, PDFium, CPU runtime.
- NVIDIA: CUDA runtime + FP16 model.
- AMD/Intel GPU: DirectML runtime where supported.
- Intel NPU: OpenVINO runtime + NPU IR.
- Reranker: download once when the retrieval milestone enables it; include a
  CPU-compatible quantized variant.
- Optional future OCR assets are separate and never required for basic search.

Download size is a product metric and must be reported in release notes.

## 10. Updating assets

- App updates may point to a new manifest.
- Model/runtime revisions are new asset IDs, not in-place mutations.
- The app verifies compatibility before activating a new set.
- Rollback keeps the previous verified set until the new set is healthy.
- An embedding-model change requires a documented reindex strategy; the app must
  not silently mix vector spaces.

## 11. Failure modes

| Failure | Behavior |
|---|---|
| Network offline | Provisioning screen with retry/import |
| Manifest unavailable | Use cached manifest if valid; otherwise retry |
| Checksum mismatch | Delete temp file, retry once, report asset issue |
| Disk full | Stop before partial install; show required/free space |
| Unsupported GPU/NPU | Provision CPU, keep hardware feature hidden |
| Corrupt installed asset | Verify on startup; offer repair |
| Model/runtime version mismatch | Reject asset, keep previous working set |
| Manifest signature invalid | Refuse update and surface a security error |

## 12. Migration from the current PoC

Current PoC status:

- CPU/CUDA models and tokenizer are read from the local Gety installation.
- The OpenVINO IR is bundled in the app resources and tracked with Git LFS.
- No network downloader exists.

Target migration tasks:

1. Define the production asset manifest and signing key.
2. Publish CPU, CUDA, DirectML, and NPU assets to R2.
3. Replace Gety path discovery with the provisioned asset resolver.
4. Remove the bundled OpenVINO IR from the installer/repository.
5. Add provisioning UI and repair flow.
6. Add checksum/signature tests and offline/retry tests.
7. Validate clean-VM first run on CPU, CUDA, AMD, and NPU hardware.

## 13. Acceptance criteria

- A clean machine with no Gety installation can provision and search.
- No account or license key is requested.
- Interrupted downloads resume or restart safely without corrupting the cache.
- Checksum/signature failures are rejected.
- The app works offline after provisioning.
- A failed update leaves the previous verified assets usable.
- CPU fallback is always available.
- No document content is included in asset requests.
