"""Candidate document and passage judgments for every draft query.

Pools are empty by design: the WP-1.4 draft predates system runs (SPEC-0004
5.4/5.6). Every grade here is candidate data with no authority; H6 verifies it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config
from .corpus import Corpus, Document, Passage, tokenize
from .templates import Draft, TEXT_FORMATS
from .semantic import slug_label


@dataclass
class PassageJudgment:
    passage_id: str
    grade: int
    spans: tuple[dict[str, int], ...] = ()


@dataclass
class DocJudgment:
    document_id: str
    grade: int
    evidence_passage_ids: list[str] = field(default_factory=list)
    subtopic_labels: list[str] = field(default_factory=list)
    passages: list[PassageJudgment] = field(default_factory=list)


def _span_for(passage: Passage, text: str) -> tuple[dict[str, int], ...]:
    """UTF-8 offsets of a token window of ``text`` inside ``passage``, if exact."""

    words = tokenize(text)
    for size in (len(words), 7, 6, 5, 4, 3):
        if size < 1 or len(words) < size:
            continue
        for start in range(0, len(words) - size + 1):
            span = passage.span_of(" ".join(words[start : start + size]))
            if span:
                return (span,)
    return ()


def _passage_for(corpus: Corpus, document_id: str, tokens: list[str]) -> Passage | None:
    return corpus.best_passage(document_id, tokens)


def _judgment(corpus: Corpus, document_id: str, grade: int, query: str, evidence: str | None = None) -> DocJudgment:
    tokens = tokenize(query)
    passage = corpus.best_passage(document_id, tokens)
    result = DocJudgment(document_id=document_id, grade=grade)
    if passage is None:
        return result
    passage_grade = grade if grade >= 1 else 0
    spans: tuple[dict[str, int], ...] = ()
    if grade >= 2 and passage_grade > 0:
        spans = _span_for(passage, evidence or query)
    result.passages.append(PassageJudgment(passage_id=passage.id, grade=passage_grade, spans=spans))
    if grade >= 2:
        result.evidence_passage_ids.append(passage.id)
    return result


class Judge:
    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus

    # -- helpers ---------------------------------------------------------

    def _distractors(
        self,
        anchor: Document,
        query: str,
        count: int,
        exclude: set[str],
        predicate=None,
    ) -> list[Document]:
        predicate = predicate or (lambda doc: doc.file_class == "document")
        candidates = self.corpus.lexical_candidates(
            anchor.lang, tokenize(query), frozenset(exclude)
        )
        chosen: list[Document] = []
        for doc_id in candidates:
            doc = self.corpus.documents[doc_id]
            if doc_id in exclude or not predicate(doc):
                continue
            chosen.append(doc)
            if len(chosen) >= count:
                return chosen
        for doc in self.corpus.select(anchor.lang, predicate, exclude=frozenset(exclude)):
            if doc.id not in {item.id for item in chosen}:
                chosen.append(doc)
            if len(chosen) >= count:
                break
        return chosen[:count]

    def _relation_grade(self, kind: str) -> int:
        if kind in ("exact_byte", "exact_text", "scanned_variant"):
            return 3
        return 2

    # -- template categories --------------------------------------------

    def template(self, draft: Draft) -> list[DocJudgment]:
        corpus = self.corpus
        anchor = corpus.documents[draft.anchor_id]
        query = draft.text
        judgments: list[DocJudgment] = []
        exclude = {anchor.id, *(member for member, _ in corpus.related(anchor.id))}

        if draft.category == "known_item":
            judgments.append(_judgment(corpus, anchor.id, 3, query, anchor.title))
            for member, kind in corpus.related(anchor.id):
                judgments.append(_judgment(corpus, member, self._relation_grade(kind), query, anchor.title))
            for doc in self._distractors(anchor, query, 2, exclude):
                judgments.append(_judgment(corpus, doc.id, 0, query))

        elif draft.category == "exact_identifier":
            identifier = next(
                (part for part in draft.text.split() if any(char.isdigit() for char in part) and "-" in part),
                draft.text,
            )
            evidence = next(
                (p for p in corpus.passages(anchor.id) if identifier in p.text),
                None,
            )
            target = DocJudgment(document_id=anchor.id, grade=3)
            if evidence is not None:
                target.evidence_passage_ids.append(evidence.id)
                span = evidence.span_of(identifier)
                target.passages.append(
                    PassageJudgment(passage_id=evidence.id, grade=3, spans=(span,) if span else ())
                )
            judgments.append(target)
            other = self._distractors(
                anchor, query, 1, exclude, lambda doc: doc.folder == anchor.folder
            )
            judgments.extend(_judgment(corpus, doc.id, 0, query) for doc in other)
            mismatched = self._distractors(
                anchor, query, 1, exclude | {doc.id for doc in other}
            )
            judgments.extend(_judgment(corpus, doc.id, 0, query) for doc in mismatched)

        elif draft.category == "needle_in_haystack":
            passage_id = draft.evidence_passage_ids[0] if draft.evidence_passage_ids else None
            target = DocJudgment(document_id=anchor.id, grade=3)
            evidence = next(
                (p for p in corpus.passages(anchor.id) if p.id == passage_id), None
            )
            if evidence is not None:
                target.evidence_passage_ids.append(evidence.id)
                target.passages.append(
                    PassageJudgment(
                        passage_id=evidence.id,
                        grade=3,
                        spans=_span_for(evidence, query),
                    )
                )
            judgments.append(target)
            for doc in self._distractors(
                anchor, query, 2, exclude, lambda doc: doc.source_item_id.startswith("syn-long-report")
            ):
                judgments.append(_judgment(corpus, doc.id, 0, query))

        elif draft.category == "mixed_semantic_metadata":
            judgments.append(_judgment(corpus, anchor.id, 3, query, anchor.title))
            others = self._distractors(
                anchor,
                query,
                2,
                exclude,
                lambda doc: doc.folder == anchor.folder and doc.fmt in TEXT_FORMATS,
            )
            template = draft.filters or {}
            for doc in others:
                grade = 0
                if doc.fmt in template.get("extensions", []):
                    grade = 1
                judgments.append(_judgment(corpus, doc.id, grade, query))

        elif draft.category == "filename_partial":
            judgments.append(_judgment(corpus, anchor.id, 3, query, anchor.stem))
            for doc in self._distractors(anchor, query, 2, exclude):
                judgments.append(_judgment(corpus, doc.id, 0, query))

        elif draft.category == "code_search":
            passage_id = draft.evidence_passage_ids[0] if draft.evidence_passage_ids else None
            target = DocJudgment(document_id=anchor.id, grade=3)
            evidence = next((p for p in corpus.passages(anchor.id) if p.id == passage_id), None)
            if evidence is not None:
                target.evidence_passage_ids.append(evidence.id)
                target.passages.append(
                    PassageJudgment(passage_id=evidence.id, grade=3, spans=_span_for(evidence, query))
                )
            judgments.append(target)
            for doc in self._distractors(
                anchor, query, 2, exclude, lambda doc: doc.file_class == "source_code"
            ):
                judgments.append(_judgment(corpus, doc.id, 0, query))

        else:
            raise KeyError(draft.category)

        return _dedupe(judgments)

    # -- LLM categories --------------------------------------------------

    def llm(self, draft: Draft) -> list[DocJudgment]:
        judgments: list[DocJudgment] = []
        for document_id, grade in draft.grades:
            doc = self.corpus.documents[document_id]
            judgment = _judgment(self.corpus, document_id, grade, draft.text, doc.title)
            if draft.category == "exploratory" and grade >= 2:
                heading = next((p.text for p in self.corpus.passages(document_id) if p.kind == "heading"), "")
                judgment.subtopic_labels = [slug_label(heading or doc.title)]
            judgments.append(judgment)
        return _dedupe(judgments)


def _dedupe(judgments: list[DocJudgment]) -> list[DocJudgment]:
    """One row per document, keeping the highest candidate grade."""

    best: dict[str, DocJudgment] = {}
    for judgment in judgments:
        current = best.get(judgment.document_id)
        if current is None or judgment.grade > current.grade:
            best[judgment.document_id] = judgment
    return [best[key] for key in sorted(best)]


def build_judgments(corpus: Corpus, drafts: list[Draft]) -> list[list[DocJudgment]]:
    judge = Judge(corpus)
    return [judge.llm(draft) if draft.origin == "llm" else judge.template(draft) for draft in drafts]
