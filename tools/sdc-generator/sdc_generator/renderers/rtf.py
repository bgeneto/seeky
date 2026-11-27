"""RTF renderer (independent reader until WP-3.4, SPEC-0004 section 5.1)."""

from __future__ import annotations

from ..canonical import Document


def _escape_rtf(text: str) -> str:
    out: list[str] = []
    for char in text:
        code = ord(char)
        if char == "\\":
            out.append("\\\\")
        elif char == "{":
            out.append("\\{")
        elif char == "}":
            out.append("\\}")
        elif char == "\n":
            out.append("\\par\n")
        elif char == "\t":
            out.append("\\tab ")
        elif 32 <= code < 127:
            out.append(char)
        else:
            # UTF-16 code unit with a '?' fallback for readers without Unicode.
            if code > 0xFFFF:
                code -= 0x10000
                high = 0xD800 + (code >> 10)
                low = 0xDC00 + (code & 0x3FF)
                out.append(f"\\u{high - 65536}?\\u{low - 65536}?")
            else:
                out.append(f"\\u{code - 65536 if code > 32767 else code}?")
    return "".join(out)


def render_rtf(doc: Document) -> bytes:
    paragraphs: list[str] = []
    for block in doc.blocks:
        prefix = ""
        if block.kind == "heading":
            prefix = "\\b "
        elif block.kind == "list_item":
            prefix = "\\li360 "
        paragraphs.append(f"\\pard{prefix}\\f0\\fs22 {_escape_rtf(block.text)}\\par")
    title = _escape_rtf(doc.title)
    body = (
        "{\\rtf1\\ansi\\ansicpg1252\\deff0\\deflang1033\n"
        "{\\fonttbl{\\f0\\fswiss Helvetica;}}\n"
        f"{{\\info{{\\title {title}}}{{\\author Seeky SDC}}}}\n"
        "\\viewkind4\\uc1\n"
        + "\n".join(paragraphs)
        + "\n}\n"
    )
    return body.encode("utf-8")
