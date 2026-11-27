"""Minimal deterministic text PDF writer (no current-date fields)."""

from __future__ import annotations

from .. import derive
from ..canonical import Document


def _pdf_string(text: str) -> bytes:
    try:
        raw = text.encode("cp1252")
    except UnicodeEncodeError:
        raw = text.encode("cp1252", errors="replace")
    out = bytearray()
    for byte in raw:
        if byte in (0x28, 0x29, 0x5C):  # ( ) backslash
            out.append(0x5C)
            out.append(byte)
        elif byte < 32:
            out.append(0x20)
        else:
            out.append(byte)
    return bytes(out)


def _content_stream(page_text: str) -> bytes:
    lines = page_text.split("\n")
    parts: list[bytes] = [b"BT\n/F1 10 Tf\n12 TL\n50 790 Td\n"]
    for index, line in enumerate(lines):
        if index:
            parts.append(b"T*\n")
        if line:
            parts.append(b"(" + _pdf_string(line) + b") Tj\n")
    parts.append(b"ET\n")
    return b"".join(parts)


def _info(doc: Document) -> bytes:
    return (
        b"<< /Title (" + _pdf_string(doc.title) + b") /Producer (Seeky SDC) >>"
    )


def render_pdf(doc: Document) -> bytes:
    pages = sorted(doc.page_texts)
    if not pages:
        pages = [1]
    font_number = 3
    objects: dict[int, bytes] = {}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    page_numbers = list(range(4, 4 + 2 * len(pages), 2))
    kids = " ".join(f"{number} 0 R" for number in page_numbers)
    objects[2] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii")
    )
    objects[font_number] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )
    for index, page in enumerate(pages):
        page_number = page_numbers[index]
        content_number = page_number + 1
        objects[page_number] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_number} 0 R >> >> "
            f"/Contents {content_number} 0 R >>"
        ).encode("ascii")
        stream = _content_stream(doc.page_texts.get(page, ""))
        objects[content_number] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"endstream"
        )
    info_number = max(objects) + 1
    objects[info_number] = _info(doc)

    buffer = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(buffer)
        buffer.extend(f"{number} 0 obj\n".encode("ascii"))
        buffer.extend(objects[number])
        buffer.extend(b"\nendobj\n")
    xref_offset = len(buffer)
    size = max(objects) + 1
    buffer.extend(f"xref\n0 {size}\n".encode("ascii"))
    buffer.extend(b"0000000000 65535 f \n")
    for number in range(1, size):
        offset = offsets.get(number)
        if offset is None:
            buffer.extend(b"0000000000 00000 f \n")
        else:
            buffer.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    identifier = derive.digest_hex("sdc-pdf", "file-id", doc.doc_id)[:32]
    buffer.extend(
        (
            f"trailer\n<< /Size {size} /Root 1 0 R /Info {info_number} 0 R "
            f"/ID [<{identifier}> <{identifier}>] >>\nstartxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(buffer)
