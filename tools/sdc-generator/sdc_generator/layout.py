"""Deterministic layout: pages, slides, sheets, code line locators.

Passages and extraction truth use the same layout as the renderer, so a block's
locator identifies the output unit it was rendered into.
"""

from __future__ import annotations

from typing import Any

from .canonical import Document
from .errors import RENDER_FAILED, SdcError

PDF_LINE_WIDTH = 88
PDF_LINES_PER_PAGE = 44
SCAN_LINE_WIDTH = 62
SCAN_LINES_PER_PAGE = 44
PPTX_BLOCKS_PER_SLIDE = 5


def wrap_text(text: str, width: int) -> list[str]:
    """Greedy word wrap that preserves every character of the block text."""

    lines: list[str] = []
    for raw_line in text.split("\n"):
        if raw_line == "":
            lines.append("")
            continue
        words = raw_line.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if len(candidate) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = word
            else:
                current = word
            while len(current) > width:
                lines.append(current[:width])
                current = current[width:]
        lines.append(current)
    return lines


def layout_pdf(doc: Document) -> dict[str, Any]:
    page_lines: dict[int, list[str]] = {}
    line_number = 0
    for block in doc.blocks:
        lines = wrap_text(block.text, PDF_LINE_WIDTH)
        doc.block_pages[block.block_id] = line_number // PDF_LINES_PER_PAGE + 1
        for line in lines:
            page = line_number // PDF_LINES_PER_PAGE + 1
            page_lines.setdefault(page, []).append(line)
            line_number += 1
        # A blank line separates blocks, matching the canonical separator.
        page = line_number // PDF_LINES_PER_PAGE + 1
        page_lines.setdefault(page, []).append("")
        line_number += 1
    doc.page_texts = {
        page: "\n".join(lines).rstrip("\n") for page, lines in page_lines.items()
    }
    for block in doc.blocks:
        block.locator["page"] = doc.block_pages[block.block_id]
    return {"pages": max(doc.page_texts) if doc.page_texts else 1}


def layout_scan(doc: Document, *, lines_per_page: int = SCAN_LINES_PER_PAGE) -> dict[str, Any]:
    page_lines: dict[int, list[str]] = {}
    line_number = 0
    for block in doc.blocks:
        lines = wrap_text(block.text, SCAN_LINE_WIDTH)
        doc.block_pages[block.block_id] = line_number // lines_per_page + 1
        for line in lines:
            page = line_number // lines_per_page + 1
            page_lines.setdefault(page, []).append(line)
            line_number += 1
        page = line_number // lines_per_page + 1
        page_lines.setdefault(page, []).append("")
        line_number += 1
    if len(page_lines) > 1:
        raise SdcError(
            RENDER_FAILED,
            f"scanned fixture {doc.doc_id} does not fit one page",
            file=doc.relative_path,
        )
    doc.page_texts = {
        page: "\n".join(lines).rstrip("\n") for page, lines in page_lines.items()
    }
    for block in doc.blocks:
        block.locator["page"] = doc.block_pages[block.block_id]
    return {"pages": 1}


def layout_pptx(doc: Document) -> dict[str, Any]:
    slide = 1
    slide_blocks: dict[int, list[str]] = {1: []}
    for index, block in enumerate(doc.blocks):
        if index and index % PPTX_BLOCKS_PER_SLIDE == 0:
            slide += 1
            slide_blocks[slide] = []
        doc.block_slides[block.block_id] = slide
        block.locator["slide"] = slide
        slide_blocks[slide].append(block.text)
    doc.slide_texts = {
        number: "\n".join(texts) for number, texts in slide_blocks.items()
    }
    return {"slides": slide}


def layout_xlsx(doc: Document) -> dict[str, Any]:
    sheets: dict[str, dict[int, dict[int, str]]] = {}
    for block in doc.blocks:
        sheet = str(block.locator["sheet"])
        row = int(block.locator["row"])
        column = int(block.locator["column"])
        sheets.setdefault(sheet, {}).setdefault(row, {})[column] = block.text
    doc.sheet_texts = {}
    for sheet, rows in sheets.items():
        lines: list[str] = []
        for row in sorted(rows):
            cells = [rows[row][column] for column in sorted(rows[row])]
            lines.append("\t".join(cells))
        doc.sheet_texts[sheet] = f"# Sheet: {sheet}\n" + "\n".join(lines)
    return {"sheets": sorted(doc.sheet_texts)}


def layout_code(doc: Document) -> dict[str, Any]:
    line = 1
    for block in doc.blocks:
        count = block.text.count("\n") + 1
        block.locator["line_start"] = line
        block.locator["line_end"] = line + count - 1
        line += count + 1  # one blank separator line
    return {"lines": line - 1}


def apply_layout(doc: Document) -> None:
    if doc.format in ("pdf", "scanned-pdf", "scanned-image"):
        if doc.format == "pdf":
            layout_pdf(doc)
        else:
            layout_scan(doc)
        return
    if doc.format == "pptx":
        layout_pptx(doc)
        return
    if doc.format == "xlsx":
        layout_xlsx(doc)
        return
    if doc.format == "code":
        layout_code(doc)
        return
    # Block-level locators are already assigned where the format needs them.
