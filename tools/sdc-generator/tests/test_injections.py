"""Duplicate, version, boilerplate, and code-root injection tests (R9-R12)."""

from __future__ import annotations

import unittest

from support import (
    PROFILES_DIR,
    SDC_ROOT,
    BuiltCorpus,
    corpus_rows,
    manifest,
    sidecar_rows,
)


class DuplicateTests(BuiltCorpus):
    def setUp(self) -> None:
        self.rows = corpus_rows(self.corpus)
        self.clusters = sidecar_rows(self.corpus, "duplicate-clusters.jsonl")
        self.passages = sidecar_rows(self.corpus, "passages.jsonl")

    def test_duplicate_injection_counts_and_clusters_match_profile(self) -> None:
        # SPEC-0004-R9.
        from support import TESTMINI_PROFILE
        from sdc_generator.profiles import load_profile

        profile = load_profile(TESTMINI_PROFILE)
        counts = manifest(self.corpus)["injection_counts"]
        for key, expected in counts.items():
            self.assertEqual(expected, profile.injection[key], key)
        kinds = {}
        for cluster in self.clusters:
            kinds[cluster["kind"]] = kinds.get(cluster["kind"], 0) + 1
        self.assertEqual(kinds.get("exact_byte"), 2)
        self.assertEqual(kinds.get("exact_text"), 2)
        self.assertEqual(kinds.get("scanned_variant"), 2)
        self.assertEqual(kinds.get("near_duplicate"), 2)
        self.assertEqual(kinds.get("version"), 2)

    def test_duplicate_clusters_are_symmetric_and_unique(self) -> None:
        # SPEC-0004-R9 property.
        for cluster in self.clusters:
            members = cluster["member_document_ids"]
            self.assertEqual(len(members), len(set(members)))
            self.assertIn(cluster["canonical_document_id"], members)
            for member in members:
                self.assertIn(
                    cluster["cluster_id"],
                    self.rows[member]["metadata"]["duplicate_cluster_ids"],
                )
        by_id = {cluster["cluster_id"]: cluster for cluster in self.clusters}
        for row in self.rows.values():
            seen: set[str] = set()
            for cluster_id in row["metadata"]["duplicate_cluster_ids"]:
                self.assertIn(cluster_id, by_id)
                self.assertNotIn(cluster_id, seen)
                seen.add(cluster_id)
                self.assertIn(row["_id"], by_id[cluster_id]["member_document_ids"])

    def test_exact_byte_copies_share_bytes_but_not_identity(self) -> None:
        # SPEC-0004-R9.
        byte_clusters = [c for c in self.clusters if c["kind"] == "exact_byte"]
        self.assertTrue(byte_clusters)
        for cluster in byte_clusters:
            canonical, copy = cluster["member_document_ids"]
            first = self.rows[canonical]["metadata"]
            second = self.rows[copy]["metadata"]
            self.assertNotEqual(canonical, copy)
            self.assertEqual(first["content_sha256"], second["content_sha256"])
            self.assertEqual(first["text_sha256"], second["text_sha256"])
            self.assertNotEqual(first["relative_path"], second["relative_path"])
            first_bytes = (self.corpus / first["relative_path"]).read_bytes()
            second_bytes = (self.corpus / second["relative_path"]).read_bytes()
            self.assertEqual(first_bytes, second_bytes)

    def test_exact_text_copies_share_text_not_bytes(self) -> None:
        text_clusters = [c for c in self.clusters if c["kind"] == "exact_text"]
        self.assertTrue(text_clusters)
        for cluster in text_clusters:
            canonical, copy = cluster["member_document_ids"]
            first = self.rows[canonical]["metadata"]
            second = self.rows[copy]["metadata"]
            self.assertEqual(first["text_sha256"], second["text_sha256"])
            self.assertEqual(first["format"] != second["format"], True)
            self.assertNotEqual(first["content_sha256"], second["content_sha256"])

    def test_renamed_and_moved_copies_keep_identity(self) -> None:
        # SPEC-0004-R9: identity derives from role and index, not path.
        supports = [
            cluster
            for cluster in self.clusters
            if cluster["kind"] == "exact_byte"
        ]
        for cluster in supports:
            canonical, copy = cluster["member_document_ids"]
            copy_path = self.rows[copy]["metadata"]["relative_path"]
            self.assertIn("/arquivo/", copy_path)
            self.assertNotEqual(copy, canonical)
            self.assertEqual(
                self.rows[copy]["_id"],
                self.rows[copy]["metadata"].get("document_id", self.rows[copy]["_id"]),
            )
        # A stale path cannot change the canonical text hash.
        row = next(iter(self.rows.values()))
        before = row["metadata"]["text_sha256"]
        path = row["metadata"]["relative_path"]
        row["metadata"]["relative_path"] = "files/documents/renamed.txt"
        self.assertEqual(row["metadata"]["text_sha256"], before)
        row["metadata"]["relative_path"] = path

    def test_near_duplicates_change_bounded_text_only(self) -> None:
        clusters = [c for c in self.clusters if c["kind"] == "near_duplicate"]
        self.assertTrue(clusters)
        for cluster in clusters:
            canonical, near = cluster["member_document_ids"]
            self.assertNotEqual(
                self.rows[canonical]["metadata"]["text_sha256"],
                self.rows[near]["metadata"]["text_sha256"],
            )
            self.assertNotEqual(
                self.rows[canonical]["metadata"]["relative_path"],
                self.rows[near]["metadata"]["relative_path"],
            )

    def test_scanned_variants_keep_canonical_text(self) -> None:
        clusters = [c for c in self.clusters if c["kind"] == "scanned_variant"]
        self.assertTrue(clusters)
        for cluster in clusters:
            canonical, scan = cluster["member_document_ids"]
            self.assertIn(
                self.rows[scan]["metadata"]["format"], ("scanned-pdf", "scanned-image")
            )
            self.assertEqual(
                self.rows[canonical]["metadata"]["text_sha256"],
                self.rows[scan]["metadata"]["text_sha256"],
            )


class VersionTests(BuiltCorpus):
    def setUp(self) -> None:
        self.rows = corpus_rows(self.corpus)
        self.passages = {
            row["_id"]: row for row in sidecar_rows(self.corpus, "passages.jsonl")
        }
        self.versions = sidecar_rows(self.corpus, "versions.jsonl")

    def test_version_groups_are_ordered_and_changed_spans_are_valid(self) -> None:
        # SPEC-0004-R10.
        self.assertTrue(self.versions)
        for group in self.versions:
            members = group["members"]
            self.assertEqual(
                [member["version_number"] for member in members],
                list(range(1, len(members) + 1)),
            )
            self.assertEqual(sum(member["is_latest"] for member in members), 1)
            self.assertTrue(members[-1]["is_latest"])
            self.assertEqual(members[0]["changed_passages"], [])
            for member in members[1:]:
                for change in member["changed_passages"]:
                    if change["change"] == "added":
                        self.assertIsNone(change["from_passage_id"])
                        self.assertIn(change["to_passage_id"], self.passages)
                    elif change["change"] == "removed":
                        self.assertIsNone(change["to_passage_id"])
                        self.assertIn(change["from_passage_id"], self.passages)
                    else:
                        self.assertIn(change["from_passage_id"], self.passages)
                        self.assertIn(change["to_passage_id"], self.passages)
                        self.assertNotEqual(
                            self.passages[change["from_passage_id"]]["text_sha256"],
                            self.passages[change["to_passage_id"]]["text_sha256"],
                        )

    def test_each_version_has_distinct_document_id(self) -> None:
        # SPEC-0004-R10.
        for group in self.versions:
            identifiers = [member["document_id"] for member in group["members"]]
            self.assertEqual(len(identifiers), len(set(identifiers)))
            for identifier in identifiers:
                self.assertIn(identifier, self.rows)
                self.assertEqual(
                    self.rows[identifier]["metadata"]["version_group_id"],
                    group["version_group_id"],
                )

    def test_version_cluster_matches_version_group(self) -> None:
        clusters = {
            row["cluster_id"]: row
            for row in sidecar_rows(self.corpus, "duplicate-clusters.jsonl")
        }
        for group in self.versions:
            cluster = clusters[group["version_group_id"]]
            self.assertEqual(cluster["kind"], "version")
            self.assertEqual(
                sorted(cluster["member_document_ids"]),
                sorted(member["document_id"] for member in group["members"]),
            )


class BoilerplateTests(BuiltCorpus):
    def setUp(self) -> None:
        self.rows = corpus_rows(self.corpus)
        self.passages = sidecar_rows(self.corpus, "passages.jsonl")
        self.by_document: dict[str, list[dict]] = {}
        for passage in self.passages:
            self.by_document.setdefault(passage["document_id"], []).append(passage)

    def test_boilerplate_counts_and_families_match_profile(self) -> None:
        # SPEC-0004-R11.
        manifest_counts = manifest(self.corpus)["injection_counts"]
        receiving = [
            row
            for row in self.rows.values()
            if row["metadata"]["boilerplate_family_ids"]
        ]
        self.assertEqual(len(receiving), manifest_counts["boilerplate_documents"])
        families = set()
        for row in receiving:
            families.update(row["metadata"]["boilerplate_family_ids"])
        self.assertEqual(
            families, {"header", "footer", "disclaimer", "navigation"}
        )

    def test_only_injected_spans_are_boilerplate(self) -> None:
        # SPEC-0004-R11 property.
        from sdc_generator.jsonio import load_json_file
        from support import SDC_ROOT

        boilerplate = load_json_file(
            SDC_ROOT / "sources" / "templates" / "syn-boilerplate-v1.json",
            display="syn-boilerplate-v1.json",
        )["families"]
        family_texts = {
            text for texts in boilerplate.values() for text in texts
        }
        for document_id, passages in self.by_document.items():
            for passage in passages:
                if passage["boilerplate_family_id"] is None:
                    self.assertNotIn(
                        passage["text"],
                        family_texts,
                        f"unique body text marked as boilerplate in {document_id}",
                    )
                else:
                    self.assertIn(passage["text"], family_texts)
                    self.assertIn(
                        passage["boilerplate_family_id"],
                        self.rows[document_id]["metadata"]["boilerplate_family_ids"],
                    )


class CodeRootTests(BuiltCorpus):
    def test_default_root_contains_no_source_code(self) -> None:
        # SPEC-0004-R12.
        rows = corpus_rows(self.corpus)
        code = [row for row in rows.values() if row["metadata"]["file_class"] == "source_code"]
        self.assertTrue(code)
        for row in rows.values():
            path = row["metadata"]["relative_path"]
            if row["metadata"]["file_class"] == "source_code":
                self.assertTrue(path.startswith("files/code/"))
            else:
                self.assertFalse(path.startswith("files/code/"))

    def test_code_enabled_root_adds_only_code(self) -> None:
        # SPEC-0004-R12.
        data = manifest(self.corpus)
        self.assertEqual(data["default_roots"], ["files/documents"])
        self.assertEqual(
            data["code_enabled_roots"], ["files/documents", "files/code"]
        )
        rows = corpus_rows(self.corpus)
        default_paths = {
            row["metadata"]["relative_path"]
            for row in rows.values()
            if row["metadata"]["file_class"] != "source_code"
        }
        code_paths = {
            row["metadata"]["relative_path"]
            for row in rows.values()
            if row["metadata"]["file_class"] == "source_code"
        }
        self.assertFalse(default_paths & code_paths)
        self.assertTrue(all(path.startswith("files/code/") for path in code_paths))
        self.assertTrue(all(path.startswith("files/documents/") for path in default_paths))


if __name__ == "__main__":
    unittest.main()
