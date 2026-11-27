"""ODT renderer (independent reader until WP-3.4, SPEC-0004 section 5.1)."""

from __future__ import annotations

from html import escape

from ..canonical import Document
from .zipfmt import build_zip

_XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>\n'
_MIMETYPE = b"application/vnd.oasis.opendocument.text"


def _text(text: str) -> str:
    return escape(text, quote=False)


def _paragraphs(doc: Document) -> str:
    parts: list[str] = []
    list_open = False
    for block in doc.blocks:
        if block.kind == "list_item":
            if not list_open:
                parts.append("<text:list><text:list-item>")
                list_open = True
            parts.append(f"<text:p>{_text(block.text)}</text:p>")
            continue
        if list_open:
            parts.append("</text:list-item></text:list>")
            list_open = False
        if block.kind == "heading":
            parts.append(
                f'<text:h text:outline-level="1">{_text(block.text)}</text:h>'
            )
        elif block.kind == "code":
            parts.append(
                f'<text:p text:style-name="Preformatted_20_Text">{_text(block.text)}</text:p>'
            )
        else:
            parts.append(f"<text:p>{_text(block.text)}</text:p>")
    if list_open:
        parts.append("</text:list-item></text:list>")
    return "".join(parts)


def render_odt(doc: Document) -> bytes:
    content_xml = (
        _XML_DECL
        + '<office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
        'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
        'office:version="1.3">'
        "<office:automatic-styles>"
        '<style:style style:name="Preformatted_20_Text" style:family="paragraph">'
        '<style:text-properties style:font-name="Liberation Mono" fo:font-family="monospace"/>'
        "</style:style>"
        "</office:automatic-styles>"
        "<office:body><office:text>"
        + _paragraphs(doc)
        + "</office:text></office:body></office:document-content>"
    )
    styles_xml = (
        _XML_DECL
        + '<office:document-styles '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'office:version="1.3">'
        "<office:styles>"
        '<style:default-style style:family="paragraph"/>'
        "</office:styles></office:document-styles>"
    )
    meta_xml = (
        _XML_DECL
        + '<office:document-meta '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'office:version="1.3">'
        "<office:meta>"
        f"<dc:title>{_text(doc.title)}</dc:title>"
        "<meta:generator>sdc-generator</meta:generator>"
        f"<meta:creation-date>{doc.modified_at}</meta:creation-date>"
        "</office:meta></office:document-meta>"
    )
    manifest_xml = (
        _XML_DECL
        + '<manifest:manifest '
        'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
        'manifest:version="1.3">'
        '<manifest:file-entry manifest:full-path="/" '
        'manifest:version="1.3" manifest:media-type="application/vnd.oasis.opendocument.text"/>'
        '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
        '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>'
        '<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>'
        "</manifest:manifest>"
    )
    return build_zip(
        [
            ("mimetype", _MIMETYPE),
            ("content.xml", content_xml.encode("utf-8")),
            ("styles.xml", styles_xml.encode("utf-8")),
            ("meta.xml", meta_xml.encode("utf-8")),
            ("META-INF/manifest.xml", manifest_xml.encode("utf-8")),
        ],
        mimetype="application/vnd.oasis.opendocument.text",
    )
