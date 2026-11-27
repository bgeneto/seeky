# mmarco-pt-en — dataset notice

This dataset is downloaded for internal Seeky evaluation only. It is
never redistributed, never committed, and never shipped in the product.
The prepared files live in `data/`, which git ignores; only this notice,
`manifest.json`, and `dataset-lock.json` enter the repository.

## Provenance

- Source revision: `6d039c4638c0ba3e46a9cb7b498b145e7edc6230`
- Dataset ID: `mmarco-pt-en`
- Layout: `beir`
- Prepared by: `tools/dataset-fetch` transform v1 (seed `dataset-transform-v1`)

| Source file | Bytes | SHA-256 |
|---|---:|---|
| `https://huggingface.co/datasets/unicamp-dl/mmarco/resolve/6d039c4638c0ba3e46a9cb7b498b145e7edc6230/data/google/collections/english_collection.tsv` | 3061567852 | `86e0c5820be6b22280337a67e54cbb626645453d9ac3c377bac45abb81c5653d` |
| `https://huggingface.co/datasets/unicamp-dl/mmarco/resolve/6d039c4638c0ba3e46a9cb7b498b145e7edc6230/data/google/queries/dev/portuguese_queries.dev.small.tsv` | 322542 | `3aa1bc9e67c009c96180864b37546eb9562a78e3a3f663d0e1a70f6aea6eb541` |
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

- Dataset fingerprint: `fc4a8a12748a9aa55348e3e16ddb883edc24e1bd27f76abff2d1cc3478e81966`
- Corpus SHA-256: `818f5dc49dd08b20786dcfd9cb82990eea6fc872179f3392e2a106acf8e17f34`
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
python -m dataset_fetch prepare --dataset mmarco-pt-en --cache <cache>
python -m dataset_fetch verify --dataset mmarco-pt-en
```
