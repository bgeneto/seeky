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
from .corpus import Corpus, Document
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


def _unique(text: str) -> str:
    return " ".join(text.split()).strip()


class TemplateDrafter:
    def __init__(self, corpus: Corpus, seed: str = config.DRAFT_SEED) -> None:
        self.corpus = corpus
        self.seed = seed
        self._cache: dict[tuple[str, str], list[Document]] = {}

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
            return lambda doc: doc.file_class == "document" and doc.fmt in TEXT_FORMATS and len(doc.title) >= 8
        if category == "exact_identifier":
            return lambda doc: doc.file_class == "document" and bool(
                _IDENTIFIER.search(doc.text) or _UUID.search(doc.text) or _ERROR_CODE.search(doc.text)
            )
        if category == "needle_in_haystack":
            return lambda doc: doc.file_class == "document" and doc.source_item_id.startswith("syn-long-report")
        if category == "mixed_semantic_metadata":
            return lambda doc: (
                doc.file_class == "document"
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
                text = f"{_title_head(title)} {words['document']}"
            else:
                text = f"{words['find']} {title}" if words["find"] else title
            return Draft(text=text, variant=f"known-{variant}", **base)

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
            passage = passages[
                uniform_int(self.seed, "needle-passage", f"{doc.id}/{slot}", 0, len(passages) - 1)
            ]
            start = uniform_int(self.seed, "needle-window", f"{passage.id}/{slot}", 0, 40)
            phrase = _phrase(passage.text, 7, start)
            if phrase is None:
                return None
            text = f"{words['find']} {phrase}" if variant else phrase
            return Draft(
                text=text,
                variant=f"needle-{variant}",
                evidence_passage_ids=(passage.id,),
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
            passage = self.corpus.best_passage(doc.id, stem.split())
            return Draft(
                text=text,
                variant=f"filename-{variant}",
                evidence_passage_ids=(passage.id,) if passage else (),
                **base,
            )

        if category == "code_search":
            passages = [p for p in self.corpus.passages(doc.id) if p.kind == "code"]
            if not passages:
                return None
            passage = passages[(variant + slot) % len(passages)]
            phrase = _phrase(
                passage.text,
                4,
                uniform_int(self.seed, "code-window", f"{passage.id}/{slot}", 0, 12),
            )
            if phrase is None:
                return None
            head = _title_head(doc.title).lower()
            language_name = doc.path.split("/")[2] if doc.path.count("/") >= 3 else "code"
            text = f"{language_name} {head} {phrase}" if variant == 0 else f"{language_name} {phrase}"
            return Draft(
                text=text,
                variant=f"code-{variant}",
                evidence_passage_ids=(passage.id,),
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
