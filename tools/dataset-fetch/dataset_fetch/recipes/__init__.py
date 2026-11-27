"""Dataset recipe registry.

A recipe turns verified source files into one :class:`BuildRequest`. Recipes
never download and never write; the CLI owns the cache, staging, and lock.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..cache import CachedFile
from ..transform import BuildRequest

Recipe = Callable[[dict[str, Any], list[CachedFile], str], BuildRequest]

_REGISTRY: dict[str, Recipe] = {}


def register(dataset_id: str) -> Callable[[Recipe], Recipe]:
    def decorator(recipe: Recipe) -> Recipe:
        _REGISTRY[dataset_id] = recipe
        return recipe

    return decorator


def recipe_for(dataset_id: str) -> Recipe:
    from ..errors import UNSUPPORTED, fail

    if dataset_id not in _REGISTRY:
        raise fail(UNSUPPORTED, f"no recipe for dataset {dataset_id!r}", location=dataset_id)
    return _REGISTRY[dataset_id]


def registered() -> list[str]:
    return sorted(_REGISTRY)


def find_source(sources: list[CachedFile], suffix: str) -> CachedFile:
    from ..errors import SCHEMA, fail

    matches = [source for source in sources if source.url.endswith(suffix)]
    if len(matches) != 1:
        raise fail(
            SCHEMA,
            f"expected exactly one source URL ending with {suffix!r}, found {len(matches)}",
            location="manifest.source.urls",
        )
    return matches[0]


def optional_source(sources: list[CachedFile], suffix: str) -> CachedFile | None:
    from ..errors import SCHEMA, fail

    matches = [source for source in sources if source.url.endswith(suffix)]
    if len(matches) > 1:
        raise fail(
            SCHEMA,
            f"ambiguous source URLs ending with {suffix!r}",
            location="manifest.source.urls",
        )
    return matches[0] if matches else None


from . import beir, miracl, mldr, mmarco, quati  # noqa: E402,F401  (registration side effects)
