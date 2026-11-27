"""Renderer dispatch and deterministic format writers."""

from __future__ import annotations

from ..canonical import Document
from ..errors import UNSUPPORTED, SdcError

# Imported lazily per format to keep import cost low and dependencies explicit.


def render(doc: Document) -> bytes:
    if doc.format == "txt":
        from .text import render_txt

        return render_txt(doc)
    if doc.format == "md":
        from .text import render_md

        return render_md(doc)
    if doc.format == "html":
        from .html import render_html

        return render_html(doc)
    if doc.format == "eml":
        from .eml import render_eml

        return render_eml(doc)
    if doc.format == "rtf":
        from .rtf import render_rtf

        return render_rtf(doc)
    if doc.format == "docx":
        from .ooxml import render_docx

        return render_docx(doc)
    if doc.format == "xlsx":
        from .ooxml import render_xlsx

        return render_xlsx(doc)
    if doc.format == "pptx":
        from .ooxml import render_pptx

        return render_pptx(doc)
    if doc.format == "odt":
        from .odf import render_odt

        return render_odt(doc)
    if doc.format == "epub":
        from .epub import render_epub

        return render_epub(doc)
    if doc.format == "pdf":
        from .pdf import render_pdf

        return render_pdf(doc)
    if doc.format in ("scanned-pdf", "scanned-image"):
        from .scan import render_scanned_image, render_scanned_pdf

        if doc.format == "scanned-image":
            return render_scanned_image(doc)
        return render_scanned_pdf(doc)
    if doc.format == "code":
        from .text import render_code

        return render_code(doc)
    raise SdcError(UNSUPPORTED, f"no renderer for format {doc.format!r}")
