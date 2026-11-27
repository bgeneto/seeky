"""Render the frozen public-domain OCR pages and their exact ground truth."""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .artifacts import ArtifactError, download_file, load_json, sha256_file, write_json
from .data import DataError, acquire_gutenberg_texts

PAGE_WIDTH = 2480
PAGE_HEIGHT = 3508
MARGIN_X = 260
MARGIN_TOP = 240
MARGIN_BOTTOM = 240
FONT_SIZE = 44
LINE_HEIGHT = 62
PAGES_PER_LANGUAGE = 8
BLANK_PAGES = 4
FONT_URL = "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip"
FONT_ARCHIVE_SHA256 = "7576310b219e04159d35ff61dd4a4ec4cdba4f35c00e002a136f00e96a908b0a"
FONT_MEMBER = "dejavu-fonts-ttf-2.37/ttf/DejaVuSerif.ttf"


class OcrDataError(RuntimeError):
    """A renderer input or output is malformed."""


def normalized_paragraphs(body: str) -> list[str]:
    paragraphs = []
    for block in re.split(r"\n\s*\n", body):
        paragraph = " ".join(line.strip() for line in block.splitlines() if line.strip())
        paragraph = " ".join(paragraph.split())
        if len(paragraph) >= 80:
            paragraphs.append(paragraph)
    if not paragraphs:
        raise OcrDataError("public-domain text has no usable paragraphs")
    return paragraphs


def wrap_lines(draw: ImageDraw.ImageDraw, paragraphs: list[str], font: ImageFont.FreeTypeFont) -> list[str]:
    width = PAGE_WIDTH - 2 * MARGIN_X
    lines: list[str] = []
    for paragraph in paragraphs:
        words = paragraph.split()
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        lines.append("")
    if not lines:
        raise OcrDataError("public-domain text produced no rendered lines")
    return lines


def _font(workspace: Path) -> Path:
    path = workspace / "data" / "fonts" / "DejaVuSerif.ttf"
    if path.exists():
        return path
    archive = workspace / "data" / "fonts" / "dejavu-fonts-ttf-2.37.zip"
    try:
        if not archive.exists():
            download_file(FONT_URL, archive, expected_sha256=FONT_ARCHIVE_SHA256)
        with zipfile.ZipFile(archive) as bundle:
            payload = bundle.read(FONT_MEMBER)
        path.write_bytes(payload)
    except (ArtifactError, KeyError, OSError, zipfile.BadZipFile) as error:
        raise OcrDataError("pinned OCR font could not be downloaded or extracted") from error
    return path


def render_ocr_pages(workspace: Path) -> dict[str, Any]:
    output_dir = workspace / "data" / "ocr"
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        return load_json(manifest_path)
    sources = acquire_gutenberg_texts(workspace)
    font_path = _font(workspace)
    try:
        font = ImageFont.truetype(str(font_path), FONT_SIZE)
    except OSError as error:
        raise OcrDataError("pinned OCR font cannot be loaded") from error
    output_dir.mkdir(parents=True, exist_ok=True)
    ground_truth: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    for language in ("en", "pt"):
        paragraphs = normalized_paragraphs(sources[language]["body"])
        measure = ImageDraw.Draw(Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "white"))
        lines = wrap_lines(measure, paragraphs, font)
        page_index = 0
        line_index = 0
        while page_index < PAGES_PER_LANGUAGE:
            image = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "white")
            draw = ImageDraw.Draw(image)
            y = MARGIN_TOP
            page_lines: list[str] = []
            while line_index < len(lines):
                line = lines[line_index]
                if y + LINE_HEIGHT > PAGE_HEIGHT - MARGIN_BOTTOM:
                    break
                if line:
                    draw.text((MARGIN_X, y), line, fill="black", font=font)
                    page_lines.append(line)
                y += LINE_HEIGHT
                line_index += 1
            if not page_lines:
                raise OcrDataError("renderer produced an empty text page")
            page_id = f"{language}-{page_index:02d}"
            image_path = output_dir / f"{page_id}.png"
            image.save(image_path, format="PNG", optimize=True)
            truth = "\n".join(page_lines)
            ground_truth[page_id] = truth
            records.append(
                {
                    "id": page_id,
                    "language": language,
                    "kind": "text",
                    "image": image_path.name,
                    "bytes": image_path.stat().st_size,
                    "sha256": sha256_file(image_path),
                    "ground_truth_sha256": hashlib.sha256(truth.encode("utf-8")).hexdigest(),
                }
            )
            page_index += 1
    for index in range(BLANK_PAGES):
        page_id = f"blank-{index:02d}"
        image = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "white")
        image_path = output_dir / f"{page_id}.png"
        image.save(image_path, format="PNG", optimize=True)
        ground_truth[page_id] = ""
        records.append(
            {
                "id": page_id,
                "language": None,
                "kind": "no-text",
                "image": image_path.name,
                "bytes": image_path.stat().st_size,
                "sha256": sha256_file(image_path),
                "ground_truth_sha256": hashlib.sha256(b"").hexdigest(),
            }
        )
    manifest = {
        "schema": 1,
        "width": PAGE_WIDTH,
        "height": PAGE_HEIGHT,
        "dpi": 300,
        "font": {
            "name": "DejaVu Serif 2.37",
            "url": FONT_URL,
            "sha256": sha256_file(font_path),
        },
        "sources": {
            language: {
                "title": row["title"],
                "source_url": row["source_url"],
                "body_sha256": row["body_sha256"],
            }
            for language, row in sources.items()
        },
        "pages": records,
        "text_pages_per_language": PAGES_PER_LANGUAGE,
        "blank_pages": BLANK_PAGES,
    }
    write_json(output_dir / "ground-truth.json", ground_truth)
    write_json(manifest_path, manifest)
    return manifest


def load_ocr_manifest(workspace: Path) -> tuple[dict[str, Any], dict[str, str]]:
    output_dir = workspace / "data" / "ocr"
    manifest = load_json(output_dir / "manifest.json")
    truth = load_json(output_dir / "ground-truth.json")
    if not isinstance(manifest, dict) or not isinstance(truth, dict):
        raise OcrDataError("OCR render manifest or ground truth is malformed")
    return manifest, truth
