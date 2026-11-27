"""HTML renderer."""

from __future__ import annotations

from html import escape

from ..canonical import Document


def _body(doc: Document) -> str:
    parts: list[str] = []
    list_open = False
    for block in doc.blocks:
        if block.kind == "list_item":
            if not list_open:
                parts.append("<ul>")
                list_open = True
            parts.append(f"<li>{escape(block.text, quote=False)}</li>")
            continue
        if list_open:
            parts.append("</ul>")
            list_open = False
        text = escape(block.text, quote=False)
        if block.kind == "heading":
            parts.append(f"<h2>{text}</h2>")
        elif block.kind == "code":
            parts.append(f"<pre><code>{text}</code></pre>")
        elif block.kind == "table_cell":
            parts.append(f"<p>{text}</p>")
        else:
            parts.append(f"<p>{text}</p>")
    if list_open:
        parts.append("</ul>")
    return "\n".join(parts)


def render_html(doc: Document) -> bytes:
    title = escape(doc.title, quote=False)
    language = escape(doc.language, quote=True)
    document = (
        "<!DOCTYPE html>\n"
        f'<html lang="{language}">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{title}</title>\n"
        "</head>\n"
        "<body>\n"
        f"{_body(doc)}\n"
        "</body>\n"
        "</html>\n"
    )
    return document.encode("utf-8")
