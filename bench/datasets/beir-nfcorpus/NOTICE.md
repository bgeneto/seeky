# beir-nfcorpus — dataset notice

This dataset is downloaded for internal Seeky evaluation only. It is
never redistributed, never committed, and never shipped in the product.
The prepared files live in `data/`, which git ignores; only this notice,
`manifest.json`, and `dataset-lock.json` enter the repository.

## Provenance

- Source revision: `52ac3f19d3449632d9f00aab0ad34a110fc03816`
- Dataset ID: `beir-nfcorpus`
- Layout: `beir`
- Prepared by: `tools/dataset-fetch` transform v1 (seed `dataset-transform-v1`)

| Source file | Bytes | SHA-256 |
|---|---:|---|
| `https://huggingface.co/datasets/mteb/nfcorpus/resolve/52ac3f19d3449632d9f00aab0ad34a110fc03816/corpus.jsonl` | 5969652 | `ee3db77bc2183e66b9c114e6eca4adf44de381705b1f8c94de8efdd232f0c4ff` |
| `https://huggingface.co/datasets/mteb/nfcorpus/resolve/52ac3f19d3449632d9f00aab0ad34a110fc03816/queries.jsonl` | 180348 | `1b893f53f3f62e8f2949a6db619a9cb058e8d97901a5010e108e60c4ef5fd924` |
| `https://huggingface.co/datasets/mteb/nfcorpus/resolve/52ac3f19d3449632d9f00aab0ad34a110fc03816/qrels/dev.tsv` | 258218 | `b1d38b5e8f78c4a5820bce2b7ec2db54911d7690dc601e76811846b211180bd8` |
| `https://huggingface.co/datasets/mteb/nfcorpus/resolve/52ac3f19d3449632d9f00aab0ad34a110fc03816/qrels/test.tsv` | 279572 | `f8fba6ef3d4dd9c3a242a8ba4ae38276fc3622fce7dcbae764766d564542fd2a` |

## License and terms

- License: `CC-BY-SA-4.0`
- License URL: https://creativecommons.org/licenses/by-sa/4.0/
- Terms: https://huggingface.co/datasets/BeIR/nfcorpus/raw/b5026a0e96e8a7ac4f95f482a596389289d46269/README.md
- Terms SHA-256: `f989282ab56b5a7b9cf2328e2e96bc6a74207fe16b9bd517fe9a2d289b692eb6`
- Redistribution: `download-only`

The pinned terms digest is checked by `prepare`; a changed or
unavailable terms document is a hard failure, not a warning.

## Prepared data

- Dataset fingerprint: `449dc9db91733255261db3766e20a963f395dde928a86a7afe08f127946db866`
- Corpus SHA-256: `5c9e5a61c7fb0b1b972f0f2a2d29ad941991546b1b331187928418c3b693d510`
- `dev`: 324 queries, 11385 qrels (11385 positive)
- `test`: 323 queries, 12334 qrels (12334 positive)
- Language slices: en
- Categories: conceptual

## Transform notes

- `dev_split_source`: https://huggingface.co/datasets/mteb/nfcorpus/resolve/52ac3f19d3449632d9f00aab0ad34a110fc03816/qrels/dev.tsv
- `query_filter`: queries with at least one qrel in the split
- `source_format`: mteb-beir
- `test_split_source`: https://huggingface.co/datasets/mteb/nfcorpus/resolve/52ac3f19d3449632d9f00aab0ad34a110fc03816/qrels/test.tsv
- `transform_seed`: dataset-transform-v1

## Reproduction

```text
python -m dataset_fetch prepare --dataset beir-nfcorpus --cache <cache>
python -m dataset_fetch verify --dataset beir-nfcorpus
```
