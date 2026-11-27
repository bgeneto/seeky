# quati-pt — dataset notice

This dataset is downloaded for internal Seeky evaluation only. It is
never redistributed, never committed, and never shipped in the product.
The prepared files live in `data/`, which git ignores; only this notice,
`manifest.json`, and `dataset-lock.json` enter the repository.

## Provenance

- Source revision: `e5279055bba3e7ba1bece5c0eddd0ba232df49c3`
- Dataset ID: `quati-pt`
- Layout: `beir`
- Prepared by: `tools/dataset-fetch` transform v1 (seed `dataset-transform-v1`)

| Source file | Bytes | SHA-256 |
|---|---:|---|
| `https://huggingface.co/datasets/unicamp-dl/quati/resolve/e5279055bba3e7ba1bece5c0eddd0ba232df49c3/quati_1M.tsv` | 1173426846 | `096b262a3444df3487eecedbdb26b9e443481b7d70d5cea9c6cbd0bf11219ec4` |
| `https://huggingface.co/datasets/unicamp-dl/quati/resolve/e5279055bba3e7ba1bece5c0eddd0ba232df49c3/topics/quati_test_topics.tsv` | 2751 | `61936c7b582b3d9b4d47ec7ff94033841578aa2c843c31b9a54f01e3549db466` |
| `https://huggingface.co/datasets/unicamp-dl/quati/resolve/e5279055bba3e7ba1bece5c0eddd0ba232df49c3/qrels/quati_1M_qrels.txt` | 68982 | `aafab4294572a043974bcb5fccfe76e55267e37d5d76d648ab1d3697d13f6f76` |

## License and terms

- License: `CC-BY-4.0`
- License URL: https://creativecommons.org/licenses/by/4.0/
- Terms: https://huggingface.co/datasets/unicamp-dl/quati/raw/e5279055bba3e7ba1bece5c0eddd0ba232df49c3/README.md
- Terms SHA-256: `8dec16ddf7ff6722ea96cbc3d921e691782e101c46141367a7c89ea599a8103c`
- Redistribution: `download-only`

The pinned terms digest is checked by `prepare`; a changed or
unavailable terms document is a hard failure, not a warning.

## Prepared data

- Dataset fingerprint: `142a0be605f865bb55fab0bed4460ee591a1db819b014dc06fd74f4be37f6620`
- Corpus SHA-256: `046680a816be784a7cb7491f8794e37e3e334327bfbf214dcd3b18b11bb51d99`
- `dev`: 25 queries, 1007 qrels (484 positive)
- `test`: 25 queries, 926 qrels (410 positive)
- Language slices: pt
- Categories: conceptual

## Transform notes

- `source_format`: quati-1M
- `source_language`: pt
- `split_source`: deterministic 50/50 carve-out of judged topics (single public qrels set)
- `transform_seed`: dataset-transform-v1

## Reproduction

```text
python -m dataset_fetch prepare --dataset quati-pt --cache <cache>
python -m dataset_fetch verify --dataset quati-pt
```
