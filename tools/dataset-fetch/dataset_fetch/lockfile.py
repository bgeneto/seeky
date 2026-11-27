"""Dataset lock and NOTICE generation (R23: pinned provenance)."""

from __future__ import annotations

import json
from typing import Any

from . import __version__
from .cache import CachedFile
from .manifest import dataset_fingerprint
from .transform import BuildResult, ParsedDataset


def build_lock(
    manifest: dict[str, Any],
    build: BuildResult,
    parsed: ParsedDataset,
    sources: list[CachedFile],
    terms: CachedFile,
) -> dict[str, Any]:
    transform = manifest["transform"]
    return {
        "schema_version": 1,
        "dataset_id": manifest["dataset_id"],
        "layout": manifest["layout"],
        "tool": {"name": "dataset-fetch", "version": __version__},
        "transform": {
            "script": transform["script"],
            "version": transform["version"],
            "seed": transform["seed"],
        },
        "source": {
            "revision": manifest["source"]["revision"],
            "files": [
                {
                    "url": source.url,
                    "size_bytes": source.size_bytes,
                    "sha256": source.sha256,
                }
                for source in sources
            ],
        },
        "license": {
            **manifest["license"],
            "terms_sha256": manifest["terms_sha256"],
        },
        "terms": {
            "url": manifest["license"]["terms_url"],
            "sha256": terms.sha256,
            "size_bytes": terms.size_bytes,
        },
        "local_file_count": len(build.local_hashes),
        "fingerprint": dataset_fingerprint(manifest, build.local_hashes),
        "corpus_sha256": build.corpus_sha256,
        "query_set_sha256": dict(sorted(build.query_set_sha256.items())),
        "counts": build.counts,
        "language_slices": build.language_slices,
        "categories": build.categories,
        "notes": build.notes,
        "reproduce": {
            "command": (
                "python -m dataset_fetch prepare --dataset "
                f"{manifest['dataset_id']} --cache <cache>"
            ),
            "offline_verify": (
                f"python -m dataset_fetch verify --dataset {manifest['dataset_id']}"
            ),
        },
        # Cross-check the parsed dataset against the writer's counters.
        "parsed": {
            "documents": len(parsed.documents),
            "counts": parsed.counts,
            "corpus_sha256": parsed.corpus_sha256,
            "language_slices": parsed.language_slices,
            "categories": parsed.categories,
        },
    }


def render_notice(manifest: dict[str, Any], lock: dict[str, Any]) -> str:
    license_record = manifest["license"]
    lines = [
        f"# {manifest['dataset_id']} — dataset notice",
        "",
        "This dataset is downloaded for internal Seeky evaluation only. It is",
        "never redistributed, never committed, and never shipped in the product.",
        "The prepared files live in `data/`, which git ignores; only this notice,",
        "`manifest.json`, and `dataset-lock.json` enter the repository.",
        "",
        "## Provenance",
        "",
        f"- Source revision: `{manifest['source']['revision']}`",
        f"- Dataset ID: `{manifest['dataset_id']}`",
        f"- Layout: `{manifest['layout']}`",
        f"- Prepared by: `{manifest['transform']['script']}` transform "
        f"v{manifest['transform']['version']} (seed `{manifest['transform']['seed']}`)",
        "",
        "| Source file | Bytes | SHA-256 |",
        "|---|---:|---|",
    ]
    for source in lock["source"]["files"]:
        lines.append(f"| `{source['url']}` | {source['size_bytes']} | `{source['sha256']}` |")
    lines.extend(
        [
            "",
            "## License and terms",
            "",
            f"- License: `{license_record['id']}`",
            f"- License URL: {license_record['url']}",
            f"- Terms: {license_record['terms_url']}",
            f"- Terms SHA-256: `{manifest['terms_sha256']}`",
            f"- Redistribution: `{license_record['redistribution']}`",
            "",
            "The pinned terms digest is checked by `prepare`; a changed or",
            "unavailable terms document is a hard failure, not a warning.",
            "",
            "## Prepared data",
            "",
            f"- Dataset fingerprint: `{lock['fingerprint']}`",
            f"- Corpus SHA-256: `{lock['corpus_sha256']}`",
        ]
    )
    for split, counts in sorted(lock["counts"]["splits"].items()):
        lines.append(
            f"- `{split}`: {counts['queries']} queries, {counts['qrels']} qrels "
            f"({counts['positive_qrels']} positive)"
        )
    lines.extend(
        [
            f"- Language slices: {', '.join(lock['language_slices']) or '—'}",
            f"- Categories: {', '.join(lock['categories']) or '—'}",
        ]
    )
    if lock.get("notes"):
        lines.extend(["", "## Transform notes", ""])
        for key in sorted(lock["notes"]):
            value = lock["notes"][key]
            if isinstance(value, (dict, list)):
                value = json.dumps(value, sort_keys=True, ensure_ascii=False)
            lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "```text",
            lock["reproduce"]["command"],
            lock["reproduce"]["offline_verify"],
            "```",
            "",
        ]
    )
    return "\n".join(lines)
