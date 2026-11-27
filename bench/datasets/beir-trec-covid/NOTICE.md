# beir-trec-covid — dataset notice

This dataset is downloaded for internal Seeky evaluation only. It is
never redistributed, never committed, and never shipped in the product.
The prepared files live in `data/`, which git ignores; only this notice,
`manifest.json`, and `dataset-lock.json` enter the repository.

## Provenance

- Source revision: `0724773f091de506941c2108e1647af956de07f7`
- Dataset ID: `beir-trec-covid`
- Layout: `beir`
- Prepared by: `tools/dataset-fetch` transform v1 (seed `dataset-transform-v1`)

| Source file | Bytes | SHA-256 |
|---|---:|---|
| `https://huggingface.co/datasets/mteb/trec-covid/resolve/0724773f091de506941c2108e1647af956de07f7/corpus.jsonl` | 200444373 | `5befacfb140bab87bc9d8026439b3575aa78ce9b11a4b9b34d6a6a3fb9e2a6bb` |
| `https://huggingface.co/datasets/mteb/trec-covid/resolve/0724773f091de506941c2108e1647af956de07f7/queries.jsonl` | 4753 | `090595ce05258400d1f77597e4b83aadd98b2be690a655af68c60eb2c44808fc` |
| `https://huggingface.co/datasets/mteb/trec-covid/resolve/0724773f091de506941c2108e1647af956de07f7/qrels/test.tsv` | 980831 | `10669ab7d526cb04f52079139fd88c3d467a0776441b046567f540582798982b` |

## License and terms

- License: `CC-BY-SA-4.0`
- License URL: https://creativecommons.org/licenses/by-sa/4.0/
- Terms: https://huggingface.co/datasets/BeIR/trec-covid/raw/7e16fde3016c639c7f856e803f4bab92645562c4/README.md
- Terms SHA-256: `d169709df9bed0dfecc17ece6b67499f9fcce7340aa433ad5450ddd8ab9656cd`
- Redistribution: `download-only`

The pinned terms digest is checked by `prepare`; a changed or
unavailable terms document is a hard failure, not a warning.

## Prepared data

- Dataset fingerprint: `29aa20d215bc46e3d2e5b452456f505426eb0829c534bdb82b5ff95ad777a879`
- Corpus SHA-256: `b6e9e682087ac7241db39c880d92f442b1ecfd2bbb0b346758f44b0cc9b1f2d9`
- `dev`: 25 queries, 32052 qrels (10843 positive)
- `test`: 25 queries, 34284 qrels (13830 positive)
- Language slices: en
- Categories: conceptual

## Transform notes

- `dev_split_source`: https://huggingface.co/datasets/mteb/trec-covid/resolve/0724773f091de506941c2108e1647af956de07f7/qrels/test.tsv
- `empty_documents_omitted`: 1
- `negative_qrel_grades_mapped_to_zero`: 2
- `qrels_dropped_for_empty_documents`: {"dev": 0, "test": 0}
- `queries_dropped_for_empty_documents`: {"dev": 0, "test": 0}
- `query_filter`: queries with at least one qrel in the split
- `source_format`: mteb-beir
- `split_source`: deterministic 50/50 carve-out of source test qrels (no public dev/train qrels)
- `test_split_source`: https://huggingface.co/datasets/mteb/trec-covid/resolve/0724773f091de506941c2108e1647af956de07f7/qrels/test.tsv
- `transform_seed`: dataset-transform-v1

## Reproduction

```text
python -m dataset_fetch prepare --dataset beir-trec-covid --cache <cache>
python -m dataset_fetch verify --dataset beir-trec-covid
```
