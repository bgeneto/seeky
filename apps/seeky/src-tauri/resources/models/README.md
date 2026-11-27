# NPU model resources

This directory contains the temporary published `gety-embed-v0` OpenVINO export
used by the current PoC's Intel NPU backend.

| File | Size | Source |
|---|---:|---|
| `openvino/model.xml` | 712,310 bytes | `gety-ai/gety-embed-v0` OpenVINO export |
| `openvino/model.bin` | 118,572,517 bytes | Git LFS (transitional) |

License: MIT, per the model card of
[`gety-ai/gety-embed-v0`](https://huggingface.co/gety-ai/gety-embed-v0) (base
model `intfloat/multilingual-e5-small`, MIT). `model.bin` is byte-identical to
the published `openvino/model.bin` (SHA-256
`aaa336bf9568aa2c3d0d3679d28457e08d2ae40e3918d1b8003748e2a2db4dcb`, verified
2026-11-27). Seeky does not use Gety's encrypted OCR weights.

The target slim setup removes this bundled copy and downloads a verified IR from
the seeky Cloudflare R2 bucket on first run. See
[`docs/architecture/distribution-and-provisioning.md`](../../../../../docs/architecture/distribution-and-provisioning.md).

The current release build copies these files to:

```text
src-tauri/target/release/resources/models/gety-embed-v0/openvino/
```

Keep the `resources/` directory beside `seeky.exe` for current portable builds.
