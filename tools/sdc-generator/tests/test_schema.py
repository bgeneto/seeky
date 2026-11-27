"""Schema strictness, fuzz, and personal-data safety tests (R6, R13)."""

from __future__ import annotations

import json
import re
import unicodedata
import unittest
from pathlib import Path

from support import (
    SDC_ROOT,
    SMOKE_DIR,
    corpus_rows,
    manifest,
    random_bytes,
    sidecar_rows,
    temporary_directory,
)

from sdc_generator.errors import SCHEMA_INVALID, SdcError
from sdc_generator.jsonio import load_json_bytes, read_jsonl_bytes, sha256_bytes
from sdc_generator.readers import read_rendered
from sdc_generator.verify import verify_corpus

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
_WINDOWS_PATH = re.compile(r"[A-Za-z]:\\|\\\\[A-Za-z0-9._\-]+\\")
_UNIX_HOME = re.compile(r"/(?:home|Users)/[A-Za-z0-9._\-]+")
_SECRET = re.compile(
    r"AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
)


def _strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)


class JsonStrictnessTests(unittest.TestCase):
    def test_duplicate_keys_are_rejected(self) -> None:
        with self.assertRaises(SdcError) as caught:
            load_json_bytes(b'{"a": 1, "a": 2}')
        self.assertEqual(caught.exception.code, SCHEMA_INVALID)

    def test_nan_and_infinity_are_rejected(self) -> None:
        for payload in (b'{"a": NaN}', b'{"a": Infinity}', b'{"a": -Infinity}'):
            with self.assertRaises(SdcError):
                load_json_bytes(payload)

    def test_invalid_utf8_is_rejected(self) -> None:
        with self.assertRaises(SdcError):
            load_json_bytes(b'{"a": "\xff"}')

    def test_trailing_data_is_rejected(self) -> None:
        with self.assertRaises(SdcError):
            load_json_bytes(b'{"a": 1} trailing')

    def test_jsonl_requires_lf_and_one_object_per_line(self) -> None:
        with self.assertRaises(SdcError):
            read_jsonl_bytes(b'{"a":1}\r\n', file="x.jsonl")
        with self.assertRaises(SdcError):
            read_jsonl_bytes(b'{"a":1}', file="x.jsonl")
        with self.assertRaises(SdcError):
            read_jsonl_bytes(b"\n", file="x.jsonl")

    def test_fuzz_json_and_jsonl_readers(self) -> None:
        # SPEC-0004-R13: arbitrary bytes, typed error or clean rejection, no crash.
        for seed in range(1, 201):
            payload = random_bytes(seed * 7, seed=seed)
            for reader in (
                lambda data: load_json_bytes(data),
                lambda data: read_jsonl_bytes(data, file="fuzz.jsonl"),
            ):
                try:
                    reader(payload)
                except SdcError:
                    pass
                except Exception as exc:  # noqa: BLE001 - only assert no crash
                    self.assertNotIsInstance(exc, (SystemExit, MemoryError))


class RendererFuzzTests(unittest.TestCase):
    def test_fuzz_renderer_readers(self) -> None:
        # Arbitrary bytes must not crash the process; a normal exception is
        # acceptable for a malformed archive or document.
        with temporary_directory() as directory:
            for fmt in ("docx", "xlsx", "pptx", "odt", "rtf", "epub", "eml"):
                for seed in (3, 11, 29):
                    path = directory / f"fuzz-{seed}.{fmt}"
                    path.write_bytes(random_bytes(512, seed=seed))
                    try:
                        read_rendered(fmt, path)
                    except Exception as exc:  # noqa: BLE001
                        self.assertNotIsInstance(exc, (SystemExit, MemoryError))


class CommittedCorpusSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = verify_corpus(SMOKE_DIR)
        cls.rows = corpus_rows(SMOKE_DIR)
        cls.manifest = manifest(SMOKE_DIR)

    def test_smoke_profile_meets_file_and_size_caps(self) -> None:
        # SPEC-0004-R5.
        self.assertEqual(self.summary["files"], 200)
        self.assertGreaterEqual(self.summary["passages"], 2_000)
        total = sum(
            path.stat().st_size
            for path in SMOKE_DIR.rglob("*")
            if path.is_file()
        )
        self.assertLessEqual(total, 67_108_864)

    def test_smoke_contains_every_renderer(self) -> None:
        formats = {row["metadata"]["format"] for row in self.rows.values()}
        expected = {
            "pdf",
            "scanned-pdf",
            "scanned-image",
            "docx",
            "xlsx",
            "pptx",
            "odt",
            "rtf",
            "html",
            "epub",
            "eml",
            "md",
            "txt",
            "code",
        }
        self.assertEqual(formats, expected)

    def test_corpus_text_is_nfc_with_lf(self) -> None:
        for row in self.rows.values():
            self.assertEqual(row["text"], unicodedata.normalize("NFC", row["text"]))
            self.assertNotIn("\r", row["text"])
            self.assertEqual(
                row["metadata"]["text_sha256"],
                sha256_bytes(row["text"].encode("utf-8")),
            )

    def test_no_personal_data_paths_or_secrets(self) -> None:
        # SPEC-0004-R6, R3.
        blobs: list[tuple[str, str]] = []
        for row in self.rows.values():
            blobs.append((row["_id"], row["text"]))
            for key, value in row["metadata"].items():
                if isinstance(value, str):
                    blobs.append((f"{row['_id']}/{key}", value))
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            blobs.append((f"{row['_id']}/{key}", item))
        for name in (
            "passages.jsonl",
            "extraction-truth.jsonl",
            "duplicate-clusters.jsonl",
            "versions.jsonl",
        ):
            for row in sidecar_rows(SMOKE_DIR, name):
                blobs.extend((name, value) for value in _strings(row))
        for where, text in blobs:
            for match in _EMAIL.finditer(text):
                self.assertIn(
                    match.group(1).lower(),
                    {"example.com", "example.org", "example.net", "example.invalid"},
                    f"{where}: {match.group(0)}",
                )
            self.assertIsNone(_WINDOWS_PATH.search(text), where)
            self.assertIsNone(_UNIX_HOME.search(text), where)
            self.assertIsNone(_SECRET.search(text), where)
        manifest_text = (SMOKE_DIR / "manifest.json").read_text(encoding="utf-8")
        self.assertNotIn("C:\\", manifest_text)
        self.assertNotIn("/Users/", manifest_text)
        self.assertNotIn(str(Path.home()), manifest_text)

    def test_relative_paths_are_posix_and_resolve(self) -> None:
        for row in self.rows.values():
            relative = row["metadata"]["relative_path"]
            self.assertFalse(relative.startswith("/"))
            self.assertNotIn("\\", relative)
            self.assertNotIn("..", relative.split("/"))
            self.assertTrue((SMOKE_DIR / relative).is_file())

    def test_smoke_supports_every_query_category_population(self) -> None:
        # SPEC-0004-R5 and section 4.5 fixture coverage.
        rows = self.rows.values()
        languages = {row["metadata"]["languages"][0] for row in rows}
        self.assertIn("pt-BR", languages)
        self.assertIn("en-US", languages)
        self.assertTrue(
            any(row["metadata"]["file_class"] == "source_code" for row in rows)
        )
        self.assertTrue(
            any("XT-4471" in row["text"] for row in rows),
            "needle passage missing",
        )
        passages_by_doc: dict[str, int] = {}
        for passage in sidecar_rows(SMOKE_DIR, "passages.jsonl"):
            passages_by_doc[passage["document_id"]] = (
                passages_by_doc.get(passage["document_id"], 0) + 1
            )
        self.assertTrue(
            any(count >= 40 for count in passages_by_doc.values()),
            "long document missing",
        )
        identifier = re.compile(r"\b(?:CT|INV|POL|RT|TR|MAN|LR|ES|FR|DE|JA|EL)-\d{4}-\d{4,6}\b")
        self.assertTrue(
            any(identifier.search(row["text"]) for row in rows),
            "exact identifier missing",
        )
        self.assertTrue(
            any(
                any(ord(char) > 127 for char in row["metadata"]["relative_path"])
                for row in rows
            ),
            "accented filename missing",
        )
        years = {row["metadata"]["modified_at"][:4] for row in rows}
        self.assertGreaterEqual(len(years), 5)
        clusters = sidecar_rows(SMOKE_DIR, "duplicate-clusters.jsonl")
        self.assertTrue(any(cluster["kind"] == "version" for cluster in clusters))
        self.assertTrue(any(cluster["kind"] == "scanned_variant" for cluster in clusters))


class ReservedExampleDomainTests(unittest.TestCase):
    def test_templates_and_committed_corpus_use_reserved_domains(self) -> None:
        # SPEC-0004-R6.
        for path in sorted((SDC_ROOT / "sources" / "templates").glob("*.json")):
            for match in _EMAIL.finditer(path.read_text(encoding="utf-8")):
                self.assertIn(
                    match.group(1).lower(),
                    {"example.com", "example.org", "example.net", "example.invalid"},
                )
        corpus = corpus_rows(SMOKE_DIR)
        for row in corpus.values():
            for match in _EMAIL.finditer(row["text"]):
                self.assertIn(
                    match.group(1).lower(),
                    {"example.com", "example.org", "example.net", "example.invalid"},
                )


if __name__ == "__main__":
    unittest.main()
