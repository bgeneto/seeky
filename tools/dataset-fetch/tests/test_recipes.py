"""Synthetic recipe tests: BEIR, MLDR, and constructed mMARCO pairs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dataset_fetch.cache import CachedFile
from dataset_fetch.canonical import sha256_bytes
from dataset_fetch.errors import DatasetFetchError
from dataset_fetch.recipes import beir, mldr, mmarco
from dataset_fetch.transform import QrelSpec, write_dataset
import support


def cached(url: str, path: Path) -> CachedFile:
    return CachedFile(url, path, path.stat().st_size, sha256_bytes(path.read_bytes()))


class BeirRecipeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def sources(self, *, dev_name: str = "qrels.dev.tsv") -> list[CachedFile]:
        return self.sources_from(support.source_files(), dev_name=dev_name)

    def sources_from(
        self, files: dict[str, bytes], *, dev_name: str = "qrels.dev.tsv"
    ) -> list[CachedFile]:
        dev_file = "dev.tsv" if dev_name == "qrels.dev.tsv" else dev_name
        urls = {
            "corpus.jsonl": "https://example.invalid/synthetic/corpus.jsonl",
            "queries.jsonl": "https://example.invalid/synthetic/queries.jsonl",
            dev_name: f"https://example.invalid/synthetic/qrels/{dev_file}",
            "qrels.test.tsv": f"https://example.invalid/synthetic/qrels/test.tsv",
        }
        files = dict(files)
        files[dev_name] = files.pop("qrels.dev.tsv")
        sources: list[CachedFile] = []
        for name, url in urls.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(files[name])
            sources.append(cached(url, path))
        return sources

    def test_empty_corpus_rows_are_omitted_and_counted(self) -> None:
        files = support.source_files()
        files["corpus.jsonl"] = support.jsonl(
            support.CORPUS + [{"_id": "d5", "title": "", "text": ""}]
        )
        files["qrels.dev.tsv"] = support.QRELS_DEV.encode() + b"q1\td5\t1\n"
        request = beir.prepare(support.manifest(), self.sources_from(files), "seed")
        self.assertNotIn("d5", {document.id for document in request.documents})
        self.assertEqual(request.notes["empty_documents_omitted"], 1)
        self.assertEqual(
            request.notes["qrels_dropped_for_empty_documents"], {"dev": 1, "test": 0}
        )
        self.assertTrue(request.splits["dev"].qrels)

    def test_dev_split_uses_source_train_claims(self) -> None:
        manifest = support.manifest()
        request = beir.prepare(manifest, self.sources(dev_name="train.tsv"), "seed")
        self.assertEqual([query.id for query in request.splits["dev"].queries], ["q1", "q2"])
        self.assertEqual([query.id for query in request.splits["test"].queries], ["q3", "q4"])
        self.assertEqual(len(request.documents), 4)
        self.assertEqual(request.splits["dev"].queries[0].language, "en")
        self.assertEqual(request.splits["dev"].queries[0].language_slice, "en")
        self.assertEqual(request.splits["dev"].queries[0].category, "conceptual")
        self.assertEqual(request.splits["dev"].queries[0].target_languages, ("en",))

    def test_beir_build_is_deterministic(self) -> None:
        manifest = support.manifest()
        request = beir.prepare(manifest, self.sources(), "seed")
        first = write_dataset(request, self.root / "a", relative_prefix="data")
        second = write_dataset(request, self.root / "b", relative_prefix="data")
        self.assertEqual(first.local_hashes, second.local_hashes)


class MldrRecipeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_mldr_native_splits_keep_language_and_ids(self) -> None:
        downloads = self.root / "downloads"
        support.write_gzip_jsonl(
            downloads / "corpus.jsonl.gz",
            [{"docid": "doc-pt-1", "text": "Primeiro artigo longo."},
             {"docid": "doc-pt-2", "text": "Segundo artigo longo."}],
        )
        support.write_gzip_jsonl(
            downloads / "dev.jsonl.gz",
            [{"query_id": "q-pt-1", "query": "primeiro artigo?", "positive_passages": []}],
        )
        support.write_gzip_jsonl(
            downloads / "test.jsonl.gz",
            [{"query_id": "q-pt-2", "query": "segundo artigo?", "positive_passages": []}],
        )
        (downloads / "qrels.dev.tsv").write_text(
            "q-pt-1\tQ0\tdoc-pt-1\t1\n", encoding="utf-8"
        )
        (downloads / "qrels.test.tsv").write_text(
            "q-pt-2\tQ0\tdoc-pt-2\t1\n", encoding="utf-8"
        )
        base = "https://example.invalid/mldr-pt"
        sources = [
            cached(f"{base}/mldr-v1.0-pt/corpus.jsonl.gz", downloads / "corpus.jsonl.gz"),
            cached(f"{base}/mldr-v1.0-pt/dev.jsonl.gz", downloads / "dev.jsonl.gz"),
            cached(f"{base}/mldr-v1.0-pt/test.jsonl.gz", downloads / "test.jsonl.gz"),
            cached(f"{base}/qrels/qrels.mldr-v1.0-pt-dev.tsv", downloads / "qrels.dev.tsv"),
            cached(f"{base}/qrels/qrels.mldr-v1.0-pt-test.tsv", downloads / "qrels.test.tsv"),
        ]
        manifest = support.manifest(
            "mldr-pt",
            defaults={
                "language": "pt",
                "target_languages": ["pt"],
                "language_slice": "pt",
            },
        )
        request = mldr.prepare_pt(manifest, sources, "dataset-transform-v1")
        self.assertEqual(request.dataset_id, "mldr-pt")
        self.assertEqual(len(request.documents), 2)
        self.assertEqual(request.splits["dev"].queries[0].id, "q-pt-1")
        self.assertEqual(request.splits["dev"].queries[0].language_slice, "pt")
        self.assertEqual(request.splits["dev"].qrels[0].document_id, "doc-pt-1")


class CrossLingualTests(unittest.TestCase):
    def test_constructed_pairs_are_stable_and_record_both_languages(self) -> None:
        queries = {"10": "qual é o significado?", "20": "outra pergunta"}
        qrels = {
            "10": [QrelSpec("10", "doc-en-9", 2)],
            "20": [QrelSpec("20", "doc-en-3", 1)],
        }
        first, first_qrels = mmarco.construct_cross_lingual(
            queries, qrels, source_language="pt", target_language="en"
        )
        second, second_qrels = mmarco.construct_cross_lingual(
            dict(reversed(list(queries.items()))),
            dict(reversed(list(qrels.items()))),
            source_language="pt",
            target_language="en",
        )
        self.assertEqual(
            [query.id for query in first], ["10-xl-pt-en", "20-xl-pt-en"]
        )
        self.assertEqual(
            [query.id for query in second], [query.id for query in first]
        )
        self.assertEqual(first[0].text, "qual é o significado?")
        self.assertEqual(first[0].language, "pt")
        self.assertEqual(first[0].target_languages, ("en",))
        self.assertEqual(first[0].language_slice, "cross_lingual")
        self.assertEqual(first_qrels[0].query_id, "10-xl-pt-en")
        self.assertEqual(first_qrels[0].document_id, "doc-en-9")
        self.assertEqual(
            [(qrel.query_id, qrel.document_id, qrel.grade) for qrel in first_qrels],
            [(qrel.query_id, qrel.document_id, qrel.grade) for qrel in second_qrels],
        )

    def test_constructed_pairs_reject_a_single_language(self) -> None:
        with self.assertRaises(DatasetFetchError):
            mmarco.construct_cross_lingual(
                {"1": "x"}, {"1": [QrelSpec("1", "d", 1)]}, source_language="pt", target_language="pt"
            )

    def test_carve_out_is_deterministic_and_disjoint(self) -> None:
        ids = [f"q{index}" for index in range(20)]
        first = mmarco.carve_out_split(ids, seed="dataset-transform-v1", purpose="test")
        second = mmarco.carve_out_split(list(reversed(ids)), seed="dataset-transform-v1", purpose="test")
        self.assertEqual(first, second)
        dev, test = first
        self.assertFalse(set(dev) & set(test))
        self.assertEqual(set(dev) | set(test), set(ids))
        self.assertTrue(dev and test)

    def test_mmarco_recipe_builds_cross_lingual_splits(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "english_collection.tsv").write_text(
            "doc-en-9\tA passage in English.\ndoc-en-3\tAnother English passage.\n",
            encoding="utf-8",
        )
        (root / "portuguese_queries.dev.tsv").write_text(
            "10\tqual é o significado?\n20\toutra pergunta\n", encoding="utf-8"
        )
        (root / "qrels.dev.tsv").write_text(
            "10\t0\tdoc-en-9\t1\n20\t0\tdoc-en-3\t1\n", encoding="utf-8"
        )
        base = "https://example.invalid/mmarco"
        sources = [
            cached(f"{base}/english_collection.tsv", root / "english_collection.tsv"),
            cached(f"{base}/portuguese_queries.dev.tsv", root / "portuguese_queries.dev.tsv"),
            cached(f"{base}/qrels.dev.tsv", root / "qrels.dev.tsv"),
        ]
        manifest = support.manifest("mmarco-pt-en")
        request = mmarco.prepare_mmarco_pt_en(manifest, sources, "dataset-transform-v1")
        self.assertEqual(len(request.documents), 2)
        for split in ("dev", "test"):
            self.assertTrue(request.splits[split].queries)
            for query in request.splits[split].queries:
                self.assertTrue(query.id.endswith("-xl-pt-en"))
                self.assertEqual(query.language, "pt")
                self.assertEqual(query.target_languages, ("en",))
        built = write_dataset(request, root / "out", relative_prefix="data")
        self.assertTrue(built.local_hashes)


if __name__ == "__main__":
    unittest.main()
