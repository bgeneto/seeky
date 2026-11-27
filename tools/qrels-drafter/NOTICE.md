# Third-party notices — qrels-drafter

This directory is development-only dataset tooling for the Seeky Desktop Corpus
(SPEC-0004). It never ships with the product, is never imported by an engine
crate, and is not part of any benchmark runtime.

## qrels-drafter (this tool)

MIT, the repository license. Python 3.12+ standard library only; the runtime
dependency set is empty (`requirements.lock`).

## Drafting models

Two pinned profiles; the tool ships neither. The default was chosen by the
bounded bake-off in [README.md](README.md#model-choice-bounded-bake-off-2026-11-27).

### Default: Qwen3-0.6B

| Field | Value |
|---|---|
| Model | Qwen3-0.6B (Apache-2.0, eligible under ADR-0022) |
| Upstream | `https://huggingface.co/Qwen/Qwen3-0.6B-GGUF` |
| Immutable revision | `23749fefcc72300e3a2ad315e1317431b06b590a` |
| File | `Qwen3-0.6B-Q8_0.gguf`, 639,446,688 bytes |
| Weight SHA-256 | `9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031` |
| Quantization | Q8_0 GGUF (the upstream repo publishes no Q4_K_M) |
| Mode | non-thinking: `/no_think` appended, any ` thinking` block stripped |
| Decoding | temperature 0.7, top-p 0.8, top-k 20, presence penalty 1.5, seed 42, 200 tokens, 8 threads |

### Alternative: Qwen2.5-1.5B-Instruct

| Field | Value |
|---|---|
| Model | Qwen2.5-1.5B-Instruct (Apache-2.0) |
| Upstream | `https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF` |
| Immutable revision | `91cad51170dc346986eccefdc2dd33a9da36ead9` |
| File | `qwen2.5-1.5b-instruct-q4_k_m.gguf`, 1,117,320,736 bytes |
| Weight SHA-256 | `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e` |
| Quantization | Q4_K_M GGUF |
| Decoding | greedy, temperature 0, top-k 1, seed 42, 160 tokens, 8 threads |

Both models are **drafting aids only**. They are never product components, never
answer generators, and their output has no authority over a relevance grade
(ADR-0021, SPEC-0004 R20/R21). Weights are not committed: they live outside the
repository under `%LOCALAPPDATA%\seeky-dev\llm` (or the path given to
`fetch-model`).

## Runtime

| Field | Value |
|---|---|
| Runner | llama.cpp `b12815` (MIT) CPU x64 build |
| Binary | `llama-b12815-bin-win-cpu-x64.zip` |
| Archive SHA-256 | `8167d30d05420295ade9b9db3e73d0325aca75b72ced25c030d5dd3d7b0fde5a` |
| Invocation | `llama-completion.exe` as a local subprocess; prompt on stdin |

No socket, HTTP client, or hosted API is used for drafting. Only the explicit
`fetch-model` command downloads anything, and it verifies the pinned digests
above. The generated prompts, corpus excerpts, and model replies stay on the
machine.

## Development acceleration

The drafting run may use the CUDA 12.4 build of the same llama.cpp release with
`--gpu-layers 99`; it is optional local development acceleration, is not
committed, is not a product component, and is not used to claim any product
budget (ADR-0019 budgets remain CPU-only). The pinned model file, revision, and
provenance are unchanged by the choice of runner build.

## Model revision check

`python -m qrels_drafter verify-model` re-hashes the local weight file against
the pinned digest for the selected `--profile` and fails on a mismatch. The
committed draft was produced with the Qwen3-0.6B file and revision above.
