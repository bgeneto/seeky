# qrels-drafter (development tooling)

Offline drafter for the WP-1.4 draft query and candidate-judgment set defined by
[SPEC-0004](../../docs/specs/SPEC-0004-sdc-corpus-and-judgments.md) (0.3,
R15–R27). It writes only into `bench/qrels/sdc/drafts/<set-id>/`, the quarantined
area that is never benchmark-eligible. Nothing here ships, and no engine crate
imports it.

Every record it writes is `state: "draft"` with `verified_by: []`. Tool and LLM
grades are candidate data: gate H6 (a human) verifies every query intent and
every relevance grade before any split can be frozen.

## Category split (SPEC-0004 4.6)

| Drafter | Categories | Provenance |
|---|---|---|
| deterministic templates | `known_item`, `exact_identifier`, `needle_in_haystack`, `mixed_semantic_metadata`, `filename_partial`, `code_search` | `tool:qrels-drafter@0.1.0` + `tool_config_sha256` |
| local instruct model | `conceptual`, `exploratory`, `cross_language` | `llm:qwen3-0.6b@23749fef…` + `llm_prompt_sha256` |

A template may only copy corpus wording where copying is faithful (an
identifier, a filename, a needle phrase, a title, a metadata filter). Semantic
paraphrase and pt↔en translation need the model, because a copied phrase would
favour lexical retrieval. The generator's `judgments validate` enforces the same
boundary.

LLM queries pass an anti-copy guard: no shared 8-token shingle with the target,
no copied 5-token verbatim span, and at most 60 % content-token reuse
(`config.GUARD`). Rejected drafts are replaced by the next deterministic anchor.

## Exact model and configuration

Default profile `qwen3-0.6b` (chosen by the bake-off below):

| Field | Value |
|---|---|
| Model | Qwen3-0.6B, Apache-2.0 |
| Revision | `23749fefcc72300e3a2ad315e1317431b06b590a` |
| Weight file | `Qwen3-0.6B-Q8_0.gguf` (639,446,688 bytes) |
| Weight SHA-256 | `9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031` |
| Mode | non-thinking (`/no_think`, thinking blocks stripped defensively) |
| Decode | temperature 0.7, top-p 0.8, top-k 20, presence penalty 1.5, seed 42, 200 tokens, 8 threads |
| Runtime | llama.cpp `b12815` CPU x64, `llama-completion.exe` |
| Prompt version | `qrels-drafter-prompts-v1` (hashed per record) |
| Seeds | draft `sdc-v1-draft-v1`, split `sdc-v1-split-v1` |

Alternative profile `qwen2.5-1.5b-instruct` (kept for comparison and reuse:
`--profile qwen2.5-1.5b-instruct`): Apache-2.0, revision
`91cad51170dc346986eccefdc2dd33a9da36ead9`, `qwen2.5-1.5b-instruct-q4_k_m.gguf`,
SHA-256 `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e`,
greedy decoding (temperature 0, top-k 1, seed 42).

Licenses, URLs, and archive digests are in [NOTICE.md](NOTICE.md).

## Model choice (bounded bake-off, 2026-11-27)

24 fixed prompts over `sdc-s` targets: 8 `conceptual`, 8 `cross_language`
(pt↔en, both directions), 8 `exploratory`. One call per prompt (up to two
JSON-repair retries), greedy sampling for Qwen2.5 and the card's non-thinking
sampling for Qwen3. Raw rows: `bakeoff-2026-11-27.json`.

| Model | Quant | Strict JSON | No copy | Language | Mean words | Median latency | Retries | Grade probe |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| qwen2.5-1.5b-instruct | Q4_K_M | 24/24 | 23/24 | 14/24 | 4.2 | 2.12 s | 2 | 3/3 |
| qwen3-0.6b | Q8_0 | 24/24 | 21/24 | 20/24 | 5.8 | 2.7 s | 0 | 3/3 |

Decision rule, fixed before the numbers: both models must pass the validity
(≥ 23/24), no-copy (≥ 20/24), and grading (3/3) gates; then the model with
materially better language correctness (≥ 2 prompts ahead) wins; a tie goes to
the smaller, faster model.

**Decision: `qwen3-0.6b`.** Both pass every gate. Qwen3 is 6 of 24 ahead on
language correctness — Qwen2.5-1.5B answered Portuguese prompts in English and
reversed the translation direction on several `cross_language` prompts, which
would corrupt the slice this category exists to measure. Qwen3's two extra
copy rejections are replaced deterministically by the next anchor and cost
latency, not quality. Qwen3 is the slower of the two here (2.7 s vs 2.12 s per
call including a cold model load) because it writes longer queries; quality
outranks that difference under the stated rule.

The template categories are unaffected: they are tool-drafted in both profiles,
and `tool_config_sha256` does not depend on the model.

## Setup (network used only by the explicit fetch)

```powershell
# Downloads the pinned models and runner into %LOCALAPPDATA%\seeky-dev\llm and
# verifies every SHA-256 pin. Run once; `draft` itself never opens a network.
$env:PYTHONPATH = "tools/qrels-drafter"
python -m qrels_drafter fetch-model
python -m qrels_drafter verify-model
python -m qrels_drafter verify-model --profile qwen2.5-1.5b-instruct
```

`fetch-model --dry-run` prints the pinned URLs without downloading. Nothing else
in this tool has a network code path.

## Drafting the full set

Build `sdc-s` first with the committed generator (never commit the corpus):

```powershell
$env:PYTHONPATH = "tools/sdc-generator"
python -m sdc_generator build `
  --profile bench/corpora/sdc/profiles/sdc-s.json `
  --seed sdc-s-v1 `
  --sources bench/corpora/sdc/sources `
  --cache "$env:LOCALAPPDATA\seeky-dev\sdc-cache" `
  --output bench/corpora/sdc/sdc-s
python -m sdc_generator verify --output bench/corpora/sdc/sdc-s
# must print 1d65b8ff04091850b8deefa34f5658bee0b87ec4ff29667f002f6cec88ac2ef0
```

Then draft, audit, and validate:

```powershell
$env:PYTHONPATH = "tools/qrels-drafter"
python -m qrels_drafter draft `
  --corpus bench/corpora/sdc/sdc-s `
  --output bench/qrels/sdc/drafts/sdc-v1 `
  --profile qwen3-0.6b `
  --llama-cli "$env:LOCALAPPDATA\seeky-dev\llm\llama.cpp-b12815\llama-completion.exe"

python -m qrels_drafter audit --set bench/qrels/sdc/drafts/sdc-v1

$env:PYTHONPATH = "tools/sdc-generator"
python -m sdc_generator judgments validate --allow-draft `
  --set bench/qrels/sdc/drafts/sdc-v1 `
  --corpus bench/corpora/sdc/sdc-s
```

`draft` regenerates the whole directory deterministically from the corpus, the
plan, and the pinned model. For a template-only smoke of the pipeline (no model),
add `--templates-only`, but that cannot satisfy the 600-query minima.

Paths in commands use environment variables only; no personal path is committed.

## What the committed draft contains

732 queries, 366 in `dev` and 366 in `test`, assigned by the SPEC-0004 5.4
stratified procedure over `(category, language_slice, configuration)`:

| Category | Queries | Drafter |
|---|---:|---|
| `known_item` | 88 | tool |
| `exact_identifier` | 80 | tool |
| `needle_in_haystack` | 80 | tool |
| `mixed_semantic_metadata` | 84 | tool |
| `filename_partial` | 80 | tool |
| `code_search` | 80 | tool (`code_enabled`) |
| `conceptual` | 80 | LLM |
| `exploratory` | 80 | LLM |
| `cross_language` | 80 | LLM (`cross_lingual`) |

Language slices: 196 Portuguese, 356 English, 80 cross-lingual, 76 `other`
(Spanish 26, French 25, German 25), and 24 non-Latin non-regression (`ja-JP`,
`el-GR`). Every query has candidate document judgments
and at least one passage judgment, with evidence passages for grades 2/3 and
explicit grade-0 rows (absence still means unjudged). Pools are empty: no system
has been run, so no pooling has happened.

`needle_in_haystack` is English-only because every long-report document in the
committed `sdc-s` generation is `en-US`; a Portuguese needle query would have no
target. R17 sets no language minimum for that category.

## Tests

```powershell
cd tools\qrels-drafter
python -m unittest discover -s tests -v
```

The hermetic suite drafts the committed `sdc-smoke` corpus with a deterministic
stub model: byte-identical reruns, provenance scope, draft-only state, evidence
and span rules, the anti-copy guard, a socket-denial test, and a cross-check that
`sdc_generator judgments validate --allow-draft` accepts the result. The
committed-draft tests fail loudly if a record stops being an unverified draft.

## Known gaps

- The model is a 1.5B draft writer: its queries and grades are candidates for
  H6, not authority. Expect the reviewer to rewrite some wording.
- Greedy decoding (Qwen2.5) and fixed-seed sampling (Qwen3) are reproducible on
  the same runner build and thread count, not guaranteed across builds. The
  committed files are the artifact of record.
- No pooling, no frozen hashes, no `test` exposure: the manifest stays
  `state: "draft"`, `test_exposure: "unexposed"`.
