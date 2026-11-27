# Models

## Runtime resolution

Seeky never downloads models. It reads Gety's installed model files and supports
environment overrides.

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

The 118.6 MB NPU `model.bin` is tracked with Git LFS. Install Git LFS before
cloning if you need the NPU path.
