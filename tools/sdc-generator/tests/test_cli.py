"""Command smoke tests (SPEC-0004-R14)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from support import (
    SOURCES_DIR,
    TESTMINI_PROFILE,
    TOOL_ROOT,
    manifest,
    temporary_directory,
)


class CommandTests(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(TOOL_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "sdc_generator", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )

    def test_build_and_verify_commands(self) -> None:
        # SPEC-0004-R14 command smoke test.
        with temporary_directory() as directory:
            output = directory / "corpus"
            build = self._run(
                "build",
                "--profile",
                str(TESTMINI_PROFILE),
                "--seed",
                "cli-v1",
                "--sources",
                str(SOURCES_DIR),
                "--cache",
                str(directory / "cache"),
                "--output",
                str(output),
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            self.assertEqual(build.stdout.strip(), manifest(output)["corpus_hash"])
            verify = self._run("verify", "--output", str(output))
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.assertEqual(verify.stdout.strip(), build.stdout.strip())

    def test_fetch_with_synthetic_only_source_set_succeeds_offline(self) -> None:
        with temporary_directory() as directory:
            result = self._run(
                "fetch",
                "--sources",
                str(SOURCES_DIR),
                "--cache",
                str(directory / "cache"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("fetched 0 source item(s)", result.stdout)

    def test_structural_error_is_machine_readable_and_relative(self) -> None:
        with temporary_directory() as directory:
            profile = directory / "badprofile.json"
            profile.write_text('{"schema_version": 1, "unknown": true}', encoding="utf-8")
            result = self._run(
                "build",
                "--profile",
                str(profile),
                "--sources",
                str(SOURCES_DIR),
                "--cache",
                str(directory / "cache"),
                "--output",
                str(directory / "corpus"),
            )
            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stderr.strip().splitlines()[-1])
            self.assertIn("code", payload)
            self.assertIn("message", payload)
            self.assertNotIn(str(directory), result.stderr)
            self.assertFalse((directory / "corpus").exists())
            self.assertFalse((directory / ".corpus.tmp").exists())

    def test_verify_rejects_a_tampered_tree(self) -> None:
        with temporary_directory() as directory:
            output = directory / "corpus"
            build = self._run(
                "build",
                "--profile",
                str(TESTMINI_PROFILE),
                "--seed",
                "cli-v1",
                "--sources",
                str(SOURCES_DIR),
                "--cache",
                str(directory / "cache"),
                "--output",
                str(output),
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            target = sorted(
                path for path in (output / "files").rglob("*") if path.is_file()
            )[0]
            target.write_bytes(target.read_bytes() + b"x")
            result = self._run("verify", "--output", str(output))
            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stderr.strip().splitlines()[-1])
            self.assertEqual(payload["code"], "OUTPUT_HASH_MISMATCH")


if __name__ == "__main__":
    unittest.main()
