# model-export (WP-0.6 v0)

Offline Python tooling for the preregistered ONNX Runtime validation gate. It is
**not shipped** and is not part of the Seeky product runtime. Model weights,
exports, datasets, reference outputs, package environments, and caches stay under
`%LOCALAPPDATA%\seeky-dev\wp06` (or another caller-selected directory outside
every repository worktree).

The gate definition is
[`docs/benchmarks/results/2026-11-27-ort-gate/PREREGISTRATION.md`](../../docs/benchmarks/results/2026-11-27-ort-gate/PREREGISTRATION.md).
Do not change models, samples, tolerances, or targets in code to make a result
pass. Amend and commit the preregistration before any affected measurement.

## Isolated setup

Use Python 3.11. The CPU environment pins ONNX Runtime 1.22.0, matching the
runtime targeted by the product's `ort = 2.0.0-rc.10` wrapper. The separate
OpenVINO environment avoids mixing the CPU and OpenVINO Python wheels.

```powershell
py -3.11 -m venv "$env:LOCALAPPDATA%\seeky-dev\wp06\venv"
& "$env:LOCALAPPDATA%\seeky-dev\wp06\venv\Scripts\python.exe" -m pip install -r tools/model-export/requirements-cpu.txt
& "$env:LOCALAPPDATA%\seeky-dev\wp06\venv\Scripts\python.exe" -m pip install -e tools/model-export

py -3.11 -m venv "$env:LOCALAPPDATA%\seeky-dev\wp06\venv-openvino"
& "$env:LOCALAPPDATA%\seeky-dev\wp06\venv-openvino\Scripts\python.exe" -m pip install -r tools/model-export/requirements-openvino.txt
& "$env:LOCALAPPDATA%\seeky-dev\wp06\venv-openvino\Scripts\python.exe" -m pip install -e tools/model-export
```

PyTorch is pinned to the CPU wheel (`2.11.0+cpu`); no CUDA package is used.
Direct dependency licenses were screened under ADR-0022: PyTorch BSD-3-Clause;
Transformers, Hugging Face Hub, RapidOCR, ONNX Runtime, ONNX, and requests
Apache-2.0; NumPy, Pillow, psutil, and py-cpuinfo BSD/MIT-class permissive
licenses; pytest and setuptools MIT. Transitive versions and licenses are
captured in the environment report. This tooling and its downloads are not
shipped artifacts.

## Gate commands

All commands refuse a workspace inside a Git worktree. Acquisition and reference
work may run before a quiet window; timed variants wait for one.

```powershell
$python = "$env:LOCALAPPDATA\seeky-dev\wp06\venv\Scripts\python.exe"
$workspace = "$env:LOCALAPPDATA\seeky-dev\wp06"
& $python -m seeky_model_export.cli --workspace $workspace prepare-text
& $python -m seeky_model_export.cli --workspace $workspace prepare-ocr
& $python -m seeky_model_export.cli --workspace $workspace t0
& $python -m seeky_model_export.cli --workspace $workspace encoders --model e5-small
& $python -m seeky_model_export.cli --workspace $workspace encoders --model granite-modernbert
& $python -m seeky_model_export.cli --workspace $workspace reranker
& $python -m seeky_model_export.cli --workspace $workspace ocr
& $python -m seeky_model_export.cli --workspace $workspace florence
```

The NPU probe must use the OpenVINO environment's interpreter and ONNX Runtime
package, with its own `PYTHONPATH` or editable install:

```powershell
$openvino = "$env:LOCALAPPDATA\seeky-dev\wp06\venv-openvino\Scripts\python.exe"
& $openvino -m seeky_model_export.cli --workspace $workspace npu
& $python -m seeky_model_export.cli --workspace $workspace export-results --destination docs/benchmarks/results/2026-11-27-ort-gate
```

Each run writes per-stage JSON under `<workspace>\results`; raw timing arrays stay
under `<workspace>\raw`. Only sanitized aggregates and hashes are copied into the
committed benchmark report.

### Bounded gate timeouts

Every gate subcommand (`t0`, `encoders`, `reranker`, `ocr`, `florence`, `npu`)
accepts `--timeout-seconds <float>`, the whole-gate wall-clock ceiling. The
default is **1800 s per gate**; override it for a slower host:

```powershell
& $python -m seeky_model_export.cli --workspace $workspace reranker --timeout-seconds 3600
```

The budget covers asset preparation, quiet-window waits, every variant, list,
batch, repetition, and decode step. `wait_for_quiet_window` and the `powercfg`
calls are clamped to the remaining budget, and `subprocess.run` calls pass it as
their timeout. An in-process ONNX Runtime `session.run` cannot be interrupted
mid-call, so the deadline is checked between calls; a single very long call can
overshoot by that one call. The Florence decode loop checks every 16 tokens.

On expiry the gate writes the completed work atomically to
`<workspace>\results\<gate>-timeout.json` (`reranker-timeout.json`,
`encoders-e5-small-timeout.json`, `ocr-timeout.json`, `florence-timeout.json`,
`npu-timeout.json`, `t0-functional-timeout.json`) with `status: "timed_out"`,
the stage that expired, the elapsed and limit seconds, and `completed_variants`;
the in-flight variant is not recorded. It never writes a K1-K4 verdict, prints the
stage and elapsed seconds, and exits **124**. `results/<gate>.json` keeps its
existing meaning and is written only for completed variants as before.
`export-results` ignores any stage whose timeout artifact is newer than its
result file (`incomplete_sources` in `summary-data.json`), so partial evidence
cannot leak into a verdict. A timeout artifact is evidence of an interrupted
run, never of a gate failure: rerun the gate after raising the ceiling or
removing the cause of the stall.

## Hardware-free checks

```powershell
$env:PYTHONPATH = "tools/model-export/src"
& "$env:LOCALAPPDATA%\seeky-dev\wp06\venv\Scripts\python.exe" -m pytest tools/model-export/tests -q
```

Tests use no network, model, file outside their temporary directory, or
hardware provider. Hardware and model commands are explicit and never part of
the default test suite.

## Data and artifact safety

Commands require `--workspace`, which must be outside the current Git worktree.
They refuse a workspace inside any Git worktree and refuse paths containing a
user profile in machine-readable committed output. Outputs contain revisions,
hashes, timings, and aggregate metrics only; source text and decoded OCR text
stay in the external workspace.
