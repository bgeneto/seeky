"""Canonical block model, passages, and extraction truth (SPEC-0004 section 4.3).

Canonical text is NFC with LF newlines. Passages are exact UTF-8 byte substrings
of that text, independent of any engine chunking recipe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .jsonio import canonical_json_bytes, nfc, sha256_bytes

BLOCK_KINDS = ("heading", "paragraph", "list_item", "table_cell", "code")
PASSAGE_KINDS = ("heading", "paragraph", "list_item", "table_cell", "code", "page", "context")
FORMATS = (
    "pdf",
    "scanned-pdf",
    "scanned-image",
    "docx",
    "xlsx",
    "pptx",
    "odt",
    "rtf",
    "html",
    "epub",
    "eml",
    "md",
    "txt",
    "code",
)

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "scanned-pdf": "application/pdf",
    "scanned-image": "image/png",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "rtf": "application/rtf",
    "html": "text/html",
    "epub": "application/epub+zip",
    "eml": "message/rfc822",
    "md": "text/markdown",
    "txt": "text/plain",
    "code": "text/plain",
}

EXTENSIONS = {
    "pdf": ".pdf",
    "scanned-pdf": ".pdf",
    "scanned-image": ".png",
    "docx": ".docx",
    "xlsx": ".xlsx",
    "pptx": ".pptx",
    "odt": ".odt",
    "rtf": ".rtf",
    "html": ".html",
    "epub": ".epub",
    "eml": ".eml",
    "md": ".md",
    "txt": ".txt",
}

SEPARATOR = "\n\n"


@dataclass
class Block:
    block_id: str
    kind: str
    text: str
    locator: dict[str, Any] = field(default_factory=dict)
    boilerplate_family_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in BLOCK_KINDS:
            raise ValueError(f"unknown block kind {self.kind!r}")
        self.text = nfc(self.text)
        if not self.text:
            raise ValueError(f"empty block {self.block_id}")
        if "\r" in self.text:
            raise ValueError(f"block {self.block_id} contains CR")


@dataclass
class Passage:
    passage_id: str
    document_id: str
    text: str
    start_utf8: int
    end_utf8: int
    text_sha256: str
    kind: str
    locator: dict[str, Any]
    boilerplate_family_id: str | None

    def as_record(self) -> dict[str, Any]:
        return {
            "_id": self.passage_id,
            "document_id": self.document_id,
            "text": self.text,
            "start_utf8": self.start_utf8,
            "end_utf8": self.end_utf8,
            "text_sha256": self.text_sha256,
            "kind": self.kind,
            "locator": self.locator,
            "boilerplate_family_id": self.boilerplate_family_id,
        }


@dataclass
class Document:
    doc_id: str
    title: str
    language: str
    languages: tuple[str, ...]
    format: str
    file_class: str
    relative_path: str
    source_set_id: str
    source_item_id: str
    source_sha256: str
    render_recipe_id: str
    modified_at: str
    blocks: list[Block]
    duplicate_cluster_ids: list[str] = field(default_factory=list)
    version_group_id: str | None = None
    version_number: int | None = None
    is_latest: bool | None = None
    scan_recipe: str | None = None
    scan_options: dict[str, Any] | None = None
    version_changes: list[dict[str, Any]] | None = None
    byte_copy_of: str | None = None

    # Filled by the layout step; never part of the identity.
    block_pages: dict[str, int] = field(default_factory=dict)
    page_texts: dict[int, str] = field(default_factory=dict)
    block_slides: dict[str, int] = field(default_factory=dict)
    slide_texts: dict[int, str] = field(default_factory=dict)
    sheet_texts: dict[str, str] = field(default_factory=dict)
    source_text: str | None = None

    @property
    def media_type(self) -> str:
        return MEDIA_TYPES[self.format]

    @property
    def text(self) -> str:
        return SEPARATOR.join(block.text for block in self.blocks)

    @property
    def text_sha256(self) -> str:
        return sha256_bytes(self.text.encode("utf-8"))

    @property
    def is_code(self) -> bool:
        return self.file_class == "source_code"

    def passages(self) -> list[Passage]:
        text = self.text
        passages: list[Passage] = []
        offset = 0
        previous_end = -1
        for block in self.blocks:
            encoded_length = len(block.text.encode("utf-8"))
            if offset < previous_end:
                raise ValueError(f"overlapping passages in {self.doc_id}")
            passage_text = text.encode("utf-8")[offset : offset + encoded_length]
            if passage_text.decode("utf-8") != block.text:
                raise ValueError(f"passage offset drift in {self.doc_id}/{block.block_id}")
            locator = dict(block.locator)
            locator["block_id"] = block.block_id
            passages.append(
                Passage(
                    passage_id=f"{self.doc_id}:p:{block.block_id}",
                    document_id=self.doc_id,
                    text=block.text,
                    start_utf8=offset,
                    end_utf8=offset + encoded_length,
                    text_sha256=sha256_bytes(block.text.encode("utf-8")),
                    kind=block.kind,
                    locator=locator,
                    boilerplate_family_id=block.boilerplate_family_id,
                )
            )
            previous_end = offset + encoded_length
            offset += encoded_length + len(SEPARATOR.encode("utf-8"))
        return passages

    def extraction_units(self) -> list[dict[str, Any]]:
        """Return one truth row per document locator unit (section 4.3)."""

        units: list[dict[str, Any]] = []
        if self.format in ("pdf", "scanned-pdf", "scanned-image"):
            for page in sorted(self.page_texts):
                units.append(
                    {
                        "document_id": self.doc_id,
                        "locator": {"page": page},
                        "text": self.page_texts[page],
                        "text_sha256": sha256_bytes(self.page_texts[page].encode("utf-8")),
                        "truth_origin": "generator-known",
                    }
                )
            return units
        if self.format == "pptx":
            for slide in sorted(self.slide_texts):
                units.append(
                    {
                        "document_id": self.doc_id,
                        "locator": {"slide": slide},
                        "text": self.slide_texts[slide],
                        "text_sha256": sha256_bytes(self.slide_texts[slide].encode("utf-8")),
                        "truth_origin": "generator-known",
                    }
                )
            return units
        if self.format == "xlsx":
            for sheet in sorted(self.sheet_texts):
                units.append(
                    {
                        "document_id": self.doc_id,
                        "locator": {"sheet": sheet},
                        "text": self.sheet_texts[sheet],
                        "text_sha256": sha256_bytes(self.sheet_texts[sheet].encode("utf-8")),
                        "truth_origin": "generator-known",
                    }
                )
            return units
        for block in self.blocks:
            locator = dict(block.locator)
            locator["block_id"] = block.block_id
            units.append(
                {
                    "document_id": self.doc_id,
                    "locator": locator,
                    "text": block.text,
                    "text_sha256": sha256_bytes(block.text.encode("utf-8")),
                    "truth_origin": "generator-known",
                }
            )
        return units

    def corpus_record(self) -> dict[str, Any]:
        return {
            "_id": self.doc_id,
            "title": self.title,
            "text": self.text,
            "metadata": {
                "relative_path": self.relative_path,
                "media_type": self.media_type,
                "format": self.format,
                "languages": list(self.languages),
                "file_class": self.file_class,
                "source_set_id": self.source_set_id,
                "source_item_id": self.source_item_id,
                "source_sha256": self.source_sha256,
                "content_sha256": "",  # filled by the builder
                "text_sha256": self.text_sha256,
                "byte_count": 0,  # filled by the builder
                "modified_at": self.modified_at,
                "render_recipe_id": self.render_recipe_id,
                "duplicate_cluster_ids": sorted(self.duplicate_cluster_ids),
                "version_group_id": self.version_group_id,
                "version_number": self.version_number,
                "is_latest": self.is_latest,
                "boilerplate_family_ids": sorted(
                    {
                        block.boilerplate_family_id
                        for block in self.blocks
                        if block.boilerplate_family_id
                    }
                ),
            },
        }


def sort_key_locator(locator: dict[str, Any]) -> str:
    return canonical_json_bytes(locator).decode("utf-8")


def sort_key_truth(row: dict[str, Any]) -> tuple[str, str]:
    return (row["document_id"], sort_key_locator(row["locator"]))


def sort_key_passage(passage: Passage) -> tuple[int, int, str]:
    return (passage.start_utf8, passage.end_utf8, passage.passage_id)
