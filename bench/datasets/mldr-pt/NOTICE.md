# mldr-pt — dataset notice

This dataset is downloaded for internal Seeky evaluation only. It is
never redistributed, never committed, and never shipped in the product.
The prepared files live in `data/`, which git ignores; only this notice,
`manifest.json`, and `dataset-lock.json` enter the repository.

## Provenance

- Source revision: `d67138e705d963e346253a80e59676ddb418810a`
- Dataset ID: `mldr-pt`
- Layout: `beir`
- Prepared by: `tools/dataset-fetch` transform v1 (seed `dataset-transform-v1`)

| Source file | Bytes | SHA-256 |
|---|---:|---|
| `https://huggingface.co/datasets/Shitao/MLDR/resolve/d67138e705d963e346253a80e59676ddb418810a/mldr-v1.0-pt/corpus.jsonl.gz` | 77507951 | `b6e3f7920972ba93fa9bd131bfe8e4c3686082c0c09910a878ca3e07be34ea45` |
| `https://huggingface.co/datasets/Shitao/MLDR/resolve/d67138e705d963e346253a80e59676ddb418810a/mldr-v1.0-pt/dev.jsonl.gz` | 9032019 | `3a713eb7280fd3005af60e9b17beec758ac9b0ed6c79d5d4c9c75d0d60e255de` |
| `https://huggingface.co/datasets/Shitao/MLDR/resolve/d67138e705d963e346253a80e59676ddb418810a/mldr-v1.0-pt/test.jsonl.gz` | 9078225 | `ca989c96fafa068c496f404bb5d2de52685419b6497601319edb2fc17be019e1` |
| `https://huggingface.co/datasets/Shitao/MLDR/resolve/d67138e705d963e346253a80e59676ddb418810a/qrels/qrels.mldr-v1.0-pt-dev.tsv` | 5224 | `716196e322067ee1eb20d7ea3400db985e8391020e3218c5fd569b160b946622` |
| `https://huggingface.co/datasets/Shitao/MLDR/resolve/d67138e705d963e346253a80e59676ddb418810a/qrels/qrels.mldr-v1.0-pt-test.tsv` | 5198 | `b5ea28baa89328c7089ddcdb0cef19a37ef35adb12cb41ece73bfe88337a075b` |

## License and terms

- License: `MIT`
- License URL: https://spdx.org/licenses/MIT.html
- Terms: https://huggingface.co/datasets/Shitao/MLDR/raw/d67138e705d963e346253a80e59676ddb418810a/README.md
- Terms SHA-256: `6e86f341c878310299c0bea404e7941fba4d499da07476c0fc3780210b90a97c`
- Redistribution: `download-only`

The pinned terms digest is checked by `prepare`; a changed or
unavailable terms document is a hard failure, not a warning.

## Prepared data

- Dataset fingerprint: `471e4f47af3cca3559de978c77736ee5ffdbf4ac5618893fb340b97eb96bb7c9`
- Corpus SHA-256: `4ebb4f421afa897a35b95b6c0390fea20a4d42b2d0fd114684f41ee9b25f87f3`
- `dev`: 200 queries, 200 qrels (200 positive)
- `test`: 200 queries, 200 qrels (200 positive)
- Language slices: pt
- Categories: conceptual

## Transform notes

- `source_format`: mldr
- `source_language`: pt
- `split_source`: native dev and test
- `title_mode`: body-only; MLDR articles start with their title
- `transform_seed`: dataset-transform-v1

## Reproduction

```text
python -m dataset_fetch prepare --dataset mldr-pt --cache <cache>
python -m dataset_fetch verify --dataset mldr-pt
```
