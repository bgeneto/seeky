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
| local instruct model | `conceptual`, `exploratory`, `cross_language` | `llm:qwen2.5-1.5b-instruct@91cad511…` + `llm_prompt_sha256` |

A template may only copy corpus wording where copying is faithful (an
identifier, a filename, a needle phrase, a title, a metadata filter). Semantic
paraphrase and pt↔en translation need the model, because a copied phrase would
favour lexical retrieval. The generator's `judgments validate` enforces the same
boundary.

LLM queries pass an anti-copy guard: no shared 8-token shingle with the target,
no copied 5-token verbatim span, and at most 60 % content-token reuse
(`config.GUARD`). Rejected drafts are replaced by the next deterministic anchor.

## Exact model and configuration

| Field | Value |
|---|---|
| Model | Qwen2.5-1.5B-Instruct, Apache-2.0 |
| Revision | `91cad51170dc346986eccefdc2dd33a9da36ead9` |
| Weight file | `qwen2.5-1.5b-instruct-q4_k_m.gguf` |
| Weight SHA-256 | `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e` |
| Runtime | llama.cpp `b12815` CPU x64, `llama-completion.exe` |
| Decode | temperature 0, top-k 1, seed 42, 160 tokens, 8 threads |
| Prompt version | `qrels-drafter-prompts-v1` (hashed per record) |
| Seeds | draft `sdc-v1-draft-v1`, split `sdc-v1-split-v1` |

Licenses, URLs, and archive digests are in [NOTICE.md](NOTICE.md).

## Setup (network used only by the explicit fetch)

```powershell
# Downloads the pinned model and runner into %LOCALAPPDATA%\seeky-dev\llm and
# verifies both SHA-256 pins. Run once; `draft` itself never opens a network.
$env:PYTHONPATH = "tools/qrels-drafter"
python -m qrels_drafter fetch-model
python -m qrels_drafter verify-model `
  --model "$env:LOCALAPPDATA\seeky-dev\llm\qwen2.5-1.5b-instruct-q4_k_m.gguf"
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
  --llama-cli "$env:LOCALAPPDATA\seeky-dev\llm\llama.cpp-b12815\llama-completion.exe" `
  --model "$env:LOCALAPPDATA\seeky-dev\llm\qwen2.5-1.5b-instruct-q4_k_m.gguf"

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
- Greedy decoding is reproducible on the same runner build and thread count, not
  guaranteed across builds. The committed files are the artifact of record.
- No pooling, no frozen hashes, no `test` exposure: the manifest stays
  `state: "draft"`, `test_exposure: "unexposed"`.
