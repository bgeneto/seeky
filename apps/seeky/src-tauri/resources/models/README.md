# NPU model resources

This directory contains the published `gety-embed-v0` OpenVINO export used by the
Intel NPU backend.

| File | Size | Source |
|---|---:|---|
| `openvino/model.xml` | 712,310 bytes | `gety-ai/gety-embed-v0` OpenVINO export |
| `openvino/model.bin` | 118,572,517 bytes | Git LFS |

Seeky does not use Gety's encrypted OCR weights. Verify the model license before
publishing installers or redistributing the IR.

The release build copies these files to:

```text
src-tauri/target/release/resources/models/gety-embed-v0/openvino/
```

Keep the `resources/` directory beside `seeky.exe` for portable builds.
