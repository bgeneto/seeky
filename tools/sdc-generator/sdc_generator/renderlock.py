"""Renderer lock: pinned renderer implementation and scan recipes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import SCHEMA_INVALID, SdcError
from .jsonio import load_json_file, sha256_bytes

_REQUIRED = {
    "schema_version",
    "renderer_lock_id",
    "python_requires",
    "generator_implementation",
    "formats",
    "assets",
    "scan_recipes",
}
_RECIPE_KEYS = {
    "dpi",
    "page",
    "noise",
    "skew_millidegrees_max",
    "compression",
    "description",
}


def load_renderer_lock(path: Path) -> tuple[dict[str, Any], str]:
    data = load_json_file(path, display="renderers.lock.json")
    if not isinstance(data, dict):
        raise SdcError(SCHEMA_INVALID, "renderer lock must be a JSON object", file=path.name)
    unknown = set(data) - _REQUIRED
    missing = _REQUIRED - set(data)
    if unknown or missing:
        raise SdcError(
            SCHEMA_INVALID,
            f"renderer lock fields mismatch (unknown={sorted(unknown)}, "
            f"missing={sorted(missing)})",
            file=path.name,
        )
    if data["schema_version"] != 1:
        raise SdcError(SCHEMA_INVALID, "unsupported renderer lock schema_version", file=path.name)
    recipes = data["scan_recipes"]
    if not isinstance(recipes, dict) or not recipes:
        raise SdcError(SCHEMA_INVALID, "scan_recipes must be a nonempty object", file=path.name)
    for name, recipe in recipes.items():
        if not isinstance(recipe, dict) or set(recipe) != _RECIPE_KEYS:
            raise SdcError(
                SCHEMA_INVALID,
                f"scan recipe {name!r} must contain exactly {sorted(_RECIPE_KEYS)}",
                file=path.name,
                field="scan_recipes",
            )
        if not isinstance(recipe["dpi"], int) or recipe["dpi"] < 72:
            raise SdcError(SCHEMA_INVALID, f"scan recipe {name!r} has an invalid dpi", file=path.name)
        if recipe["compression"] != "png-bilevel-stored":
            raise SdcError(
                SCHEMA_INVALID,
                f"scan recipe {name!r} uses unsupported compression",
                file=path.name,
            )
        if not isinstance(recipe["skew_millidegrees_max"], int) or recipe["skew_millidegrees_max"] < 0:
            raise SdcError(SCHEMA_INVALID, f"scan recipe {name!r} has invalid skew", file=path.name)
    return data, sha256_bytes(path.read_bytes())
