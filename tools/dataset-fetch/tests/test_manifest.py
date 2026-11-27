"""Manifest completeness, §4.2 validation, license policy, and fingerprint tests."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from dataset_fetch.errors import DatasetFetchError
from dataset_fetch.manifest import (
    dataset_fingerprint,
    query_set_sha256,
    validate_manifest,
)
from dataset_fetch.terms import check_license
import support


class ManifestValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = support.manifest()
        self.dataset_dir = Path("/repo/bench/datasets") / support.DATASET_ID

    def assert_rejected(self, mutate, *, field: str | None = None) -> None:
        value = copy.deepcopy(self.manifest)
        mutate(value)
        with self.assertRaises(DatasetFetchError) as raised:
            validate_manifest(value, dataset_dir=self.dataset_dir, require_local_hashes=False)
        self.assertEqual(raised.exception.code, "SCHEMA")
        if field is not None:
            self.assertIn(field, raised.exception.as_json())

    def test_valid_manifest_passes(self) -> None:
        validate_manifest(self.manifest, dataset_dir=self.dataset_dir, require_local_hashes=False)

    def test_manifest_requires_license_source_and_hashes(self) -> None:
        self.assert_rejected(lambda value: value["license"].pop("id"), field="license")
        self.assert_rejected(lambda value: value["license"].update(id=""), field="license.id")
        self.assert_rejected(lambda value: value["license"].pop("terms_url"))
        self.assert_rejected(lambda value: value["source"].update(revision=""))
        self.assert_rejected(lambda value: value["source"].update(urls=[]))
        self.assert_rejected(lambda value: value["source"]["sha256"].pop())
        self.assert_rejected(lambda value: value["source"].update(sha256=["xyz"]))
        self.assert_rejected(lambda value: value.pop("terms_sha256"))

    def test_manifest_requires_both_splits(self) -> None:
        self.assert_rejected(lambda value: value["splits"].pop("dev"))
        self.assert_rejected(lambda value: value["splits"].pop("test"))

    def test_manifest_requires_a_transform_version(self) -> None:
        self.assert_rejected(lambda value: value["transform"].update(version=0))
        self.assert_rejected(lambda value: value["transform"].update(seed=""))
        self.assert_rejected(lambda value: value["transform"].update(script=""))

    def test_manifest_rejects_unknown_split_or_layout(self) -> None:
        self.assert_rejected(lambda value: value.update(layout="sdc"))
        self.assert_rejected(lambda value: value["splits"].update(validation={}))

    def test_manifest_requires_local_hashes_when_asked(self) -> None:
        with self.assertRaises(DatasetFetchError):
            validate_manifest(self.manifest, dataset_dir=self.dataset_dir)

    def test_manifest_dataset_id_matches_directory(self) -> None:
        with self.assertRaises(DatasetFetchError) as raised:
            validate_manifest(
                self.manifest,
                dataset_dir=Path("/repo/bench/datasets/other"),
                require_local_hashes=False,
            )
        self.assertIn("directory name", raised.exception.message)

    def test_manifest_paths_cannot_escape(self) -> None:
        self.assert_rejected(lambda value: value.update(corpus="../secret"))
        self.assert_rejected(lambda value: value["splits"]["dev"].update(qrels="/abs"))
        self.assert_rejected(
            lambda value: value["local_file_sha256"].update({"data/x": "0" * 63})
        )

    def test_manifest_rejects_code_category_and_unknown_slice(self) -> None:
        self.assert_rejected(lambda value: value["query_defaults"].update(category="code_search"))
        self.assert_rejected(
            lambda value: value["query_defaults"].update(language_slice="klingon")
        )
        self.assert_rejected(
            lambda value: value["query_defaults"].update(configuration="code_enabled")
        )


class LicensePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = support.manifest()

    def assert_forbidden(self, license_id: str) -> None:
        value = copy.deepcopy(self.manifest)
        value["license"]["id"] = license_id
        with self.assertRaises(DatasetFetchError) as raised:
            check_license(value)
        self.assertEqual(raised.exception.code, "LICENSE_FORBIDDEN")

    def test_permissive_and_download_only_sources_pass(self) -> None:
        for identifier in ("MIT", "Apache-2.0", "CC-BY-4.0", "CC-BY-SA-4.0"):
            value = copy.deepcopy(self.manifest)
            value["license"]["id"] = identifier
            self.assertEqual(check_license(value), identifier)

    def test_forbidden_or_unreviewed_licenses_are_rejected(self) -> None:
        for identifier in ("GPL-3.0", "AGPL-3.0", "CC-BY-NC-4.0", "UNKNOWN", "Proprietary"):
            self.assert_forbidden(identifier)

    def test_redistribution_must_be_download_only(self) -> None:
        value = copy.deepcopy(self.manifest)
        value["license"]["redistribution"] = "redistributable"
        with self.assertRaises(DatasetFetchError) as raised:
            check_license(value)
        self.assertEqual(raised.exception.code, "LICENSE_FORBIDDEN")


class FingerprintTests(unittest.TestCase):
    def test_fingerprint_matches_the_typed_rust_manifest(self) -> None:
        manifest = support.manifest()
        local = {"data/corpus.jsonl": "1" * 64, "data/qrels.dev.tsv": "2" * 64}
        first = dataset_fingerprint(manifest, local)
        # Unknown fields are dropped by serde; terms_sha256 must not change it.
        mutated = copy.deepcopy(manifest)
        mutated["terms_sha256"] = "3" * 64
        mutated["extra_unknown_field"] = {"ignored": True}
        self.assertEqual(dataset_fingerprint(mutated, local), first)
        # A byte change (local hash) must change it.
        changed = dict(local)
        changed["data/corpus.jsonl"] = "4" * 64
        self.assertNotEqual(dataset_fingerprint(manifest, changed), first)

    def test_query_set_hash_is_order_independent(self) -> None:
        records = [
            {
                "id": "b",
                "text": "beta",
                "language": "en",
                "target_languages": ["en"],
                "language_slice": "en",
                "category": "conceptual",
                "configuration": "default",
                "split": "dev",
            },
            {
                "id": "a",
                "text": "alpha",
                "language": "pt",
                "target_languages": ["en"],
                "language_slice": "cross_lingual",
                "category": "conceptual",
                "configuration": "default",
                "split": "dev",
            },
        ]
        self.assertEqual(query_set_sha256(records), query_set_sha256(list(reversed(records))))
        self.assertEqual(len(query_set_sha256(records)), 64)


if __name__ == "__main__":
    unittest.main()
