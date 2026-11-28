"""Read a generated SDC corpus (SPEC-0004 4.3) without the generator package."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .jsonio import load_json, read_jsonl

_TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN.findall(text)]


@dataclass(frozen=True)
class Passage:
    id: str
    document_id: str
    text: str
    text_sha256: str
    kind: str
    start_utf8: int
    end_utf8: int
    boilerplate_family_id: str | None
    token_set: frozenset[str]

    def span_of(self, phrase: str) -> dict[str, int] | None:
        """UTF-8 byte offsets of the first exact occurrence of ``phrase``."""

        index = self.text.find(phrase)
        if index < 0 or not phrase:
            return None
        start = len(self.text[:index].encode("utf-8"))
        return {"start_utf8": start, "end_utf8": start + len(phrase.encode("utf-8"))}


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    text: str
    text_sha256: str
    languages: tuple[str, ...]
    fmt: str
    file_class: str
    path: str
    folder: str
    basename: str
    stem: str
    byte_count: int
    modified_at: str
    source_item_id: str
    duplicate_cluster_ids: tuple[str, ...]
    version_group_id: str | None
    version_number: int | None
    is_latest: bool | None

    @property
    def language(self) -> str:
        return self.languages[0]

    @property
    def lang(self) -> str:
        return self.languages[0].split("-")[0].lower()


@dataclass(frozen=True)
class Cluster:
    cluster_id: str
    kind: str
    canonical_document_id: str
    member_document_ids: tuple[str, ...]


@dataclass(frozen=True)
class VersionGroup:
    version_group_id: str
    ordered: tuple[str, ...]


class Corpus:
    def __init__(
        self,
        root: Path,
        corpus_hash: str,
        documents: dict[str, Document],
        clusters: dict[str, Cluster],
        versions: dict[str, VersionGroup],
    ) -> None:
        self.root = root
        self.corpus_hash = corpus_hash
        self.documents = documents
        self.clusters = clusters
        self.versions = versions
        self._by_lang: dict[str, list[str]] = defaultdict(list)
        self._index: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for doc in documents.values():
            self._by_lang[doc.lang].append(doc.id)
            for token in set(tokenize(doc.title + "\n" + doc.text)):
                self._index[doc.lang][token].append(doc.id)
        for ids in self._by_lang.values():
            ids.sort()
        for per_lang in self._index.values():
            for ids in per_lang.values():
                ids.sort()
        self._passages: dict[str, list[Passage]] | None = None

    @classmethod
    def load(cls, root: Path) -> "Corpus":
        manifest = load_json(root / "manifest.json")
        documents: dict[str, Document] = {}
        for row in read_jsonl(root / "corpus.jsonl"):
            metadata = row["metadata"]
            path = metadata["relative_path"]
            parts = path.split("/")
            basename = parts[-1]
            stem = basename.rsplit(".", 1)[0] if "." in basename else basename
            documents[row["_id"]] = Document(
                id=row["_id"],
                title=row["title"],
                text=row["text"],
                text_sha256=metadata["text_sha256"],
                languages=tuple(metadata["languages"]),
                fmt=metadata["format"],
                file_class=metadata["file_class"],
                path=path,
                folder=parts[2] if len(parts) >= 4 else "",
                basename=basename,
                stem=stem,
                byte_count=metadata["byte_count"],
                modified_at=metadata["modified_at"],
                source_item_id=metadata["source_item_id"],
                duplicate_cluster_ids=tuple(metadata["duplicate_cluster_ids"]),
                version_group_id=metadata["version_group_id"],
                version_number=metadata["version_number"],
                is_latest=metadata["is_latest"],
            )
        clusters: dict[str, Cluster] = {}
        for row in read_jsonl(root / "duplicate-clusters.jsonl"):
            clusters[row["cluster_id"]] = Cluster(
                cluster_id=row["cluster_id"],
                kind=row["kind"],
                canonical_document_id=row["canonical_document_id"],
                member_document_ids=tuple(row["member_document_ids"]),
            )
        versions: dict[str, VersionGroup] = {}
        for row in read_jsonl(root / "versions.jsonl"):
            ordered = tuple(
                member["document_id"]
                for member in sorted(row["members"], key=lambda m: m["version_number"])
            )
            versions[row["version_group_id"]] = VersionGroup(row["version_group_id"], ordered)
        return cls(root, manifest["corpus_hash"], documents, clusters, versions)

    # -- selection -------------------------------------------------------

    def documents_of(self, lang: str) -> list[str]:
        return list(self._by_lang.get(lang, ()))

    def select(
        self,
        lang: str,
        predicate,
        *,
        exclude: frozenset[str] = frozenset(),
        limit: int | None = None,
    ) -> list[Document]:
        chosen: list[Document] = []
        for doc_id in self._by_lang.get(lang, ()):
            if doc_id in exclude:
                continue
            doc = self.documents[doc_id]
            if predicate(doc):
                chosen.append(doc)
                if limit is not None and len(chosen) >= limit:
                    break
        return chosen

    def related(self, document_id: str) -> list[tuple[str, str]]:
        """Cluster and version neighbours as ``(document_id, relation)``."""

        doc = self.documents[document_id]
        out: list[tuple[str, str]] = []
        seen = {document_id}
        for cluster_id in doc.duplicate_cluster_ids:
            cluster = self.clusters[cluster_id]
            for member in cluster.member_document_ids:
                if member not in seen:
                    seen.add(member)
                    out.append((member, cluster.kind))
        if doc.version_group_id is not None:
            group = self.versions[doc.version_group_id]
            for member in group.ordered:
                if member not in seen:
                    seen.add(member)
                    out.append((member, "version"))
        return out

    def lexical_candidates(self, lang: str, tokens: list[str], exclude: frozenset[str]) -> list[str]:
        """Documents sharing rare query tokens, best first, then by ``_id``."""

        counts: dict[str, int] = defaultdict(int)
        per_lang = self._index.get(lang, {})
        for token in sorted(set(tokens)):
            postings = per_lang.get(token, ())
            if 0 < len(postings) <= 2000:
                for doc_id in postings:
                    counts[doc_id] += 1
        ranked = sorted(
            ((count, doc_id) for doc_id, count in counts.items() if doc_id not in exclude),
            key=lambda entry: (-entry[0], entry[1]),
        )
        return [doc_id for _, doc_id in ranked]

    def documents_with_phrase(self, phrase: str) -> list[str]:
        """Documents whose text contains the exact token sequence of ``phrase``."""

        tokens = tokenize(phrase)
        if len(tokens) < 2:
            return []
        candidates: set[str] | None = None
        for token in set(tokens):
            ids: set[str] = set()
            for per_lang in self._index.values():
                ids.update(per_lang.get(token, ()))
            candidates = ids if candidates is None else candidates & ids
            if not candidates:
                return []
        assert candidates is not None
        needle = " ".join(tokens)
        return [
            doc_id
            for doc_id in sorted(candidates)
            if needle in " ".join(tokenize(self.documents[doc_id].text))
        ]

    # -- passages --------------------------------------------------------

    def load_passages(self) -> None:
        if self._passages is not None:
            return
        by_doc: dict[str, list[Passage]] = defaultdict(list)
        for row in read_jsonl(self.root / "passages.jsonl"):
            text = row["text"]
            by_doc[row["document_id"]].append(
                Passage(
                    id=row["_id"],
                    document_id=row["document_id"],
                    text=text,
                    text_sha256=row["text_sha256"],
                    kind=row["kind"],
                    start_utf8=row["start_utf8"],
                    end_utf8=row["end_utf8"],
                    boilerplate_family_id=row["boilerplate_family_id"],
                    token_set=frozenset(tokenize(text)),
                )
            )
        for passages in by_doc.values():
            passages.sort(key=lambda p: (p.start_utf8, p.end_utf8, p.id))
        self._passages = dict(by_doc)

    def passages(self, document_id: str) -> list[Passage]:
        self.load_passages()
        assert self._passages is not None
        return self._passages.get(document_id, [])

    def best_passage(self, document_id: str, tokens: list[str]) -> Passage | None:
        """Passage with the largest query-token overlap, ties by passage ID."""

        wanted = set(tokens)
        best: Passage | None = None
        best_score = -1
        for passage in self.passages(document_id):
            score = len(wanted & passage.token_set)
            if score > best_score or (score == best_score and best is not None and passage.id < best.id):
                best, best_score = passage, score
        return best
