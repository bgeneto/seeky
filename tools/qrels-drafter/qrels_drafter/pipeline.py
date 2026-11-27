"""Draft pipeline: templates + local model -> audited quarantined draft."""

from __future__ import annotations

from pathlib import Path

from . import config
from .audit import audit_rows
from .corpus import Corpus
from .emit import assign_ids, assign_splits, build_rows, write_set
from .judge import build_judgments
from .model import Runner
from .semantic import build_all_llm
from .templates import build_all_templates


def run_draft(
    corpus_root: Path,
    output: Path,
    runner: Runner | None,
    *,
    plan: dict | None = None,
    check_minima: bool = True,
) -> dict:
    """Draft the full set (or only the template categories when ``runner`` is None)."""

    corpus = Corpus.load(Path(corpus_root))
    drafts = build_all_templates(corpus, plan)
    if runner is not None:
        drafts.extend(build_all_llm(corpus, runner, plan))
    identified = assign_ids(drafts)
    splits = assign_splits(identified, config.SPLIT_SEED)
    judgments = build_judgments(corpus, [draft for _, draft in identified])
    queries, documents, passages = build_rows(corpus, identified, judgments, splits)
    # Refuse to write a draft that cannot pass the WP-1.4 minima and scope rules.
    summary = audit_rows(queries, documents, passages, [], check_minima=check_minima)
    write_set(output, corpus.corpus_hash, splits, queries, documents, passages)
    summary["output"] = str(output)
    return summary
