"""Plain-text, Markdown, and source-code renderers."""

from __future__ import annotations

from ..canonical import Document


def render_txt(doc: Document) -> bytes:
    return (doc.text + "\n").encode("utf-8")


def render_code(doc: Document) -> bytes:
    return (doc.text + "\n").encode("utf-8")


def render_md(doc: Document) -> bytes:
    lines: list[str] = []
    for block in doc.blocks:
        if block.kind == "heading":
            lines.append(f"# {block.text}")
        elif block.kind == "list_item":
            lines.append(f"- {block.text}")
        elif block.kind == "code":
            lines.append("```")
            lines.append(block.text)
            lines.append("```")
        elif block.kind == "table_cell":
            lines.append(f"| {block.text} |")
        else:
            lines.append(block.text)
        lines.append("")
    return ("\n".join(lines).rstrip("\n") + "\n").encode("utf-8")
