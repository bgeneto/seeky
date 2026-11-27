"""Shared helpers for the SDC generator test suite."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterator

TESTS_DIR = Path(__file__).resolve().parent
TOOL_ROOT = TESTS_DIR.parent
REPO_ROOT = TOOL_ROOT.parents[1]
SDC_ROOT = REPO_ROOT / "bench" / "corpora" / "sdc"
SOURCES_DIR = SDC_ROOT / "sources"
PROFILES_DIR = SDC_ROOT / "profiles"
SMOKE_DIR = SDC_ROOT / "sdc-smoke"
TESTMINI_PROFILE = TESTS_DIR / "fixtures" / "profiles" / "testmini.json"

if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from sdc_generator.build import build_corpus  # noqa: E402
from sdc_generator.jsonio import (  # noqa: E402
    canonical_json_sha256,
    load_json_file,
    write_json_file,
)
from sdc_generator.profiles import load_profile  # noqa: E402


@contextlib.contextmanager
def temporary_directory(prefix: str = "sdc-test-") -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=os.environ.get("SDC_TEST_TMP")))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def build_mini(output: Path, seed: str = "testmini-v1", **kwargs: Any) -> dict[str, Any]:
    return build_corpus(
        profile_path=TESTMINI_PROFILE,
        seed=seed,
        sources_dir=SOURCES_DIR,
        cache=output.parent / "cache",
        output=output,
        repo_root=REPO_ROOT,
        **kwargs,
    )


def tree_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def corpus_rows(root: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    text = (root / "corpus.jsonl").read_text(encoding="utf-8")
    for line in text.splitlines():
        row = json.loads(line)
        rows[row["_id"]] = row
    return rows


def sidecar_rows(root: Path, name: str) -> list[dict[str, Any]]:
    text = (root / name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def manifest(root: Path) -> dict[str, Any]:
    return load_json_file(root / "manifest.json", display="manifest.json")


def refresh_manifest(root: Path) -> dict[str, Any]:
    """Recompute sidecar hashes and corpus_hash after a test mutation."""

    from sdc_generator.jsonio import sha256_file

    data = manifest(root)
    data["sidecars"] = {
        name: sha256_file(root / name)[0]
        for name in (
            "corpus.jsonl",
            "passages.jsonl",
            "extraction-truth.jsonl",
            "duplicate-clusters.jsonl",
            "versions.jsonl",
        )
    }
    payload = {
        "files": data["files"],
        "sidecars": data["sidecars"],
        "default_roots": data["default_roots"],
        "code_enabled_roots": data["code_enabled_roots"],
    }
    data["corpus_hash"] = canonical_json_sha256(payload)
    write_json_file(root / "manifest.json", data)
    return data


class BuiltCorpus(unittest.TestCase):
    """Build testmini once per class for read-only tests."""

    corpus: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = Path(tempfile.mkdtemp(prefix="sdc-mini-"))
        cls.corpus = cls._tmp / "testmini"
        build_mini(cls.corpus)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._tmp, ignore_errors=True)


def random_bytes(count: int, seed: int = 1) -> bytes:
    import random

    generator = random.Random(seed)
    return bytes(generator.randrange(256) for _ in range(count))
