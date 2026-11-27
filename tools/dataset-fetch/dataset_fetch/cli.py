"""Command line interface for offline dataset preparation."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import __version__
from .cache import DownloadCache, default_cache_root
from .canonical import sha256_file
from .errors import (
    IO,
    LOCK_MISMATCH,
    OUTPUT_EXISTS,
    SCHEMA,
    TRANSFORM,
    DatasetFetchError,
    fail,
)
from .jsio import pretty_json_bytes, read_json, write_bytes
from .lockfile import build_lock, render_notice
from .manifest import dataset_fingerprint, validate_manifest
from .recipes import recipe_for, registered
from .terms import check_license
from .transform import parse_prepared, write_dataset


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _dataset_dir(args: argparse.Namespace) -> Path:
    if args.dataset_dir is not None:
        return Path(args.dataset_dir)
    return _repo_root() / "bench" / "datasets" / args.dataset


def _load_manifest(dataset_dir: Path, *, require_local_hashes: bool) -> dict[str, Any]:
    path = dataset_dir / "manifest.json"
    value = read_json(path)
    return validate_manifest(
        value, dataset_dir=dataset_dir, require_local_hashes=require_local_hashes
    )


def _require_terms(manifest: dict[str, Any]) -> None:
    if not manifest.get("terms_sha256"):
        raise fail(
            SCHEMA,
            "manifest must pin terms_sha256: the terms digest is part of R23",
            location="manifest.terms_sha256",
        )


def _swap_directory(staging: Path, output: Path, *, overwrite: bool) -> None:
    if output.exists():
        if not overwrite:
            raise fail(
                OUTPUT_EXISTS,
                "prepared data already exists; pass --overwrite to replace it",
                location=str(output),
            )
        backup = output.with_name(output.name + ".bak")
        if backup.exists():
            shutil.rmtree(backup)
        output.rename(backup)
        try:
            staging.rename(output)
        except OSError:
            backup.rename(output)
            raise
        shutil.rmtree(backup)
    else:
        staging.rename(output)


def _sanity_check(build: Any, parsed: Any, manifest: dict[str, Any]) -> None:
    checks = {
        "counts": (build.counts, parsed.counts),
        "corpus_sha256": (build.corpus_sha256, parsed.corpus_sha256),
        "query_set_sha256": (build.query_set_sha256, parsed.query_set_sha256),
        "language_slices": (build.language_slices, parsed.language_slices),
        "categories": (build.categories, parsed.categories),
    }
    for name, (expected, actual) in checks.items():
        if expected != actual:
            raise fail(
                TRANSFORM,
                f"prepared {name} does not match the writer result",
                location=manifest["dataset_id"],
            )


def command_prepare(args: argparse.Namespace) -> dict[str, Any]:
    dataset_dir = _dataset_dir(args)
    manifest = _load_manifest(dataset_dir, require_local_hashes=False)
    _require_terms(manifest)
    check_license(manifest)
    recipe = recipe_for(manifest["dataset_id"])
    cache = DownloadCache(
        Path(args.cache), manifest["dataset_id"], offline=args.offline
    )
    sources = cache.ensure(manifest["source"])
    terms = cache.ensure_terms(manifest["license"]["terms_url"], manifest["terms_sha256"])
    request = recipe(manifest, sources, manifest["transform"]["seed"])
    staging = dataset_dir / (manifest["corpus"].split("/", 1)[0] + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        build = write_dataset(request, staging, relative_prefix=manifest["corpus"].split("/", 1)[0])
        _swap_directory(staging, dataset_dir / manifest["corpus"].split("/", 1)[0], overwrite=args.overwrite)
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    updated = deepcopy(manifest)
    updated["local_file_sha256"] = dict(sorted(build.local_hashes.items()))
    validate_manifest(updated, dataset_dir=dataset_dir, require_local_hashes=True)
    parsed = parse_prepared(dataset_dir, updated)
    _sanity_check(build, parsed, updated)
    write_bytes(dataset_dir / "manifest.json", pretty_json_bytes(updated))
    lock = build_lock(updated, build, parsed, sources, terms)
    write_bytes(dataset_dir / "dataset-lock.json", pretty_json_bytes(lock))
    write_bytes(dataset_dir / "NOTICE.md", render_notice(updated, lock).encode("utf-8"))
    return {
        "status": "prepared",
        "dataset_id": updated["dataset_id"],
        "fingerprint": lock["fingerprint"],
        "documents": build.document_count,
        "splits": {
            name: counts["queries"] for name, counts in build.counts["splits"].items()
        },
        "data_dir": manifest["corpus"].split("/", 1)[0],
    }


def _load_lock(dataset_dir: Path) -> dict[str, Any]:
    path = dataset_dir / "dataset-lock.json"
    if not path.exists():
        raise fail(LOCK_MISMATCH, "dataset-lock.json is missing", location=str(path))
    value = read_json(path)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise fail(LOCK_MISMATCH, "unsupported dataset lock", location=str(path))
    return value


def _verify_lock_against_manifest(
    dataset_dir: Path,
    manifest: dict[str, Any],
    lock: dict[str, Any],
    *,
    verify_files: bool = True,
) -> None:
    if lock.get("dataset_id") != manifest["dataset_id"]:
        raise fail(LOCK_MISMATCH, "lock dataset_id differs from the manifest")
    if lock.get("transform") != {
        "script": manifest["transform"]["script"],
        "version": manifest["transform"]["version"],
        "seed": manifest["transform"]["seed"],
    }:
        raise fail(LOCK_MISMATCH, "lock transform differs from the manifest")
    if lock.get("local_file_count") != len(manifest["local_file_sha256"]):
        raise fail(LOCK_MISMATCH, "lock local file count differs from the manifest")
    if lock.get("license", {}).get("terms_sha256") != manifest.get("terms_sha256"):
        raise fail(LOCK_MISMATCH, "lock terms digest differs from the manifest")
    source = lock.get("source", {})
    if source.get("revision") != manifest["source"]["revision"]:
        raise fail(LOCK_MISMATCH, "lock source revision differs from the manifest")
    locked = {entry["url"]: entry["sha256"] for entry in source.get("files", [])}
    expected = dict(zip(manifest["source"]["urls"], manifest["source"]["sha256"], strict=True))
    if locked != expected:
        raise fail(LOCK_MISMATCH, "lock source files differ from the manifest")
    fingerprint = dataset_fingerprint(manifest, manifest["local_file_sha256"])
    if lock.get("fingerprint") != fingerprint:
        raise fail(LOCK_MISMATCH, "lock fingerprint differs from the recomputed value")
    if not verify_files:
        return
    for relative, digest in manifest["local_file_sha256"].items():
        path = dataset_dir / relative
        if not path.is_file():
            raise fail(IO, "prepared file is missing", location=str(path))
        actual = sha256_file(path)
        if actual != digest:
            raise fail(
                LOCK_MISMATCH,
                "prepared file digest differs from the pinned hash",
                location=relative,
            )


def command_verify(args: argparse.Namespace) -> dict[str, Any]:
    dataset_dir = _dataset_dir(args)
    manifest = _load_manifest(dataset_dir, require_local_hashes=True)
    _require_terms(manifest)
    check_license(manifest)
    lock = _load_lock(dataset_dir)
    _verify_lock_against_manifest(dataset_dir, manifest, lock)
    parsed = parse_prepared(dataset_dir, manifest)
    if parsed.counts != lock.get("counts"):
        raise fail(LOCK_MISMATCH, "parsed split counts differ from the lock")
    if parsed.corpus_sha256 != lock.get("corpus_sha256"):
        raise fail(LOCK_MISMATCH, "parsed corpus hash differs from the lock")
    if parsed.query_set_sha256 != lock.get("query_set_sha256"):
        raise fail(LOCK_MISMATCH, "parsed query-set hashes differ from the lock")
    if parsed.language_slices != lock.get("language_slices"):
        raise fail(LOCK_MISMATCH, "parsed language slices differ from the lock")
    if parsed.categories != lock.get("categories"):
        raise fail(LOCK_MISMATCH, "parsed categories differ from the lock")
    return {
        "status": "verified",
        "dataset_id": manifest["dataset_id"],
        "fingerprint": lock["fingerprint"],
        "documents": len(parsed.documents),
        "splits": {name: counts["queries"] for name, counts in parsed.counts["splits"].items()},
        "network": "none",
    }


def command_check(args: argparse.Namespace) -> dict[str, Any]:
    dataset_dir = _dataset_dir(args)
    manifest = _load_manifest(dataset_dir, require_local_hashes=True)
    _require_terms(manifest)
    check_license(manifest)
    lock = _load_lock(dataset_dir)
    _verify_lock_against_manifest(dataset_dir, manifest, lock, verify_files=False)
    return {
        "status": "ok",
        "dataset_id": manifest["dataset_id"],
        "fingerprint": lock["fingerprint"],
    }


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    root = args.datasets_root or (_repo_root() / "bench" / "datasets")
    datasets = []
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            manifest_path = entry / "manifest.json"
            if manifest_path.is_file():
                value: dict[str, Any] = read_json(manifest_path)
                datasets.append(
                    {
                        "dataset_id": value.get("dataset_id", entry.name),
                        "license": value.get("license", {}).get("id"),
                        "has_lock": (entry / "dataset-lock.json").is_file(),
                    }
                )
    return {
        "status": "ok",
        "tool_version": __version__,
        "recipes": registered(),
        "datasets": datasets,
    }


def _cache_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cache",
        default=str(default_cache_root()),
        help="external download cache (default: %(default)s)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dataset_fetch")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="download, verify, and prepare one dataset")
    prepare.add_argument("--dataset", required=True)
    prepare.add_argument("--dataset-dir", type=Path, default=None)
    _cache_option(prepare)
    prepare.add_argument("--offline", action="store_true")
    prepare.add_argument("--overwrite", action="store_true")
    prepare.set_defaults(handler=command_prepare)

    verify = sub.add_parser("verify", help="offline hash and schema verification")
    verify.add_argument("--dataset", required=True)
    verify.add_argument("--dataset-dir", type=Path, default=None)
    _cache_option(verify)
    verify.set_defaults(handler=command_verify)

    check = sub.add_parser("check", help="validate committed manifest and lock only")
    check.add_argument("--dataset", required=True)
    check.add_argument("--dataset-dir", type=Path, default=None)
    _cache_option(check)
    check.set_defaults(handler=command_check)

    listing = sub.add_parser("list", help="list committed dataset manifests")
    listing.add_argument("--datasets-root", type=Path, default=None)
    listing.set_defaults(handler=command_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except DatasetFetchError as error:
        sys.stderr.write(error.as_json() + "\n")
        if os.environ.get("DATASET_FETCH_DEBUG"):
            raise
        return 2
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0
