"""Shared test fixtures: the committed smoke corpus and a stub model runner."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOL_ROOT.parents[1]
CORPUS = REPO_ROOT / "bench" / "corpora" / "sdc" / "sdc-smoke"
GENERATOR = REPO_ROOT / "tools" / "sdc-generator"
COMMITTED = REPO_ROOT / "bench" / "qrels" / "sdc" / "drafts" / "sdc-v1"
STUB = Path(__file__).with_name("stub_llm.py")

# A reduced plan over the committed smoke corpus: even strata, every category.
TEST_PLAN = {
    "known_item": {"pt": 2, "en": 2, "other": 2, "non_latin": 2},
    "exact_identifier": {"pt": 2, "en": 2},
    "needle_in_haystack": {"en": 2},
    "mixed_semantic_metadata": {"pt": 2, "en": 2},
    "filename_partial": {"pt": 2, "en": 2},
    "code_search": {"en": 2},
    "conceptual": {"pt": 2, "en": 2},
    "exploratory": {"pt": 2, "en": 2},
    "cross_language": {"cross_lingual": 2},
}

_cache: dict[str, object] = {}


def stub_runner():
    from qrels_drafter.model import command_runner

    return command_runner([sys.executable, str(STUB)])


def draft_fixture() -> Path:
    """Draft the reduced plan once per test session and return its directory."""

    from qrels_drafter.pipeline import run_draft

    if "dir" not in _cache:
        directory = Path(tempfile.mkdtemp(prefix="qrels-drafter-"))
        output = directory / "draft"
        run_draft(CORPUS, output, stub_runner(), plan=TEST_PLAN, check_minima=False)
        _cache["dir"] = output
    return _cache["dir"]  # type: ignore[return-value]
