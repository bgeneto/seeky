"""DOCX, XLSX, and PPTX renderers with deterministic package metadata."""

from __future__ import annotations

from html import escape

from ..canonical import Document
from .zipfmt import build_zip

_XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _text(text: str) -> str:
    return escape(text, quote=False)


def _attr(text: str) -> str:
    return escape(text, quote=True)


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def _docx_paragraph(text: str, style: str | None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return (
        f"<w:p>{ppr}<w:r><w:t xml:space=\"preserve\">{_text(text)}</w:t></w:r></w:p>"
    )


def render_docx(doc: Document) -> bytes:
    body: list[str] = []
    for block in doc.blocks:
        if block.kind == "heading":
            body.append(_docx_paragraph(block.text, "Heading1"))
        elif block.kind == "list_item":
            body.append(_docx_paragraph(block.text, "ListParagraph"))
        else:
            body.append(_docx_paragraph(block.text, None))
    document_xml = (
        _XML_DECL
        + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<w:body>"
        + "".join(body)
        + "<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
        "</w:body></w:document>"
    )
    styles_xml = (
        _XML_DECL
        + '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1">'
        '<w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
        '<w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="ListParagraph">'
        '<w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/>'
        '<w:pPr><w:ind w:left="720"/></w:pPr></w:style>'
        "</w:styles>"
    )
    content_types = (
        _XML_DECL
        + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )
    root_rels = (
        _XML_DECL
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        _XML_DECL
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        "</Relationships>"
    )
    core_xml = (
        _XML_DECL
        + '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{_text(doc.title)}</dc:title>"
        "<dc:creator>Seeky SDC</dc:creator>"
        "<cp:lastModifiedBy>Seeky SDC</cp:lastModifiedBy>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{doc.modified_at}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{doc.modified_at}</dcterms:modified>'
        "</cp:coreProperties>"
    )
    app_xml = (
        _XML_DECL
        + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        "<Application>sdc-generator</Application></Properties>"
    )
    return build_zip(
        [
            ("[Content_Types].xml", content_types.encode("utf-8")),
            ("_rels/.rels", root_rels.encode("utf-8")),
            ("word/document.xml", document_xml.encode("utf-8")),
            ("word/styles.xml", styles_xml.encode("utf-8")),
            ("word/_rels/document.xml.rels", document_rels.encode("utf-8")),
            ("docProps/core.xml", core_xml.encode("utf-8")),
            ("docProps/app.xml", app_xml.encode("utf-8")),
        ]
    )


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------


def _column_letters(index: int) -> str:
    letters = ""
    value = index
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def render_xlsx(doc: Document) -> bytes:
    sheets: dict[str, dict[int, dict[int, str]]] = {}
    for block in doc.blocks:
        sheet = str(block.locator["sheet"])
        row = int(block.locator["row"])
        column = int(block.locator["column"])
        sheets.setdefault(sheet, {}).setdefault(row, {})[column] = block.text

    shared: list[str] = []
    shared_index: dict[str, int] = {}

    def shared_id(text: str) -> int:
        if text not in shared_index:
            shared_index[text] = len(shared)
            shared.append(text)
        return shared_index[text]

    sheet_entries: list[tuple[str, bytes]] = []
    for position, sheet in enumerate(sorted(sheets), start=1):
        rows_xml: list[str] = []
        for row in sorted(sheets[sheet]):
            cells_xml: list[str] = []
            for column in sorted(sheets[sheet][row]):
                reference = f"{_column_letters(column)}{row}"
                index = shared_id(sheets[sheet][row][column])
                cells_xml.append(f'<c r="{reference}" t="s"><v>{index}</v></c>')
            rows_xml.append(f'<row r="{row}">' + "".join(cells_xml) + "</row>")
        sheet_xml = (
            _XML_DECL
            + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData>"
            + "".join(rows_xml)
            + "</sheetData></worksheet>"
        )
        sheet_entries.append((f"xl/worksheets/sheet{position}.xml", sheet_xml.encode("utf-8")))

    sheet_names = sorted(sheets)
    sheet_list = "".join(
        f'<sheet name="{_attr(name)}" sheetId="{position}" r:id="rId{position}"/>'
        for position, name in enumerate(sheet_names, start=1)
    )
    workbook_xml = (
        _XML_DECL
        + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheet_list}</sheets></workbook>"
    )
    sheet_rels = "".join(
        f'<Relationship Id="rId{position}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{position}.xml"/>'
        for position in range(1, len(sheet_names) + 1)
    )
    text_rel_id = len(sheet_names) + 1
    style_rel_id = len(sheet_names) + 2
    workbook_rels = (
        _XML_DECL
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + sheet_rels
        + f'<Relationship Id="rId{text_rel_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
        'Target="sharedStrings.xml"/>'
        + f'<Relationship Id="rId{style_rel_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        "</Relationships>"
    )
    shared_xml = (
        _XML_DECL
        + '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared)}" uniqueCount="{len(shared)}">'
        + "".join(f"<si><t>{_text(text)}</t></si>" for text in shared)
        + "</sst>"
    )
    styles_xml = (
        _XML_DECL
        + '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        "</styleSheet>"
    )
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{position}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for position in range(1, len(sheet_names) + 1)
    )
    content_types = (
        _XML_DECL
        + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + overrides
        + '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        "</Types>"
    )
    root_rels = (
        _XML_DECL
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        "</Relationships>"
    )
    core_xml = (
        _XML_DECL
        + '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{_text(doc.title)}</dc:title>"
        "<dc:creator>Seeky SDC</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{doc.modified_at}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{doc.modified_at}</dcterms:modified>'
        "</cp:coreProperties>"
    )
    return build_zip(
        [
            ("[Content_Types].xml", content_types.encode("utf-8")),
            ("_rels/.rels", root_rels.encode("utf-8")),
            ("xl/workbook.xml", workbook_xml.encode("utf-8")),
            ("xl/_rels/workbook.xml.rels", workbook_rels.encode("utf-8")),
            ("xl/sharedStrings.xml", shared_xml.encode("utf-8")),
            ("xl/styles.xml", styles_xml.encode("utf-8")),
            ("docProps/core.xml", core_xml.encode("utf-8")),
            *sheet_entries,
        ]
    )


# ---------------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------------

_THEME_XML = (
    _XML_DECL
    + '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="SDC">'
    '<a:themeElements><a:clrScheme name="SDC">'
    '<a:dk1><a:srgbClr val="000000"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>'
    '<a:dk2><a:srgbClr val="1F1F1F"/></a:dk2><a:lt2><a:srgbClr val="EFEFEF"/></a:lt2>'
    '<a:accent1><a:srgbClr val="1F4E79"/></a:accent1>'
    "</a:clrScheme>"
    '<a:fontScheme name="SDC"><a:majorFont><a:latin typeface="Calibri"/></a:majorFont>'
    '<a:minorFont><a:latin typeface="Calibri"/></a:minorFont></a:fontScheme>'
    '<a:fmtScheme name="SDC"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
    "<a:lnStyleLst><a:ln/></a:lnStyleLst>"
    "<a:effectStyleLst><a:effectStyle/></a:effectStyleLst>"
    "<a:bgFillStyleLst><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill></a:bgFillStyleLst>"
    "</a:fmtScheme></a:themeElements></a:theme>"
)


def _slide_xml(blocks) -> bytes:
    shapes: list[str] = []
    y = 600000
    for index, block in enumerate(blocks, start=1):
        size = 2800 if block.kind == "heading" else 1800
        shapes.append(
            "<p:sp><p:nvSpPr>"
            f'<p:cNvPr id="{index + 1}" name="TextBox {index}"/>'
            '<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="600000" y="{y}"/>'
            '<a:ext cx="7800000" cy="500000"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" sz="{size}"/>'
            f"<a:t>{_text(block.text)}</a:t></a:r></a:p></p:txBody></p:sp>"
        )
        y += 600000
    xml = (
        _XML_DECL
        + '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        "<p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/>"
        + "".join(shapes)
        + "</p:spTree></p:cSld></p:sld>"
    )
    return xml.encode("utf-8")


def render_pptx(doc: Document) -> bytes:
    slides: dict[int, list] = {}
    for block in doc.blocks:
        slides.setdefault(int(block.locator["slide"]), []).append(block)
    slide_numbers = sorted(slides)
    entries: list[tuple[str, bytes]] = []
    for number in slide_numbers:
        entries.append((f"ppt/slides/slide{number}.xml", _slide_xml(slides[number])))
        rels = (
            _XML_DECL
            + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
            'Target="../slideLayouts/slideLayout1.xml"/>'
            "</Relationships>"
        )
        entries.append((f"ppt/slides/_rels/slide{number}.xml.rels", rels.encode("utf-8")))

    slide_ids = "".join(
        f'<p:sldId id="{255 + number}" r:id="rId{number + 1}"/>'
        for number in slide_numbers
    )
    presentation_xml = (
        _XML_DECL
        + '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        f"<p:sldIdLst>{slide_ids}</p:sldIdLst>"
        '<p:sldSz cx="9144000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/>'
        "</p:presentation>"
    )
    presentation_rels = (
        _XML_DECL
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" '
        'Target="slideMasters/slideMaster1.xml"/>'
        + "".join(
            f'<Relationship Id="rId{number + 1}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
            f'Target="slides/slide{number}.xml"/>'
            for number in slide_numbers
        )
        + "</Relationships>"
    )
    master_xml = (
        _XML_DECL
        + '<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        "<p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/></p:spTree></p:cSld>"
        '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
        "</p:sldMaster>"
    )
    master_rels = (
        _XML_DECL
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
        'Target="../slideLayouts/slideLayout1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" '
        'Target="../theme/theme1.xml"/>'
        "</Relationships>"
    )
    layout_xml = (
        _XML_DECL
        + '<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank">'
        "<p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/></p:spTree></p:cSld>"
        "</p:sldLayout>"
    )
    layout_rels = (
        _XML_DECL
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" '
        'Target="../slideMasters/slideMaster1.xml"/>'
        "</Relationships>"
    )
    slide_overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{number}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for number in slide_numbers
    )
    content_types = (
        _XML_DECL
        + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/presentation.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        '<Override PartName="/ppt/theme/theme1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        + slide_overrides
        + '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        "</Types>"
    )
    root_rels = (
        _XML_DECL
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="ppt/presentation.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        "</Relationships>"
    )
    core_xml = (
        _XML_DECL
        + '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{_text(doc.title)}</dc:title>"
        "<dc:creator>Seeky SDC</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{doc.modified_at}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{doc.modified_at}</dcterms:modified>'
        "</cp:coreProperties>"
    )
    entries.extend(
        [
            ("[Content_Types].xml", content_types.encode("utf-8")),
            ("_rels/.rels", root_rels.encode("utf-8")),
            ("ppt/presentation.xml", presentation_xml.encode("utf-8")),
            ("ppt/_rels/presentation.xml.rels", presentation_rels.encode("utf-8")),
            ("ppt/slideMasters/slideMaster1.xml", master_xml.encode("utf-8")),
            ("ppt/slideMasters/_rels/slideMaster1.xml.rels", master_rels.encode("utf-8")),
            ("ppt/slideLayouts/slideLayout1.xml", layout_xml.encode("utf-8")),
            ("ppt/slideLayouts/_rels/slideLayout1.xml.rels", layout_rels.encode("utf-8")),
            ("ppt/theme/theme1.xml", _THEME_XML.encode("utf-8")),
            ("docProps/core.xml", core_xml.encode("utf-8")),
        ]
    )
    return build_zip(entries)
