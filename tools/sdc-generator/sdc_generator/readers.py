"""Independent, permissively licensed renderer readers for round-trip tests.

ODT, RTF, EPUB, and EML have no engine extractor until WP-3.4, so SPEC-0004
section 5.1 requires an independent reader here. The DOCX/XLSX/PPTX/HTML
readers below are deliberately minimal test oracles; the engine extractors are
exercised by the ``engine-roundtrip`` harness.
"""

from __future__ import annotations

import email
import zipfile
from email import policy
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


class _HTMLText(HTMLParser):
    _BLOCK = {
        "p",
        "div",
        "br",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "tr",
        "td",
        "th",
        "pre",
        "blockquote",
        "section",
        "article",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def read_html_text(data: bytes) -> str:
    parser = _HTMLText()
    parser.feed(data.decode("utf-8"))
    parser.close()
    return "".join(parser.parts)


def read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{{{_W_NS}}}p"):
        texts = [node.text or "" for node in paragraph.iter(f"{{{_W_NS}}}t")]
        paragraphs.append("".join(texts))
    return "\n".join(paragraphs)


def read_pptx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
        chunks: list[str] = []
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            texts = [node.text or "" for node in root.iter(f"{{{_A_NS}}}t")]
            chunks.append(" ".join(texts))
    return "\n".join(chunks)


def read_xlsx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = [
            "".join(node.text or "" for node in item.iter(f"{{{_S_NS}}}t"))
            for item in shared_root.iter(f"{{{_S_NS}}}si")
        ]
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        names = [
            sheet.attrib.get("name", "")
            for sheet in workbook.iter(f"{{{_S_NS}}}sheet")
        ]
        chunks: list[str] = []
        for index in range(1, len(names) + 1):
            sheet_root = ElementTree.fromstring(
                archive.read(f"xl/worksheets/sheet{index}.xml")
            )
            rows: list[str] = []
            for row in sheet_root.iter(f"{{{_S_NS}}}row"):
                cells: list[str] = []
                for cell in row.iter(f"{{{_S_NS}}}c"):
                    value = cell.find(f"{{{_S_NS}}}v")
                    if value is None or value.text is None:
                        continue
                    if cell.attrib.get("t") == "s":
                        cells.append(shared[int(value.text)])
                    else:
                        cells.append(value.text)
                if cells:
                    rows.append("\t".join(cells))
            chunks.append(f"# Sheet: {names[index - 1]}\n" + "\n".join(rows))
        return "\n".join(chunks)


def read_odt(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("content.xml"))
    lines: list[str] = []

    def visit(element) -> None:
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in ("h", "p"):
            text = "".join(element.itertext())
            lines.append(text)
        for child in element:
            visit(child)

    body = root.find(f".//{{{_OFFICE_NS}}}text")
    if body is not None:
        visit(body)
    return "\n".join(lines)


_RTF_SKIP = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer"}


def read_rtf(path: Path) -> str:
    data = path.read_bytes().decode("latin-1")
    out: list[str] = []
    skip_stack: list[bool] = []
    skip = False
    index = 0
    length = len(data)
    pending_unicode = 0
    while index < length:
        char = data[index]
        if char == "{":
            skip_stack.append(skip)
            index += 1
            continue
        if char == "}":
            skip = skip_stack.pop() if skip_stack else False
            index += 1
            continue
        if char == "\\":
            index += 1
            if index >= length:
                break
            next_char = data[index]
            if next_char in "\\{}":
                if not skip:
                    out.append(next_char)
                index += 1
                continue
            if next_char == "'":
                hex_text = data[index + 1 : index + 3]
                index += 3
                if not skip and len(hex_text) == 2:
                    out.append(bytes([int(hex_text, 16)]).decode("cp1252", errors="replace"))
                continue
            if next_char == "*":
                skip = True
                index += 1
                continue
            start = index
            while index < length and (data[index].isalpha() or data[index] == "-"):
                index += 1
            word = data[start:index]
            parameter = ""
            param_start = index
            while index < length and (data[index].isdigit() or data[index] == "-"):
                index += 1
            parameter = data[param_start:index]
            if index < length and data[index] == " ":
                index += 1
            if word in _RTF_SKIP:
                skip = True
                continue
            if skip:
                continue
            if word in ("par", "line", "sect", "page"):
                out.append("\n")
            elif word == "tab":
                out.append("\t")
            elif word == "u" and parameter:
                code = int(parameter)
                if code < 0:
                    code += 65536
                out.append(chr(code))
                pending_unicode = 1
            elif word == "uc" and parameter:
                pending_unicode = int(parameter)
            elif word == "bullet":
                out.append("* ")
            continue
        if pending_unicode:
            pending_unicode -= 1
            index += 1
            continue
        if not skip and char not in "\r\n":
            out.append(char)
        index += 1
    return "".join(out)


def _epub_text(data: bytes) -> str:
    parser = _HTMLText()
    parser.feed(data.decode("utf-8"))
    parser.close()
    return "".join(parser.parts)


def read_epub(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
        rootfile = None
        for element in container.iter():
            if element.tag.endswith("rootfile"):
                rootfile = element.attrib.get("full-path")
                break
        if rootfile is None:
            raise ValueError("EPUB has no rootfile")
        opf = ElementTree.fromstring(archive.read(rootfile))
        base = rootfile.rsplit("/", 1)[0] + "/" if "/" in rootfile else ""
        manifest = {}
        for element in opf.iter():
            if element.tag.endswith("item") and "id" in element.attrib:
                manifest[element.attrib["id"]] = element.attrib.get("href", "")
        spine: list[str] = []
        for element in opf.iter():
            if element.tag.endswith("itemref") and "idref" in element.attrib:
                spine.append(element.attrib["idref"])
        chunks: list[str] = []
        for idref in spine:
            href = manifest.get(idref)
            if href:
                chunks.append(_epub_text(archive.read(base + href)))
        return "\n".join(chunks)


def read_eml(path: Path) -> str:
    message = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                return part.get_content()
        for part in message.walk():
            if part.get_content_type() == "text/html":
                return read_html_text(part.get_payload(decode=True) or b"")
        return ""
    return str(message.get_content())


def read_rendered(doc_format: str, path: Path) -> str:
    if doc_format in ("txt", "md", "code"):
        return read_txt(path)
    if doc_format == "html":
        return read_html_text(path.read_bytes())
    if doc_format == "docx":
        return read_docx(path)
    if doc_format == "pptx":
        return read_pptx(path)
    if doc_format == "xlsx":
        return read_xlsx(path)
    if doc_format == "odt":
        return read_odt(path)
    if doc_format == "rtf":
        return read_rtf(path)
    if doc_format == "epub":
        return read_epub(path)
    if doc_format == "eml":
        return read_eml(path)
    if doc_format in ("pdf", "scanned-pdf", "scanned-image"):
        raise ValueError("PDF and scans are read through the engine (PDFium)")
    raise ValueError(f"no independent reader for {doc_format}")
