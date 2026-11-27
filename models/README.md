# Models

## Current PoC resolution

Seeky never downloads models in the current PoC. It reads Gety's installed model
files and supports environment overrides.

| Purpose | Default | Override |
|---|---|---|
| CPU/CUDA ONNX + tokenizer | `%APPDATA%\ai.gety\data\models\gety-ai\gety-embed-v0\<revision>` | `SEEKY_GETY_MODEL_DIR` |
| ONNX Runtime | `%APPDATA%\ai.gety\data\ep\onnxruntime.dll` | `SEEKY_ORT_DLL` |
| OpenVINO runtime | `%APPDATA%\ai.gety\data\third_party_libs\openvino` | `SEEKY_OPENVINO_DIR` |
| NPU OpenVINO IR | `apps/seeky/src-tauri/resources/models/gety-embed-v0/openvino` | `SEEKY_NPU_DIR` |
| PDFium | `%LOCALAPPDATA%\Gety\lib\pdfium.dll` | `SEEKY_PDFIUM_DLL` |

`local-model-paths.example.json` records the expected machine-local layout for
development.

- CPU model: `onnx/model_uint8.onnx`
- CUDA model: `onnx_cuda/model_fp16.onnx`
- Tokenizer: `tokenizer.json`
- NPU IR: `model.xml` + `model.bin`

The 118.6 MB NPU `model.bin` is tracked with Git LFS for the current PoC.

## Target slim setup

The shipped product will not require Gety. First run downloads verified runtimes,
models, tokenizers, and native libraries from the seeky Cloudflare R2 bucket,
caches them under the app data directory, and runs offline afterward. No account
or license key is required.

See
[`docs/architecture/distribution-and-provisioning.md`](../docs/architecture/distribution-and-provisioning.md)
and
[`docs/architecture/model-strategy.md`](../docs/architecture/model-strategy.md).
