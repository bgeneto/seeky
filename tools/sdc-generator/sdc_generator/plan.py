"""Deterministic corpus plan: base documents, injections, clusters, versions.

Document IDs derive from the source item, renderer role, injection role, and
occurrence index only. Paths never contribute to identity.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import derive
from .canonical import EXTENSIONS, FORMATS, Document, Block, MEDIA_TYPES
from .compose import Work, compose_work
from .derive import parse_iso_utc, timestamp_between
from .errors import PROFILE_INVALID, SCHEMA_INVALID, SdcError
from .layout import wrap_text
from .profiles import Profile
from .renderlock import load_renderer_lock
from .sources import SourceSet, TemplateSource

_TEXT_FORMATS = ("pdf", "docx", "xlsx", "pptx", "odt", "rtf", "html", "epub", "eml", "md", "txt")
_SHARES = {
    "pdf": 100,
    "docx": 100,
    "xlsx": 90,
    "pptx": 90,
    "odt": 80,
    "rtf": 80,
    "html": 100,
    "epub": 80,
    "eml": 90,
    "md": 100,
    "txt": 90,
}
_NON_LATIN_PREFIXES = ("ja", "zh", "ko", "el", "ru", "ar", "he", "th", "hi", "uk", "bg")
_TEXT_COPY_TARGET = {
    "md": "html",
    "txt": "docx",
    "docx": "odt",
    "html": "txt",
    "pdf": "md",
    "eml": "txt",
    "rtf": "html",
    "odt": "txt",
    "epub": "txt",
    "pptx": "txt",
    "xlsx": "txt",
}
_RECIPE_IDS = {
    "pdf": "pdf-text-v1",
    "docx": "docx-ooxml-v1",
    "xlsx": "xlsx-ooxml-v1",
    "pptx": "pptx-ooxml-v1",
    "odt": "odt-odf-v1",
    "rtf": "rtf-1-v1",
    "html": "html5-v1",
    "epub": "epub3-v1",
    "eml": "eml-mime-v1",
    "md": "markdown-v1",
    "txt": "text-utf8-v1",
    "code": "code-utf8-v1",
    "scanned-pdf": "scanned-pdf-v1",
    "scanned-image": "scanned-image-v1",
}

_ILLEGAL_FILENAME = '<>:"/\\|?*'


@dataclass
class Plan:
    profile: Profile
    seed: str
    documents: list[Document]
    clusters: list[dict[str, Any]]
    versions: list[dict[str, Any]]
    source_sets: dict[str, SourceSet]
    templates: dict[str, TemplateSource]
    boilerplate_families: dict[str, list[str]]
    scan_recipes: dict[str, dict[str, Any]]
    renderer_lock_sha256: str
    injection_counts: dict[str, int]
    code_documents: int


def _require(condition: bool, message: str, *, field: str = "") -> None:
    if not condition:
        raise SdcError(PROFILE_INVALID, message, field=field)


def _format_schedule(count: int, seed: str) -> list[str]:
    """Prefix-stable format assignment.

    The first 1000 formats follow a fixed, share-proportional pattern. Profiles
    of different sizes therefore agree on every shared base index, which keeps
    a larger corpus an extension of the smaller one.
    """

    total_share = sum(_SHARES.values())
    counts: dict[str, int] = {}
    remainders: list[tuple[int, int, str]] = []
    assigned = 0
    for order, fmt in enumerate(_TEXT_FORMATS):
        numerator = 1000 * _SHARES[fmt]
        quotient, remainder = divmod(numerator, total_share)
        counts[fmt] = quotient
        assigned += quotient
        remainders.append((-remainder, order, fmt))
    for _, _, fmt in sorted(remainders)[: 1000 - assigned]:
        counts[fmt] += 1
    pattern: list[str] = []
    for fmt in _TEXT_FORMATS:
        pattern.extend([fmt] * counts[fmt])
    ordered = derive.ordered(
        list(enumerate(pattern)), "sdc-format-pattern", "format-pattern", key=lambda entry: f"{entry[0]}"
    )
    pattern = [fmt for _, fmt in ordered]
    return [pattern[index % len(pattern)] for index in range(count)]


def _safe_component(text: str) -> str:
    cleaned = "".join(
        char
        for char in text
        if char not in _ILLEGAL_FILENAME and ord(char) >= 32
    )
    cleaned = " ".join(cleaned.split()).strip(" .")
    return cleaned or "item"


def _safe_filename(title: str, extension: str) -> str:
    base = _safe_component(title)
    if len(base) > 90:
        base = base[:90].rstrip(" .")
    return f"{base}{extension}"


def _safe_folder(folder: str) -> str:
    parts = [
        _safe_component(part)
        for part in folder.replace("\\", "/").split("/")
        if part.strip()
    ]
    return "/".join(parts) or "documentos"


def _is_non_latin(language: str) -> bool:
    return language.lower().startswith(_NON_LATIN_PREFIXES)


def _fits_scan(doc: Document) -> bool:
    if _is_non_latin(doc.language):
        return False
    lines = 0
    for block in doc.blocks:
        lines += len(wrap_text(block.text, 62)) + 1
    return lines <= 40 and doc.format in ("pdf", "docx", "md", "txt", "html", "rtf", "odt", "epub", "eml")


def _render_recipe(fmt: str, scan_recipe: str | None) -> str:
    if scan_recipe is not None:
        return f"{_RECIPE_IDS[fmt]}:{scan_recipe}"
    return _RECIPE_IDS[fmt]


def _base_id(template: TemplateSource, index: int) -> str:
    short = template.source_item_id.removeprefix("syn-")
    if short.endswith("-v1"):
        short = short[:-3]
    return f"doc-{short}-{index + 1:05d}"


def _document(
    work: Work,
    *,
    doc_id: str,
    fmt: str,
    relative_path: str,
    profile: Profile,
    seed: str,
    start,
    end,
    file_class: str = "document",
    scan_recipe: str | None = None,
    scan_options: dict[str, Any] | None = None,
) -> Document:
    language = work.language
    return Document(
        doc_id=doc_id,
        title=work.title,
        language=language,
        languages=(language,),
        format=fmt,
        file_class=file_class,
        relative_path=relative_path,
        source_set_id=work.template.source_set_id,
        source_item_id=work.template.source_item_id,
        source_sha256=work.template.template_sha256,
        render_recipe_id=_render_recipe(fmt, scan_recipe),
        modified_at=timestamp_between(
            seed, "modified-at", doc_id, start, end
        ),
        blocks=work.blocks,
        scan_recipe=scan_recipe,
        scan_options=scan_options,
    )


class _PathPool:
    def __init__(self) -> None:
        self.used: set[str] = set()

    def take(self, path: str) -> str:
        candidate = path
        if candidate.casefold() in self.used:
            stem, dot, extension = candidate.rpartition(".")
            if not dot:
                stem, extension = candidate, ""
            counter = 2
            while True:
                suffix = f"-{counter}"
                candidate = f"{stem}{suffix}.{extension}" if extension else f"{stem}{suffix}"
                if candidate.casefold() not in self.used:
                    break
                counter += 1
        self.used.add(candidate.casefold())
        return candidate


def plan_corpus(
    *,
    profile: Profile,
    seed: str,
    source_sets: dict[str, SourceSet],
    templates: dict[str, TemplateSource],
    sdc_root: Path,
) -> Plan:
    lock, lock_sha = load_renderer_lock(sdc_root / "renderers.lock.json")
    recipes = lock["scan_recipes"]
    for recipe in profile.scan_recipes:
        if recipe not in recipes:
            raise SdcError(
                PROFILE_INVALID,
                f"profile scan recipe {recipe!r} is not in the renderer lock",
                file=profile.path.name,
                field="scan_recipes",
            )

    selected_items: list[str] = []
    for set_id in profile.source_set_ids:
        if set_id not in source_sets:
            raise SdcError(
                SCHEMA_INVALID,
                f"profile names unknown source set {set_id!r}",
                file=profile.path.name,
                field="source_set_ids",
            )
        selected_items.extend(item.source_item_id for item in source_sets[set_id].items)
    missing = [item for item in selected_items if item not in templates]
    if missing:
        raise SdcError(
            SCHEMA_INVALID,
            f"selected source items have no synthetic template: {missing}",
            file=profile.path.name,
            field="source_set_ids",
        )
    chosen = {item: templates[item] for item in selected_items}

    text_templates = [t for t in chosen.values() if t.data["kind"] == "text"]
    long_templates = [t for t in chosen.values() if t.data["kind"] == "long"]
    code_templates = [t for t in chosen.values() if t.data["kind"] == "code"]
    boiler_templates = [t for t in chosen.values() if t.data["kind"] == "boilerplate"]
    _require(bool(text_templates), "no text templates in the selected source sets")
    _require(bool(long_templates), "no long-document template in the selected source sets")
    _require(bool(code_templates), "no code template in the selected source sets")
    _require(bool(boiler_templates), "no boilerplate template in the selected source sets")

    families: dict[str, list[str]] = {}
    for template in boiler_templates:
        for name, blocks in template.data["families"].items():
            families[name] = list(blocks)
    _require(bool(families), "boilerplate template defines no families")

    base_count = profile.base_documents
    schedule = _format_schedule(base_count, seed)
    start = parse_iso_utc(profile.clock_start)
    end = parse_iso_utc(profile.clock_end)

    paths = _PathPool()
    documents: list[Document] = []
    base_documents: list[Document] = []

    for index in range(base_count):
        if index % 100 == 7:
            template = long_templates[index % len(long_templates)]
            fmt = "pdf" if (index // 100) % 2 == 0 else "txt"
        else:
            template = text_templates[index % len(text_templates)]
            fmt = schedule[index]
            if _is_non_latin(str(template.data["language"])):
                fmt = "txt" if index % 2 == 0 else "md"
        work = compose_work(template, index, seed, format_hint=fmt)
        doc_id = _base_id(template, index)
        folder = _safe_folder(str(template.data["folder"]))
        filename = _safe_filename(work.title, EXTENSIONS[fmt])
        path = paths.take(f"files/documents/{folder}/{work.year}/{filename}")
        document = _document(
            work,
            doc_id=doc_id,
            fmt=fmt,
            relative_path=path,
            profile=profile,
            seed=seed,
            start=start,
            end=end,
        )
        documents.append(document)
        base_documents.append(document)

    # Code root: disjoint, opt-in only (ADR-0024, SPEC-0004-R12).
    code_count = profile.code_documents
    for index in range(code_count):
        template = code_templates[index % len(code_templates)]
        work = compose_work(template, index, seed, format_hint="code")
        doc_id = f"doc-code-{index + 1:03d}"
        language_folder = _safe_component(work.code_language or "code")
        extension = work.code_extension or ".txt"
        filename = _safe_filename(work.title, extension)
        path = paths.take(f"files/code/{language_folder}/{filename}")
        document = _document(
            work,
            doc_id=doc_id,
            fmt="code",
            relative_path=path,
            profile=profile,
            seed=seed,
            start=start,
            end=end,
            file_class="source_code",
        )
        document.languages = ("en",)
        documents.append(document)

    injection = profile.injection
    clusters: list[dict[str, Any]] = []
    # Injection sources follow base creation order, which is stable when a
    # larger profile appends more base documents: a smaller corpus's injected
    # documents are an exact prefix/subset of the larger one.
    ordered_base = list(base_documents)
    cursor = 0

    def take(count: int, predicate=None) -> list[Document]:
        nonlocal cursor
        chosen_docs: list[Document] = []
        while len(chosen_docs) < count:
            if cursor >= len(ordered_base):
                raise SdcError(
                    PROFILE_INVALID,
                    "not enough base documents to satisfy the injection counts",
                    file=profile.path.name,
                )
            candidate = ordered_base[cursor]
            cursor += 1
            if predicate is not None and not predicate(candidate):
                continue
            chosen_docs.append(candidate)
        return chosen_docs

    # Exact byte copies: identical bytes, distinct path and document ID.
    byte_sources = take(injection["exact_byte_copies"])
    for ordinal, source in enumerate(byte_sources, start=1):
        cluster = f"dup-byte-{ordinal:02d}"
        copy_id = f"{source.doc_id}-copy-byte-{ordinal:02d}"
        folder = source.relative_path.rsplit("/", 1)[0]
        filename = _safe_filename(
            f"{source.title} (cópia idêntica {ordinal:02d})",
            Path(source.relative_path).suffix,
        )
        copy_doc = copy.deepcopy(source)
        copy_doc.doc_id = copy_id
        copy_doc.relative_path = paths.take(f"{folder}/arquivo/{filename}")
        copy_doc.duplicate_cluster_ids = sorted(
            set(copy_doc.duplicate_cluster_ids) | {cluster}
        )
        copy_doc.byte_copy_of = source.doc_id
        copy_doc.version_group_id = None
        copy_doc.version_number = None
        copy_doc.is_latest = None
        copy_doc.version_changes = None
        source.duplicate_cluster_ids = sorted(
            set(source.duplicate_cluster_ids) | {cluster}
        )
        documents.append(copy_doc)
        clusters.append(
            {
                "cluster_id": cluster,
                "kind": "exact_byte",
                "canonical_document_id": source.doc_id,
                "member_document_ids": sorted([source.doc_id, copy_id]),
            }
        )

    # Exact text copies: same canonical text, usually another format.
    text_sources = take(injection["exact_text_copies"])
    for ordinal, source in enumerate(text_sources, start=1):
        cluster = f"dup-text-{ordinal:02d}"
        target = _TEXT_COPY_TARGET.get(source.format, "txt")
        if target == source.format or target not in EXTENSIONS:
            target = "txt"
        copy_id = f"{source.doc_id}-copy-text-{ordinal:02d}"
        folder = source.relative_path.rsplit("/", 1)[0]
        filename = _safe_filename(
            f"{source.title} (cópia de texto {ordinal:02d})", EXTENSIONS[target]
        )
        copy_doc = copy.deepcopy(source)
        copy_doc.doc_id = copy_id
        copy_doc.format = target
        copy_doc.relative_path = paths.take(f"{folder}/arquivo/{filename}")
        copy_doc.render_recipe_id = _render_recipe(target, None)
        copy_doc.duplicate_cluster_ids = sorted(
            set(copy_doc.duplicate_cluster_ids) | {cluster}
        )
        copy_doc.byte_copy_of = None
        copy_doc.version_group_id = None
        copy_doc.version_number = None
        copy_doc.is_latest = None
        copy_doc.version_changes = None
        source.duplicate_cluster_ids = sorted(
            set(source.duplicate_cluster_ids) | {cluster}
        )
        documents.append(copy_doc)
        clusters.append(
            {
                "cluster_id": cluster,
                "kind": "exact_text",
                "canonical_document_id": source.doc_id,
                "member_document_ids": sorted([source.doc_id, copy_id]),
            }
        )

    # Scanned variants: same canonical text, no text layer in the image/PDF.
    scan_sources = take(injection["scanned_variants"], predicate=_fits_scan)
    for ordinal, source in enumerate(scan_sources, start=1):
        cluster = f"dup-scan-{ordinal:02d}"
        fmt = "scanned-pdf" if ordinal % 2 else "scanned-image"
        recipe_name = profile.scan_recipes[(ordinal - 1) % len(profile.scan_recipes)]
        scan_id = f"{source.doc_id}-scan-{ordinal:02d}"
        folder = source.relative_path.rsplit("/", 1)[0]
        filename = _safe_filename(
            f"{source.title} (digitalizado {ordinal:02d})", EXTENSIONS[fmt]
        )
        scan_doc = copy.deepcopy(source)
        scan_doc.doc_id = scan_id
        scan_doc.format = fmt
        scan_doc.relative_path = paths.take(f"{folder}/scans/{filename}")
        scan_doc.render_recipe_id = _render_recipe(fmt, recipe_name)
        scan_doc.scan_recipe = recipe_name
        scan_doc.scan_options = dict(recipes[recipe_name])
        scan_doc.duplicate_cluster_ids = sorted(
            set(scan_doc.duplicate_cluster_ids) | {cluster}
        )
        scan_doc.byte_copy_of = None
        scan_doc.version_group_id = None
        scan_doc.version_number = None
        scan_doc.is_latest = None
        scan_doc.version_changes = None
        scan_doc.block_pages = {}
        scan_doc.page_texts = {}
        source.duplicate_cluster_ids = sorted(
            set(source.duplicate_cluster_ids) | {cluster}
        )
        documents.append(scan_doc)
        clusters.append(
            {
                "cluster_id": cluster,
                "kind": "scanned_variant",
                "canonical_document_id": source.doc_id,
                "member_document_ids": sorted([source.doc_id, scan_id]),
            }
        )

    # Near duplicates: bounded block edits, path-independent cluster label.
    near_sources = take(
        injection["near_duplicate_documents"],
        predicate=lambda doc: doc.format not in ("xlsx", "pptx", "code"),
    )
    for ordinal, source in enumerate(near_sources, start=1):
        cluster = f"dup-near-{ordinal:02d}"
        near_id = f"{source.doc_id}-near-{ordinal:02d}"
        folder = source.relative_path.rsplit("/", 1)[0]
        filename = _safe_filename(
            f"{source.title} (versão próxima {ordinal:02d})",
            Path(source.relative_path).suffix,
        )
        near_doc = copy.deepcopy(source)
        near_doc.doc_id = near_id
        near_doc.relative_path = paths.take(f"{folder}/revisoes/{filename}")
        near_blocks = near_doc.blocks
        editable = [
            block for block in near_blocks if block.kind == "paragraph"
        ]
        if editable:
            target = editable[ordinal % len(editable)]
            suffix = (
                " Revisão interna: os valores foram atualizados."
                if source.language.startswith("pt")
                else " Internal revision: the figures were updated."
            )
            target.text = target.text + suffix
        near_blocks.append(
            Block(
                block_id=f"b-near-{ordinal:02d}",
                kind="paragraph",
                text=(
                    f"Nota de revisão {ordinal:02d}: este documento incorpora "
                    "alterações internas face à versão original."
                    if source.language.startswith("pt")
                    else f"Revision note {ordinal:02d}: this document "
                    "incorporates internal changes against the original."
                ),
            )
        )
        near_doc.duplicate_cluster_ids = sorted(
            set(near_doc.duplicate_cluster_ids) | {cluster}
        )
        near_doc.byte_copy_of = None
        near_doc.version_group_id = None
        near_doc.version_number = None
        near_doc.is_latest = None
        near_doc.version_changes = None
        source.duplicate_cluster_ids = sorted(
            set(source.duplicate_cluster_ids) | {cluster}
        )
        documents.append(near_doc)
        clusters.append(
            {
                "cluster_id": cluster,
                "kind": "near_duplicate",
                "canonical_document_id": source.doc_id,
                "member_document_ids": sorted([source.doc_id, near_id]),
            }
        )

    # Version groups: ordered chain, distinct IDs, explicit changed passages.
    versions: list[dict[str, Any]] = []
    version_formats = ("docx", "pdf", "md", "txt", "rtf", "odt", "html", "epub")
    for group in range(injection["version_groups"]):
        template = text_templates[(base_count + group) % len(text_templates)]
        fmt = version_formats[group % len(version_formats)]
        if _is_non_latin(str(template.data["language"])):
            fmt = "txt"
        work = compose_work(template, base_count + group, seed, format_hint=fmt)
        group_id = f"ver-group-{group + 1:02d}"
        v1_id = f"doc-version-{group + 1:02d}-v1"
        v2_id = f"doc-version-{group + 1:02d}-v2"
        folder = _safe_folder(str(template.data["folder"]))
        v1_path = paths.take(
            f"files/documents/{folder}/versoes/{_safe_filename(work.title + ' (v1)', EXTENSIONS[fmt])}"
        )
        v2_path = paths.take(
            f"files/documents/{folder}/versoes/{_safe_filename(work.title + ' (v2)', EXTENSIONS[fmt])}"
        )
        v1 = _document(
            work,
            doc_id=v1_id,
            fmt=fmt,
            relative_path=v1_path,
            profile=profile,
            seed=seed,
            start=start,
            end=end,
        )
        v2 = copy.deepcopy(v1)
        v2.doc_id = v2_id
        v2.relative_path = v2_path
        v2.blocks = copy.deepcopy(v1.blocks)
        modified = 0
        for block in v2.blocks:
            if block.kind == "paragraph" and modified < 2:
                block.text = block.text + (
                    " Cláusula revista em assembleia."
                    if v2.language.startswith("pt")
                    else " Clause revised at the general meeting."
                )
                modified += 1
        v2.blocks.append(
            Block(
                block_id=f"b-add-{group + 1:02d}",
                kind="paragraph",
                text=(
                    "Novo anexo: o prazo de renovação passa a ser trimestral."
                    if v2.language.startswith("pt")
                    else "New annex: the renewal period becomes quarterly."
                ),
            )
        )
        v1.duplicate_cluster_ids = sorted(
            set(v1.duplicate_cluster_ids) | {group_id}
        )
        v2.duplicate_cluster_ids = sorted(
            set(v2.duplicate_cluster_ids) | {group_id}
        )
        v1.version_group_id = group_id
        v2.version_group_id = group_id
        v1.version_number = 1
        v2.version_number = 2
        v1.is_latest = False
        v2.is_latest = True
        v1.version_changes = []
        v1_ids = {block.block_id: block for block in v1.blocks}
        v2_ids = {block.block_id: block for block in v2.blocks}
        changes: list[dict[str, Any]] = [
            {
                "change": "added",
                "from_passage_id": None,
                "to_passage_id": f"{v2_id}:p:{block.block_id}",
            }
            for block in v2.blocks
            if block.block_id not in v1_ids
        ]
        changes.extend(
            {
                "change": "removed",
                "from_passage_id": f"{v1_id}:p:{block.block_id}",
                "to_passage_id": None,
            }
            for block in v1.blocks
            if block.block_id not in v2_ids
        )
        changes.extend(
            {
                "change": "modified",
                "from_passage_id": f"{v1_id}:p:{block.block_id}",
                "to_passage_id": f"{v2_id}:p:{block.block_id}",
            }
            for block in v1.blocks
            if block.block_id in v2_ids
            and block.text != v2_ids[block.block_id].text
        )
        v2.version_changes = changes
        documents.extend([v1, v2])
        versions.append(
            {
                "version_group_id": group_id,
                "members": [
                    {
                        "document_id": v1_id,
                        "version_number": 1,
                        "is_latest": False,
                        "changed_passages": [],
                    },
                    {
                        "document_id": v2_id,
                        "version_number": 2,
                        "is_latest": True,
                        "changed_passages": changes,
                    },
                ],
            }
        )
        clusters.append(
            {
                "cluster_id": group_id,
                "kind": "version",
                "canonical_document_id": v1_id,
                "member_document_ids": sorted([v1_id, v2_id]),
            }
        )

    # Boilerplate: exactly the configured number of receiving documents. The
    # receivers are chosen from base documents that no injected copy reuses, so
    # the realized count is exactly the profile count.
    used_sources = {
        doc.doc_id
        for doc in (
            byte_sources + text_sources + scan_sources + near_sources
        )
    }
    candidates = [
        doc
        for doc in ordered_base
        if doc.doc_id not in used_sources
        and not doc.is_code
        and doc.format not in ("xlsx", "pptx")
    ]
    _require(
        len(candidates) >= injection["boilerplate_documents"],
        "not enough base documents left for boilerplate injection",
    )
    receivers = candidates[: injection["boilerplate_documents"]]
    family_names = sorted(families)
    for ordinal, document in enumerate(receivers):
        first = family_names[ordinal % len(family_names)]
        second = family_names[(ordinal + 1) % len(family_names)]
        header_text = families[first][ordinal % len(families[first])]
        footer_text = families[second][(ordinal + 2) % len(families[second])]
        document.blocks.insert(
            0,
            Block(
                block_id="b-0000-h",
                kind="paragraph",
                text=header_text,
                boilerplate_family_id=first,
            ),
        )
        document.blocks.append(
            Block(
                block_id="b-9999-f",
                kind="paragraph",
                text=footer_text,
                boilerplate_family_id=second,
            )
        )

    realized = {
        "exact_byte_copies": len(byte_sources),
        "exact_text_copies": len(text_sources),
        "scanned_variants": len(scan_sources),
        "near_duplicate_documents": len(near_sources),
        "version_groups": len(versions),
        "boilerplate_documents": len(receivers),
    }
    for key, expected in injection.items():
        if realized[key] != expected:
            raise SdcError(
                PROFILE_INVALID,
                f"injection {key} realized {realized[key]}, expected {expected}",
                file=profile.path.name,
                field=f"injection.{key}",
            )

    seen: set[str] = set()
    for document in documents:
        if document.doc_id in seen:
            raise SdcError(
                PROFILE_INVALID,
                f"duplicate document ID {document.doc_id}",
                file=profile.path.name,
            )
        seen.add(document.doc_id)

    return Plan(
        profile=profile,
        seed=seed,
        documents=documents,
        clusters=sorted(clusters, key=lambda row: row["cluster_id"]),
        versions=sorted(versions, key=lambda row: row["version_group_id"]),
        source_sets={key: source_sets[key] for key in profile.source_set_ids},
        templates=chosen,
        boilerplate_families=families,
        scan_recipes={key: recipes[key] for key in profile.scan_recipes},
        renderer_lock_sha256=lock_sha,
        injection_counts=realized,
        code_documents=code_count,
    )
