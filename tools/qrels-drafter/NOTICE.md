# Third-party notices — qrels-drafter

This directory is development-only dataset tooling for the Seeky Desktop Corpus
(SPEC-0004). It never ships with the product, is never imported by an engine
crate, and is not part of any benchmark runtime.

## qrels-drafter (this tool)

MIT, the repository license. Python 3.12+ standard library only; the runtime
dependency set is empty (`requirements.lock`).

## Drafting model

| Field | Value |
|---|---|
| Model | Qwen2.5-1.5B-Instruct (instruction-tuned, text only) |
| License | Apache-2.0 (eligible under ADR-0022) |
| Upstream | `https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF` |
| Immutable revision | `91cad51170dc346986eccefdc2dd33a9da36ead9` |
| File | `qwen2.5-1.5b-instruct-q4_k_m.gguf`, 1,117,320,736 bytes |
| Weight SHA-256 | `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e` |
| Quantization | Q4_K_M GGUF |
| Decoding | greedy, temperature 0, top-k 1, seed 42, max 160 tokens, 8 threads |

The model is a **drafting aid only**. It is never a product component, never an
answer generator, and its output has no authority over a relevance grade
(ADR-0021, SPEC-0004 R20/R21). Model weights are not committed: they live
outside the repository under `%LOCALAPPDATA%\seeky-dev\llm` (or the path given
to `fetch-model`).

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

## Model revision check

`python -m qrels_drafter verify-model --model <path>` re-hashes the local weight
file and fails if it does not match `6a1a2eb6…`. The committed draft was
produced with exactly that file and revision.
