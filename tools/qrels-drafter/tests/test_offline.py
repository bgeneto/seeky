"""``draft`` is offline: no socket, and no network module outside fetch-model."""

from __future__ import annotations

import ast
import socket
import unittest
from unittest import mock

import support
from qrels_drafter.pipeline import run_draft

_NETWORK_MODULES = {"socket", "http", "urllib", "ftplib", "smtplib", "telnetlib", "requests"}


class OfflineDraft(unittest.TestCase):
    def test_draft_never_opens_a_network_socket(self):
        def deny(*args, **kwargs):
            raise AssertionError("draft must not open a network socket")

        with mock.patch.object(socket, "socket", deny), mock.patch.object(
            socket, "create_connection", deny
        ):
            summary = run_draft(
                support.CORPUS,
                support.draft_fixture().parent / "offline",
                support.stub_runner(),
                plan=support.TEST_PLAN,
                check_minima=False,
            )
        self.assertGreater(summary["queries"], 0)

    def test_only_the_explicit_fetch_command_imports_network_modules(self):
        offenders: list[str] = []
        for path in sorted((support.TOOL_ROOT / "qrels_drafter").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    root = name.split(".")[0]
                    if root in _NETWORK_MODULES and path.name != "cli.py":
                        offenders.append(f"{path.name}: {name}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
