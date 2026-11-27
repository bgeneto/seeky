"""Deterministic bilevel page rasterizer, PNG writer, and image-only PDF.

The scan recipes are pinned in ``bench/corpora/sdc/renderers.lock.json``. The
rasterizer uses a built-in 5x7 bitmap font (no external font asset), a
hardcoded fixed-point rotation table, and a deterministic speckle stream, so
the same recipe yields byte-identical images on every host.
"""

from __future__ import annotations

import zlib

from .. import derive
from ..canonical import Document

# 5x7 glyphs. Each row is a 5-bit mask; bit 4 is the leftmost pixel.
_GLYPHS: dict[str, tuple[int, ...]] = {
    " ": (0, 0, 0, 0, 0, 0, 0),
    "!": (4, 4, 4, 4, 4, 0, 4),
    '"': (10, 10, 10, 0, 0, 0, 0),
    "#": (10, 31, 10, 10, 31, 10, 0),
    "$": (4, 15, 20, 14, 5, 30, 4),
    "%": (24, 25, 2, 4, 8, 19, 3),
    "&": (12, 18, 20, 8, 21, 18, 13),
    "'": (4, 4, 8, 0, 0, 0, 0),
    "(": (2, 4, 8, 8, 8, 4, 2),
    ")": (8, 4, 2, 2, 2, 4, 8),
    "*": (0, 4, 21, 14, 21, 4, 0),
    "+": (0, 4, 4, 31, 4, 4, 0),
    ",": (0, 0, 0, 0, 4, 4, 8),
    "-": (0, 0, 0, 31, 0, 0, 0),
    ".": (0, 0, 0, 0, 0, 12, 12),
    "/": (1, 1, 2, 4, 8, 16, 16),
    "0": (14, 17, 19, 21, 25, 17, 14),
    "1": (4, 12, 4, 4, 4, 4, 14),
    "2": (14, 17, 1, 2, 4, 8, 31),
    "3": (31, 2, 4, 2, 1, 17, 14),
    "4": (2, 6, 10, 18, 31, 2, 2),
    "5": (31, 16, 30, 1, 1, 17, 14),
    "6": (6, 8, 16, 30, 17, 17, 14),
    "7": (31, 1, 2, 4, 8, 8, 8),
    "8": (14, 17, 17, 14, 17, 17, 14),
    "9": (14, 17, 17, 15, 1, 2, 12),
    ":": (0, 12, 12, 0, 12, 12, 0),
    ";": (0, 12, 12, 0, 4, 4, 8),
    "<": (2, 4, 8, 16, 8, 4, 2),
    "=": (0, 0, 31, 0, 31, 0, 0),
    ">": (8, 4, 2, 1, 2, 4, 8),
    "?": (14, 17, 1, 2, 4, 0, 4),
    "@": (14, 17, 1, 13, 21, 21, 14),
    "A": (14, 17, 17, 31, 17, 17, 17),
    "B": (30, 17, 17, 30, 17, 17, 30),
    "C": (14, 17, 16, 16, 16, 17, 14),
    "D": (30, 17, 17, 17, 17, 17, 30),
    "E": (31, 16, 16, 30, 16, 16, 31),
    "F": (31, 16, 16, 30, 16, 16, 16),
    "G": (14, 17, 16, 23, 17, 17, 15),
    "H": (17, 17, 17, 31, 17, 17, 17),
    "I": (14, 4, 4, 4, 4, 4, 14),
    "J": (7, 2, 2, 2, 2, 18, 12),
    "K": (17, 18, 20, 24, 20, 18, 17),
    "L": (16, 16, 16, 16, 16, 16, 31),
    "M": (17, 27, 21, 21, 17, 17, 17),
    "N": (17, 25, 21, 19, 17, 17, 17),
    "O": (14, 17, 17, 17, 17, 17, 14),
    "P": (30, 17, 17, 30, 16, 16, 16),
    "Q": (14, 17, 17, 17, 21, 18, 13),
    "R": (30, 17, 17, 30, 20, 18, 17),
    "S": (15, 16, 16, 14, 1, 1, 30),
    "T": (31, 4, 4, 4, 4, 4, 4),
    "U": (17, 17, 17, 17, 17, 17, 14),
    "V": (17, 17, 17, 17, 17, 10, 4),
    "W": (17, 17, 17, 21, 21, 21, 10),
    "X": (17, 17, 10, 4, 10, 17, 17),
    "Y": (17, 17, 10, 4, 4, 4, 4),
    "Z": (31, 1, 2, 4, 8, 16, 31),
    "[": (14, 8, 8, 8, 8, 8, 14),
    "\\": (16, 16, 8, 4, 2, 1, 1),
    "]": (14, 2, 2, 2, 2, 2, 14),
    "^": (4, 10, 17, 0, 0, 0, 0),
    "_": (0, 0, 0, 0, 0, 0, 31),
    "`": (8, 4, 2, 0, 0, 0, 0),
    "a": (0, 0, 14, 1, 15, 17, 15),
    "b": (16, 16, 22, 25, 17, 17, 30),
    "c": (0, 0, 14, 16, 16, 17, 14),
    "d": (1, 1, 13, 19, 17, 17, 15),
    "e": (0, 0, 14, 17, 31, 16, 14),
    "f": (6, 9, 8, 28, 8, 8, 8),
    "g": (0, 15, 17, 17, 15, 1, 14),
    "h": (16, 16, 22, 25, 17, 17, 17),
    "i": (4, 0, 12, 4, 4, 4, 14),
    "j": (2, 0, 6, 2, 2, 18, 12),
    "k": (16, 16, 18, 20, 24, 20, 18),
    "l": (12, 4, 4, 4, 4, 4, 14),
    "m": (0, 0, 26, 21, 21, 21, 21),
    "n": (0, 0, 22, 25, 17, 17, 17),
    "o": (0, 0, 14, 17, 17, 17, 14),
    "p": (0, 30, 17, 17, 30, 16, 16),
    "q": (0, 13, 19, 17, 15, 1, 1),
    "r": (0, 0, 22, 25, 16, 16, 16),
    "s": (0, 0, 15, 16, 14, 1, 30),
    "t": (8, 8, 28, 8, 8, 9, 6),
    "u": (0, 0, 17, 17, 17, 19, 13),
    "v": (0, 0, 17, 17, 17, 10, 4),
    "w": (0, 0, 17, 17, 21, 21, 10),
    "x": (0, 0, 17, 10, 4, 10, 17),
    "y": (0, 17, 17, 17, 15, 1, 14),
    "z": (0, 0, 31, 2, 4, 8, 31),
    "{": (2, 4, 4, 8, 4, 4, 2),
    "|": (4, 4, 4, 4, 4, 4, 4),
    "}": (8, 4, 4, 2, 4, 4, 8),
    "~": (0, 8, 21, 2, 0, 0, 0),
    "\u20ac": (14, 17, 20, 30, 20, 17, 14),
}

_ACCENTS = {
    "acute": ((4, 8), "above"),
    "grave": ((8, 4), "above"),
    "circumflex": ((4, 10, 17), "above"),
    "tilde": ((10, 21, 0), "above"),
    "diaeresis": ((10, 10), "above"),
    "cedilla": ((8, 4), "below"),
}

_ACCENTED = {
    "á": ("a", "acute"),
    "à": ("a", "grave"),
    "â": ("a", "circumflex"),
    "ã": ("a", "tilde"),
    "ä": ("a", "diaeresis"),
    "é": ("e", "acute"),
    "è": ("e", "grave"),
    "ê": ("e", "circumflex"),
    "ë": ("e", "diaeresis"),
    "í": ("i", "acute"),
    "ì": ("i", "grave"),
    "î": ("i", "circumflex"),
    "ï": ("i", "diaeresis"),
    "ó": ("o", "acute"),
    "ò": ("o", "grave"),
    "ô": ("o", "circumflex"),
    "õ": ("o", "tilde"),
    "ö": ("o", "diaeresis"),
    "ú": ("u", "acute"),
    "ù": ("u", "grave"),
    "û": ("u", "circumflex"),
    "ü": ("u", "diaeresis"),
    "ç": ("c", "cedilla"),
    "ñ": ("n", "tilde"),
    "Á": ("A", "acute"),
    "À": ("A", "grave"),
    "Â": ("A", "circumflex"),
    "Ã": ("A", "tilde"),
    "Ä": ("A", "diaeresis"),
    "É": ("E", "acute"),
    "È": ("E", "grave"),
    "Ê": ("E", "circumflex"),
    "Ë": ("E", "diaeresis"),
    "Í": ("I", "acute"),
    "Ì": ("I", "grave"),
    "Î": ("I", "circumflex"),
    "Ï": ("I", "diaeresis"),
    "Ó": ("O", "acute"),
    "Ò": ("O", "grave"),
    "Ô": ("O", "circumflex"),
    "Õ": ("O", "tilde"),
    "Ö": ("O", "diaeresis"),
    "Ú": ("U", "acute"),
    "Ù": ("U", "grave"),
    "Û": ("U", "circumflex"),
    "Ü": ("U", "diaeresis"),
    "Ç": ("C", "cedilla"),
    "Ñ": ("N", "tilde"),
}

_TRANSLITERATE = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2026": "...",
    "\u00a0": " ",
    "\u00ab": '"',
    "\u00bb": '"',
    "\u00a7": "S",
    "\u2022": "*",
}

_SCALE = 2
_CHAR_ADVANCE = 6 * _SCALE
_LINE_HEIGHT = 12 * _SCALE
_MARGIN_X = 30
_MARGIN_Y = 45
_TEXT_WIDTH = 62
_TEXT_LINES = 44
_IMAGE_WIDTH = 870
_IMAGE_HEIGHT = 1240

# Fixed-point sin/cos scaled by 2^16, keyed by absolute millidegrees. Values
# are integer literals so parsing and arithmetic stay host-independent.
_TRIG = {
    0: (0, 65536),
    125: (143, 65536),
    250: (286, 65535),
    375: (429, 65534),
    500: (572, 65533),
}


class Bitmap:
    def __init__(self, width: int, height: int, *, white: bool = True) -> None:
        self.width = width
        self.height = height
        fill = 1 if white else 0
        self.pixels = bytearray([fill]) * (width * height)

    def set_pixel(self, x: int, y: int, value: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.pixels[y * self.width + x] = value

    def get_pixel(self, x: int, y: int) -> int:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.pixels[y * self.width + x]
        return 1

    def draw_glyph(self, x: int, y: int, rows: tuple[int, ...]) -> None:
        for row_index, mask in enumerate(rows):
            for column in range(5):
                if mask & (1 << (4 - column)):
                    for dy in range(_SCALE):
                        for dx in range(_SCALE):
                            self.set_pixel(
                                x + column * _SCALE + dx,
                                y + row_index * _SCALE + dy,
                                0,
                            )


def _glyph_for(char: str) -> tuple[tuple[int, ...], str | None]:
    if char in _ACCENTED:
        base, accent = _ACCENTED[char]
        return _GLYPHS[base], accent
    translated = _TRANSLITERATE.get(char, char)
    if translated in _GLYPHS:
        return _GLYPHS[translated], None
    return _GLYPHS["?"], None


def _draw_text(bitmap: Bitmap, lines: list[str]) -> None:
    y = _MARGIN_Y
    for line in lines[:_TEXT_LINES]:
        x = _MARGIN_X
        for char in line[:_TEXT_WIDTH]:
            glyph, accent = _glyph_for(char)
            if accent is not None:
                rows, position = _ACCENTS[accent]
                offset = (
                    y - len(rows) * _SCALE
                    if position == "above"
                    else y + 7 * _SCALE
                )
                for row_index, mask in enumerate(rows):
                    for column in range(5):
                        if mask & (1 << (4 - column)):
                            for dy in range(_SCALE):
                                for dx in range(_SCALE):
                                    bitmap.set_pixel(
                                        x + column * _SCALE + dx,
                                        offset + row_index * _SCALE + dy,
                                        0,
                                    )
            bitmap.draw_glyph(x, y, glyph)
            x += _CHAR_ADVANCE
        y += _LINE_HEIGHT


def _rotate(bitmap: Bitmap, angle_millidegrees: int) -> Bitmap:
    if angle_millidegrees == 0:
        return bitmap
    sign = -1 if angle_millidegrees < 0 else 1
    sin, cos = _TRIG[abs(angle_millidegrees)]
    sin *= sign
    rotated = Bitmap(bitmap.width, bitmap.height)
    width = bitmap.width
    height = bitmap.height
    source = bitmap.pixels
    target = rotated.pixels
    cx = width // 2
    cy = height // 2
    for y in range(height):
        base = y * width
        dy = y - cy
        for x in range(width):
            dx = x - cx
            source_x = cx + ((dx * cos + dy * sin) >> 16)
            source_y = cy + ((-dx * sin + dy * cos) >> 16)
            if 0 <= source_x < width and 0 <= source_y < height:
                target[base + x] = source[source_y * width + source_x]
    return rotated


def _speckle(bitmap: Bitmap, seed: str, stable_key: str) -> None:
    """Add deterministic salt noise in 32-pixel groups (fast, order-free)."""

    width = bitmap.width
    pixels = bitmap.pixels
    for y in range(bitmap.height):
        stream = derive.XorShift64(
            derive.stream_u64(seed, "scan-speckle", f"{stable_key}/{y}", 0)
        )
        base = y * width
        group = 0
        while group * 32 < width:
            if stream.random_below(44) == 0:
                x = group * 32 + stream.random_below(32)
                if x < width:
                    pixels[base + x] = 0
            group += 1


def _pack_rows(bitmap: Bitmap) -> bytes:
    stride = (bitmap.width + 7) // 8
    rows = bytearray(stride * bitmap.height)
    for y in range(bitmap.height):
        base = y * stride
        row = y * bitmap.width
        for x in range(bitmap.width):
            if bitmap.pixels[row + x]:
                rows[base + (x >> 3)] |= 1 << (7 - (x & 7))
    return bytes(rows)


def rasterize_page(page_text: str, *, seed: str, stable_key: str, recipe: dict) -> Bitmap:
    bitmap = Bitmap(_IMAGE_WIDTH, _IMAGE_HEIGHT)
    _draw_text(bitmap, page_text.split("\n")[:_TEXT_LINES])
    if recipe.get("skew_millidegrees_max", 0):
        maximum = int(recipe["skew_millidegrees_max"])
        if maximum > 0:
            magnitude = derive.uniform_int(
                seed, "scan-skew", stable_key, 0, maximum // 125
            ) * 125
            if derive.uniform_int(seed, "scan-skew-sign", stable_key, 0, 1):
                magnitude = -magnitude
            bitmap = _rotate(bitmap, magnitude)
    if recipe.get("noise") == "speckle-1-in-1400":
        _speckle(bitmap, seed, stable_key)
    return bitmap


def page_bitmap(doc: Document) -> Bitmap:
    recipe = doc.scan_options or {}
    page = doc.page_texts[sorted(doc.page_texts)[0]]
    return rasterize_page(
        page,
        seed=f"sdc-scan/{doc.doc_id}",
        stable_key=doc.doc_id,
        recipe=recipe,
    )


# ---------------------------------------------------------------------------
# PNG (bilevel, stored deflate: no zlib-version dependence)
# ---------------------------------------------------------------------------


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        len(data).to_bytes(4, "big")
        + kind
        + data
        + zlib.crc32(kind + data).to_bytes(4, "big")
    )


def _stored_zlib(data: bytes) -> bytes:
    out = bytearray(b"\x78\x01")
    if not data:
        out.extend(b"\x01\x00\x00\xff\xff")
    else:
        offset = 0
        while offset < len(data):
            chunk = data[offset : offset + 65535]
            offset += len(chunk)
            final = 1 if offset >= len(data) else 0
            out.append(final)
            out.extend(len(chunk).to_bytes(2, "little"))
            out.extend((0xFFFF - len(chunk)).to_bytes(2, "little"))
            out.extend(chunk)
    out.extend(zlib.adler32(data).to_bytes(4, "big"))
    return bytes(out)


def encode_png(bitmap: Bitmap) -> bytes:
    stride = (bitmap.width + 7) // 8
    packed = _pack_rows(bitmap)
    raw = bytearray()
    for y in range(bitmap.height):
        raw.append(0)  # filter: none
        start = y * stride
        raw.extend(packed[start : start + stride])
    ihdr = (
        bitmap.width.to_bytes(4, "big")
        + bitmap.height.to_bytes(4, "big")
        + bytes((1, 0, 0, 0, 0))
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", _stored_zlib(bytes(raw)))
        + _png_chunk(b"IEND", b"")
    )


def render_scanned_image(doc: Document) -> bytes:
    return encode_png(page_bitmap(doc))


def render_scanned_pdf(doc: Document) -> bytes:
    bitmap = page_bitmap(doc)
    image_data = _pack_rows(bitmap)
    image_object = (
        f"<< /Type /XObject /Subtype /Image /Width {bitmap.width} "
        f"/Height {bitmap.height} /ColorSpace /DeviceGray "
        f"/BitsPerComponent 1 /Length {len(image_data)} >>\nstream\n"
    ).encode("ascii") + image_data + b"\nendstream"
    content = b"q 420 0 0 595 0 0 cm /Im1 Do Q\n"
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 420 595] "
            b"/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        4: f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
        + content
        + b"endstream",
        5: image_object,
    }
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
        buffer.extend(f"{offsets[number]:010d} 00000 n \n".encode("ascii"))
    identifier = derive.digest_hex("sdc-scan", "file-id", doc.doc_id)[:32]
    buffer.extend(
        (
            f"trailer\n<< /Size {size} /Root 1 0 R "
            f"/ID [<{identifier}> <{identifier}>] >>\nstartxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(buffer)
