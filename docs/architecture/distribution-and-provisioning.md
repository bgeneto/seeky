# Distribution and First-Run Provisioning

| Field | Value |
|---|---|
| Status | Accepted target contract |
| Date | 2026-11-27 (v2) |
| Governs | Installer contents, asset bucket, manifest, download/verify/install, offline use, updates |
| Related | [ADR-0011](../adr/0011-slim-first-run-provisioning.md), [ADR-0018](../adr/0018-lexical-first-availability.md), [ADR-0016](../adr/0016-cpu-first-npu-ready-execution.md), [ADR-0022](../adr/0022-permissive-license-gate.md) |

## 1. Decision summary

- The installer is small and contains the app plus the Tier-0 dependencies that
  lexical search needs (for example PDFium), within the installer budget.
- Inference runtimes, models, tokenizers, and optional packs (OCR) are
  downloaded from the public `seeky` Cloudflare R2 bucket, verified, and cached.
- **Search works before provisioning completes** (filename + lexical); semantic
  stages activate as assets verify ([ADR-0018](../adr/0018-lexical-first-availability.md)).
- No account, license key, or credentials; downloads carry no user data.
- After provisioning, Seeky runs fully offline.

## 2. Bucket and endpoints

| Item | Value |
|---|---|
| Provider | Cloudflare R2 |
| Bucket | `seeky` (R2 identifiers are lowercase; product name Seeky) |
| Access | Public, read-only, immutable versioned keys |
| Client credentials | None embedded |
| Transport | HTTPS only, plus per-file SHA-256 and manifest signature |
| Base URL | Build-time `SEEKY_ASSET_BASE_URL`, overridable for development/testing |

A production build uses a Cloudflare custom domain in front of the bucket.
Public listing is unnecessary; clients fetch only manifest-referenced keys.

## 3. Asset classes

| Class | Examples | When downloaded |
|---|---|---|
| Runtime | ONNX Runtime core library (ADR-0019); NPU execution-provider libraries | First run (core); NPU EPs only on matching hardware |
| Embedding model | Selected multilingual embedder (CPU int8 variant + NPU variants) | First run |
| Reranker | Selected cross-encoder (CPU int8; NPU variant) | First run, after the embedder |
| OCR pack (CPU) | OCR models selected by the OCR bake-off (for example detection + recognition, or a small transcription model) | When the user enables OCR |
| GPU OCR pack (opt-in) | Higher-accuracy OCR model and an ONNX Runtime GPU execution provider, only if the OCR bake-off justifies it (ADR-0016) | Only on explicit user opt-in with a supported GPU |
| Visual pack | Vision encoder selected by the visual bake-off, plus the visual channel's text encoder in a specialized design ([ADR-0023](../adr/0023-multimodal-ready-engine.md)); outside D2 | When the user enables image search |
| Notices | LICENSE/NOTICE per asset | With each asset |

GPU runtimes are not part of the default asset set ([ADR-0016](../adr/0016-cpu-first-npu-ready-execution.md)).

## 4. Object layout

```text
channels/
  stable/manifest.json            (+ manifest.json.sig)
  beta/manifest.json              (+ manifest.json.sig)
runtimes/
  onnxruntime/<version>/<os>-<arch>/...
  ep-openvino/<version>/<os>-<arch>/...
  ep-qnn/<version>/windows-arm64/...
  ep-vitisai/<version>/windows-x64/...
models/
  embedding/<family>/<revision>/   tokenizer.json, <component>_<variant>.onnx, parity.jsonl, model.toml
                                   (components such as text and vision are separate assets)
  reranker/<family>/<revision>/    tokenizer.json, model_<variant>.onnx, parity.jsonl, model.toml
  ocr/<family>/<revision>/         det/rec models, dictionaries, model.toml
licenses/
  <asset-id>/LICENSE.txt
  <asset-id>/NOTICE.txt
offline/
  seeky-assets-<channel>-<date>-<os>-<arch>.zip   (air-gapped bundle, signed)
```

Keys are immutable once published; a new revision gets a new path.

## 5. Manifest

A small JSON document validated against a Rust serde schema; Ed25519-signed
(detached signature) with the public key compiled into the app.

Required fields:

- schema version, channel, generation timestamp, minimum app version;
- target platform (`os`, `arch`) and hardware requirements per asset
  (instruction-set level, NPU vendor/driver minimums);
- per asset: ID, class, version, relative URL, byte size, SHA-256, provider
  (`cpu`, `openvino`, `qnn`, `vitisai`, `coreml`), license and notice paths;
- for models: the full model manifest (`model.toml`, see
  [inference-and-models](inference-and-models.md)) or a hash-pinned reference to it;
- default selections per hardware profile.

```json
{
  "schema": 2,
  "channel": "stable",
  "generated_at": "2026-11-27T00:00:00Z",
  "minimum_app_version": "0.5.0",
  "assets": [
    {
      "id": "embed/example-multilingual/int8-cpu",
      "class": "embedding-model",
      "version": "2026.11",
      "url": "models/embedding/example-multilingual/2026.11/model_int8.onnx",
      "size": 123456789,
      "sha256": "…",
      "provider": "cpu",
      "platform": { "os": "any", "arch": "any" },
      "license": "licenses/embed-example-multilingual/LICENSE.txt"
    }
  ]
}
```

## 6. First-run flow

1. App starts; lexical/filename search is available immediately.
2. Detect OS, architecture, CPU features, NPU vendor/driver, RAM, free disk.
3. Fetch the channel manifest (conditional request, cached copy if valid);
   verify signature.
4. Select the **smallest compatible set**: ORT CPU + embedder CPU variant +
   reranker CPU variant; NPU runtime/variants only when a supported NPU and
   driver are present.
5. Skip assets already present with valid hashes.
6. Download to temporary files: HTTP range resume, bounded retries with
   exponential backoff, measured concurrency limit, progress in bytes.
7. Verify SHA-256 and (for the manifest) the signature; reject anything else.
8. Atomically move into the immutable versioned asset cache; write
   `provisioned.json`.
9. Load models, run parity vectors, enable semantic stages; background
   embedding starts filling semantic coverage.

Non-blocking UI: a compact progress indicator, not a wall. If the network is
unavailable, Seeky keeps working lexically and offers retry and **offline bundle
import**.

## 7. Local storage

```text
<app-data>/assets/
  runtimes/<asset-id>/<version>/
  models/<asset-id>/<revision>/
  cache/manifests/
  provisioned.json
```

- `provisioned.json` records manifest version, asset IDs, versions, hashes, and
  install times.
- The last known-good set is retained until a new set is fully verified; a
  failed update never deletes the working set.
- **Repair assets** re-verifies and re-downloads missing/corrupt files.

## 8. Security

- HTTPS only; reject redirects to non-HTTPS.
- Verify every file hash before use; verify the manifest signature always in
  release builds.
- Reject path traversal and absolute paths in manifest keys.
- Load native libraries only from the app-controlled asset cache, by absolute
  path; never from `PATH` or user-selected directories.
- No write credentials in the client; publishing uses a separate CI-only
  credential and signing key (key management documented in the release spec).
- Release checklist includes runtime CVE review and license review.

## 9. Licensing and attribution

- Every asset carries license metadata and notice files; the app exposes a
  minimal **Third-party notices** view.
- Assets must pass [ADR-0022](../adr/0022-permissive-license-gate.md) before
  upload.

## 10. Updates

- App updates may point to a newer manifest; asset revisions are new IDs.
- Compatibility is verified before activation; rollback keeps the previous set.
- A new embedding recipe triggers a background index generation build; the old
  generation serves until promotion ([indexing](indexing.md)).
- No silent self-update of the application binary unless a later ADR adds a
  signed updater.

## 11. Failure modes

| Failure | Behavior |
|---|---|
| Network offline | Lexical search works; retry and offline import offered |
| Manifest unavailable | Use cached valid manifest; otherwise retry later |
| Manifest signature invalid | Refuse; security error surfaced; keep current assets |
| Checksum mismatch | Delete temp file, retry once, then report the asset |
| Disk full | Stop before partial install; show required vs free space |
| Unsupported or failing NPU | Use CPU variants; NPU hidden in diagnostics |
| Corrupt installed asset | Detected on load/parity; repair offered; lexical search continues |
| Version mismatch | Reject asset; keep the previous working set |

## 12. Migration from the PoC

Today the PoC reads CPU/CUDA models, ORT, OpenVINO, and PDFium from a local Gety
installation and bundles an OpenVINO IR via Git LFS. Migration (provisioning
phase of the plan):

1. Define the manifest schema and signing flow (spec).
2. Export, benchmark, and publish the selected models and runtimes.
3. Replace Gety path discovery with the asset resolver; remove env-var paths
   except development overrides.
4. Remove the bundled OpenVINO IR and its LFS rule.
5. Implement the non-blocking provisioning UI, repair, and offline import.
6. Validate on clean VMs: Windows x64 CPU-only, Windows x64 with Intel NPU,
   Windows ARM64 with Qualcomm NPU; macOS/Linux before GA.

## 13. Acceptance criteria

- A clean machine with no Gety installation installs, searches lexically at
  once, provisions, and searches semantically.
- No account, key, or credential is ever requested.
- Interrupted downloads resume or restart without corrupting the cache.
- Hash and signature failures are rejected and reported.
- The app works offline after provisioning; offline bundle import works.
- A failed update leaves the previous verified assets usable.
- No document content or identifying data appears in any request.
