"""Pinned source manifests, license gates, and the content-addressed cache.

SPEC-0004 sections 4.2 and 5.2 and requirements R1, R2, R14. Only ``fetch``
imports a network module; ``build`` and ``verify`` read cache objects and
committed files only.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from .errors import (
    CACHE_MISS,
    IO_ERROR,
    LICENSE_INELIGIBLE,
    LICENSE_NOTICE_MISSING,
    SCHEMA_INVALID,
    SOURCE_HASH_MISMATCH,
    SOURCE_PIN_MISSING,
    SdcError,
)
from .jsonio import assert_relative_posix, load_json_file, sha256_bytes, sha256_file

SCHEMA_VERSION = 1
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

PERMISSIVE_LICENSES = {
    "MIT",
    "ISC",
    "0BSD",
    "Unlicense",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "Apache-2.0",
    "CC0-1.0",
    "CC-BY-4.0",
}
PUBLIC_DOMAIN_REF = "LicenseRef-Public-Domain"

_DENIED_MARKERS = (
    "AGPL",
    "GPL",
    "LGPL",
    "CC-BY-SA",
    "CC-BY-NC",
    "CC-BY-ND",
    "NONCOMMERCIAL",
    "NONDERIVATIVE",
    "RESEARCH",
    "PROPRIETARY",
)

REDISTRIBUTION_CLASSES = ("permissive-core", "sharealike-extension", "local-only")

_SOURCE_SET_KEYS = {
    "schema_version",
    "source_set_id",
    "redistribution_class",
    "items",
}
_ITEM_KEYS_EXTERNAL = {
    "source_item_id",
    "origin",
    "url",
    "byte_length",
    "media_type",
    "sha256",
    "license",
}
_ITEM_KEYS_SYNTHETIC = {
    "source_item_id",
    "origin",
    "template_id",
    "template_sha256",
    "license",
}
_LICENSE_KEYS = {
    "id",
    "text_url",
    "text_sha256",
    "attribution",
    "notice_path",
}


@dataclass(frozen=True)
class License:
    id: str
    text_url: str
    text_sha256: str
    attribution: str
    notice_path: str


@dataclass(frozen=True)
class SourceItem:
    source_item_id: str
    origin: str
    license: License
    redistribution_class: str
    source_set_id: str
    url: str | None = None
    byte_length: int | None = None
    media_type: str | None = None
    sha256: str | None = None
    template_id: str | None = None
    template_sha256: str | None = None


@dataclass(frozen=True)
class SourceSet:
    source_set_id: str
    redistribution_class: str
    items: tuple[SourceItem, ...]
    file_sha256: str
    path: Path


@dataclass(frozen=True)
class TemplateSource:
    source_item_id: str
    source_set_id: str
    template_id: str
    template_sha256: str
    data: dict[str, Any]
    license: License


def _require(condition: bool, code: str, message: str, *, file: str, field: str) -> None:
    if not condition:
        raise SdcError(code, message, file=file, field=field)


def _is_https_url(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def license_ineligible_reason(license_id: str, attribution: str) -> str | None:
    """Return why a license is ineligible for the permissive core, or None."""

    upper = license_id.upper()
    for marker in _DENIED_MARKERS:
        if marker in upper:
            return f"license {license_id!r} is not redistributable in the permissive core"
    if license_id == PUBLIC_DOMAIN_REF:
        if not attribution.strip():
            return "LicenseRef-Public-Domain requires the public-domain basis in attribution"
        return None
    if license_id not in PERMISSIVE_LICENSES:
        return f"license {license_id!r} is not on the permissive allowlist"
    return None


def _load_license(raw: Any, *, file: str) -> License:
    _require(isinstance(raw, dict), SCHEMA_INVALID, "license must be an object", file=file, field="license")
    unknown = set(raw) - _LICENSE_KEYS
    missing = _LICENSE_KEYS - set(raw)
    _require(not unknown, SCHEMA_INVALID, f"unknown license fields: {sorted(unknown)}", file=file, field="license")
    _require(not missing, SCHEMA_INVALID, f"missing license fields: {sorted(missing)}", file=file, field="license")
    license_id = raw["id"]
    _require(
        isinstance(license_id, str) and license_id,
        SCHEMA_INVALID,
        "license.id must be a nonempty string",
        file=file,
        field="license.id",
    )
    _require(
        _is_https_url(raw["text_url"]),
        SCHEMA_INVALID,
        "license.text_url must be an absolute http(s) URL",
        file=file,
        field="license.text_url",
    )
    _require(
        isinstance(raw["text_sha256"], str) and _HEX64.match(raw["text_sha256"]) is not None,
        SCHEMA_INVALID,
        "license.text_sha256 must be 64 lowercase hex characters",
        file=file,
        field="license.text_sha256",
    )
    _require(
        isinstance(raw["attribution"], str),
        SCHEMA_INVALID,
        "license.attribution must be a string",
        file=file,
        field="license.attribution",
    )
    assert_relative_posix(raw["notice_path"], field="license.notice_path", file=file)
    return License(
        id=license_id,
        text_url=raw["text_url"],
        text_sha256=raw["text_sha256"],
        attribution=raw["attribution"],
        notice_path=raw["notice_path"],
    )


def _load_item(raw: Any, *, file: str, redistribution_class: str, source_set_id: str) -> SourceItem:
    _require(isinstance(raw, dict), SCHEMA_INVALID, "source item must be an object", file=file, field="items")
    origin = raw.get("origin")
    _require(
        origin in ("external", "synthetic"),
        SCHEMA_INVALID,
        f"origin must be 'external' or 'synthetic', got {origin!r}",
        file=file,
        field="origin",
    )
    allowed = _ITEM_KEYS_SYNTHETIC if origin == "synthetic" else _ITEM_KEYS_EXTERNAL
    unknown = set(raw) - allowed
    _require(not unknown, SCHEMA_INVALID, f"unknown source item fields: {sorted(unknown)}", file=file, field="items")
    missing = allowed - set(raw)
    _require(not missing, SOURCE_PIN_MISSING, f"source pin is incomplete; missing {sorted(missing)}", file=file, field="items")

    source_item_id = raw["source_item_id"]
    _require(
        isinstance(source_item_id, str) and source_item_id and source_item_id.isascii(),
        SCHEMA_INVALID,
        "source_item_id must be a nonempty ASCII string",
        file=file,
        field="source_item_id",
    )
    license = _load_license(raw["license"], file=file)

    if origin == "synthetic":
        template_id = raw["template_id"]
        _require(
            isinstance(template_id, str) and template_id and "/" not in template_id,
            SCHEMA_INVALID,
            "template_id must be a nonempty path-safe string",
            file=file,
            field="template_id",
        )
        _require(
            isinstance(raw["template_sha256"], str)
            and _HEX64.match(raw["template_sha256"]) is not None,
            SOURCE_PIN_MISSING,
            "template_sha256 must be 64 lowercase hex characters",
            file=file,
            field="template_sha256",
        )
        return SourceItem(
            source_item_id=source_item_id,
            origin=origin,
            license=license,
            redistribution_class=redistribution_class,
            source_set_id=source_set_id,
            template_id=template_id,
            template_sha256=raw["template_sha256"],
        )

    _require(_is_https_url(raw["url"]), SOURCE_PIN_MISSING, "url must be an absolute http(s) URL", file=file, field="url")
    byte_length = raw["byte_length"]
    _require(
        isinstance(byte_length, int) and not isinstance(byte_length, bool) and byte_length >= 0,
        SOURCE_PIN_MISSING,
        "byte_length must be a non-negative integer",
        file=file,
        field="byte_length",
    )
    _require(
        isinstance(raw["media_type"], str) and "/" in raw["media_type"],
        SOURCE_PIN_MISSING,
        "media_type must be a media type",
        file=file,
        field="media_type",
    )
    _require(
        isinstance(raw["sha256"], str) and _HEX64.match(raw["sha256"]) is not None,
        SOURCE_PIN_MISSING,
        "sha256 must be 64 lowercase hex characters",
        file=file,
        field="sha256",
    )
    return SourceItem(
        source_item_id=source_item_id,
        origin=origin,
        license=license,
        redistribution_class=redistribution_class,
        source_set_id=source_set_id,
        url=raw["url"],
        byte_length=byte_length,
        media_type=raw["media_type"],
        sha256=raw["sha256"],
    )


def load_source_sets(sources_dir: Path) -> dict[str, SourceSet]:
    """Load and validate every ``<source-set>.json`` under ``sources_dir``."""

    if not sources_dir.is_dir():
        raise SdcError(IO_ERROR, f"source directory not found: {sources_dir.name}")
    sets: dict[str, SourceSet] = {}
    seen_items: dict[str, str] = {}
    for path in sorted(sources_dir.glob("*.json")):
        display = f"sources/{path.name}"
        raw_bytes = path.read_bytes()
        value = load_json_file(path, display=display)
        _require(isinstance(value, dict), SCHEMA_INVALID, "source set must be a JSON object", file=display, field="")
        unknown = set(value) - _SOURCE_SET_KEYS
        missing = _SOURCE_SET_KEYS - set(value)
        _require(not unknown, SCHEMA_INVALID, f"unknown source set fields: {sorted(unknown)}", file=display, field="")
        _require(not missing, SCHEMA_INVALID, f"missing source set fields: {sorted(missing)}", file=display, field="")
        _require(
            value["schema_version"] == SCHEMA_VERSION,
            SCHEMA_INVALID,
            f"unsupported source schema_version {value['schema_version']!r}",
            file=display,
            field="schema_version",
        )
        source_set_id = value["source_set_id"]
        _require(
            isinstance(source_set_id, str) and source_set_id == path.stem,
            SCHEMA_INVALID,
            "source_set_id must equal the manifest file stem",
            file=display,
            field="source_set_id",
        )
        redistribution_class = value["redistribution_class"]
        _require(
            redistribution_class in REDISTRIBUTION_CLASSES,
            SCHEMA_INVALID,
            f"unknown redistribution_class {redistribution_class!r}",
            file=display,
            field="redistribution_class",
        )
        _require(
            isinstance(value["items"], list) and value["items"],
            SCHEMA_INVALID,
            "items must be a nonempty array",
            file=display,
            field="items",
        )
        items: list[SourceItem] = []
        for raw_item in value["items"]:
            item = _load_item(
                raw_item,
                file=display,
                redistribution_class=redistribution_class,
                source_set_id=source_set_id,
            )
            if item.source_item_id in seen_items:
                raise SdcError(
                    SCHEMA_INVALID,
                    f"duplicate source_item_id {item.source_item_id!r} "
                    f"(also in {seen_items[item.source_item_id]})",
                    file=display,
                    field="source_item_id",
                )
            seen_items[item.source_item_id] = display
            items.append(item)
        sets[source_set_id] = SourceSet(
            source_set_id=source_set_id,
            redistribution_class=redistribution_class,
            items=tuple(items),
            file_sha256=sha256_bytes(raw_bytes),
            path=path,
        )
    if not sets:
        raise SdcError(SCHEMA_INVALID, "no source manifests found", file="sources/")
    return sets


def _repo_license_path(repo_root: Path) -> Path:
    return repo_root / "LICENSE"


def _check_notice(sources_dir: Path, item: SourceItem) -> None:
    notice = sources_dir / PurePosixPath(item.license.notice_path)
    display = f"sources/{item.license.notice_path}"
    if not notice.is_file():
        raise SdcError(
            LICENSE_NOTICE_MISSING,
            "license notice file is missing",
            file=display,
            field="license.notice_path",
        )
    text = notice.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise SdcError(
            LICENSE_NOTICE_MISSING,
            "license notice file is empty",
            file=display,
            field="license.notice_path",
        )
    if item.license.id not in text:
        raise SdcError(
            LICENSE_NOTICE_MISSING,
            f"license notice does not name {item.license.id}",
            file=display,
            field="license.notice_path",
        )
    if item.license.id == PUBLIC_DOMAIN_REF and item.license.attribution.strip() not in text:
        raise SdcError(
            LICENSE_NOTICE_MISSING,
            "public-domain notice does not include the attribution basis",
            file=display,
            field="license.notice_path",
        )


def validate_source_set(
    sources_dir: Path,
    source_set: SourceSet,
    *,
    repo_root: Path,
    require_permissive_core: bool = True,
) -> None:
    """Enforce R1/R2 eligibility before a build touches output."""

    display = f"sources/{source_set.path.name}"
    if require_permissive_core and source_set.redistribution_class != "permissive-core":
        raise SdcError(
            LICENSE_INELIGIBLE,
            f"{source_set.source_set_id} is {source_set.redistribution_class!r}; "
            "only permissive-core sets may enter sdc-smoke",
            file=display,
            field="redistribution_class",
        )
    for item in source_set.items:
        reason = license_ineligible_reason(item.license.id, item.license.attribution)
        if reason is not None:
            raise SdcError(
                LICENSE_INELIGIBLE,
                reason,
                file=display,
                field=f"items.{item.source_item_id}.license.id",
            )
        _check_notice(sources_dir, item)
        if item.origin == "synthetic":
            template_path = sources_dir / "templates" / f"{item.template_id}.json"
            if not template_path.is_file():
                raise SdcError(
                    SOURCE_PIN_MISSING,
                    f"synthetic template {item.template_id!r} is missing",
                    file=f"sources/templates/{item.template_id}.json",
                    field="template_id",
                )
            digest = sha256_file(template_path)[0]
            if digest != item.template_sha256:
                raise SdcError(
                    SOURCE_HASH_MISMATCH,
                    f"synthetic template digest {digest} does not match the pin",
                    file=f"sources/templates/{item.template_id}.json",
                    field="template_sha256",
                )
            license_path = _repo_license_path(repo_root)
            if not license_path.is_file():
                raise SdcError(
                    LICENSE_NOTICE_MISSING,
                    "repository LICENSE file is required for synthetic source items",
                    file="LICENSE",
                )
            license_digest = sha256_file(license_path)[0]
            if license_digest != item.license.text_sha256:
                raise SdcError(
                    SOURCE_HASH_MISMATCH,
                    f"repository LICENSE digest {license_digest} does not match "
                    "the synthetic item's license text pin",
                    file="LICENSE",
                    field="license.text_sha256",
                )


def load_templates(
    sources_dir: Path, source_sets: dict[str, SourceSet]
) -> dict[str, TemplateSource]:
    templates: dict[str, TemplateSource] = {}
    for source_set in source_sets.values():
        for item in source_set.items:
            if item.origin != "synthetic" or item.template_id is None:
                continue
            path = sources_dir / "templates" / f"{item.template_id}.json"
            data = load_json_file(path, display=f"sources/templates/{path.name}")
            if not isinstance(data, dict):
                raise SdcError(
                    SCHEMA_INVALID,
                    "template must be a JSON object",
                    file=f"sources/templates/{path.name}",
                )
            templates[item.source_item_id] = TemplateSource(
                source_item_id=item.source_item_id,
                source_set_id=source_set.source_set_id,
                template_id=item.template_id,
                template_sha256=item.template_sha256 or "",
                data=data,
                license=item.license,
            )
    return templates


def cache_path(cache: Path, digest: str) -> Path:
    return cache / "sha256" / digest


def require_cached(cache: Path, digest: str, *, what: str) -> Path:
    path = cache_path(cache, digest)
    if not path.is_file():
        raise SdcError(
            CACHE_MISS,
            f"{what} is not in the cache; run fetch first",
            file=f"cache/sha256/{digest}",
        )
    return path


def verify_cached(cache: Path, digest: str, byte_length: int | None, *, what: str) -> Path:
    path = require_cached(cache, digest, what=what)
    actual_digest, actual_length = sha256_file(path)
    if actual_digest != digest or (byte_length is not None and actual_length != byte_length):
        raise SdcError(
            SOURCE_HASH_MISMATCH,
            f"cached {what} does not match its pin",
            file=f"cache/sha256/{digest}",
        )
    return path


# ---------------------------------------------------------------------------
# fetch: the only network entry point (R14)
# ---------------------------------------------------------------------------


def _download(url: str, target_tmp: Path, *, timeout: float) -> tuple[str, int]:
    import urllib.request  # local import keeps build/verify free of network modules

    digest = hashlib.sha256()
    length = 0
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            with open(target_tmp, "wb") as handle:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    length += len(chunk)
                    digest.update(chunk)
                    handle.write(chunk)
    except OSError as exc:
        target_tmp.unlink(missing_ok=True)
        raise SdcError(IO_ERROR, f"download failed: {exc}", file=url) from exc
    return digest.hexdigest(), length


def _fetch_object(
    cache: Path,
    *,
    url: str,
    digest: str,
    byte_length: int | None,
    what: str,
    timeout: float,
) -> Path:
    target = cache_path(cache, digest)
    if target.is_file():
        actual, actual_length = sha256_file(target)
        if actual == digest and (byte_length is None or actual_length == byte_length):
            return target
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    tmp.unlink(missing_ok=True)
    actual, length = _download(url, tmp, timeout=timeout)
    if actual != digest or (byte_length is not None and length != byte_length):
        tmp.unlink(missing_ok=True)
        raise SdcError(
            SOURCE_HASH_MISMATCH,
            f"{what} digest {actual} ({length} bytes) does not match "
            f"the pin {digest} ({byte_length} bytes)",
            file=url,
            field="sha256",
        )
    os.replace(tmp, target)
    return target


def fetch_sources(
    *,
    sources_dir: Path,
    cache: Path,
    repo_root: Path,
    source_set_ids: list[str] | None = None,
    timeout: float = 60.0,
) -> list[str]:
    """Download pinned external sources and license texts into the cache."""

    sets = load_source_sets(sources_dir)
    wanted = source_set_ids or sorted(sets)
    unknown = set(wanted) - set(sets)
    if unknown:
        raise SdcError(
            SCHEMA_INVALID,
            f"unknown source set(s): {sorted(unknown)}",
            file="sources/",
            field="source_set_ids",
        )
    fetched: list[str] = []
    for set_id in wanted:
        source_set = sets[set_id]
        validate_source_set(sources_dir, source_set, repo_root=repo_root, require_permissive_core=False)
        for item in source_set.items:
            if item.origin != "external":
                # Synthetic source bytes are the committed template; their
                # license text is the repository LICENSE, verified by build.
                continue
            assert item.url is not None and item.sha256 is not None
            _fetch_object(
                cache,
                url=item.url,
                digest=item.sha256,
                byte_length=item.byte_length,
                what=f"source {item.source_item_id}",
                timeout=timeout,
            )
            _fetch_object(
                cache,
                url=item.license.text_url,
                digest=item.license.text_sha256,
                byte_length=None,
                what=f"license text for {item.source_item_id}",
                timeout=timeout,
            )
            fetched.append(item.source_item_id)
    return fetched


def copy_cache_object(source: Path, cache: Path, digest: str) -> Path:
    target = cache_path(cache, digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target
