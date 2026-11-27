"""Compose canonical works from pinned synthetic templates.

The templates are the only document-content source in this version. They are
committed, MIT-licensed, and pinned by SHA-256 in the source manifest. Every
name, company, domain, identifier, and date is fictitious.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from . import derive
from .canonical import Block
from .errors import SCHEMA_INVALID, SdcError
from .jsonio import nfc
from .sources import TemplateSource

_PLACEHOLDER = re.compile(r"\{([a-z_]+)(?::([0-9]*d))?\}")

_TEMPLATE_KEYS = {
    "template_id",
    "schema_version",
    "kind",
    "language",
    "domain",
    "folder",
    "title_forms",
    "identifier",
    "entity_pools",
    "identifier_sentence",
    "headings",
    "paragraphs",
    "list_items",
    "table_columns",
    "table_rows",
    "long_paragraphs",
    "needle",
    "code_languages",
    "notes",
}
_IDENTIFIER_KEYS = {"kind", "pattern"}

KINDS = ("text", "long", "code", "boilerplate")


@dataclass(frozen=True)
class Work:
    work_index: int
    template: TemplateSource
    title: str
    language: str
    folder: str
    year: int
    blocks: list[Block]
    code_language: str | None = None
    code_extension: str | None = None

    @property
    def domain(self) -> str:
        return str(self.template.data["domain"])


def _require(condition: bool, message: str, *, file: str, field: str) -> None:
    if not condition:
        raise SdcError(SCHEMA_INVALID, message, file=file, field=field)


def validate_template(template: TemplateSource) -> None:
    data = template.data
    display = f"sources/templates/{template.template_id}.json"
    _require(isinstance(data, dict), "template must be a JSON object", file=display, field="")
    _require(
        data.get("schema_version") == 1,
        "unsupported template schema_version",
        file=display,
        field="schema_version",
    )
    _require(
        data.get("template_id") == template.template_id,
        "template_id must match the manifest pin",
        file=display,
        field="template_id",
    )
    kind = data.get("kind")
    _require(kind in KINDS, f"template kind must be one of {KINDS}", file=display, field="kind")
    for key, expected in (
        ("language", str),
        ("domain", str),
        ("folder", str),
        ("title_forms", list),
        ("entity_pools", dict),
        ("identifier", dict),
        ("identifier_sentence", str),
    ):
        _require(
            isinstance(data.get(key), expected),
            f"template field {key} must be {expected.__name__}",
            file=display,
            field=key,
        )
    _require(len(data["title_forms"]) >= 1, "title_forms must not be empty", file=display, field="title_forms")
    identifier = data["identifier"]
    _require(
        set(identifier) == _IDENTIFIER_KEYS,
        "identifier must contain exactly kind and pattern",
        file=display,
        field="identifier",
    )
    _require(
        isinstance(identifier["kind"], str) and isinstance(identifier["pattern"], str),
        "identifier kind and pattern must be strings",
        file=display,
        field="identifier",
    )
    for name, values in data["entity_pools"].items():
        _require(
            isinstance(name, str)
            and isinstance(values, list)
            and values
            and all(isinstance(value, str) and value for value in values),
            f"entity pool {name!r} must be a nonempty string array",
            file=display,
            field="entity_pools",
        )
    if kind in ("text", "long"):
        for key in ("headings", "paragraphs", "list_items"):
            _require(
                isinstance(data.get(key), list)
                and data[key]
                and all(isinstance(value, str) and value for value in data[key]),
                f"{key} must be a nonempty string array",
                file=display,
                field=key,
            )
        _require(
            isinstance(data.get("table_columns"), list)
            and isinstance(data.get("table_rows"), list)
            and all(isinstance(row, list) for row in data["table_rows"]),
            "table_columns and table_rows must be arrays",
            file=display,
            field="table_rows",
        )
    if kind == "long":
        _require(
            isinstance(data.get("long_paragraphs"), list)
            and len(data["long_paragraphs"]) >= 20,
            "long templates need at least 20 long_paragraphs",
            file=display,
            field="long_paragraphs",
        )
        _require(
            isinstance(data.get("needle"), str) and data["needle"],
            "long templates need a needle paragraph",
            file=display,
            field="needle",
        )
    if kind == "code":
        languages = data.get("code_languages")
        _require(
            isinstance(languages, list) and len(languages) >= 1,
            "code templates need code_languages",
            file=display,
            field="code_languages",
        )
        for language in languages:
            _require(
                isinstance(language, dict)
                and isinstance(language.get("name"), str)
                and isinstance(language.get("extension"), str)
                and isinstance(language.get("units"), list)
                and language["units"]
                and all(isinstance(unit, str) and unit for unit in language["units"]),
                "each code language needs name, extension, and units",
                file=display,
                field="code_languages",
            )
    if kind == "boilerplate":
        families = data.get("families")
        _require(
            isinstance(families, dict) and families,
            "boilerplate templates need a families object",
            file=display,
            field="families",
        )
        for name, blocks in families.items():
            _require(
                isinstance(name, str)
                and isinstance(blocks, list)
                and blocks
                and all(isinstance(block, str) and block for block in blocks),
                f"boilerplate family {name!r} must be a nonempty string array",
                file=display,
                field="families",
            )


def validate_templates(templates: dict[str, TemplateSource]) -> None:
    if not templates:
        raise SdcError(
            SCHEMA_INVALID,
            "the selected source sets contain no synthetic templates",
            file="sources/",
        )
    for template in templates.values():
        validate_template(template)


def _fill(text: str, values: dict[str, str], *, file: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        spec = match.group(2)
        if name not in values:
            raise SdcError(
                SCHEMA_INVALID,
                f"unknown template placeholder {{{name}}}",
                file=file,
                field="paragraphs",
            )
        value = values[name]
        if spec is not None and spec.endswith("d"):
            width = int(spec[:-1] or "0")
            return str(int(value)).zfill(width)
        return value

    return nfc(_PLACEHOLDER.sub(replace, text))


def _values_for(
    template: TemplateSource, work_index: int, seed: str
) -> dict[str, str]:
    data = template.data
    file = f"sources/templates/{template.template_id}.json"
    key_root = f"{template.template_id}/{work_index}"
    values: dict[str, str] = {"seq": str(work_index + 1)}
    values["year"] = str(
        derive.uniform_int(seed, "work-year", key_root, 2018, 2025)
    )
    values["month"] = f"{derive.uniform_int(seed, 'work-month', key_root, 1, 12):02d}"
    values["day"] = f"{derive.uniform_int(seed, 'work-day', key_root, 1, 28):02d}"
    values["date"] = f"{values['year']}-{values['month']}-{values['day']}"
    values["uuid"] = derive.uuid4_like(seed + ":uuid", key_root)
    values["amount"] = (
        f"{derive.uniform_int(seed, 'work-amount', key_root, 1000, 999999) / 100:.2f}"
    )
    values["currency"] = "EUR"
    values["error_code"] = f"E-{derive.uniform_int(seed, 'work-error', key_root, 1000, 9999)}"
    for name, pool in data["entity_pools"].items():
        values[name] = derive.choose(pool, seed, f"entity-{name}", key_root)
    identifier = data["identifier"]
    values["id"] = _fill(identifier["pattern"], values, file=file)
    return values


def _order_texts(
    items: list[str], seed: str, purpose: str, key_root: str
) -> list[str]:
    indexed = list(enumerate(items))
    ordered = derive.ordered(
        indexed,
        seed,
        purpose,
        key=lambda entry: f"{key_root}/{entry[0]}",
    )
    return [text for _, text in ordered]


def compose_work(
    template: TemplateSource,
    work_index: int,
    seed: str,
    *,
    format_hint: str,
) -> Work:
    """Compose one canonical work, deterministic in (template, index, seed)."""

    validate_template(template)
    data = template.data
    file = f"sources/templates/{template.template_id}.json"
    kind = data["kind"]
    values = _values_for(template, work_index, seed)
    key_root = f"{template.template_id}/{work_index}"

    title = _fill(
        derive.choose(data["title_forms"], seed, "work-title", key_root),
        values,
        file=file,
    )
    year = int(values["year"])
    folder = str(data["folder"])

    if kind == "code":
        return _compose_code(template, work_index, seed, values, title, folder, year)

    blocks: list[Block] = []

    def add(text: str, block_kind: str) -> None:
        blocks.append(
            Block(
                block_id=f"b-{len(blocks) + 1:04d}",
                kind=block_kind,
                text=_fill(text, values, file=file),
            )
        )

    if format_hint == "xlsx":
        columns = [
            _fill(column, values, file=file) for column in data["table_columns"]
        ]
        sheet = _sheet_name(str(data["domain"]))
        rows = data["table_rows"]
        chosen_rows = derive.ordered(
            list(enumerate(rows)), seed, "table-rows", key=lambda entry: str(entry[0])
        )
        row_count = derive.uniform_int(seed, "table-row-count", key_root, 5, 7)
        for column_index, column in enumerate(columns, start=1):
            blocks.append(
                Block(
                    block_id=f"b-{len(blocks) + 1:04d}",
                    kind="table_cell",
                    text=column,
                    locator={"sheet": sheet, "row": 1, "column": column_index},
                )
            )
        for row_number, (_, row) in enumerate(chosen_rows[:row_count], start=2):
            for column_index, cell in enumerate(row, start=1):
                text = _fill(str(cell), values, file=file)
                if not text:
                    continue
                blocks.append(
                    Block(
                        block_id=f"b-{len(blocks) + 1:04d}",
                        kind="table_cell",
                        text=text,
                        locator={
                            "sheet": sheet,
                            "row": row_number,
                            "column": column_index,
                        },
                    )
                )
        return Work(work_index, template, title, str(data["language"]), folder, year, blocks)

    heading_pool = _order_texts(data["headings"], seed, "headings", key_root)
    paragraph_pool = _order_texts(data["paragraphs"], seed, "paragraphs", key_root)
    list_pool = _order_texts(data["list_items"], seed, "list-items", key_root)

    if format_hint == "pptx":
        add(heading_pool[0], "heading")
        add(data["identifier_sentence"], "paragraph")
        slides = 2
        for slide in range(slides):
            add(heading_pool[(slide + 1) % len(heading_pool)], "heading")
            count = derive.uniform_int(
                seed, "slide-bullets", f"{key_root}/{slide}", 2, 3
            )
            start = (slide * 3) % len(list_pool)
            for offset in range(count):
                add(list_pool[(start + offset) % len(list_pool)], "list_item")
        return Work(work_index, template, title, str(data["language"]), folder, year, blocks)

    if kind == "long":
        add(heading_pool[0], "heading")
        pool = _order_texts(
            data["long_paragraphs"], seed, "long-paragraphs", key_root
        )
        target = derive.uniform_int(seed, "long-block-count", key_root, 55, 65)
        needle_index = max(2, target // 2)
        inserted = False
        for index in range(target):
            if index == needle_index:
                add(data["needle"], "paragraph")
                inserted = True
            add(pool[index % len(pool)], "paragraph")
            if index in (needle_index // 2, target - 3):
                add(
                    heading_pool[(index + 1) % len(heading_pool)],
                    "heading",
                )
        if not inserted:
            add(data["needle"], "paragraph")
        return Work(work_index, template, title, str(data["language"]), folder, year, blocks)

    add(heading_pool[0], "heading")
    add(data["identifier_sentence"], "paragraph")
    paragraph_count = derive.uniform_int(seed, "paragraph-count", key_root, 4, 6)
    list_count = derive.uniform_int(seed, "list-count", key_root, 1, 3)
    for index in range(paragraph_count):
        add(paragraph_pool[index % len(paragraph_pool)], "paragraph")
        if index == 2:
            add(heading_pool[1 % len(heading_pool)], "heading")
    for index in range(list_count):
        add(list_pool[index % len(list_pool)], "list_item")
    return Work(work_index, template, title, str(data["language"]), folder, year, blocks)


def _compose_code(
    template: TemplateSource,
    work_index: int,
    seed: str,
    values: dict[str, str],
    title: str,
    folder: str,
    year: int,
) -> Work:
    data = template.data
    file = f"sources/templates/{template.template_id}.json"
    key_root = f"{template.template_id}/{work_index}"
    languages = data["code_languages"]
    language = derive.choose(
        languages, seed, "code-language", key_root
    )
    values = dict(values)
    values["fn"] = derive.slugify(title).replace("-", "_")[:40] + f"_{work_index + 1:03d}"
    values["class_name"] = "".join(
        part.capitalize() for part in derive.slugify(title).split("-")[:3]
    ) or "Module"
    units = _order_texts(language["units"], seed, "code-units", key_root)
    unit_count = derive.uniform_int(seed, "code-unit-count", key_root, 2, 4)
    blocks: list[Block] = []
    for unit in units[:unit_count]:
        text = _fill(unit, values, file=file).strip("\n")
        blocks.append(
            Block(
                block_id=f"b-{len(blocks) + 1:04d}",
                kind="code",
                text=text,
            )
        )
    return Work(
        work_index,
        template,
        title,
        str(data["language"]),
        folder,
        year,
        blocks,
        code_language=str(language["name"]),
        code_extension=str(language["extension"]),
    )


def _sheet_name(domain: str) -> str:
    cleaned = "".join(char for char in domain.title() if char.isascii() and char.isalnum())
    return (cleaned or "Dados")[:31]
