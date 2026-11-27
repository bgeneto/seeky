"""Build pipeline: render, emit sidecars, verify, atomically replace output.

SPEC-0004 section 5.1. Nothing is written into an existing output tree before a
complete, verified sibling build succeeds.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Callable

from . import GENERATOR_VERSION
from .canonical import Document, sort_key_truth
from .errors import PROFILE_INVALID, SdcError
from .jsonio import (
    canonical_json_sha256,
    load_json_file,
    pretty_json_bytes,
    sha256_bytes,
    sha256_file,
    write_json_file,
    write_jsonl_file,
    write_bytes,
)
from .layout import apply_layout
from .plan import Plan, plan_corpus
from .profiles import Profile
from .renderers import render as default_render
from .sources import (
    SourceSet,
    load_source_sets,
    load_templates,
    require_cached,
    validate_source_set,
    verify_cached,
)

SIDECARS = (
    "corpus.jsonl",
    "passages.jsonl",
    "extraction-truth.jsonl",
    "duplicate-clusters.jsonl",
    "versions.jsonl",
)
DEFAULT_ROOTS = ["files/documents"]
CODE_ENABLED_ROOTS = ["files/documents", "files/code"]


def source_set_sha256(source_sets: dict[str, SourceSet]) -> str:
    payload = [
        {"source_set_id": key, "file_sha256": value.file_sha256}
        for key, value in sorted(source_sets.items())
    ]
    import json

    return sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _check_cache(plan: Plan, cache: Path) -> None:
    """Require every external source and license text in the cache."""

    for source_set in plan.source_sets.values():
        for item in source_set.items:
            if item.origin != "external":
                continue
            assert item.sha256 is not None
            verify_cached(cache, item.sha256, item.byte_length, what=f"source {item.source_item_id}")
            require_cached(cache, item.license.text_sha256, what=f"license {item.source_item_id}")


def _render_documents(
    plan: Plan,
    *,
    render_fn: Callable[[Document], bytes],
) -> dict[str, bytes]:
    rendered: dict[str, bytes] = {}
    for document in plan.documents:
        apply_layout(document)
        if document.byte_copy_of is not None:
            if document.byte_copy_of not in rendered:
                raise SdcError(
                    "RENDER_FAILED",
                    f"byte copy source {document.byte_copy_of} was not rendered first",
                    file=document.relative_path,
                )
            continue
        try:
            rendered[document.doc_id] = render_fn(document)
        except SdcError:
            raise
        except Exception as exc:  # noqa: BLE001 - convert renderer bugs to typed errors
            raise SdcError(
                "RENDER_FAILED",
                f"renderer failed: {exc}",
                file=document.relative_path,
            ) from exc
    # Byte copies reuse the exact source bytes, never a re-render.
    for document in plan.documents:
        if document.byte_copy_of is not None:
            rendered[document.doc_id] = rendered[document.byte_copy_of]
    return rendered


def _manifest(
    plan: Plan,
    *,
    files: list[dict[str, Any]],
    sidecars: dict[str, str],
    document_count: int,
    passage_count: int,
) -> dict[str, Any]:
    corpus_payload = {
        "files": files,
        "sidecars": sidecars,
        "default_roots": DEFAULT_ROOTS,
        "code_enabled_roots": CODE_ENABLED_ROOTS,
    }
    return {
        "schema_version": 1,
        "corpus_id": plan.profile.corpus_id,
        "profile_sha256": plan.profile.file_sha256,
        "source_set_sha256": source_set_sha256(plan.source_sets),
        "seed": plan.seed,
        "generator_version": GENERATOR_VERSION,
        "renderer_lock_sha256": plan.renderer_lock_sha256,
        "document_count": document_count,
        "passage_count": passage_count,
        "default_roots": DEFAULT_ROOTS,
        "code_enabled_roots": CODE_ENABLED_ROOTS,
        "injection_counts": plan.injection_counts,
        "files": files,
        "sidecars": sidecars,
        "corpus_hash": canonical_json_sha256(corpus_payload),
    }


def build_corpus(
    *,
    profile_path: Path,
    seed: str,
    sources_dir: Path,
    cache: Path,
    output: Path,
    repo_root: Path,
    render_fn: Callable[[Document], bytes] | None = None,
    verify_build: bool = True,
) -> dict[str, Any]:
    """Build a corpus atomically and return its manifest."""

    if seed != seed.strip() or not seed or not seed.isascii():
        raise SdcError(
            PROFILE_INVALID, "seed must be a nonempty ASCII string without spaces"
        )
    from .profiles import load_profile

    profile = load_profile(profile_path)
    source_sets = load_source_sets(sources_dir)
    for set_id in profile.source_set_ids:
        if set_id not in source_sets:
            raise SdcError(
                PROFILE_INVALID,
                f"unknown source set {set_id!r}",
                file=profile_path.name,
                field="source_set_ids",
            )
        validate_source_set(
            sources_dir, source_sets[set_id], repo_root=repo_root, require_permissive_core=True
        )
    templates = load_templates(sources_dir, source_sets)
    plan = plan_corpus(
        profile=profile,
        seed=seed,
        source_sets=source_sets,
        templates=templates,
        sdc_root=sources_dir.parent,
    )
    _check_cache(plan, cache)
    renderer = render_fn or default_render

    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / f".{output.name}.tmp"
    backup = parent / f".{output.name}.old"
    for path in (temporary, backup):
        if path.exists():
            shutil.rmtree(path)

    try:
        _build_into(
            plan,
            destination=temporary,
            render_fn=renderer,
        )
        if verify_build:
            from .verify import verify_corpus

            verify_corpus(temporary)
        if output.exists():
            os.rename(output, backup)
            try:
                os.rename(temporary, output)
            except OSError:
                os.rename(backup, output)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        else:
            os.rename(temporary, output)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        if backup.exists() and not output.exists():
            os.rename(backup, output)
        raise
    return load_json_file(output / "manifest.json", display="manifest.json")


def _build_into(
    plan: Plan,
    *,
    destination: Path,
    render_fn: Callable[[Document], bytes],
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    rendered = _render_documents(plan, render_fn=render_fn)

    files: list[dict[str, Any]] = []
    for document in sorted(plan.documents, key=lambda doc: doc.relative_path):
        data = rendered[document.doc_id]
        write_bytes(destination / Path(document.relative_path), data)

    documents_by_id = {document.doc_id: document for document in plan.documents}
    for document in sorted(plan.documents, key=lambda doc: doc.doc_id):
        data = rendered[document.doc_id]
        digest = sha256_bytes(data)
        record = document.corpus_record()
        record["metadata"]["content_sha256"] = digest
        record["metadata"]["byte_count"] = len(data)
        # Byte copies are verified to be literally identical.
        if document.byte_copy_of is not None:
            source_digest = sha256_bytes(rendered[document.byte_copy_of])
            if source_digest != digest:
                raise SdcError(
                    "OUTPUT_HASH_MISMATCH",
                    f"byte copy {document.doc_id} differs from {document.byte_copy_of}",
                    file=document.relative_path,
                )
        document._record = record  # type: ignore[attr-defined]
    # Write corpus.jsonl from the prepared records.
    corpus_rows = [doc._record for doc in sorted(plan.documents, key=lambda doc: doc.doc_id)]  # type: ignore[attr-defined]
    write_jsonl_file(destination / "corpus.jsonl", corpus_rows)

    passages = []
    truth = []
    for document in plan.documents:
        passages.extend(document.passages())
        truth.extend(document.extraction_units())
    passages.sort(key=lambda item: item.passage_id)
    truth.sort(key=sort_key_truth)
    write_jsonl_file(destination / "passages.jsonl", (item.as_record() for item in passages))
    write_jsonl_file(destination / "extraction-truth.jsonl", truth)
    write_jsonl_file(destination / "duplicate-clusters.jsonl", plan.clusters)
    write_jsonl_file(destination / "versions.jsonl", plan.versions)

    sidecars = {
        name: sha256_file(destination / name)[0] for name in SIDECARS
    }
    for document in sorted(plan.documents, key=lambda doc: doc.relative_path):
        data = rendered[document.doc_id]
        files.append(
            {
                "path": document.relative_path,
                "byte_count": len(data),
                "sha256": sha256_bytes(data),
            }
        )
    manifest = _manifest(
        plan,
        files=sorted(files, key=lambda row: row["path"]),
        sidecars=sidecars,
        document_count=len(plan.documents),
        passage_count=len(passages),
    )
    total_bytes = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
    total_bytes += len(pretty_json_bytes(manifest))
    plan.profile.validate_generated_counts(
        rendered_files=len(files),
        passages=len(passages),
        total_bytes=total_bytes,
    )
    write_json_file(destination / "manifest.json", manifest)
