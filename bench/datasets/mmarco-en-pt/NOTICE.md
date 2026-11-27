# mmarco-en-pt — dataset notice

This dataset is downloaded for internal Seeky evaluation only. It is
never redistributed, never committed, and never shipped in the product.
The prepared files live in `data/`, which git ignores; only this notice,
`manifest.json`, and `dataset-lock.json` enter the repository.

## Provenance

- Source revision: `6d039c4638c0ba3e46a9cb7b498b145e7edc6230`
- Dataset ID: `mmarco-en-pt`
- Layout: `beir`
- Prepared by: `tools/dataset-fetch` transform v1 (seed `dataset-transform-v1`)

| Source file | Bytes | SHA-256 |
|---|---:|---|
| `https://huggingface.co/datasets/unicamp-dl/mmarco/resolve/6d039c4638c0ba3e46a9cb7b498b145e7edc6230/data/google/collections/portuguese_collection.tsv` | 3431011785 | `bd0074d22ec0deacb08e9f9851f8f3aeb6d03b0d59b1b05f926ad4961a229520` |
| `https://huggingface.co/datasets/unicamp-dl/mmarco/resolve/6d039c4638c0ba3e46a9cb7b498b145e7edc6230/data/google/queries/dev/english_queries.dev.small.tsv` | 290192 | `988cb8424d997bd5cf829753de7dfe7496efcdba318186c5d904a2d5c410d2e7` |
| `https://huggingface.co/datasets/unicamp-dl/mmarco/resolve/6d039c4638c0ba3e46a9cb7b498b145e7edc6230/data/qrels.dev.small.tsv` | 143300 | `ddc607dbe7b748d7168e8675a242f0811d47febaa2e69d3af09d7ab249c68d7e` |

## License and terms

- License: `MS-MARCO-Research`
- License URL: https://microsoft.github.io/msmarco/
- Terms: https://huggingface.co/datasets/unicamp-dl/mmarco/raw/6d039c4638c0ba3e46a9cb7b498b145e7edc6230/README.md
- Terms SHA-256: `bff638032720d33c3e99843ebde1b12a6b65ab517d0491ab8cd0a89737a297ca`
- Redistribution: `download-only`

The pinned terms digest is checked by `prepare`; a changed or
unavailable terms document is a hard failure, not a warning.

## Prepared data

- Dataset fingerprint: `83c4a3b5bc2f3d22fb32ec99b62f03e69d235fd798d09cfc844ccfcd20f41465`
- Corpus SHA-256: `30f702672aa65bc5c47ce114e1218f96e078b7e23f00118faea9b03f470b4d63`
- `dev`: 3490 queries, 3716 qrels (3716 positive)
- `test`: 3490 queries, 3721 qrels (3721 positive)
- Language slices: cross_lingual
- Categories: conceptual

## Transform notes

- `cross_lingual`: True
- `source_format`: mmarco-tsv
- `split_source`: deterministic carve-out of dev (no public test qrels)
- `transform_seed`: dataset-transform-v1

## Reproduction

```text
python -m dataset_fetch prepare --dataset mmarco-en-pt --cache <cache>
python -m dataset_fetch verify --dataset mmarco-en-pt
```
