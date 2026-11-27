"""Source pin, license, cache, and fetch tests (SPEC-0004-R1, R2, R14)."""

from __future__ import annotations

import hashlib
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from support import REPO_ROOT, SDC_ROOT, SOURCES_DIR, temporary_directory

from sdc_generator.errors import (
    CACHE_MISS,
    LICENSE_INELIGIBLE,
    LICENSE_NOTICE_MISSING,
    SCHEMA_INVALID,
    SOURCE_HASH_MISMATCH,
    SOURCE_PIN_MISSING,
    SdcError,
)
from sdc_generator.jsonio import canonical_json_bytes, sha256_bytes
from sdc_generator.sources import (
    cache_path,
    fetch_sources,
    load_source_sets,
    load_templates,
    validate_source_set,
)


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _manifest(
    *,
    url: str,
    payload: bytes,
    license_text: bytes,
    license_id: str = "MIT",
    redistribution_class: str = "permissive-core",
    notice: bool = True,
    attribution: str = "Synthetic test source",
    sha256: str | None = None,
    include_license: bool = True,
    include_sha: bool = True,
) -> dict:
    item: dict = {
        "source_item_id": "ext-sample-v1",
        "origin": "external",
        "url": url,
        "byte_length": len(payload),
        "media_type": "text/plain",
    }
    if include_sha:
        item["sha256"] = sha256 or sha256_bytes(payload)
    if include_license:
        item["license"] = {
            "id": license_id,
            "text_url": url + ".license",
            "text_sha256": sha256_bytes(license_text),
            "attribution": attribution,
            "notice_path": "notices/ext-sample-v1.txt",
        }
    if notice:
        notice_path = (
            item.get("license", {}).get("notice_path")
            if include_license
            else "notices/ext-sample-v1.txt"
        )
    return {
        "schema_version": 1,
        "source_set_id": "external-test-v1",
        "redistribution_class": redistribution_class,
        "items": [item],
    }


def _write_manifest(root: Path, data: dict, *, notice_text: str | None = None) -> Path:
    _write(root / "external-test-v1.json", canonical_json_bytes(data))
    if notice_text is not None:
        _write(root / "notices" / "ext-sample-v1.txt", notice_text.encode("utf-8"))
    return root


class _Handler(BaseHTTPRequestHandler):
    routes: dict[str, bytes] = {}

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        payload = self.routes.get(self.path)
        if payload is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:  # silence test server
        return


class FetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = b"pinned source bytes\n"
        cls.license_text = b"MIT License test text\n"
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.base_url = f"http://{host}:{port}"
        _Handler.routes = {
            "/source.bin": cls.payload,
            "/source.bin.license": cls.license_text,
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_fetch_downloads_and_verifies_pinned_objects(self) -> None:
        with temporary_directory() as directory:
            root = directory / "sources"
            data = _manifest(
                url=self.base_url + "/source.bin",
                payload=self.payload,
                license_text=self.license_text,
            )
            _write_manifest(root, data, notice_text="MIT notice for ext-sample-v1")
            fetched = fetch_sources(
                sources_dir=root,
                cache=directory / "cache",
                repo_root=REPO_ROOT,
                timeout=5,
            )
            self.assertEqual(fetched, ["ext-sample-v1"])
            self.assertEqual(
                (directory / "cache" / "sha256" / sha256_bytes(self.payload)).read_bytes(),
                self.payload,
            )
            self.assertTrue(
                (directory / "cache" / "sha256" / sha256_bytes(self.license_text)).is_file()
            )

    def test_source_download_rejects_sha256_mismatch(self) -> None:
        # SPEC-0004-R1.
        with temporary_directory() as directory:
            root = directory / "sources"
            data = _manifest(
                url=self.base_url + "/source.bin",
                payload=self.payload,
                license_text=self.license_text,
                sha256="0" * 64,
            )
            _write_manifest(root, data, notice_text="MIT notice")
            with self.assertRaises(SdcError) as caught:
                fetch_sources(
                    sources_dir=root,
                    cache=directory / "cache",
                    repo_root=REPO_ROOT,
                    timeout=5,
                )
            self.assertEqual(caught.exception.code, SOURCE_HASH_MISMATCH)
            self.assertFalse(
                cache_path(directory / "cache", "0" * 64).exists()
            )

    def test_source_item_requires_complete_pin(self) -> None:
        # SPEC-0004-R1.
        with temporary_directory() as directory:
            root = directory / "sources"
            data = _manifest(
                url=self.base_url + "/source.bin",
                payload=self.payload,
                license_text=self.license_text,
                include_sha=False,
            )
            _write_manifest(root, data, notice_text="MIT notice")
            with self.assertRaises(SdcError) as caught:
                load_source_sets(root)
            self.assertEqual(caught.exception.code, SOURCE_PIN_MISSING)

    def test_source_manifest_requires_license_and_notice(self) -> None:
        # SPEC-0004-R2.
        with temporary_directory() as directory:
            root = directory / "sources"
            data = _manifest(
                url=self.base_url + "/source.bin",
                payload=self.payload,
                license_text=self.license_text,
                include_license=False,
            )
            _write_manifest(root, data)
            with self.assertRaises(SdcError):
                load_source_sets(root)

            root2 = directory / "sources2"
            data = _manifest(
                url=self.base_url + "/source.bin",
                payload=self.payload,
                license_text=self.license_text,
            )
            _write_manifest(root2, data)
            sources = load_source_sets(root2)
            with self.assertRaises(SdcError) as caught:
                validate_source_set(
                    root2,
                    sources["external-test-v1"],
                    repo_root=REPO_ROOT,
                )
            self.assertEqual(caught.exception.code, LICENSE_NOTICE_MISSING)

    def test_notice_must_name_the_license(self) -> None:
        with temporary_directory() as directory:
            root = directory / "sources"
            data = _manifest(
                url=self.base_url + "/source.bin",
                payload=self.payload,
                license_text=self.license_text,
            )
            _write_manifest(root, data, notice_text="Some unrelated notice")
            sources = load_source_sets(root)
            with self.assertRaises(SdcError) as caught:
                validate_source_set(root, sources["external-test-v1"], repo_root=REPO_ROOT)
            self.assertEqual(caught.exception.code, LICENSE_NOTICE_MISSING)

    def test_core_rejects_ineligible_or_missing_license(self) -> None:
        # SPEC-0004-R2.
        cases = [
            ("sharealike-extension", "MIT"),
            ("local-only", "MIT"),
            ("permissive-core", "CC-BY-SA-4.0"),
            ("permissive-core", "CC-BY-NC-4.0"),
            ("permissive-core", "LicenseRef-Research-Only"),
        ]
        with temporary_directory() as directory:
            for index, (redistribution, license_id) in enumerate(cases):
                root = directory / f"sources-{index}"
                data = _manifest(
                    url=self.base_url + "/source.bin",
                    payload=self.payload,
                    license_text=self.license_text,
                    license_id=license_id,
                    redistribution_class=redistribution,
                )
                _write_manifest(root, data, notice_text=f"{license_id} notice")
                sources = load_source_sets(root)
                with self.assertRaises(SdcError) as caught:
                    validate_source_set(root, sources["external-test-v1"], repo_root=REPO_ROOT)
                self.assertEqual(
                    caught.exception.code,
                    LICENSE_INELIGIBLE,
                    f"{redistribution}/{license_id}",
                )

    def test_public_domain_requires_basis(self) -> None:
        with temporary_directory() as directory:
            root = directory / "sources"
            data = _manifest(
                url=self.base_url + "/source.bin",
                payload=self.payload,
                license_text=self.license_text,
                license_id="LicenseRef-Public-Domain",
                attribution="",
            )
            _write_manifest(root, data, notice_text="LicenseRef-Public-Domain notice")
            sources = load_source_sets(root)
            with self.assertRaises(SdcError) as caught:
                validate_source_set(root, sources["external-test-v1"], repo_root=REPO_ROOT)
            self.assertEqual(caught.exception.code, LICENSE_INELIGIBLE)

    def test_unknown_schema_version_and_duplicate_ids_are_rejected(self) -> None:
        with temporary_directory() as directory:
            root = directory / "sources"
            data = _manifest(
                url=self.base_url + "/source.bin",
                payload=self.payload,
                license_text=self.license_text,
            )
            data["schema_version"] = 2
            _write_manifest(root, data, notice_text="MIT notice")
            with self.assertRaises(SdcError) as caught:
                load_source_sets(root)
            self.assertEqual(caught.exception.code, SCHEMA_INVALID)

            root2 = directory / "sources2"
            data = _manifest(
                url=self.base_url + "/source.bin",
                payload=self.payload,
                license_text=self.license_text,
            )
            data["items"].append(dict(data["items"][0]))
            _write_manifest(root2, data, notice_text="MIT notice")
            with self.assertRaises(SdcError) as caught:
                load_source_sets(root2)
            self.assertEqual(caught.exception.code, SCHEMA_INVALID)


class CacheTests(unittest.TestCase):
    def test_build_requires_cached_external_source(self) -> None:
        with temporary_directory() as directory:
            root = directory / "sources"
            data = _manifest(
                url="https://example.invalid/source",
                payload=b"source",
                license_text=b"MIT",
            )
            _write_manifest(root, data, notice_text="MIT notice")
            sources = load_source_sets(root)
            validate_source_set(root, sources["external-test-v1"], repo_root=REPO_ROOT)
            with self.assertRaises(SdcError) as caught:
                from sdc_generator.sources import require_cached

                require_cached(directory / "cache", "0" * 64, what="source")
            self.assertEqual(caught.exception.code, CACHE_MISS)


class RealManifestTests(unittest.TestCase):
    def test_real_source_set_and_templates_validate(self) -> None:
        sets = load_source_sets(SOURCES_DIR)
        self.assertIn("synthetic-office-v1", sets)
        validate_source_set(
            SOURCES_DIR, sets["synthetic-office-v1"], repo_root=REPO_ROOT
        )
        templates = load_templates(SOURCES_DIR, sets)
        self.assertGreaterEqual(len(templates), 15)
        for item in sets["synthetic-office-v1"].items:
            self.assertEqual(item.origin, "synthetic")
            self.assertEqual(item.license.id, "MIT")

    def test_template_hashes_match_the_manifest(self) -> None:
        sets = load_source_sets(SOURCES_DIR)
        for item in sets["synthetic-office-v1"].items:
            path = SOURCES_DIR / "templates" / f"{item.template_id}.json"
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item.template_sha256)

    def test_synthetic_content_uses_reserved_example_domains(self) -> None:
        # SPEC-0004-R6: scan all template text for e-mail addresses.
        import re

        email = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
        for path in sorted((SOURCES_DIR / "templates").glob("*.json")):
            for match in email.finditer(path.read_text(encoding="utf-8")):
                domain = match.group(1).lower()
                self.assertIn(
                    domain,
                    {"example.com", "example.org", "example.net", "example.invalid"},
                    f"{path.name}: {match.group(0)}",
                )


if __name__ == "__main__":
    unittest.main()
