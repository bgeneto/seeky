"""Local-LLM drafts for ``conceptual``, ``exploratory``, and ``cross_language``.

These categories exist to measure semantic paraphrase and pt<->en transfer, so a
template must never draft them (SPEC-0004 0.3). The pinned local instruct model
(Qwen3-0.6B by default) runs through llama.cpp as a subprocess: no network, no
hosted API, model body text never leaves the machine.
"""

from __future__ import annotations

import json
import unicodedata

from . import config
from .corpus import Corpus, Document, tokenize
from .guard import guard_violation
from .language import build_lexicons, detect_language
from .model import ModelError, Runner, prompt_sha256
from .templates import TEXT_FORMATS, Draft, slice_for_language

_LANGUAGE_NAMES = {
    "pt-BR": "Portuguese (Brazil)",
    "en-US": "English",
    "es-ES": "Spanish",
    "fr-FR": "French",
    "de-DE": "German",
    "ja-JP": "Japanese",
    "el-GR": "Greek",
}

_RUBRIC = (
    "Rubric: 0 = does not satisfy the intent; 1 = topically related but not "
    "useful; 2 = relevant and useful but incomplete; 3 = directly satisfies "
    "the intent."
)

_EXPLORATORY_FOLDERS = {
    "pt": ("politicas", "pesquisa", "manuais", "contratos", "faturas", "notas"),
    "en": ("policies", "research", "manuals", "contracts", "invoices", "notes"),
}

_JSON_EXAMPLE = 'Example answer: {"query": "security policy home office checklist"}'


class DraftError(RuntimeError):
    pass


def _json_object(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _plain_query(text: str) -> str:
    """Accept a bare quoted or bare-line answer from a small model."""

    candidate = text.strip()
    if "{" in candidate or "}" in candidate:
        return ""
    lines = [line.strip() for line in candidate.splitlines() if line.strip()]
    if not lines:
        return ""
    line = lines[0].strip().strip('"').strip("'").strip()
    return " ".join(line.split())


def _excerpt(text: str, limit: int = 240) -> str:
    flat = " ".join(text.split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


def _looks_like_identifier(text: str, anchor_id: str) -> bool:
    """Reject an echo of the prompt's anchor instead of a search query."""

    folded = text.casefold()
    return anchor_id.casefold() in folded or folded.startswith("doc-") or "doc-" in folded


def copies_a_judged_target(text: str, grades: dict[str, int], corpus: Corpus) -> bool:
    """True when a query copies any document it is about to grade 3.

    The audit checks the guard against every grade-3 row, so the draft must pass
    the same rule before it is accepted; otherwise a query can copy a relevant
    document that is not the anchor.
    """

    for document_id, grade in grades.items():
        if grade != 3:
            continue
        target = corpus.documents[document_id]
        if guard_violation(text, [target.title, target.text], config.GUARD) is not None:
            return True
    return False


def slug_label(text: str, fallback: str = "general") -> str:
    """ASCII snake_case subtopic label (SPEC-0004 4.6)."""

    folded = unicodedata.normalize("NFKD", text)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    parts: list[str] = []
    current: list[str] = []
    for char in ascii_text.lower():
        if char.isalnum():
            current.append(char)
        elif current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    label = "_".join(parts[:4])[:40].strip("_")
    return label or fallback


class LlmDrafter:
    QUERY_ATTEMPTS = 5

    def __init__(self, corpus: Corpus, runner: Runner, model: config.ModelPin = config.DEFAULT_MODEL) -> None:
        self.corpus = corpus
        self.runner = runner
        self.model = model
        self.lexicons = build_lexicons(corpus)

    # -- prompts ---------------------------------------------------------

    def _query_prompt(self, category: str, doc: Document, query_language: str) -> tuple[str, str]:
        language_name = _LANGUAGE_NAMES[query_language]
        if category == "conceptual":
            body = (
                f"TASK: conceptual\nANCHOR: {doc.id}\nLANGUAGE: {query_language}\n"
                f"Below are sentences from one document. Write ONE short search query in "
                f"{language_name} that a person would type into a file-search box to find a "
                "document about this content.\n"
                "Rules: 3 to 10 words; a keyword phrase, not a question and not an instruction; "
                "describe the meaning with your own words; never reuse three consecutive words "
                "from the text; do not mention a file name; stay specific enough that this "
                "document is a good answer.\n"
                f"TEXT: {_excerpt(doc.text, 500)}\n"
                'Answer with exactly this JSON and nothing else: {"query": "..."}\n'
                + _JSON_EXAMPLE
            )
        elif category == "exploratory":
            titles = self._folder_titles(doc)
            body = (
                f"TASK: exploratory\nANCHOR: {doc.id}\nLANGUAGE: {query_language}\n"
                f"FOLDER: {doc.folder}\n"
                "These titles share one folder in a personal document collection:\n"
                + "\n".join(f"- {title}" for title in titles)
                + f"\nWrite ONE broad keyword search query in {language_name} that should "
                "find several of these documents in a file-search box.\n"
                "Rules: 3 to 9 words; broad topic intent, not a single title; no question and "
                "no instruction; never copy a title; no file names.\n"
                'Answer with exactly this JSON and nothing else: {"query": "..."}\n'
                + _JSON_EXAMPLE
            )
        elif category == "cross_language":
            body = (
                f"TASK: cross_language\nANCHOR: {doc.id}\nLANGUAGE: {query_language}\n"
                f"SOURCE_LANGUAGE: {doc.language}\n"
                f"Read the {_LANGUAGE_NAMES.get(doc.language, doc.language)} sentences below and "
                f"write ONE short search query in {language_name}, as typed into a file-search "
                "box, that should find the document they come from.\n"
                "Rules: 3 to 10 words; a keyword phrase, not a question; translate the meaning, "
                "never copy source-language phrases; do not mention a file name.\n"
                f"TEXT: {_excerpt(doc.text, 500)}\n"
                'Answer with exactly this JSON and nothing else: {"query": "..."}\n'
                + _JSON_EXAMPLE
            )
        else:
            raise DraftError(f"no LLM prompt for {category}")
        return body, prompt_sha256(category, "query", body, self.model)

    def _grade_prompt(self, category: str, query: str, candidates: list[Document]) -> tuple[str, dict[str, str]]:
        lines = [
            f"TASK: grade\nCATEGORY: {category}\nQUERY: {query}\n",
            "Candidate documents:",
        ]
        mapping: dict[str, str] = {}
        for index, doc in enumerate(candidates, start=1):
            key = f"c{index}"
            mapping[key] = doc.id
            lines.append(f"[{key}] {doc.title} | {_excerpt(doc.text, 240)}")
        lines.append(_RUBRIC)
        lines.append(
            "Judge every candidate for this query. Reply with exactly this JSON and nothing "
            'else: {"grades": [{"candidate": "c1", "grade": 2}, ...]}'
        )
        body = "\n".join(lines)
        return body, mapping

    # -- corpus helpers --------------------------------------------------

    def _folder_titles(self, doc: Document) -> list[str]:
        docs = [
            other
            for other in self.corpus.documents_of(doc.lang)
            if self.corpus.documents[other].folder == doc.folder
            and other >= doc.id
        ][:6]
        return [self.corpus.documents[other].title for other in docs]

    def _anchors(self, category: str, lang: str) -> list[Document]:
        if category == "exploratory":
            folders = set(_EXPLORATORY_FOLDERS.get(lang, ()))
            return self.corpus.select(
                lang,
                lambda doc: doc.file_class == "document"
                and doc.folder in folders
                and len(doc.title) >= 8,
            )
        return self.corpus.select(
            lang,
            lambda doc: doc.file_class == "document"
            and doc.fmt in TEXT_FORMATS
            and not doc.source_item_id.startswith("syn-long-report")
            and len(doc.title) >= 8,
        )

    def _candidates(self, category: str, anchor: Document) -> list[Document]:
        exclude = {anchor.id, *(member for member, _ in self.corpus.related(anchor.id))}
        if category == "exploratory":
            picked = [
                self.corpus.documents[doc_id]
                for doc_id in self.corpus.documents_of(anchor.lang)
                if self.corpus.documents[doc_id].folder == anchor.folder and doc_id >= anchor.id
            ][:6]
            return picked or [anchor]
        tokens = tokenize(anchor.title + " " + anchor.text[:600])
        lexical = self.corpus.lexical_candidates(anchor.lang, tokens, frozenset(exclude))
        chosen = [anchor]
        for doc_id in lexical:
            if len(chosen) >= 3:
                break
            if doc_id not in exclude:
                chosen.append(self.corpus.documents[doc_id])
        same_folder = [
            doc_id
            for doc_id in self.corpus.documents_of(anchor.lang)
            if self.corpus.documents[doc_id].folder == anchor.folder
            and doc_id not in exclude
            and doc_id not in {doc.id for doc in chosen}
        ]
        if same_folder:
            chosen.append(self.corpus.documents[same_folder[0]])
        return chosen

    # -- generation ------------------------------------------------------

    def _ask_query(self, category: str, doc: Document, query_language: str) -> tuple[str, str]:
        """Return a query that passes the language, identifier, and copy gates.

        A failing attempt stays on the same target with a specific correction
        instruction; the gate never relaxes. Exhausting the budget raises
        ``DraftError`` so the caller can exclude the target and backfill.
        """

        prompt, _ = self._query_prompt(category, doc, query_language)
        expected = query_language.split("-")[0]
        language_name = _LANGUAGE_NAMES[query_language]
        feedback = ""
        last = ""
        for _ in range(self.QUERY_ATTEMPTS):
            request = prompt + feedback
            answer = self.runner.complete(request)
            last = answer
            parsed = _json_object(answer)
            query = ""
            if parsed and isinstance(parsed.get("query"), str):
                query = " ".join(parsed["query"].split()).strip()
            if not query:
                query = _plain_query(answer)
            if not query:
                feedback = (
                    "\n\nYour previous reply was not valid JSON. "
                    "Reply with the JSON object only."
                )
                continue
            if _looks_like_identifier(query, doc.id):
                feedback = (
                    "\n\nDo not repeat the document identifier. Write a search query in "
                    f"{language_name} instead."
                )
                continue
            violation = guard_violation(query, [doc.title, doc.text], config.GUARD)
            if violation is not None:
                feedback = (
                    f"\n\nYour previous answer copied the document ({violation}). Rewrite "
                    "the query with different words and never reuse a phrase from the text."
                )
                continue
            detected = detect_language(query, self.lexicons)
            if detected != expected:
                feedback = (
                    f"\n\nYour previous answer was not written in {language_name}. "
                    f"Write the query only in {language_name}."
                )
                continue
            return query, prompt_sha256(category, "query", request, self.model)
        raise DraftError(
            f"no {expected} query passed the language and no-copy gates for {doc.id} "
            f"(last reply: {last[:120]!r})"
        )

    def _ask_grades(self, category: str, query: str, candidates: list[Document]) -> tuple[dict[str, int], str]:
        prompt, mapping = self._grade_prompt(category, query, candidates)
        digest = prompt_sha256(category, "grade", prompt, self.model)
        for attempt in range(3):
            request = prompt if attempt == 0 else prompt + "\n\nYour previous reply was not valid JSON. Reply with the JSON object only."
            answer = self.runner.complete(request)
            parsed = _json_object(answer)
            if not parsed or not isinstance(parsed.get("grades"), list):
                continue
            grades: dict[str, int] = {}
            for item in parsed["grades"]:
                if not isinstance(item, dict):
                    continue
                key = item.get("candidate")
                grade = item.get("grade")
                if key in mapping and isinstance(grade, int) and not isinstance(grade, bool) and 0 <= grade <= 3:
                    grades[mapping[key]] = grade
            if grades:
                return grades, digest
        raise DraftError("the model returned no usable grades")

    def build(self, category: str, slice_name: str, count: int, used: set[str]) -> list[Draft]:
        drafts: list[Draft] = []
        anchors: dict[str, list[Document]] = {}
        cursor: dict[str, int] = {}
        attempt = 0
        while len(drafts) < count:
            if attempt > count * 12 + 200:
                raise DraftError(
                    f"cannot draft {count} {category}/{slice_name} queries: "
                    "the local model did not return usable, non-copying drafts"
                )
            if category == "cross_language":
                if attempt % 2 == 0:
                    lang, query_language = "en", "pt-BR"
                else:
                    lang, query_language = "pt", "en-US"
            else:
                lang = slice_name
                query_language = config.SLICE_LANGUAGE[lang]
            if lang not in anchors:
                anchors[lang] = self._anchors(category, lang)
            index = cursor.get(lang, 0)
            cursor[lang] = index + 1
            attempt += 1
            pool = anchors[lang]
            if index >= len(pool):
                continue
            anchor = pool[index]

            try:
                text, query_digest = self._ask_query(category, anchor, query_language)
            except DraftError:
                continue
            if text.casefold() in used:
                continue

            candidates = self._candidates(category, anchor)
            try:
                grades, grade_digest = self._ask_grades(category, text, candidates)
            except DraftError:
                continue
            if not any(grade >= 2 for grade in grades.values()):
                continue
            # The audit checks the guard against every grade-3 target, so enforce
            # the same rule here: a query may not copy any document it grades 3.
            if copies_a_judged_target(text, grades, self.corpus):
                continue
            used.add(text.casefold())
            drafts.append(
                Draft(
                    category=category,
                    language=query_language,
                    target_languages=(anchor.language,),
                    language_slice=slice_for_language(query_language, anchor.language),
                    configuration="default",
                    text=text,
                    filters=None,
                    anchor_id=anchor.id,
                    origin="llm",
                    variant="llm",
                    prompt_sha256=query_digest,
                    grades=tuple(sorted(grades.items())),
                    grade_prompt_sha256=grade_digest,
                )
            )
        return drafts


def build_all_llm(
    corpus: Corpus,
    runner: Runner,
    plan: dict | None = None,
    progress=None,
) -> list[Draft]:
    plan = plan or config.PLAN
    drafter = LlmDrafter(corpus, runner, runner.model)
    drafts: list[Draft] = []
    used: set[str] = set()
    for category in config.LLM_CATEGORIES:
        for slice_name, count in plan.get(category, {}).items():
            drafts.extend(drafter.build(category, slice_name, count, used))
            if progress is not None:
                progress(f"{category}/{slice_name}: {count} queries ready")
    return drafts
