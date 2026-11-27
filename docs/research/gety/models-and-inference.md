> **Research note.** This is reverse-engineering context, not the active build contract. Code snippets are illustrative; Seeky is implemented in Rust/Tauri/TypeScript. See the [implementation plan](../../plans/seeky-implementation-plan.md).

# 05 — Models and Inference

This document explains which Gety model artifacts are reusable, how to load
them, and how to plan the Qwen3 upgrade for the minimal app.

> **Licensing note:** the Gety application is proprietary; the published
> `gety-embed-v0` model is MIT-licensed per its Hugging Face model card. Do not
> redistribute Gety binaries or the private OCR weights. Model licenses are
> separate from application licenses.

---

## 1. Installed model inventory

### 1.1 `gety-embed-v0`

Path:

```
%APPDATA%\ai.gety\data\models\gety-ai\gety-embed-v0\
  424f41cb36776481b7e2c9f619ca7ce5d5351fe0\
    config.json
    tokenizer.json
    tokenizer_config.json
    special_tokens_map.json
    onnx/model_uint8.onnx          118,130,759 bytes
    onnx_cuda/model_fp16.onnx      235,074,703 bytes
```

SHA-256:

```
model_uint8.onnx   183B375D5F27B6AB5CB8AB6C7154231652920D4AD5CDD23DE2000DA23B19324A
```

Observed config:

| Field | Value |
|---|---|
| `architectures` | `["BertModel"]` |
| `hidden_size` | 384 |
| `num_hidden_layers` | 12 |
| `num_attention_heads` | 12 |
| `intermediate_size` | 1,536 |
| `vocab_size` | 250,037 |
| `max_position_embeddings` | 512 |
| `model_type` | `bert` |
| `tokenizer_class` | `XLMRobertaTokenizer` |
| `pad_token_id` | 0 (`<s>`) in config; tokenizer uses `<pad>` id 1 |
| `type_vocab_size` | 2 |
| `hidden_act` | `gelu` |

ONNX I/O (observed in the installed file):

```
inputs:  input_ids, attention_mask
output:  sentence_embedding   (384-d, L2-normalized)
```

Pooling and normalization are baked into the graph. This is confirmed by the
public model card and by the lack of a separate `pooler_output` /
`last_hidden_state` output in the installed export.

Public model card facts:

- Fine-tuned from `intfloat/multilingual-e5-small`.
- MIT license.
- 384 dimensions, 512 tokens.
- CPU UINT8 112 MB, CUDA FP16 224 MB, CoreML FP16, OpenVINO INT8 weight-only
  + FP16 activations.
- Masked mean pooling + L2 normalization in the graph.
- OpenVINO variant expects `input_ids` only, pads with token id 1, computes the
  attention mask in-graph.

Source: <https://huggingface.co/gety-ai/gety-embed-v0>

### 1.2 `gety-ocr-v0`

Path:

```
%APPDATA%\ai.gety\data\models\gety-ai\gety-ocr-v0\
  038b6e4d17e55ec43ea07df3a6bcb997b0fbfb6e\
    gety_ocr_cpu_v3.safetensors   50,342,620 bytes
    gety_ocr_cuda_v4.safetensors 180,262,124 bytes
```

SHA-256 (CPU):

```
3C7519E6DC7E449CEC34C1E6E04FB711198B4FF41C9AF38473B19EB47666B129
```

Observed metadata: 16 tensors, F32 declared, `__metadata__.format = "pt"`.
Tensor payloads are high-entropy/NaN when interpreted as F32; the binary
contains `gety-ocr-v1-salt`, HKDF length checks, and AES-GCM failure strings.
The header shapes are not a coherent transformer/CNN topology.

**Verdict:** encrypted/obfuscated private OCR weights. Do not plan to reuse them
standalone. Use RapidOCR, PaddleOCR, Tesseract, or a hosted OCR API for the
minimal app if OCR is required.

---

## 2. Loading `gety-embed-v0` with ONNX Runtime

The following is a complete CPU baseline. It uses the installed tokenizer and
ONNX file and does not require `sentence-transformers`.

```python
from pathlib import Path
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_DIR = Path(
    r"%APPDATA%\ai.gety\data\models\gety-ai"
    r"\gety-embed-v0\424f41cb36776481b7e2c9f619ca7ce5d5351fe0"
)

tokenizer = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
tokenizer.enable_truncation(max_length=512)
tokenizer.enable_padding(pad_id=1, pad_token="<pad>")

session = ort.InferenceSession(
    str(MODEL_DIR / "onnx" / "model_uint8.onnx"),
    providers=["CPUExecutionProvider"],  # or CUDAExecutionProvider
)
print("inputs:", [(i.name, i.shape, i.type) for i in session.get_inputs()])
print("outputs:", [(o.name, o.shape, o.type) for o in session.get_outputs()])

def embed(texts: list[str], batch_size: int = 32) -> np.ndarray:
    vectors = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        enc = tokenizer.encode_batch(batch)
        input_ids = np.array([e.ids for e in enc], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feeds = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        out = session.run(["sentence_embedding"], feeds)[0]
        # The graph already normalizes; this is a safety net.
        out = out / np.linalg.norm(out, axis=1, keepdims=True).clip(min=1e-12)
        vectors.append(out.astype(np.float32))
    return np.vstack(vectors)

vecs = embed(["contract renewal terms", "agreement extension conditions"])
print(vecs.shape)  # (2, 384)
print(np.linalg.norm(vecs, axis=1))  # ~1.0
```

Notes:

- If `sentence_embedding` is not the output name in a different export, use
  `session.get_outputs()[0].name`.
- `pad_id=1` (`<pad>`) matches the tokenizer config; the config's
  `pad_token_id=0` is `<s>`. Attention-mask zeros make masked pooling ignore
  padding either way.
- CUDA: install the matching `onnxruntime-gpu` and use
  `providers=["CUDAExecutionProvider", "CPUExecutionProvider"]`; the installed
  `model_fp16.onnx` is the CUDA export.
- OpenVINO: use the OpenVINO export if you have an Intel NPU/GPU; the model
  card documents the input/padding differences.
- `tokenizers` is available from Hugging Face; the installed `tokenizer.json`
  is a standard XLM-R tokenizer.

### 2.1 Query/document prefixes

`multilingual-e5-small` was trained with `query: ` and `passage: ` prefixes.
The Gety binary does **not** expose these as literal constants that we could
recover. Test both on your evaluation set:

```python
queries = ["query: " + q for q in queries]
passages = ["passage: " + p for p in passages]
```

Record which variant wins and store the choice in `embedding_models.query_prefix`
and `passage_prefix`. Do not assume; E5-family models are sensitive to this.

### 2.2 Chunk length

The model max is 512 tokens. Chunk at 400–512 tokens with 64–96 overlap. Longer
chunks are truncated and lose recall; shorter chunks lose context.

---

## 3. Reranker

Gety ships **no reranker**. The minimal app should add one after the RRF
baseline.

### 3.1 Recommended: Qwen3-Reranker-0.6B

Facts from the model card:

| Field | Value |
|---|---|
| Parameters | 0.6B |
| Layers | 28 |
| Context | 32k |
| Languages | 100+ |
| License | Apache-2.0 |
| Instruction-aware | Yes |
| Output | relevance logit / probability |

Simple use with `sentence-transformers`:

```python
import torch
from sentence_transformers import CrossEncoder

reranker = CrossEncoder("Qwen/Qwen3-Reranker-0.6B")

query = "renewal clauses"
passages = [c.text for c in candidates]

# Raw logit differences by default.
scores = reranker.predict([(query, p) for p in passages])

# Or 0-1 probabilities:
scores = reranker.predict(
    [(query, p) for p in passages],
    activation_fn=torch.nn.Sigmoid(),
)
```

The model card's default prompt is
`"Given a web search query, retrieve relevant passages that answer the query"`.
You can supply a custom instruction for local-file search:

```python
reranker = CrossEncoder(
    "Qwen/Qwen3-Reranker-0.6B",
    prompts={
        "classification": "Given a query about local files, judge whether the document passage contains information that helps answer it"
    },
    default_prompt_name="classification",
)
```

For Transformers-only inference, the model card computes the probability from
the `yes`/`no` logits at the last position. That path is useful for ONNX export
or batch serving; see the model card.

### 3.2 Alternatives

| Model | Size | License | Notes |
|---|---|---|---|
| `BAAI/bge-reranker-v2-m3` | 0.6B | MIT | Strong multilingual baseline, simple cross-encoder. |
| `jinaai/jina-reranker-v2-base-multilingual` | 0.3B | CC-BY-NC-4.0 (check) | Lower latency; check commercial license. |
| `Qwen/Qwen3-Reranker-0.6B` | 0.6B | Apache-2.0 | Best fit if you also use Qwen3 embeddings. |

### 3.3 Reranking policy

- Retrieve 50–100 candidates per retriever; RRF; rerank the top 20–50.
- Batch 8–16, truncate pairs to 1,024–2,048 tokens.
- Use a timeout (e.g. 300 ms) and fall back to RRF order.
- Return `reranked: true/false` and both scores for debugging.
- Evaluate with and without blending:
  `final = 0.7 * sigmoid(rerank) + 0.3 * rrf_norm`.

---

## 4. Embedding upgrade: Qwen3-Embedding-0.6B

Facts from the model card:

| Field | Value |
|---|---|
| Parameters | 0.6B |
| Layers | 28 |
| Context | 32k |
| Dimensions | up to 1024, MRL 32–1024 |
| Languages | 100+ |
| License | Apache-2.0 |
| Instruction-aware | Yes |

Usage:

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

query_vecs = model.encode(
    queries,
    prompt_name="query",
    normalize_embeddings=True,
)
doc_vecs = model.encode(
    documents,
    normalize_embeddings=True,
)
```

For Transformers, use last-token pooling with left padding and L2 normalize;
the model card provides the exact code. The recommended query instruction is:

```
Instruct: Given a local file search query, retrieve relevant passages that answer the query
Query: <user query>
```

Documents are embedded without the instruction.

### 4.1 Migration plan

1. Add a second row to `embedding_models` (`qwen3-embedding-0.6b`, dim 1024).
2. Backfill `chunk_embeddings` for the new model; keep the old rows.
3. Run the evaluation set against both models (BM25-only, dense-only, RRF,
   reranker).
4. Switch the active model in `settings` only if the new model wins on nDCG@10
   and latency is acceptable.
5. Keep the old vectors for rollback; delete them after a stable period.
6. Rebuild the ANN table for the new dimension.

Do not mix 384-d and 1024-d vectors in one similarity computation. Filter by
`model_id` and `dim` in every query.

### 4.2 Dimension/latency trade-off

- 1024-d f32 = 4 KB/chunk; 1M chunks = ~4 GB.
- 512-d MRL = 2 KB/chunk; ~2 GB.
- i8 1024-d = 1 KB/chunk; ~1 GB.
- Exact cosine cost scales with dimension; ANN cost scales with index size.

For a desktop app, 512-d MRL or i8 is often the right compromise. Measure
nDCG loss before truncating.

---

## 5. Pruner model (future)

There is no standard “pruner” model comparable to a reranker. The minimal app
should define the interface first:

```python
class Pruner:
    def prune(self, query: str, passages: list[Passage], token_budget: int) -> list[Passage]:
        ...
```

Baseline (no model):

- Deduplicate by content hash and cosine > 0.95.
- Max 2–3 chunks per document.
- MMR for diversity.
- Neighbor expansion around the best hit.
- Hard token budget.

Future learned pruner:

- A small cross-encoder/classifier scoring `(query, passage) -> keep/drop`.
- Train on query–passage–answer triples or weak labels from the reranker.
- Evaluate answer quality with and without it; pruning can hurt recall.

Do not use Gety's Q4 index pruning code as a model; it is embedding-index
maintenance.

---

## 6. Inference performance and deployment

| Scenario | Recommendation |
|---|---|
| CPU-only laptop | `gety-embed-v0` uint8 ONNX, batch 16–32; Qwen3-0.6B may be too slow for interactive indexing. |
| NVIDIA GPU | CUDA EP with FP16; use `model_fp16.onnx`; batch 32–64. |
| Intel NPU | OpenVINO IR; static shape buckets (32/64/128/256/512); batch 1. |
| Apple Silicon | CoreML FP16 export (macOS 13+); no padding for the CoreML graph. |
| Reranker | GPU preferred; CPU okay for top 20–30 with a 0.6B model but expect hundreds of ms. |

Latency budget for a local search:

```
BM25 + dense retrieval : 20–150 ms
RRF + dedupe           : <5 ms
Rerank top 30          : 50–400 ms (hardware dependent)
Prune/build context    : <20 ms
-----------------------------------
Target p95             : <500 ms interactive
```

Indexing throughput is dominated by extraction and embedding batch size; use a
worker pool and persist progress.

---

## 7. Model files in the minimal app

Suggested layout:

```
data/
  models/
    gety-embed-v0/
      tokenizer.json
      config.json
      model_uint8.onnx
    qwen3-embedding-0.6b/       # later
    qwen3-reranker-0.6b/        # later
  index/
    app.db
```

Registry row example:

```sql
INSERT INTO embedding_models
  (id, dim, normalized, query_prefix, passage_prefix, max_tokens, created_at)
VALUES
  ('gety-embed-v0', 384, 1, '', '', 512, '2026-11-26T00:00:00Z');
```

If you test E5 prefixes, store the winning values:

```sql
UPDATE embedding_models
SET query_prefix = 'query: ', passage_prefix = 'passage: '
WHERE id = 'gety-embed-v0';
```

---

## 8. What not to do

- Do not ship the encrypted OCR weights as if they were open; they are not
  usable without Gety's private runtime/key.
- Do not assume the `config.json` `pad_token_id=0` is the right padding token
  for the ONNX graph; use `<pad>` id 1 and an attention mask, and test.
- Do not mix embedding models/dimensions in one index.
- Do not use raw BM25 and cosine scores as if they were on the same scale; use
  RRF or normalize.
- Do not add a reranker before you have a retrieval evaluation set; you will
  not know whether it helps.

---

## 9. Model card references

- Gety embedding model: <https://huggingface.co/gety-ai/gety-embed-v0>
- Gety OCR model: <https://huggingface.co/gety-ai/gety-ocr-v0>
- Qwen3-Embedding-0.6B: <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B>
- Qwen3-Reranker-0.6B: <https://huggingface.co/Qwen/Qwen3-Reranker-0.6B>
