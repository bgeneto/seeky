# beir-fiqa — dataset notice

This dataset is downloaded for internal Seeky evaluation only. It is
never redistributed, never committed, and never shipped in the product.
The prepared files live in `data/`, which git ignores; only this notice,
`manifest.json`, and `dataset-lock.json` enter the repository.

## Provenance

- Source revision: `5e59eeb3a7df6b85882112b747008547c21587ea`
- Dataset ID: `beir-fiqa`
- Layout: `beir`
- Prepared by: `tools/dataset-fetch` transform v1 (seed `dataset-transform-v1`)

| Source file | Bytes | SHA-256 |
|---|---:|---|
| `https://huggingface.co/datasets/mteb/fiqa/resolve/5e59eeb3a7df6b85882112b747008547c21587ea/corpus.jsonl` | 47027289 | `a5e31bffdcbab9dbe0ff849faa170a6e71b60587ff3a99a4272584183e64d729` |
| `https://huggingface.co/datasets/mteb/fiqa/resolve/5e59eeb3a7df6b85882112b747008547c21587ea/queries.jsonl` | 599879 | `95edd2939eda9de0b5bdae18352eb9b677a133d5965ec55dc911c863f9af7bb9` |
| `https://huggingface.co/datasets/mteb/fiqa/resolve/5e59eeb3a7df6b85882112b747008547c21587ea/qrels/dev.tsv` | 18327 | `03b27e547cd29dc721c3b93ce8ddd70df6b2d0ce954d8ef3659d386e8cd72c11` |
| `https://huggingface.co/datasets/mteb/fiqa/resolve/5e59eeb3a7df6b85882112b747008547c21587ea/qrels/test.tsv` | 25256 | `6adc2a640dcdd22bb8b3858f89107adef2a7c3db20a63550dfa7a0f71e379e44` |

## License and terms

- License: `CC-BY-SA-4.0`
- License URL: https://creativecommons.org/licenses/by-sa/4.0/
- Terms: https://huggingface.co/datasets/BeIR/fiqa/raw/979c07a7cb5ccc6ca009792241fa1250b98055dd/README.md
- Terms SHA-256: `aa8389d527feaffdf7ac73b708914155df2781ad9d2a8d146287f1abc7fc762f`
- Redistribution: `download-only`

The pinned terms digest is checked by `prepare`; a changed or
unavailable terms document is a hard failure, not a warning.

## Prepared data

- Dataset fingerprint: `5eb927312d7f75885f3da3cab6840c1b98b3b1777781eed5d6e6bc42e1555d06`
- Corpus SHA-256: `5cbb5c1aff058e08209660f4bb56f94f193aec4d7502ac70e99d5f0c9ef48544`
- `dev`: 500 queries, 1236 qrels (1236 positive)
- `test`: 648 queries, 1705 qrels (1705 positive)
- Language slices: en
- Categories: conceptual

## Transform notes

- `dev_split_source`: https://huggingface.co/datasets/mteb/fiqa/resolve/5e59eeb3a7df6b85882112b747008547c21587ea/qrels/dev.tsv
- `empty_documents_omitted`: 38
- `qrels_dropped_for_empty_documents`: {"dev": 2, "test": 1}
- `queries_dropped_for_empty_documents`: {"dev": 0, "test": 0}
- `query_filter`: queries with at least one qrel in the split
- `source_format`: mteb-beir
- `test_split_source`: https://huggingface.co/datasets/mteb/fiqa/resolve/5e59eeb3a7df6b85882112b747008547c21587ea/qrels/test.tsv
- `transform_seed`: dataset-transform-v1

## Reproduction

```text
python -m dataset_fetch prepare --dataset beir-fiqa --cache <cache>
python -m dataset_fetch verify --dataset beir-fiqa
```
