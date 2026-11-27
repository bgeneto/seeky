"""Byte determinism, split invariants, and category/language validation (R24)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dataset_fetch.canonical import sha256_bytes
from dataset_fetch.errors import DatasetFetchError
from dataset_fetch.jsio import pretty_json_bytes, write_bytes
from dataset_fetch.manifest import dataset_fingerprint, validate_manifest
from dataset_fetch.transform import (
    BuildRequest,
    DocumentSpec,
    QrelSpec,
    QuerySpec,
    SplitSpec,
    parse_prepared,
    write_dataset,
)
import support


def base_request(*, files_root: str | None = "data/files") -> BuildRequest:
    documents = [
        DocumentSpec("d1", "Alpha", "First document about induction."),
        DocumentSpec("d2", "", "Second document about magnets."),
        DocumentSpec("d3", "Gamma", "Third document about induction and magnets."),
    ]
    dev = SplitSpec(
        queries=[QuerySpec("q1", "induction", "en", ("en",), "en", "conceptual")],
        qrels=[QrelSpec("q1", "d1", 2)],
    )
    test = SplitSpec(
        queries=[
            QuerySpec(
                "q2",
                "indução",
                "pt",
                ("en",),
                "cross_lingual",
                "conceptual",
            )
        ],
        qrels=[QrelSpec("q2", "d3", 1)],
    )
    return BuildRequest(
        dataset_id="synthetic-transform",
        documents=documents,
        splits={"dev": dev, "test": test},
        files_root=files_root,
    )


class TransformDeterminismTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def tree(self, root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_transform_is_byte_deterministic(self) -> None:
        first = write_dataset(base_request(), self.root / "a", relative_prefix="data")
        second = write_dataset(base_request(), self.root / "b", relative_prefix="data")
        self.assertEqual(first.local_hashes, second.local_hashes)
        self.assertEqual(first.corpus_sha256, second.corpus_sha256)
        self.assertEqual(first.query_set_sha256, second.query_set_sha256)
        self.assertEqual(self.tree(self.root / "a"), self.tree(self.root / "b"))
        self.assertEqual(self.tree(self.root / "a"), self.tree(self.root / "a"))

    def test_input_order_does_not_change_bytes(self) -> None:
        request = base_request()
        shuffled = BuildRequest(
            dataset_id=request.dataset_id,
            documents=list(reversed(request.documents)),
            splits={
                "dev": SplitSpec(
                    queries=list(reversed(request.splits["dev"].queries)),
                    qrels=list(reversed(request.splits["dev"].qrels)),
                ),
                "test": request.splits["test"],
            },
            files_root=request.files_root,
        )
        first = write_dataset(request, self.root / "a", relative_prefix="data")
        second = write_dataset(shuffled, self.root / "b", relative_prefix="data")
        self.assertEqual(first.local_hashes, second.local_hashes)
        self.assertEqual(self.tree(self.root / "a"), self.tree(self.root / "b"))

    def test_crlf_and_decomposed_text_are_normalized(self) -> None:
        request = base_request()
        request.documents.append(
            DocumentSpec("d4", "Cafe\u0301", "line one\r\nline two\rline three")
        )
        result = write_dataset(request, self.root / "data", relative_prefix="data")
        path = self.root / "data" / "files" / (sha256_bytes(b"d4") + ".txt")
        self.assertEqual(
            path.read_text(encoding="utf-8"), "Café\n\nline one\nline two\nline three"
        )
        self.assertEqual(result.local_hashes[f"data/files/{sha256_bytes(b'd4')}.txt"], sha256_bytes(path.read_bytes()))


class TransformInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_rejected(self, request: BuildRequest) -> None:
        with self.assertRaises(DatasetFetchError):
            write_dataset(request, self.root / "data", relative_prefix="data")

    def test_splits_must_be_disjoint(self) -> None:
        request = base_request()
        request.splits["test"].queries.append(
            QuerySpec("q1", "duplicate", "en", ("en",), "en", "conceptual")
        )
        self.assert_rejected(request)

    def test_qrels_must_resolve(self) -> None:
        request = base_request()
        request.splits["dev"].qrels.append(QrelSpec("q1", "missing", 1))
        self.assert_rejected(request)
        request = base_request()
        request.splits["dev"].qrels.append(QrelSpec("missing", "d1", 1))
        self.assert_rejected(request)

    def test_grades_must_be_between_zero_and_three(self) -> None:
        request = base_request()
        request.splits["dev"].qrels.append(QrelSpec("q1", "d2", 4))
        self.assert_rejected(request)

    def test_duplicate_ids_are_rejected(self) -> None:
        request = base_request()
        request.documents.append(DocumentSpec("d1", "", "duplicate"))
        self.assert_rejected(request)

    def test_beir_categories_and_language_slices_are_enforced(self) -> None:
        request = base_request()
        request.splits["dev"].queries[0] = QuerySpec(
            "q1", "code", "en", ("en",), "en", "code_search"
        )
        self.assert_rejected(request)

        request = base_request()
        request.splits["dev"].queries[0] = QuerySpec(
            "q1", "odd", "en", ("en",), "klingon", "conceptual"
        )
        self.assert_rejected(request)

        request = base_request()
        request.splits["test"].queries[0] = QuerySpec(
            "q2", "indução", "pt", ("pt",), "cross_lingual", "conceptual"
        )
        self.assert_rejected(request)

        request = base_request()
        request.splits["dev"].queries[0] = QuerySpec(
            "q1", "induction", "en", ("pt",), "en", "conceptual"
        )
        self.assert_rejected(request)


class PreparedDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def prepare(self, request: BuildRequest) -> tuple[Path, dict, object]:
        dataset_dir = self.root / "synthetic-transform"
        dataset_dir.mkdir()
        manifest = support.manifest("synthetic-transform")
        manifest["files_root"] = request.files_root
        result = write_dataset(request, dataset_dir / "data", relative_prefix="data")
        manifest["local_file_sha256"] = result.local_hashes
        manifest["corpus"] = "data/corpus.jsonl"
        manifest["splits"] = {
            "dev": {"queries": "data/queries.dev.jsonl", "qrels": "data/qrels.dev.tsv"},
            "test": {"queries": "data/queries.test.jsonl", "qrels": "data/qrels.test.tsv"},
        }
        validate_manifest(manifest, dataset_dir=dataset_dir, require_local_hashes=True)
        write_bytes(dataset_dir / "manifest.json", pretty_json_bytes(manifest))
        return dataset_dir, manifest, result

    def test_prepared_dataset_round_trips_and_hashes(self) -> None:
        dataset_dir, manifest, result = self.prepare(base_request())
        parsed = parse_prepared(dataset_dir, manifest)
        self.assertEqual(parsed.counts, result.counts)
        self.assertEqual(parsed.language_slices, {"cross_lingual": 1, "en": 1})
        self.assertEqual(parsed.categories, {"conceptual": 2})
        self.assertEqual(parsed.corpus_sha256, result.corpus_sha256)
        expected = dataset_fingerprint(manifest, manifest["local_file_sha256"])
        self.assertEqual(len(expected), 64)

    def test_engine_file_text_must_match_corpus(self) -> None:
        dataset_dir, manifest, _ = self.prepare(base_request())
        path = dataset_dir / "data" / "files" / (sha256_bytes(b"d1") + ".txt")
        path.write_text("tampered text", encoding="utf-8")
        with self.assertRaises(DatasetFetchError):
            parse_prepared(dataset_dir, manifest)

    def test_manifest_without_files_root_has_no_relative_paths(self) -> None:
        dataset_dir, manifest, _ = self.prepare(base_request(files_root=None))
        parsed = parse_prepared(dataset_dir, manifest)
        self.assertEqual(len(parsed.documents), 3)
        self.assertFalse((dataset_dir / "data" / "files").exists())


if __name__ == "__main__":
    unittest.main()
