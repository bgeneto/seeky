"""Determinism, layout, and atomicity tests (SPEC-0004-R3, R4, R13)."""

from __future__ import annotations

import json
import socket
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from support import (
    PROFILES_DIR,
    REPO_ROOT,
    SDC_ROOT,
    SMOKE_DIR,
    TESTMINI_PROFILE,
    build_mini,
    corpus_rows,
    manifest,
    refresh_manifest,
    sidecar_rows,
    temporary_directory,
    tree_digests,
)

from sdc_generator.build import build_corpus
from sdc_generator.errors import OUTPUT_HASH_MISMATCH, SdcError
from sdc_generator.verify import verify_corpus


class DeterminismTests(unittest.TestCase):
    def test_same_seed_rebuild_is_byte_identical(self) -> None:
        # SPEC-0004-R3: two checkout paths and identical inputs.
        with temporary_directory() as first, temporary_directory() as second:
            build_mini(first / "corpus", seed="determinism-v1")
            build_mini(second / "corpus", seed="determinism-v1")
            left = tree_digests(first / "corpus")
            right = tree_digests(second / "corpus")
            self.assertEqual(set(left), set(right))
            self.assertEqual(left, right)
            self.assertEqual(manifest(first / "corpus")["corpus_hash"], manifest(second / "corpus")["corpus_hash"])

    def test_different_seed_changes_corpus_hash_without_host_nondeterminism(self) -> None:
        # SPEC-0004-R3, R4.
        with temporary_directory() as first, temporary_directory() as second:
            build_mini(first / "corpus", seed="seed-a")
            build_mini(second / "corpus", seed="seed-b")
            self.assertNotEqual(manifest(first / "corpus")["corpus_hash"], manifest(second / "corpus")["corpus_hash"])
            # The same seed on a second host path remains byte-identical.
            build_mini(first / "copy", seed="seed-a")
            self.assertEqual(tree_digests(first / "corpus"), tree_digests(first / "copy"))

    def test_manifest_contains_no_host_specific_data(self) -> None:
        # SPEC-0004-R3, R6.
        with temporary_directory() as directory:
            root = directory / "corpus"
            build_mini(root)
            data = (root / "manifest.json").read_text(encoding="utf-8")
            self.assertNotIn(str(REPO_ROOT), data)
            self.assertNotIn(str(Path.home()), data)
            self.assertNotIn("C:\\", data)
            self.assertNotIn("/Users/", data)
            self.assertNotIn("/home/", data)
            self.assertNotIn(socket.gethostname(), data)
            self.assertNotIn("\\", data)

    def test_ids_and_target_hashes_survive_regeneration(self) -> None:
        # SPEC-0004-R4, R9, R25.
        with temporary_directory() as first, temporary_directory() as second:
            build_mini(first / "corpus")
            build_mini(second / "corpus")
            rows_a = corpus_rows(first / "corpus")
            rows_b = corpus_rows(second / "corpus")
            self.assertEqual(set(rows_a), set(rows_b))
            for key in rows_a:
                self.assertEqual(rows_a[key]["text"], rows_b[key]["text"])
                self.assertEqual(
                    rows_a[key]["metadata"]["text_sha256"],
                    rows_b[key]["metadata"]["text_sha256"],
                )
                self.assertEqual(
                    rows_a[key]["metadata"]["content_sha256"],
                    rows_b[key]["metadata"]["content_sha256"],
                )
            passages_a = sidecar_rows(first / "corpus", "passages.jsonl")
            passages_b = sidecar_rows(second / "corpus", "passages.jsonl")
            self.assertEqual(
                [(row["_id"], row["text_sha256"]) for row in passages_a],
                [(row["_id"], row["text_sha256"]) for row in passages_b],
            )

    def test_scale_profiles_meet_document_and_passage_ranges(self) -> None:
        # SPEC-0004-R5: profile math and a reduced-scale build.
        from sdc_generator.profiles import load_profile

        smoke = load_profile(PROFILES_DIR / "sdc-smoke.json")
        self.assertEqual(smoke.target_documents, 200)
        self.assertEqual(smoke.base_documents, 120)
        self.assertEqual(smoke.code_documents, 20)
        small = load_profile(PROFILES_DIR / "sdc-s.json")
        self.assertEqual(small.base_documents + small.derived_documents, 10_000)
        medium = load_profile(PROFILES_DIR / "sdc-m.json")
        self.assertEqual(medium.extends, "sdc-s")
        self.assertEqual(medium.base_documents + medium.derived_documents, 100_000)
        with temporary_directory() as directory:
            root = directory / "corpus"
            summary = build_mini(root)
            self.assertEqual(summary["document_count"], 40)
            self.assertGreaterEqual(summary["passage_count"], 120)


class LayoutAndManifestTests(unittest.TestCase):
    def test_corpus_layout_matches_schema(self) -> None:
        # SPEC-0004-R4.
        with temporary_directory() as directory:
            root = directory / "corpus"
            build_mini(root)
            summary = verify_corpus(root)
            self.assertEqual(summary["documents"], 40)
            data = manifest(root)
            self.assertEqual(
                sorted(data["sidecars"]),
                [
                    "corpus.jsonl",
                    "duplicate-clusters.jsonl",
                    "extraction-truth.jsonl",
                    "passages.jsonl",
                    "versions.jsonl",
                ],
            )
            self.assertEqual(data["default_roots"], ["files/documents"])
            self.assertEqual(
                data["code_enabled_roots"], ["files/documents", "files/code"]
            )
            for row in corpus_rows(root).values():
                path = row["metadata"]["relative_path"]
                self.assertFalse(path.startswith("/"))
                self.assertNotIn("\\", path)
                self.assertRegex(row["metadata"]["content_sha256"], r"^[0-9a-f]{64}$")
            for truth in sidecar_rows(root, "extraction-truth.jsonl"):
                self.assertEqual(truth["truth_origin"], "generator-known")

    def test_manifest_detects_added_changed_and_missing_files(self) -> None:
        # SPEC-0004-R4, R13.
        with temporary_directory() as directory:
            root = directory / "corpus"
            build_mini(root)
            files = sorted((root / "files").rglob("*"))
            rendered = [path for path in files if path.is_file()]
            victim = rendered[0]
            original = victim.read_bytes()

            victim.write_bytes(original + b"tamper")
            with self.assertRaises(SdcError) as caught:
                verify_corpus(root)
            self.assertEqual(caught.exception.code, OUTPUT_HASH_MISMATCH)
            victim.write_bytes(original)

            extra = root / "files" / "documents" / "extra.txt"
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_text("extra", encoding="utf-8")
            with self.assertRaises(SdcError):
                verify_corpus(root)
            extra.unlink()

            victim.unlink()
            with self.assertRaises(SdcError):
                verify_corpus(root)
            victim.write_bytes(original)

            # The untouched corpus verifies again.
            verify_corpus(root)

    def test_failed_build_is_atomic(self) -> None:
        # SPEC-0004-R13: a render failure leaves the pre-existing tree intact.
        with temporary_directory() as directory:
            root = directory / "corpus"
            build_mini(root)
            before = tree_digests(root)

            def broken(document):
                raise RuntimeError("injected render failure")

            with self.assertRaises(SdcError):
                build_mini(root, render_fn=broken)
            self.assertEqual(before, tree_digests(root))
            verify_corpus(root)

    def test_build_and_verify_never_access_network(self) -> None:
        # SPEC-0004-R14.
        with temporary_directory() as directory:
            root = directory / "corpus"
            with mock.patch("socket.socket", side_effect=AssertionError("network used")), \
                    mock.patch.object(
                        urllib.request, "urlopen", side_effect=AssertionError("network used")
                    ):
                build_mini(root)
                verify_corpus(root)

    def test_corpus_hash_is_stable_for_the_committed_smoke_tree(self) -> None:
        # SPEC-0004-R3 golden hash: rebuild equals the committed tree.
        summary = verify_corpus(SMOKE_DIR)
        with temporary_directory() as directory:
            root = directory / "corpus"
            build_corpus(
                profile_path=PROFILES_DIR / "sdc-smoke.json",
                seed="sdc-smoke-v1",
                sources_dir=SDC_ROOT / "sources",
                cache=directory / "cache",
                output=root,
                repo_root=SDC_ROOT.parents[2],
            )
            self.assertEqual(
                summary["corpus_hash"], manifest(root)["corpus_hash"]
            )
            self.assertEqual(tree_digests(SMOKE_DIR), tree_digests(root))


class MalformedManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = Path(__import__("tempfile").mkdtemp(prefix="sdc-malformed-"))
        cls.original = cls._tmp / "original"
        build_mini(cls.original)

    @classmethod
    def tearDownClass(cls) -> None:
        import shutil

        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _copy(self, name: str) -> Path:
        import shutil

        target = self._tmp / name
        shutil.copytree(self.original, target)
        return target

    def test_duplicate_corpus_id_is_rejected(self) -> None:
        root = self._copy("duplicate-id")
        rows = sidecar_rows(root, "corpus.jsonl")
        rows[1]["_id"] = rows[0]["_id"]
        (root / "corpus.jsonl").write_text(
            "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
            + "\n",
            encoding="utf-8",
        )
        refresh_manifest(root)
        with self.assertRaises(SdcError):
            verify_corpus(root)

    def test_unknown_format_is_rejected(self) -> None:
        root = self._copy("unknown-format")
        rows = sidecar_rows(root, "corpus.jsonl")
        rows[0]["metadata"]["format"] = "docm"
        (root / "corpus.jsonl").write_text(
            "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
            + "\n",
            encoding="utf-8",
        )
        refresh_manifest(root)
        with self.assertRaises(SdcError):
            verify_corpus(root)

    def test_bad_utf8_jsonl_is_rejected(self) -> None:
        root = self._copy("bad-utf8")
        data = (root / "corpus.jsonl").read_bytes()
        (root / "corpus.jsonl").write_bytes(data + b"\xff\n")
        refresh_manifest(root)
        with self.assertRaises(SdcError):
            verify_corpus(root)

    def test_blank_jsonl_line_is_rejected(self) -> None:
        root = self._copy("blank-line")
        data = (root / "corpus.jsonl").read_text(encoding="utf-8")
        (root / "corpus.jsonl").write_text(data.replace("\n", "\n\n", 1), encoding="utf-8")
        refresh_manifest(root)
        with self.assertRaises(SdcError):
            verify_corpus(root)


if __name__ == "__main__":
    unittest.main()
