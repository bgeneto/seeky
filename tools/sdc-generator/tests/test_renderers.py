"""Renderer round-trip, scan determinism, and truth tests (R7, R8)."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from support import BuiltCorpus, SMOKE_DIR, corpus_rows, sidecar_rows

from sdc_generator.jsonio import normalize_extracted
from sdc_generator.readers import read_rendered

_HARNESS_DIR = Path(__file__).resolve().parent.parent / "engine-roundtrip" / "target" / "debug"
_ENGINE_BIN = next(
    (
        candidate
        for candidate in (
            _HARNESS_DIR / "sdc-engine-roundtrip.exe",
            _HARNESS_DIR / "sdc-engine-roundtrip",
        )
        if candidate.is_file()
    ),
    _HARNESS_DIR / "sdc-engine-roundtrip",
)
_PDFIUM = Path(
    os.environ.get("SDC_PDFIUM_DLL", "")
    or (Path(os.environ.get("LOCALAPPDATA", "")) / "Gety" / "lib" / "pdfium.dll")
)


def _passages_by_doc(root: Path) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in sidecar_rows(root, "passages.jsonl"):
        grouped.setdefault(row["document_id"], []).append(row)
    return grouped


class RendererRoundTripTests(unittest.TestCase):
    corpus = SMOKE_DIR

    def test_renderer_round_trip_preserves_text_and_locators(self) -> None:
        # SPEC-0004-R7, parameterized by format.
        rows = corpus_rows(self.corpus)
        passages = _passages_by_doc(self.corpus)
        formats = [
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
        ]
        for fmt in formats:
            document = next(
                (row for row in rows.values() if row["metadata"]["format"] == fmt),
                None,
            )
            self.assertIsNotNone(document, f"corpus lacks {fmt}")
            text = read_rendered(fmt, self.corpus / document["metadata"]["relative_path"])
            normalized = normalize_extracted(text)
            for passage in passages[document["_id"]]:
                self.assertIn(
                    normalize_extracted(passage["text"]),
                    normalized,
                    f"{fmt} lost passage {passage['_id']}",
                )
                self.assertIn("block_id", passage["locator"])
                self.assertTrue(passage["locator"]["block_id"])

    def test_text_pdf_contains_text_operators(self) -> None:
        rows = corpus_rows(self.corpus)
        document = next(
            row for row in rows.values() if row["metadata"]["format"] == "pdf"
        )
        data = (self.corpus / document["metadata"]["relative_path"]).read_bytes()
        self.assertIn(b"/Font", data)
        self.assertIn(b"BT", data)
        self.assertIn(b"Tj", data)
        self.assertNotIn(b"/Subtype /Image", data)

    @unittest.skipUnless(
        _ENGINE_BIN.is_file() and _PDFIUM.is_file(),
        "build tools/sdc-generator/engine-roundtrip and provide PDFium to run the engine round-trip",
    )
    def test_engine_extractors_round_trip_supported_formats(self) -> None:
        # SPEC-0004-R7: formats the Phase 0 engine supports go through the
        # real engine extractor.
        import subprocess

        rows = corpus_rows(self.corpus)
        passages = _passages_by_doc(self.corpus)
        for fmt in ("pdf", "docx", "xlsx", "pptx", "html", "md", "txt", "code"):
            document = next(
                (row for row in rows.values() if row["metadata"]["format"] == fmt),
                None,
            )
            self.assertIsNotNone(document, fmt)
            path = self.corpus / document["metadata"]["relative_path"]
            result = subprocess.run(
                [str(_ENGINE_BIN), str(_PDFIUM), str(path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            normalized = normalize_extracted(result.stdout)
            for passage in passages[document["_id"]]:
                self.assertIn(normalize_extracted(passage["text"]), normalized)


class ScanTests(BuiltCorpus):
    def test_scanned_pdf_has_no_text_layer(self) -> None:
        # SPEC-0004-R8.
        rows = corpus_rows(self.corpus)
        scans = [
            row for row in rows.values() if row["metadata"]["format"] == "scanned-pdf"
        ]
        self.assertTrue(scans)
        for row in scans:
            data = (self.corpus / row["metadata"]["relative_path"]).read_bytes()
            for token in (b"/Font", b"BT", b"Tj", b"TJ"):
                self.assertNotIn(token, data)
            self.assertIn(b"/Subtype /Image", data)

    def test_scan_recipe_is_deterministic(self) -> None:
        # SPEC-0004-R3, R8.
        from sdc_generator.layout import apply_layout
        from sdc_generator.plan import plan_corpus
        from sdc_generator.profiles import load_profile
        from sdc_generator.renderers import render
        from sdc_generator.sources import load_source_sets, load_templates
        from support import SOURCES_DIR, TESTMINI_PROFILE

        profile = load_profile(TESTMINI_PROFILE)
        source_sets = load_source_sets(SOURCES_DIR)
        templates = load_templates(SOURCES_DIR, source_sets)
        plan = plan_corpus(
            profile=profile,
            seed="testmini-v1",
            source_sets=source_sets,
            templates=templates,
            sdc_root=SOURCES_DIR.parent,
        )
        scanned = [doc for doc in plan.documents if doc.format == "scanned-image"]
        self.assertTrue(scanned)
        first_document = scanned[0]
        apply_layout(first_document)
        first = render(first_document)
        second = render(first_document)
        self.assertEqual(hashlib_sha(first), hashlib_sha(second))
        self.assertEqual(first[:8], b"\x89PNG\r\n\x1a\n")
        # A second plan for the same seed reproduces the same bytes.
        second_plan = plan_corpus(
            profile=profile,
            seed="testmini-v1",
            source_sets=load_source_sets(SOURCES_DIR),
            templates=load_templates(SOURCES_DIR, load_source_sets(SOURCES_DIR)),
            sdc_root=SOURCES_DIR.parent,
        )
        mirror = next(
            doc for doc in second_plan.documents if doc.doc_id == first_document.doc_id
        )
        apply_layout(mirror)
        self.assertEqual(hashlib_sha(render(mirror)), hashlib_sha(first))

    def test_scan_truth_matches_canonical_pages(self) -> None:
        # SPEC-0004-R8.
        rows = corpus_rows(self.corpus)
        passages = _passages_by_doc(self.corpus)
        truth = {
            row["document_id"]: row
            for row in sidecar_rows(self.corpus, "extraction-truth.jsonl")
        }
        scans = [
            row
            for row in rows.values()
            if row["metadata"]["format"] in ("scanned-pdf", "scanned-image")
        ]
        self.assertTrue(scans)
        for row in scans:
            unit = truth[row["_id"]]
            self.assertEqual(unit["locator"], {"page": 1})
            normalized = normalize_extracted(unit["text"])
            for passage in passages[row["_id"]]:
                self.assertIn(normalize_extracted(passage["text"]), normalized)

    def test_scan_recipes_are_declared_with_settings(self) -> None:
        from support import SDC_ROOT
        from sdc_generator.renderlock import load_renderer_lock

        lock, _ = load_renderer_lock(SDC_ROOT / "renderers.lock.json")
        for name, recipe in lock["scan_recipes"].items():
            self.assertGreaterEqual(recipe["dpi"], 72)
            self.assertEqual(recipe["page"], "A5")
            self.assertEqual(recipe["compression"], "png-bilevel-stored")
            self.assertIn(recipe["noise"], ("none", "speckle-1-in-1400"))


def hashlib_sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    unittest.main()
