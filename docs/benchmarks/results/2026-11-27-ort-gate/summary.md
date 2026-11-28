# 2026-11-27 — inference: WP-0.6 ORT validation gate (K1–K4)

| Field | Value |
|---|---|
| Work package / spec | WP-0.6 / — (gate report; protocol frozen in [`PREREGISTRATION.md`](PREREGISTRATION.md), amendments 1–4) |
| Hypothesis | ONNX Runtime 1.22.0 can serve every model role CPU-first within the provisional budgets, reach the Intel NPU through its OpenVINO EP, and stay inside D2 (ADR-0019) |
| Gate(s) | K1 (embedder, reranker, PP-OCR, Florence probe), K2 (deferred), K3, K4 / D2 — methodology §8.7 |
| Decision | **Evidence only.** K1 fires for the embedder and reranker roles; K3 fires; K4 does not fire (the models alone exceed D2). H5 (2026-11-27): the maintainer chose the isolated O2 reading, so PP-OCRv6 tiny passes O1–O3 and K1 does not fire for OCR. The rest of H5 (embedder and reranker roles) is open |
| Commit | Harness `tools/model-export` on `main` up to `ccd8ffb`; see §3.4 for which fixes landed after which rows |
| Config hash | n/a (no `seeky-bench` engine config; each row records model revisions, variant hashes, and providers) |
| Hardware tier | **T1-emulated** (gate H3 approved 2026-11-27: logical CPUs 0–7, 12 GiB Job Object, High Performance) on an Intel Core Ultra 7 265KF, 20 logical CPUs, 64 GiB, Windows 11 26200; NPU "Intel AI Boost", driver 32.0.100.3717 |

Machine-readable evidence: [`summary-data.json`](summary-data.json) (verdicts
computed by `seeky-model-export export-results`) and the sanitized per-gate
files in [`raw-results/`](raw-results/). Every number below is copied from
those files.

## 1. Setup

- **Data.** Frozen public samples from §3 of the preregistration: 1,024
  passages and 64 queries (MIRACL-en dev and mMARCO-pt, amendment 1) for the
  embedders; 30 frozen first-stage lists at depth 50 (384-token pair limit) for
  the rerankers; 20 rendered A4 300-dpi public-domain pages (16 text, 4 blank)
  for OCR and Florence. Hashes in `raw-results/text-acquisition-summary.json`
  and `raw-results/manifest.json`.
- **Runtime.** ONNX Runtime 1.22.0 CPU EP (Python 3.11, PyTorch 2.11.0+cpu and
  Transformers 5.18.0 for references and exports). NPU: `onnxruntime-openvino`
  1.22.0 with `openvino` 2025.1.0 in a separate environment, CPU fallback
  disabled.
- **Proxies (K1/K4).** `intfloat/multilingual-e5-small` and
  `ibm-granite/granite-embedding-97m-multilingual-r2` (ModernBERT) (embedders),
  `Alibaba-NLP/gte-multilingual-reranker-base`
  (reranker), PP-OCRv6 tiny det + rec (OCR, amendment 4), Florence-2-large split
  graphs (transcription probe). Revisions and hashes are in each raw file.
- **Supplementary rows (never part of K1).** `bekko-a8m` and `gety-embed-v0`
  (amendment 2), `hs-rerank-1` (amendment 3).
- **Commands.** `python -m seeky_model_export.cli --workspace <external dir>`
  with `t0`, `encoders --model <slug>`, `reranker [--model hs-rerank-1]`, `ocr`,
  `ocr-memory`, `florence`, `npu` (OpenVINO environment), then
  `export-results --destination docs/benchmarks/results/2026-11-27-ort-gate`.
  Setup and the NPU prepare step are in `tools/model-export/README.md`.

T0 functional check (not budget evidence): embedder, reranker, and PP-OCRv6
tiny all run end to end (`raw-results/t0.json`).

## 2. Results

### Embedders (K1: ≥56 passages/s and batch-1 query p95 ≤20 ms)

| Model | Variant | Parity | Mean cosine | Neighbor R@100 | nDCG@10 Δ | Passages/s | Query p95 (ms) | Bytes |
|---|---|---|---:|---:|---:|---:|---:|---:|
| e5-small (proxy) | fp32 | pass | 1.0000 | 1.0000 | 0.0000 | **32.3** | 3.41 | 470,268,510 |
| e5-small (proxy) | int8-dynamic | fail | 0.9967 | 0.8967 | 0.0000 | — | — | 118,320,728 |
| e5-small (proxy) | int8-static-qdq | fail | 0.7102 | 0.1281 | −0.3900 | — | — | 118,625,809 |
| granite-modernbert (proxy) | fp32 | pass | 1.0000 | 1.0000 | 0.0000 | **12.3** | **24.20** | 390,004,608 |
| granite-modernbert (proxy) | int8-dynamic | fail | 0.9516 | 0.6770 | +0.0119 | — | — | 98,163,944 |
| granite-modernbert (proxy) | int8-static-qdq | fail | 0.6936 | 0.1016 | −0.4059 | — | — | 98,461,269 |
| bekko-a8m (amend. 2) | fp32 | pass | 1.0000 | 1.0000 | 0.0000 | 162.4 | 1.05 | 423,986,463 |
| bekko-a8m (amend. 2) | published-default | pass | 0.9999 | 0.9873 | +0.0009 | 153.9 | 1.22 | 130,099,079 |
| bekko-a8m (amend. 2) | int8-dynamic | fail | 0.9621 | 0.8575 | −0.0062 | — | — | 106,210,366 |
| gety-embed-v0 (amend. 2) | fp16-upcast | pass | 1.0000 | 1.0000 | 0.0000 | 57.4 | 2.46 | 470,086,600 |
| gety-embed-v0 (amend. 2) | published-uint8 | fail | 0.9898 | 0.8739 | −0.0053 | — | — | 118,130,759 |

**K1 embedder fires**: neither proxy has a parity-passing variant meeting both
targets (e5 misses throughput, Granite misses both). Both supplementary models
meet them on the same runtime, profile, and data.

### Rerankers (K1: depth-50 p95 ≤250 ms)

| Model | Variant | Parity | Mean τ-b | Worst τ-b | nDCG@10 Δ | Depth-50 p50 (ms) | Depth-50 p95 (ms) [95% CI] | Bytes |
|---|---|---|---:|---:|---:|---:|---:|---:|
| gte-reranker (proxy) | fp32 | pass | 1.0000 | 1.0000 | 0.0000 | 8,457 | **9,934** [8,605–10,083] | 1,224,105,101 |
| gte-reranker (proxy) | int8-dynamic | fail | 0.6682 | 0.4612 | +0.0270 | — | — | 307,307,833 |
| gte-reranker (proxy) | int8-static-qdq | fail | 0.0000 | 0.0000 | −0.7002 | — | — | 307,596,440 |
| hs-rerank-1 (amend. 3) | fp32 | pass | 1.0000 | 1.0000 | 0.0000 | 4,335 | 5,971 [4,569–6,337] | 455,387,654 |
| hs-rerank-1 (amend. 3) | published-default | pass | 0.9951 | 0.9902 | +0.0010 | 2,285 | 4,966 [4,743–5,066] | 160,582,339 |
| hs-rerank-1 (amend. 3) | int8-dynamic | fail | 0.9451 | 0.9069 | +0.0046 | — | — | 114,327,772 |
| hs-rerank-1 (amend. 3) | int8-static-qdq | fail | 0.0000 | 0.0000 | −0.7694 | — | — | 114,646,641 |

Mean pair length is 196 tokens (gte) and 179 tokens (hs-rerank-1), p95 380 and
338. **K1 reranker fires**, by 40× on the proxy. The fastest parity-passing
supplementary variant still misses by 20×.

### PP-OCRv6 tiny (K1: O1 p95 ≤2.0 s/page, O2 added peak RSS ≤1.0 GB, O3 ≤150 MB)

| Variant | Parity | CER | WER | Page CER p95 | Blank pages with output | Page p95 (ms) [95% CI] | O2 gate upper bound | O2 isolated | Model bytes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fp32 | pass (deterministic) | 0.70% | 3.92% | 1.78% | 0 / 4 | **724** [693–736] | 1,173,417,984 | **434,532,352** | 6,243,229 |
| int8-static-qdq | fail (CER Δ +69.6 pts) | 70.28% | 87.95% | 77.89% | 0 / 4 | — | — | — | 2,035,952 |
| int8-dynamic | not runnable | — | — | — | — | — | — | — | — |

int8-dynamic fails at session creation: ORT has no CPU kernel for
`ConvInteger(10)`. O1 and O3 pass with wide margins. O2 has two readings:

- **Gate figure, 1.17 GB.** This is the frozen §7 rule (process peak minus
  pre-model baseline) applied in the gate process. That process had already
  quantized and calibrated the int8 variants before it timed fp32, so its peak
  working set includes that work. The exporter's verdict uses this figure, so
  **`k1_ocr` fires** in `summary-data.json`. Its threshold is 1 GiB
  (1,073,741,824 bytes), not the preregistered 1.0 GB, which changes nothing
  here.
- **Isolated probe, 0.43 GB.** `ocr-memory` (added after the gate figure was
  seen, §3.4) applies the same §7 rule in a fresh process that only loads fp32
  and reads all 16 text pages after 3 warm-up pages.

On the isolated reading, PP-OCRv6 tiny meets O1–O3 and K1 does not fire for
OCR. **H5 decision (maintainer, 2026-11-27): the isolated reading decides.**
`summary-data.json` is exporter output and still shows `k1_ocr` on the gate
figure; it is not hand-edited.

### Florence-2-large probe (out of the CPU tier)

| Variant | Parity | CER | Timed pages | Page times (ms) | Pages at the 1,024-token bound |
|---|---|---:|---:|---|---|
| fp32 | pass (deterministic) | 48.96% | 3 (early stop) | min 14,825, p50 18,634, max 174,454 | 1 |
| int4-matmulnbits | fail (CER 100%) | 100% | 3 (early stop) | min 41,296, p50 88,597, max 106,850 | 3 |
| int8-dynamic | not runnable (`ModelError`) | — | — | — | — |

Three distinct timed pages exceeded 4.0 s, so under §6 Florence is **out of
the CPU tier on any engine and K1 does not fire**. The PP-OCR class serves the
CPU OCR role. Its added peak RSS upper bound was 8.3 GB. Static QDQ was not
attempted: the published split graphs have dynamic KV-cache inputs.

### Intel NPU (K3)

| Graph | Reached NPU | Cold load (s) | Pooled-embedding cosine vs ORT CPU | Token-0 cosine (diagnostic) | Parity |
|---|---|---:|---:|---:|---|
| e5-small static fp32, batch 1 × 32 | yes (OpenVINO EP, CPU fallback disabled) | 1.52 | 0.9077 | 0.9722 | **fail** (needs ≥0.99) |
| e5-small static QDQ, batch 1 × 32 | no: the NPU compiler crashed the attempt process (0xC0000005) | — | — | — | — |

**K3 fires.** The NPU accepts and runs the fp32 graph, but its output is not
within the embedder tolerance. A diagnostic outside the gate compiled the same
graph directly in OpenVINO 2025.1 for the NPU: the output was non-finite, with
and without an f32 precision hint, and also after replacing the attention-mask
fill (−3.4e38) with −1e4. On OpenVINO's CPU device the same graph matches ORT
CPU exactly. The fault therefore sits in the NPU compiler/driver stack, not in
the ONNX graph. Only the query bucket (32) of one embedder was attempted. The
preregistered passage bucket (384), the reranker and the OCR graphs were not,
so K3 is established for this driver/runtime pair, not for every graph.

### K4 / D2 (250 MB)

| Component | Bytes |
|---|---:|
| ORT CPU runtime (installed) | 14,877,304 |
| Best parity-passing e5-class embedder (e5-small fp32) | 470,268,510 |
| Best parity-passing reranker (gte fp32) | 1,224,105,101 |
| **Models alone** | **1,694,373,611** |
| Total | 1,709,250,915 |

**K4 does not fire**: the models alone already exceed D2 by 6.8×, so the
§6 rule reports a model-budget miss instead of attributing it to ORT. The ORT
runtime is 6% of D2. For scale only (not part of the K4 arithmetic): Bekko
`published-default` (130 MB) plus hs-rerank-1 `published-default` (161 MB) is
291 MB of models.

### Performance summary

| System | Query p95 | Depth-50 rerank p95 | OCR page p95 | Passages/s | Added peak RSS | Download (model bytes) |
|---|---:|---:|---:|---:|---:|---:|
| e5-small fp32 | 3.41 ms | — | — | 32.3 | — | 470.3 MB |
| bekko-a8m published-default | 1.22 ms | — | — | 153.9 | — | 130.1 MB |
| gte-reranker fp32 | — | 9,934 ms | — | — | — | 1,224.1 MB |
| hs-rerank-1 published-default | — | 4,966 ms | — | — | — | 160.6 MB |
| PP-OCRv6 tiny fp32 | — | — | 724 ms | — | 0.43 GB isolated / 1.17 GB gate | 6.2 MB |

No retrieval-quality table is reported: this gate creates no relevance
judgments, and the nDCG@10 columns are parity diagnostics on public qrels, not
model comparisons (K2 is deferred to the Stage A bake-offs; OCR K2 to WP-2.11).

## 3. Analysis

### 3.1 What the fired criteria say about ONNX Runtime

- **Embedder K1 reflects the proxies' compute, not the runtime.** On the same
  ORT build, profile, and passages, Bekko runs 5× faster than e5-small and
  gety-embed-v0 (an e5-small fine-tune exported by its publisher) clears 56
  passages/s while the e5-small proxy reaches 32.3. The supplementary rows
  cannot change the frozen verdict (amendment 2), but they answer its question:
  a smaller-compute model meets the budget on ORT. The gety-vs-e5 gap on the
  same architecture is unexplained here (export graph differences are one
  candidate) and is worth checking in WP-2.2.
- **Reranker K1 reflects the budget, not the runtime.** 50 cross-encoder pairs
  of about 180 tokens are about 9,000 tokens of encoder work per query. Even
  hs-rerank-1, with about 15M parameters active per pair, needs 2.3 s median.
  250 ms at depth 50 needs roughly a 20× faster model or a shallower depth on
  this hardware, whatever the engine. The Bekko card claims native OpenVINO ran
  about 5.5× faster than ORT on an x86 CPU. That is vendor evidence and was not
  measured (amendment 2); even if it held, it would not close a 20× gap.
- **OCR** passes O1 and O3 by wide margins, and O2 on the isolated reading
  the maintainer chose at H5.
- **K3** is a driver/compiler failure on this stack. It does not bear on the
  CPU-default runtime, and ADR-0019 already keeps the NPU optional with CPU
  fallback.

### 3.2 Quantization near-misses (parity is not relaxed)

- e5-small int8-dynamic: mean cosine 0.9967 passes, but neighbor Recall@100
  is 0.8967 (needs ≥0.98).
- gety-embed-v0 published-uint8: mean cosine 0.9898 (needs ≥0.99).
- hs-rerank-1 int8-dynamic: mean τ-b 0.9451 (needs ≥0.95), worst list 0.9069.
- Every derived int8 static-QDQ variant collapsed (cosine ≈0.7, τ-b 0,
  OCR CER 70%). MinMax calibration with 128 samples, as preregistered, is not
  usable for these graphs.

### 3.3 Threats to validity

1. **Contamination during timed series.** The quiet window (§4.3) is checked
   only before each series. Another agent's `cargo test`, `unittest`, and
   dataset jobs ran during this lane's series (about 16:24 and 16:43). The gte
   fp32 series (finished 16:55) is affected: its p95 confidence interval is
   wide (8.6–10.1 s). Its p50 of 8.46 s alone misses the budget by 34×, so the
   verdict does not depend on it. Two idle MCP server processes started at
   17:14 (about 3 CPU-seconds in total) during the hs-rerank-1 series, which is
   negligible. The PP-OCRv5 mobile row was the most affected (bursts of
   4.6–12.7 s) and is superseded.
2. **Unexplained earlier gte run.** A 12:52 gte fp32 series, with an open quiet
   window, measured 23.56 s p95 (archived outside the repo as
   `reranker-fp32-partial.json`). That is 2.4× the 16:55 row. The cause is not
   established. Both runs miss the budget by more than an order of magnitude.
3. **Amendment 4 was decided after the PP-OCRv5 row was seen** (that row had
   clean quality, CER 0.30%, and no clean timing). The replacement is the
   maintainer's decision and is stated in the preregistration. PP-OCRv6 tiny's
   CER (0.70%) is higher than v5's on these synthetic pages; neither is an O4
   quality verdict.
4. **References.** gety-embed-v0 and hs-rerank-1 are compared with their fp16
   checkpoints computed in fp32, not with fp32 checkpoints (stated in
   amendments 2 and 3). gety-embed-v0's e5 prefixes are assumed.
5. **Raw-sample loss.** Before `ccd8ffb` both rerankers wrote raw timings to
   the same path, so the hs-rerank-1 run overwrote gte's raw fp32 sample array.
   gte's aggregates in `reranker.json` are intact.
6. **Per-row commit.** The result files do not record which harness commit
   produced each row; §3.4 lists the post-measurement changes.

### 3.4 Harness and analysis changes after measurement

Every change after a row was measured is listed here. None relaxes a
tolerance or target.

| Commit | Change | Effect on this report |
|---|---|---|
| `c3d4208`, `c1ba288`, `c5121dc` | Florence decode stops at the 1,024-token bound; static NPU export fixed for Transformers 5 and padded to 32; NPU probe tokens frozen in the CPU environment; removed EP option dropped | Florence and NPU rows rerun; the first Florence attempt (decode overflow) is archived |
| `68456a8` | `openvino` runtime pinned and loaded; static export uses eager attention (the NPU compiler rejects SDPA's `IsNaN`); each NPU attempt runs in a child process; NPU parity uses pooled embeddings (§5) instead of token 0 | K3 measurable. Parity fails under both the old token-0 comparison (0.972) and the §5 comparison (0.908) |
| `f8d6f8a` | `ocr-memory` isolated O2 probe | Adds the 0.43 GB reading. The exporter's `k1_ocr` verdict still uses the gate figure |
| `d35ffa8` | K4 counts only the e5-class embedder (§6 excludes ModernBERT; the exporter had picked Granite's smaller fp32) | K4 bytes corrected (embedder 390 → 470 MB); verdict unchanged |
| `ccd8ffb` | Raw reranker timings kept per model | Prevents threat 5 recurring |

## 4. Decision and follow-ups

Per §6, no fired criterion is waived or retuned. This report recommends, for
gate H5:

- **Embedder role.** K1 fired on the proxies. On the evidence of amendment 2
  it is a model-compute miss that ORT clears with a smaller model. Recommend
  that ADR-0019 stand for this role, and that the Stage A embedder bake-off
  (WP-2.2) include compact candidates such as Bekko, rather than starting a
  challenger engine (WP-2.3) for embedders.
- **Reranker role.** K1 fired. The depth-50 / 250 ms budget is out of reach of
  any measured cross-encoder on T1-class CPUs, by 20–40×. WP-2.3 on another
  engine would not plausibly close that gap. Recommend an ADR that revisits the
  reranker budget or depth (or makes reranking an opt-in Refined stage) before
  any engine bake-off. If the maintainer still wants a challenger measured,
  WP-2.3 starts for the reranker role only.
- **OCR role. Decided at H5 (maintainer, 2026-11-27):** the isolated O2
  reading decides, so PP-OCRv6 tiny passes O1–O3 on ORT, K1 does not fire for
  OCR, and WP-2.3 does not start for OCR.
- **Florence.** Out of the CPU tier on any engine; no K1. VLM transcription
  stays a gated non-default pack (ADR-0021).
- **K3.** Fired on OpenVINO 2025.1 with NPU driver 32.0.100.3717. Keep Auto
  CPU-only (as today) and retest the NPU when ORT ships a newer OpenVINO EP or
  the driver updates, with the 384 passage bucket and the reranker/OCR graphs.
- **K4.** Does not fire. The default path's model bytes (1.69 GB with the
  proxies) are a model-budget miss for D2 that the bake-offs must solve.
- **K2.** Not evaluable here; deferred to Stage A (OCR to WP-2.11).

No ADR is created by this report. The remaining H5 decisions (embedder and
reranker roles) and their ADR are the maintainer's.

## 5. Reproduction

1. Create the two environments and install pinned requirements
   (`tools/model-export/README.md`); opt out of OpenVINO telemetry.
2. `prepare-text`, `prepare-ocr`, then the gate commands in §1 under the
   T1-emulated profile on a quiet machine. Each gate has a 1,800 s default
   ceiling (`--timeout-seconds`); runs here used up to 5,400 s for the
   reranker and Florence gates.
3. `export-results` writes `summary-data.json` and `raw-results/`.

Raw per-sample timings, model files, quantized variants, and archived
superseded rows stay in the external workspace and are not committed. They are
regenerated by the commands above.
