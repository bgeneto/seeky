"""Anti-copy guard for LLM drafts (WP-1.4 brief; SPEC-0004 4.6, 5.5).

A query that reuses a long verbatim span of its target would reward lexical
retrieval instead of the semantic paraphrase the category exists to measure.
"""

from __future__ import annotations

from .corpus import tokenize

_STOPWORDS = frozenset(
    """a an the of and or to in for on with by at from is are was were be been this
    that these those as it its into over under about after before during between
    o a os as um uma uns umas de do da dos das e ou em no na nos nas para por com
    sem sobre entre que qual quais como mais menos este esta esse essa aquele
    el la los las un una de del y o en para por con sin sobre entre que cual
    le les des du et ou dans pour sur avec sans entre ce cette ces qui
    der die das den dem des und oder in im auf mit ohne von zu fuer für ist
    ein eine einen einem einer""".split()
)


def _shingles(tokens: list[str], size: int) -> set[tuple[str, ...]]:
    if size <= 0 or len(tokens) < size:
        return set()
    return {tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def guard_violation(query: str, target_texts: list[str], guard: dict) -> str | None:
    """Return a rejection reason, or ``None`` when the query passes."""

    tokens = tokenize(query)
    if len(tokens) < 2:
        return "query is too short"
    if len(tokens) > 24:
        return "query is too long"

    shingle = int(guard["shingle_tokens"])
    verbatim = int(guard["verbatim_tokens"])
    for text in target_texts:
        target = tokenize(text)
        shared = _shingles(tokens, shingle) & _shingles(target, shingle)
        if shared:
            return f"shares a {shingle}-token shingle with its target"
        if len(tokens) >= verbatim:
            windows = _shingles(target, verbatim)
            for index in range(len(tokens) - verbatim + 1):
                if tuple(tokens[index : index + verbatim]) in windows:
                    return f"copies a {verbatim}-token verbatim span"

    content = {word for word in tokens if len(word) >= 4 and word not in _STOPWORDS}
    if len(content) >= 3:
        for text in target_texts:
            target = set(tokenize(text))
            shared = len(content & target)
            if shared / len(content) > float(guard["max_content_overlap_ratio"]):
                return "reuses too much of its target's wording"
    return None
