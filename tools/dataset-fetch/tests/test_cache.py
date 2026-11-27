"""Download cache hash, terms, and offline tests (no real network)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dataset_fetch.cache import DownloadCache
from dataset_fetch.canonical import sha256_bytes
from dataset_fetch.errors import DatasetFetchError
import support


class DownloadCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.payload = b"dataset bytes\n"
        self.url = "https://example.invalid/synthetic/corpus.jsonl"
        self.terms_url = "https://example.invalid/synthetic/terms.txt"
        self.terms = b"terms text\n"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def source(self, digest: str | None = None) -> dict[str, list[str]]:
        return {
            "urls": [self.url],
            "sha256": [digest or sha256_bytes(self.payload)],
        }

    def test_download_verifies_and_caches(self) -> None:
        fetch = support.FakeFetch({self.url: self.payload})
        cache = DownloadCache(self.root, "synthetic", fetch=fetch)
        files = cache.ensure(self.source())
        self.assertEqual(files[0].sha256, sha256_bytes(self.payload))
        self.assertEqual(files[0].path.read_bytes(), self.payload)
        # A second call is served from the cache without another fetch.
        cache.ensure(self.source())
        self.assertEqual(len(fetch.calls), 1)

    def test_download_rejects_hash_mismatch(self) -> None:
        fetch = support.FakeFetch({self.url: b"tampered\n"})
        cache = DownloadCache(self.root, "synthetic", fetch=fetch)
        with self.assertRaises(DatasetFetchError) as raised:
            cache.ensure(self.source())
        self.assertEqual(raised.exception.code, "HASH_MISMATCH")
        self.assertFalse((cache.downloads / "corpus.jsonl").exists())

    def test_cached_file_hash_mismatch_is_rejected(self) -> None:
        cache = DownloadCache(self.root, "synthetic", fetch=support.FakeFetch({}))
        cache.downloads.mkdir(parents=True)
        (cache.downloads / "corpus.jsonl").write_bytes(b"stale\n")
        with self.assertRaises(DatasetFetchError) as raised:
            cache.ensure(self.source())
        self.assertEqual(raised.exception.code, "HASH_MISMATCH")

    def test_offline_cache_miss_is_typed(self) -> None:
        cache = DownloadCache(self.root, "synthetic", offline=True, fetch=support.FakeFetch({}))
        with self.assertRaises(DatasetFetchError) as raised:
            cache.ensure(self.source())
        self.assertEqual(raised.exception.code, "CACHE_MISS")

    def test_download_rejects_terms_mismatch(self) -> None:
        fetch = support.FakeFetch({self.terms_url: b"changed terms\n"})
        cache = DownloadCache(self.root, "synthetic", fetch=fetch)
        with self.assertRaises(DatasetFetchError) as raised:
            cache.ensure_terms(self.terms_url, sha256_bytes(self.terms))
        self.assertEqual(raised.exception.code, "TERMS_MISMATCH")

    def test_terms_snapshot_is_cached_and_verified(self) -> None:
        fetch = support.FakeFetch({self.terms_url: self.terms})
        cache = DownloadCache(self.root, "synthetic", fetch=fetch)
        digest = sha256_bytes(self.terms)
        first = cache.ensure_terms(self.terms_url, digest)
        second = cache.ensure_terms(self.terms_url, digest)
        self.assertEqual(first.path, second.path)
        self.assertEqual(len(fetch.calls), 1)
        # A cached snapshot with a different digest is a hard failure.
        first.path.write_bytes(b"changed\n")
        with self.assertRaises(DatasetFetchError) as raised:
            cache.ensure_terms(self.terms_url, digest)
        self.assertEqual(raised.exception.code, "TERMS_MISMATCH")


if __name__ == "__main__":
    unittest.main()
