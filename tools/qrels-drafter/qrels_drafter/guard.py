"""Anti-copy guard for LLM drafts (WP-1.4 brief; SPEC-0004 4.6, 5.5).

A query that reuses a long verbatim span of its target would reward lexical
retrieval instead of the semantic paraphrase the category exists to measure.
"""

from __future__ import annotations

from .corpus import tokenize


def _shingles(tokens: list[str], size: int) -> set[tuple[str, ...]]:
    if size <= 0 or len(tokens) < size:
        return set()
    return {tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def guard_violation(query: str, target_texts: list[str], guard: dict) -> str | None:
    """Return a rejection reason, or ``None`` when the query passes.

    The guard rejects a long verbatim span: a shared 8-token shingle or a copied
    5-token window of the target. Short keyword queries that share common topic
    words are allowed -- that is normal search behaviour, not copying a span.
    """

    tokens = tokenize(query)
    if len(tokens) < 2:
        return "query is too short"
    if len(tokens) > 24:
        return "query is too long"

    shingle = int(guard["shingle_tokens"])
    verbatim = int(guard["verbatim_tokens"])
    for text in target_texts:
        target = tokenize(text)
        if _shingles(tokens, shingle) & _shingles(target, shingle):
            return f"shares a {shingle}-token shingle with its target"
        if len(tokens) >= verbatim:
            windows = _shingles(target, verbatim)
            for index in range(len(tokens) - verbatim + 1):
                if tuple(tokens[index : index + verbatim]) in windows:
                    return f"copies a {verbatim}-token verbatim span"
    return None
