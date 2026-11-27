"""EPUB 3 renderer (independent reader until WP-3.4)."""

from __future__ import annotations

from html import escape

from .. import derive
from ..canonical import Document
from .zipfmt import build_zip

_XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>\n'


def _xhtml(title: str, language: str, body: str) -> str:
    return (
        _XML_DECL
        + "<!DOCTYPE html>\n"
        + '<html xmlns="http://www.w3.org/1999/xhtml" '
        f'xmlns:epub="http://www.idpf.org/2007/ops" lang="{escape(language, quote=True)}" '
        f'xml:lang="{escape(language, quote=True)}">\n'
        "<head>\n"
        '<meta charset="utf-8"/>\n'
        f"<title>{escape(title, quote=False)}</title>\n"
        "</head>\n"
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def _body(doc: Document) -> str:
    parts: list[str] = []
    for block in doc.blocks:
        text = escape(block.text, quote=False)
        if block.kind == "heading":
            parts.append(f"<h2>{text}</h2>")
        elif block.kind == "list_item":
            parts.append(f"<p>• {text}</p>")
        elif block.kind == "code":
            parts.append(f"<pre><code>{text}</code></pre>")
        else:
            parts.append(f"<p>{text}</p>")
    return "\n".join(parts)


def render_epub(doc: Document) -> bytes:
    identifier = derive.uuid4_like("sdc-epub", doc.doc_id)
    modified = doc.modified_at
    nav = _xhtml(
        doc.title,
        doc.language,
        '<nav epub:type="toc" id="toc"><h1>'
        + escape(doc.title, quote=False)
        + '</h1><ol><li><a href="chapter1.xhtml">'
        + escape(doc.title, quote=False)
        + "</a></li></ol></nav>",
    )
    chapter = _xhtml(doc.title, doc.language, _body(doc))
    content_opf = (
        _XML_DECL
        + '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="pub-id">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'<dc:identifier id="pub-id">urn:uuid:{identifier}</dc:identifier>\n'
        f"<dc:title>{escape(doc.title, quote=False)}</dc:title>\n"
        f"<dc:language>{escape(doc.language, quote=False)}</dc:language>\n"
        "<dc:creator>Seeky SDC</dc:creator>\n"
        f'<meta property="dcterms:modified">{modified}</meta>\n'
        "</metadata>\n"
        "<manifest>\n"
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>\n'
        '<item id="chapter1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>\n'
        "</manifest>\n"
        '<spine><itemref idref="chapter1"/></spine>\n'
        "</package>\n"
    )
    container = (
        _XML_DECL
        + '<container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        "<rootfiles>"
        '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
        "</rootfiles></container>"
    )
    return build_zip(
        [
            ("mimetype", b"application/epub+zip"),
            ("META-INF/container.xml", container.encode("utf-8")),
            ("OEBPS/content.opf", content_opf.encode("utf-8")),
            ("OEBPS/nav.xhtml", nav.encode("utf-8")),
            ("OEBPS/chapter1.xhtml", chapter.encode("utf-8")),
        ],
        mimetype="application/epub+zip",
    )
