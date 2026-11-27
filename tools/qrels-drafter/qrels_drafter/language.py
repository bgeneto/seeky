"""Language identification for draft queries, from the corpus vocabulary.

Short keyword queries carry no function words, so a stopword list is unreliable.
The drafter builds a word set per language from the corpus itself and classifies
a query by how many of its tokens appear in each set. This is the gate that keeps
a Portuguese query Portuguese (and a ``cross_language`` query in the language it
claims), which the bake-off showed a small model can otherwise violate.
"""

from __future__ import annotations

from collections import Counter

from .corpus import Corpus, tokenize

_PT_MARKERS = {"de", "da", "do", "das", "dos", "para", "com", "que", "não", "uma", "um", "em", "no", "na", "por"}
_EN_MARKERS = {"the", "of", "with", "for", "and", "from", "in", "to", "on", "by", "a", "an", "is"}
_DIACRITICS = "ãõçáéíóúâêôà"


def build_lexicons(corpus: Corpus, minimum_count: int = 3) -> dict[str, set[str]]:
    """Word sets for Portuguese and English from corpus titles and text."""

    documents: dict[str, Counter] = {"pt": Counter(), "en": Counter()}
    for doc in corpus.documents.values():
        if doc.lang not in documents:
            continue
        documents[doc.lang].update(set(tokenize(doc.title + " " + doc.text)))
    return {
        lang: {word for word, count in counts.items() if count >= minimum_count and len(word) >= 3}
        for lang, counts in documents.items()
    }


def detect_language(text: str, lexicons: dict[str, set[str]] | None = None) -> str:
    """Return ``pt``, ``en``, or ``unknown``."""

    tokens = tokenize(text)
    folded = text.lower()
    if lexicons:
        scores = {
            lang: sum(1 for token in tokens if token in words)
            for lang, words in lexicons.items()
        }
        if scores.get("pt", 0) != scores.get("en", 0):
            return "pt" if scores.get("pt", 0) > scores.get("en", 0) else "en"
        if any(char in folded for char in _DIACRITICS):
            return "pt"
        return "unknown"
    pt = sum(1 for token in tokens if token in _PT_MARKERS) + (
        2 if any(char in folded for char in _DIACRITICS) else 0
    )
    en = sum(1 for token in tokens if token in _EN_MARKERS)
    if pt > en:
        return "pt"
    if en > pt:
        return "en"
    return "unknown"
