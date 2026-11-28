"""Deterministic template drafts for the template-faithful categories.

SPEC-0004 4.6: a tool may draft only where copying from the corpus is
faithful -- ``known_item``, ``exact_identifier``, ``needle_in_haystack``,
``mixed_semantic_metadata``, ``filename_partial``, and ``code_search``. These
builders never invent a semantic paraphrase and never produce a pt<->en pair.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import config
from .corpus import Corpus, Document, Passage
from .digest import uniform_int

_IDENTIFIER = re.compile(r"\b[A-Z]{2,4}-\d{4}-\d{3,6}\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")
_ERROR_CODE = re.compile(r"\bE-\d{4}\b")
_TOKEN = re.compile(r"\w+", re.UNICODE)

TEXT_FORMATS = frozenset(
    {"md", "txt", "docx", "pdf", "html", "odt", "rtf", "epub", "pptx", "xlsx", "eml"}
)

_WORD = {
    "pt": {"document": "documento", "invoice": "fatura", "number": "número", "find": "encontrar", "in": "em"},
    "en": {"document": "document", "invoice": "invoice", "number": "number", "find": "find", "in": "in"},
    "es": {"document": "documento", "invoice": "factura", "number": "número", "find": "encontrar", "in": "en"},
    "fr": {"document": "document", "invoice": "facture", "number": "numéro", "find": "trouver", "in": "en"},
    "de": {"document": "Dokument", "invoice": "Rechnung", "number": "Nummer", "find": "finden", "in": "in"},
    "ja": {"document": "文書", "invoice": "請求書", "number": "番号", "find": "検索", "in": ""},
    "el": {"document": "έγγραφο", "invoice": "τιμολόγιο", "number": "αριθμός", "find": "εύρεση", "in": ""},
}


@dataclass
class Draft:
    category: str
    language: str
    target_languages: tuple[str, ...]
    language_slice: str
    configuration: str
    text: str
    filters: dict | None
    anchor_id: str
    origin: str
    variant: str
    prompt_sha256: str | None = None
    evidence_passage_ids: tuple[str, ...] = ()
    grades: tuple[tuple[str, int], ...] = ()
    grade_prompt_sha256: str | None = None
    # The distinctive text a template query reuses (code phrase, needle, title,
    # filename fragment, identifier). A document containing it cannot be a
    # grade-0 hard negative.
    literal: str | None = None


def language_for_slice(slice_name: str, index: int) -> str:
    if slice_name == "other":
        return config.OTHER_LANGUAGES[index % len(config.OTHER_LANGUAGES)]
    if slice_name == "non_latin":
        return config.NON_LATIN_LANGUAGES[index % len(config.NON_LATIN_LANGUAGES)]
    return slice_name


def slice_for_language(language: str, target: str | None = None) -> str:
    if target is not None and target.split("-")[0] != language.split("-")[0]:
        return "cross_lingual"
    root = language.split("-")[0].lower()
    if root == "pt":
        return "pt"
    if root == "en":
        return "en"
    if root in config.OTHER_LANGUAGES:
        return "other"
    return "non_latin_non_regression"


def _phrase(text: str, tokens: int, start: int) -> str | None:
    matches = list(_TOKEN.finditer(text))
    if len(matches) < tokens:
        return None
    first = min(max(0, start), len(matches) - tokens)
    return text[matches[first].start() : matches[first + tokens - 1].end()]


def _title_head(title: str) -> str:
    for separator in (" — ", " – ", " - "):
        if separator in title:
            return title.split(separator)[0].strip()
    return title


def _canonical(doc: Document) -> bool:
    """True for a document that is not a duplicate copy or a version member."""

    return not doc.duplicate_cluster_ids and doc.version_group_id is None


def _unique(text: str) -> str:
    return " ".join(text.split()).strip()


class TemplateDrafter:
    def __init__(self, corpus: Corpus, seed: str = config.DRAFT_SEED) -> None:
        self.corpus = corpus
        self.seed = seed
        self._cache: dict[tuple[str, str], list[Document]] = {}

    # -- uniqueness ------------------------------------------------------

    def _related(self, doc: Document) -> set[str]:
        return {member for member, _ in self.corpus.related(doc.id)}

    def _phrase_is_unique(self, doc: Document, phrase: str) -> bool:
        """True when only the anchor (or its duplicates) contains the phrase."""

        hits = self.corpus.documents_with_phrase(phrase)
        return set(hits) <= self._related(doc) | {doc.id}

    def _pick_phrase(self, doc: Document, windows) -> tuple[Passage, str] | None:
        """The first phrase only the anchor family contains, else the first phrase.

        A template corpus can repeat every sentence across documents (the SDC
        long reports draw from one sentence pool). A shared phrase is still a
        valid query; the judge then grades every document that contains it
        (SPEC-0004 5.4: at least one candidate target).
        """

        fallback: tuple[Passage, str] | None = None
        seen: set[str] = set()
        for passage, phrase in windows:
            if phrase is None or phrase in seen:
                continue
            seen.add(phrase)
            if fallback is None:
                fallback = (passage, phrase)
            if self._phrase_is_unique(doc, phrase):
                return passage, phrase
        return fallback

    def _filename_is_unique(self, doc: Document, fragment: str) -> bool:
        """True when the filename fragment selects one document family."""

        needle = fragment.casefold()
        allowed = self._related(doc) | {doc.id}
        for other in self.corpus.documents.values():
            if other.id in allowed:
                continue
            if needle in other.basename.casefold():
                return False
        return True

    def _title_head_is_unique(self, doc: Document, head: str) -> bool:
        """True when a title head identifies one document family."""

        needle = head.casefold()
        allowed = self._related(doc) | {doc.id}
        for other in self.corpus.documents.values():
            if other.id in allowed:
                continue
            if needle in other.title.casefold():
                return False
        return True

    # -- eligibility -----------------------------------------------------

    def _docs(self, category: str, lang: str) -> list[Document]:
        key = (category, lang)
        if key in self._cache:
            return self._cache[key]
        predicate = self._predicate(category)
        docs = self.corpus.select(lang, predicate)
        self._cache[key] = docs
        return docs

    def _predicate(self, category: str):
        if category == "known_item":
            return lambda doc: (
                doc.file_class == "document"
                and doc.fmt in TEXT_FORMATS
                and len(doc.title) >= 8
                and _canonical(doc)
            )
        if category == "exact_identifier":
            return lambda doc: doc.file_class == "document" and _canonical(doc) and bool(
                _IDENTIFIER.search(doc.text) or _UUID.search(doc.text) or _ERROR_CODE.search(doc.text)
            )
        if category == "needle_in_haystack":
            return lambda doc: doc.file_class == "document" and doc.source_item_id.startswith("syn-long-report")
        if category == "mixed_semantic_metadata":
            return lambda doc: (
                doc.file_class == "document"
                and _canonical(doc)
                and doc.fmt in TEXT_FORMATS
                and bool(doc.folder)
                and doc.fmt in {"pdf", "docx", "md", "txt", "html", "odt", "rtf", "epub", "pptx", "xlsx", "eml"}
                and len(doc.title) >= 8
            )
        if category == "filename_partial":
            return lambda doc: doc.file_class == "document" and len(doc.stem) >= 10
        if category == "code_search":
            return lambda doc: doc.file_class == "source_code"
        raise KeyError(category)

    # -- building --------------------------------------------------------

    def build(self, category: str, slice_name: str, count: int, used: set[str]) -> list[Draft]:
        drafts: list[Draft] = []
        cursor: dict[str, int] = {}
        attempt = 0
        languages = self._languages(slice_name)
        while len(drafts) < count:
            if attempt > count * 60 + 500:
                raise RuntimeError(f"cannot fill {category}/{slice_name}: not enough eligible documents")
            lang = languages[len(drafts) % len(languages)]
            index = cursor.get(lang, 0)
            cursor[lang] = index + 1
            docs = self._docs(category, lang)
            if not docs:
                attempt += 1
                continue
            doc = docs[index % len(docs)]
            slot = index // len(docs)
            variant = (attempt + slot) % 3
            draft = self._make(category, doc, lang, slice_name, variant, slot)
            attempt += 1
            if draft is None:
                continue
            text = _unique(draft.text)
            if not text or len(text) > 200:
                continue
            key = text.casefold()
            if key in used:
                continue
            used.add(key)
            draft.text = text
            drafts.append(draft)
        return drafts

    @staticmethod
    def _languages(slice_name: str) -> list[str]:
        if slice_name == "other":
            return list(config.OTHER_LANGUAGES)
        if slice_name == "non_latin":
            return list(config.NON_LATIN_LANGUAGES)
        return [slice_name]

    def _make(
        self,
        category: str,
        doc: Document,
        lang: str,
        slice_name: str,
        variant: int,
        slot: int = 0,
    ) -> Draft | None:
        words = _WORD[lang]
        language = doc.language
        base = dict(
            category=category,
            language=language,
            target_languages=(language,),
            language_slice=slice_for_language(language),
            configuration="default",
            filters=None,
            anchor_id=doc.id,
            origin="tool",
        )

        if category == "known_item":
            title = doc.title
            if variant == 0:
                text = f"{words['document']} {title}"
            elif variant == 1:
                head = _title_head(title)
                if not self._title_head_is_unique(doc, head):
                    return None
                text = f"{head} {words['document']}"
            else:
                text = f"{words['find']} {title}" if words["find"] else title
            return Draft(text=text, variant=f"known-{variant}", literal=title, **base)

        if category == "exact_identifier":
            kinds = ("code", "uuid", "error")
            kind = kinds[variant % len(kinds)]
            pattern = {"code": _IDENTIFIER, "uuid": _UUID, "error": _ERROR_CODE}[kind]
            match = pattern.search(doc.text)
            if match is None:
                return None
            identifier = match.group(0)
            text = f"{words['number']} {identifier}" if variant else identifier
            passage = next((p for p in self.corpus.passages(doc.id) if identifier in p.text), None)
            return Draft(
                text=text,
                variant=f"identifier-{kind}",
                evidence_passage_ids=(passage.id,) if passage else (),
                literal=identifier,
                **base,
            )

        if category == "needle_in_haystack":
            passages = [
                p
                for p in self.corpus.passages(doc.id)
                if p.kind == "paragraph"
                and p.boilerplate_family_id is None
                and 80 <= len(p.text) <= 260
            ]
            if len(passages) < 3:
                return None
            first = uniform_int(self.seed, "needle-passage", f"{doc.id}/{slot}", 0, len(passages) - 1)

            def needle_windows():
                for offset in range(len(passages)):
                    passage = passages[(first + offset) % len(passages)]
                    start = uniform_int(self.seed, "needle-window", f"{passage.id}/{slot}", 0, 40)
                    for step in range(41):
                        yield passage, _phrase(passage.text, 7, (start + step) % 41)

            picked = self._pick_phrase(doc, needle_windows())
            if picked is None:
                return None
            passage, phrase = picked
            text = f"{words['find']} {phrase}" if variant else phrase
            return Draft(
                text=text,
                variant=f"needle-{variant}",
                evidence_passage_ids=(passage.id,),
                literal=phrase,
                **base,
            )

        if category == "mixed_semantic_metadata":
            year = int(doc.modified_at[:4])
            filters = {
                "extensions": [doc.fmt],
                "modified_after": f"{year:04d}-01-01T00:00:00Z",
                "modified_before": f"{year + 1:04d}-01-01T00:00:00Z",
                "folder_prefix": f"files/documents/{doc.folder}/",
            }
            if not doc.path.startswith(filters["folder_prefix"]):
                return None
            head = _title_head(doc.title)
            text = f"{head} {words['in']} {doc.fmt}".strip() if words["in"] else f"{head} {doc.fmt}"
            passage = self.corpus.best_passage(doc.id, head.split())
            return Draft(
                text=text,
                variant=f"metadata-{variant}",
                evidence_passage_ids=(passage.id,) if passage else (),
                literal=head,
                **{**base, "filters": filters},
            )

        if category == "filename_partial":
            stem, extension = doc.stem, doc.basename.rsplit(".", 1)[-1]
            if variant == 0:
                text = f"{stem[:12].strip()}.{extension}"
            elif variant == 1:
                middle = max(0, len(stem) // 3)
                text = f"{stem[middle:middle + 8].strip()}.{extension}"
            else:
                if any(ord(char) > 127 for char in stem):
                    text = f"{stem}.{extension}"
                else:
                    cut = max(1, len(stem) // 2)
                    text = f"{stem[:cut]}{stem[cut + 1:]}.{extension}"
            if len(text) < 6:
                return None
            if not self._filename_is_unique(doc, text.rsplit(".", 1)[0]):
                return None
            passage = self.corpus.best_passage(doc.id, stem.split())
            return Draft(
                text=text,
                variant=f"filename-{variant}",
                evidence_passage_ids=(passage.id,) if passage else (),
                literal=text.rsplit(".", 1)[0],
                **base,
            )

        if category == "code_search":
            passages = [p for p in self.corpus.passages(doc.id) if p.kind == "code"]
            if not passages:
                return None
            head = _title_head(doc.title).lower()
            language_name = doc.path.split("/")[2] if doc.path.count("/") >= 3 else "code"
            def code_windows():
                for offset in range(len(passages)):
                    passage = passages[(variant + slot + offset) % len(passages)]
                    first = uniform_int(self.seed, "code-window", f"{passage.id}/{slot}", 0, 12)
                    for step in range(13):
                        yield passage, _phrase(passage.text, 4, (first + step) % 13)

            picked = self._pick_phrase(doc, code_windows())
            if picked is None:
                return None
            passage, phrase = picked
            text = f"{language_name} {head} {phrase}" if variant == 0 else f"{language_name} {phrase}"
            return Draft(
                text=text,
                variant=f"code-{variant}",
                evidence_passage_ids=(passage.id,),
                literal=phrase,
                **{**base, "configuration": "code_enabled"},
            )

        raise KeyError(category)


def build_all_templates(
    corpus: Corpus, plan: dict | None = None, seed: str = config.DRAFT_SEED
) -> list[Draft]:
    plan = plan or config.PLAN
    drafter = TemplateDrafter(corpus, seed)
    drafts: list[Draft] = []
    used: set[str] = set()
    for category in config.TEMPLATE_CATEGORIES:
        for slice_name, count in plan.get(category, {}).items():
            drafts.extend(drafter.build(category, slice_name, count, used))
    return drafts
