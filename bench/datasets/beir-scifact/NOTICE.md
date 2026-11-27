# beir-scifact — dataset notice

This dataset is downloaded for internal Seeky evaluation only. It is
never redistributed, never committed, and never shipped in the product.
The prepared files live in `data/`, which git ignores; only this notice,
`manifest.json`, and `dataset-lock.json` enter the repository.

## Provenance

- Source revision: `cf10ab6856b15b0e670ef8ae5dae4e266c12d035`
- Dataset ID: `beir-scifact`
- Layout: `beir`
- Prepared by: `tools/dataset-fetch` transform v1 (seed `dataset-transform-v1`)

| Source file | Bytes | SHA-256 |
|---|---:|---|
| `https://huggingface.co/datasets/mteb/scifact/resolve/cf10ab6856b15b0e670ef8ae5dae4e266c12d035/corpus.jsonl` | 8023638 | `f0d32db0d156b526d75921ed7a76f2cb912902631c87248c5c97c617bad0b60c` |
| `https://huggingface.co/datasets/mteb/scifact/resolve/cf10ab6856b15b0e670ef8ae5dae4e266c12d035/queries.jsonl` | 129085 | `9db7df096f7414435d52bafcbacf814c30cea50eb565c1e8fa6d11440759bba8` |
| `https://huggingface.co/datasets/mteb/scifact/resolve/cf10ab6856b15b0e670ef8ae5dae4e266c12d035/qrels/train.tsv` | 14502 | `a53f2114831916c096b6c37d9e54da68cef4efdcdbd5ed46533601af972acf1d` |
| `https://huggingface.co/datasets/mteb/scifact/resolve/cf10ab6856b15b0e670ef8ae5dae4e266c12d035/qrels/test.tsv` | 5389 | `0864bb985e0ca2367ba217977e72004d549054b2b06666ed9d4825ac7c21284c` |

## License and terms

- License: `CC-BY-SA-4.0`
- License URL: https://creativecommons.org/licenses/by-sa/4.0/
- Terms: https://huggingface.co/datasets/BeIR/scifact/raw/b3b5335604bf5ee3c4447671af975ea25143d4f5/README.md
- Terms SHA-256: `b5f57be1839fdb75867073986a019a78afe0a149950f79d1165509efc5e5cf2f`
- Redistribution: `download-only`

The pinned terms digest is checked by `prepare`; a changed or
unavailable terms document is a hard failure, not a warning.

## Prepared data

- Dataset fingerprint: `07305042eaf2792854974f90bf553d6529a0126d130a93922aed896ec7e3387f`
- Corpus SHA-256: `52fd2923f7f6942f38dfc583645ac50ee558c9ce488ad9792971abd18ad1d17f`
- `dev`: 809 queries, 919 qrels (919 positive)
- `test`: 300 queries, 339 qrels (339 positive)
- Language slices: en
- Categories: conceptual

## Transform notes

- `dev_split_source`: https://huggingface.co/datasets/mteb/scifact/resolve/cf10ab6856b15b0e670ef8ae5dae4e266c12d035/qrels/train.tsv
- `query_filter`: queries with at least one qrel in the split
- `source_format`: mteb-beir
- `test_split_source`: https://huggingface.co/datasets/mteb/scifact/resolve/cf10ab6856b15b0e670ef8ae5dae4e266c12d035/qrels/test.tsv
- `transform_seed`: dataset-transform-v1

## Reproduction

```text
python -m dataset_fetch prepare --dataset beir-scifact --cache <cache>
python -m dataset_fetch verify --dataset beir-scifact
```
