"""End-to-end prepare/verify/check tests with injected downloads (no network)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from dataset_fetch import cache as cache_module
from dataset_fetch.cli import main
from dataset_fetch.errors import DatasetFetchError
import support


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def parse_error(stderr: str) -> dict:
    return json.loads(stderr.strip().splitlines()[-1])


class CliLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.dataset_dir = support.write_dataset_dir(self.root / "repo")
        self.cache = self.root / "cache"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def prepare(self, *, offline: bool = False, overwrite: bool = False) -> tuple[int, str, str]:
        argv = [
            "prepare",
            "--dataset",
            support.DATASET_ID,
            "--dataset-dir",
            str(self.dataset_dir),
            "--cache",
            str(self.cache),
        ]
        if offline:
            argv.append("--offline")
        if overwrite:
            argv.append("--overwrite")
        with mock.patch.object(
            cache_module, "_http_get", support.FakeFetch(support.fetch_mapping())
        ):
            return run_cli(argv)

    def test_prepare_then_offline_verify_and_check(self) -> None:
        code, stdout, stderr = self.prepare()
        self.assertEqual(code, 0, stderr)
        summary = json.loads(stdout)
        self.assertEqual(summary["status"], "prepared")
        manifest = json.loads((self.dataset_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["local_file_sha256"])
        self.assertIn("data/corpus.jsonl", manifest["local_file_sha256"])
        self.assertTrue((self.dataset_dir / "dataset-lock.json").is_file())
        self.assertTrue((self.dataset_dir / "NOTICE.md").is_file())
        self.assertTrue((self.dataset_dir / "data" / "corpus.jsonl").is_file())
        lock = json.loads((self.dataset_dir / "dataset-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["fingerprint"], summary["fingerprint"])
        self.assertEqual(lock["license"]["terms_sha256"], manifest["terms_sha256"])

        # verify and check must not touch the network at all.
        def refuse(*args, **kwargs):
            raise AssertionError("network access during verify")

        argv = [
            "verify",
            "--dataset",
            support.DATASET_ID,
            "--dataset-dir",
            str(self.dataset_dir),
            "--cache",
            str(self.cache),
        ]
        with mock.patch.object(urllib.request, "urlopen", refuse), mock.patch.object(
            cache_module, "_http_get", refuse
        ):
            code, stdout, stderr = run_cli(argv)
            self.assertEqual(code, 0, stderr)
            self.assertEqual(json.loads(stdout)["network"], "none")
            code, stdout, stderr = run_cli(
                [
                    "check",
                    "--dataset",
                    support.DATASET_ID,
                    "--dataset-dir",
                    str(self.dataset_dir),
                ]
            )
            self.assertEqual(code, 0, stderr)

    def test_prepare_is_deterministic(self) -> None:
        first_code, first_out, first_err = self.prepare()
        self.assertEqual(first_code, 0, first_err)
        second_code, second_out, second_err = self.prepare(offline=True, overwrite=True)
        self.assertEqual(second_code, 0, second_err)
        self.assertEqual(json.loads(first_out)["fingerprint"], json.loads(second_out)["fingerprint"])
        # Offline prepare succeeds because every source and the terms snapshot
        # are already cached.
        self.assertEqual(json.loads(second_out)["status"], "prepared")

    def test_prepare_refuses_to_replace_data_without_overwrite(self) -> None:
        self.assertEqual(self.prepare()[0], 0)
        code, _, stderr = self.prepare()
        self.assertEqual(code, 2)
        self.assertEqual(parse_error(stderr)["code"], "OUTPUT_EXISTS")

    def test_offline_prepare_without_cache_fails(self) -> None:
        code, _, stderr = self.prepare(offline=True)
        self.assertEqual(code, 2)
        self.assertEqual(parse_error(stderr)["code"], "CACHE_MISS")

    def test_download_rejects_source_hash_mismatch(self) -> None:
        manifest = support.manifest()
        manifest["source"]["sha256"][0] = "0" * 64
        from dataset_fetch.jsio import pretty_json_bytes

        (self.dataset_dir / "manifest.json").write_bytes(pretty_json_bytes(manifest))
        code, _, stderr = self.prepare()
        self.assertEqual(code, 2)
        self.assertEqual(parse_error(stderr)["code"], "HASH_MISMATCH")

    def test_download_rejects_terms_mismatch(self) -> None:
        mapping = support.fetch_mapping()
        mapping[f"https://example.invalid/{support.DATASET_ID}/terms.txt"] = b"different terms\n"
        argv = [
            "prepare",
            "--dataset",
            support.DATASET_ID,
            "--dataset-dir",
            str(self.dataset_dir),
            "--cache",
            str(self.cache),
        ]
        with mock.patch.object(cache_module, "_http_get", support.FakeFetch(mapping)):
            code, _, stderr = run_cli(argv)
        self.assertEqual(code, 2)
        self.assertEqual(parse_error(stderr)["code"], "TERMS_MISMATCH")

    def test_verify_detects_tampered_data(self) -> None:
        self.assertEqual(self.prepare()[0], 0)
        path = self.dataset_dir / "data" / "corpus.jsonl"
        path.write_bytes(path.read_bytes() + b"\n")
        code, _, stderr = run_cli(
            ["verify", "--dataset", support.DATASET_ID, "--dataset-dir", str(self.dataset_dir)]
        )
        self.assertEqual(code, 2)
        self.assertEqual(parse_error(stderr)["code"], "LOCK_MISMATCH")

    def test_check_does_not_need_prepared_data(self) -> None:
        self.assertEqual(self.prepare()[0], 0)
        import shutil

        shutil.rmtree(self.dataset_dir / "data")
        code, stdout, stderr = run_cli(
            ["check", "--dataset", support.DATASET_ID, "--dataset-dir", str(self.dataset_dir)]
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["status"], "ok")


class ErrorShapeTests(unittest.TestCase):
    def test_unknown_dataset_recipe_is_typed(self) -> None:
        from dataset_fetch.recipes import recipe_for

        with self.assertRaises(DatasetFetchError) as raised:
            recipe_for("unknown-dataset")
        self.assertEqual(raised.exception.code, "UNSUPPORTED")

    def test_dataset_fetch_error_serializes_stable_fields(self) -> None:
        error = DatasetFetchError("SCHEMA", "bad", location="x", line=3)
        self.assertEqual(
            json.loads(error.as_json()),
            {"code": "SCHEMA", "location": "x", "line": 3, "message": "bad"},
        )


if __name__ == "__main__":
    unittest.main()
