"""Repository hygiene: committed dataset metadata only, size, and licensing."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from dataset_fetch.errors import DatasetFetchError
from dataset_fetch.terms import check_license

REPO_ROOT = Path(__file__).resolve().parents[3]
DATASETS = REPO_ROOT / "bench" / "datasets"
TOOL = REPO_ROOT / "tools" / "dataset-fetch"
MAX_TOTAL_METADATA_BYTES = 24 * 1024 * 1024
MAX_FILE_BYTES = 12 * 1024 * 1024


def git_tracked(path: Path) -> list[str]:
    git = shutil.which("git")
    if git is None:
        return []
    result = subprocess.run(
        [git, "-C", str(REPO_ROOT), "ls-files", "--", str(path.relative_to(REPO_ROOT))],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


class RepositoryHygieneTests(unittest.TestCase):
    def setUp(self) -> None:
        if not DATASETS.is_dir():
            self.skipTest("no committed datasets yet")

    def test_no_bulk_data_is_tracked(self) -> None:
        tracked = git_tracked(DATASETS)
        if not tracked:
            self.skipTest("git ls-files unavailable or nothing tracked")
        for relative in tracked:
            self.assertNotIn("/data/", f"/{relative}")
            self.assertFalse(relative.endswith((".gz", ".zip", ".tsv")), relative)

    def test_committed_metadata_stays_small(self) -> None:
        tracked = git_tracked(DATASETS)
        if not tracked:
            self.skipTest("git ls-files unavailable or nothing tracked")
        total = 0
        for relative in tracked:
            path = REPO_ROOT / relative
            size = path.stat().st_size
            total += size
            self.assertLessEqual(size, MAX_FILE_BYTES, relative)
        self.assertLessEqual(total, MAX_TOTAL_METADATA_BYTES)

    def test_every_dataset_has_manifest_lock_and_notice(self) -> None:
        manifests = sorted(DATASETS.glob("*/manifest.json"))
        if not manifests:
            self.skipTest("no dataset manifests yet")
        for manifest_path in manifests:
            dataset_dir = manifest_path.parent
            self.assertTrue((dataset_dir / "dataset-lock.json").is_file(), dataset_dir)
            notice = dataset_dir / "NOTICE.md"
            self.assertTrue(notice.is_file(), dataset_dir)
            text = notice.read_text(encoding="utf-8")
            self.assertIn("download-only", text)
            self.assertIn("never redistributed", text)

    def test_dataset_licenses_are_allowed_and_download_only(self) -> None:
        manifests = sorted(DATASETS.glob("*/manifest.json"))
        if not manifests:
            self.skipTest("no dataset manifests yet")
        for manifest_path in manifests:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["visibility"], "public")
            self.assertEqual(manifest["license"]["redistribution"], "download-only")
            check_license(manifest)
            self.assertTrue(manifest["terms_sha256"])
            for url in manifest["source"]["urls"]:
                self.assertTrue(url.startswith("https://"), url)
                self.assertNotIn("C:\\", url)
                self.assertNotIn("Users/", url)

    def test_manifest_hashes_are_real_and_complete(self) -> None:
        manifests = sorted(DATASETS.glob("*/manifest.json"))
        if not manifests:
            self.skipTest("no dataset manifests yet")
        for manifest_path in manifests:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["local_file_sha256"])
            self.assertIn(manifest["corpus"], manifest["local_file_sha256"])
            for name in ("dev", "test"):
                split = manifest["splits"][name]
                self.assertIn(split["queries"], manifest["local_file_sha256"])
                self.assertIn(split["qrels"], manifest["local_file_sha256"])
            for digest in manifest["local_file_sha256"].values():
                self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_gitignore_excludes_prepared_data(self) -> None:
        ignore = DATASETS / ".gitignore"
        self.assertTrue(ignore.is_file())
        text = ignore.read_text(encoding="utf-8")
        for pattern in ("data/", "data.staging", "data.bak"):
            self.assertIn(pattern, text)

    def test_tool_has_no_third_party_dependencies(self) -> None:
        lock = (TOOL / "requirements.lock").read_text(encoding="utf-8")
        for line in lock.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            self.fail(f"unexpected dependency line in requirements.lock: {line}")


if __name__ == "__main__":
    unittest.main()
