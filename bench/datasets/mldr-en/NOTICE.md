# mldr-en — dataset notice

This dataset is downloaded for internal Seeky evaluation only. It is
never redistributed, never committed, and never shipped in the product.
The prepared files live in `data/`, which git ignores; only this notice,
`manifest.json`, and `dataset-lock.json` enter the repository.

## Provenance

- Source revision: `d67138e705d963e346253a80e59676ddb418810a`
- Dataset ID: `mldr-en`
- Layout: `beir`
- Prepared by: `tools/dataset-fetch` transform v1 (seed `dataset-transform-v1`)

| Source file | Bytes | SHA-256 |
|---|---:|---|
| `https://huggingface.co/datasets/Shitao/MLDR/resolve/d67138e705d963e346253a80e59676ddb418810a/mldr-v1.0-en/corpus.jsonl.gz` | 984905843 | `3fe3c8473eccf8a35deda63981ac838f6a866319d3568e7472ba1a873c9e0341` |
| `https://huggingface.co/datasets/Shitao/MLDR/resolve/d67138e705d963e346253a80e59676ddb418810a/mldr-v1.0-en/dev.jsonl.gz` | 20895359 | `d858aff311937ba2c46309e7be8cecea8e848ae906f8c207cd84cf1fd44b3b15` |
| `https://huggingface.co/datasets/Shitao/MLDR/resolve/d67138e705d963e346253a80e59676ddb418810a/mldr-v1.0-en/test.jsonl.gz` | 82052983 | `e3d79c5cb2c5c635aa9b7908e636cdbc99bb76db5ebe65cbff96acd4a10204c0` |
| `https://huggingface.co/datasets/Shitao/MLDR/resolve/d67138e705d963e346253a80e59676ddb418810a/qrels/qrels.mldr-v1.0-en-dev.tsv` | 5381 | `188a2269c9d3101f90a2d3e8c48f350b7b6f78e984aff324ad0be2ab30811461` |
| `https://huggingface.co/datasets/Shitao/MLDR/resolve/d67138e705d963e346253a80e59676ddb418810a/qrels/qrels.mldr-v1.0-en-test.tsv` | 21491 | `6897fd5db8df40ebc9dd350ebbaacd5bb9e2ca5273cf2855fd06e69ec3c3dd7d` |

## License and terms

- License: `MIT`
- License URL: https://spdx.org/licenses/MIT.html
- Terms: https://huggingface.co/datasets/Shitao/MLDR/raw/d67138e705d963e346253a80e59676ddb418810a/README.md
- Terms SHA-256: `6e86f341c878310299c0bea404e7941fba4d499da07476c0fc3780210b90a97c`
- Redistribution: `download-only`

The pinned terms digest is checked by `prepare`; a changed or
unavailable terms document is a hard failure, not a warning.

## Prepared data

- Dataset fingerprint: `98470904b91a28235e0d928c0a37b1090991349b3f4e9babf8c327b10c2709cb`
- Corpus SHA-256: `e684a1bb0def9e2a192d9a99b8dc8a8a54733598281f68c200e36c4d58289000`
- `dev`: 200 queries, 200 qrels (200 positive)
- `test`: 800 queries, 800 qrels (800 positive)
- Language slices: en
- Categories: conceptual

## Transform notes

- `source_format`: mldr
- `source_language`: en
- `split_source`: native dev and test
- `title_mode`: body-only; MLDR articles start with their title
- `transform_seed`: dataset-transform-v1

## Reproduction

```text
python -m dataset_fetch prepare --dataset mldr-en --cache <cache>
python -m dataset_fetch verify --dataset mldr-en
```
