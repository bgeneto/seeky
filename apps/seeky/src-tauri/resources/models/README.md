# NPU model resources

This directory contains the temporary published `gety-embed-v0` OpenVINO export
used by the current PoC's Intel NPU backend.

| File | Size | Source |
|---|---:|---|
| `openvino/model.xml` | 712,310 bytes | `gety-ai/gety-embed-v0` OpenVINO export |
| `openvino/model.bin` | 118,572,517 bytes | Git LFS (transitional) |

Seeky does not use Gety's encrypted OCR weights. Verify the model license before
publishing installers or redistributing the IR.

The target slim setup removes this bundled copy and downloads a verified IR from
the seeky Cloudflare R2 bucket on first run. See
[`docs/architecture/distribution-and-provisioning.md`](../../../../../docs/architecture/distribution-and-provisioning.md).

The current release build copies these files to:

```text
src-tauri/target/release/resources/models/gety-embed-v0/openvino/
```

Keep the `resources/` directory beside `seeky.exe` for current portable builds.
