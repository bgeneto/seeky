"""Read and qualify the externally stored frozen public sample."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import ArtifactError, load_json

# Models trained with the e5 `query: `/`passage: ` input prefixes.
E5_PREFIXED = frozenset({"e5-small", "gety-embed-v0"})


class FrozenDataError(RuntimeError):
    """The frozen text sample is missing, malformed, or incomplete."""


def load_frozen(workspace: Path) -> dict[str, Any]:
    try:
        value = load_json(workspace / "data" / "frozen-text.json")
    except ArtifactError as error:
        raise FrozenDataError("frozen public text sample is unavailable") from error
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise FrozenDataError("frozen public text sample has an unsupported schema")
    return value


def embedding_view(frozen: dict[str, Any], slug: str) -> dict[str, Any]:
    if frozen.get("schema") != 1 or not isinstance(frozen.get("miracl"), dict) or not isinstance(
        frozen.get("mmarco"), dict
    ):
        raise FrozenDataError("frozen public text sample is malformed")
    queries: list[dict[str, str]] = []
    passages: list[dict[str, str]] = []
    qrels: dict[str, dict[str, int]] = {}
    source_counts: dict[str, dict[str, int]] = {}
    for source_name in ("miracl", "mmarco"):
        source = frozen[source_name]
        source_queries = source.get("queries")
        source_passages = source.get("passages")
        if not isinstance(source_queries, list) or not isinstance(source_passages, list):
            raise FrozenDataError("frozen source has missing query or passage rows")
        if not source_queries or not source_passages:
            raise FrozenDataError("frozen source has an empty query or passage set")
        for row in source_queries:
            if not isinstance(row, dict) or not row.get("id") or not row.get("text"):
                raise FrozenDataError("frozen query row is malformed")
            identifier = f"{source_name}:{row['id']}"
            text = row["text"]
            if slug in E5_PREFIXED:
                text = f"query: {text}"
            queries.append({"id": identifier, "text": text, "source": source_name})
        for row in source_passages:
            if not isinstance(row, dict) or not row.get("id") or not row.get("text"):
                raise FrozenDataError("frozen passage row is malformed")
            identifier = f"{source_name}:{row['id']}"
            text = row["text"]
            if slug in E5_PREFIXED:
                text = f"passage: {text}"
            passages.append({"id": identifier, "text": text, "source": source_name})
        source_qrels = source.get("qrels", {})
        if not isinstance(source_qrels, dict):
            raise FrozenDataError("frozen qrels are malformed")
        for query_id, judged in source_qrels.items():
            qrels[f"{source_name}:{query_id}"] = {
                f"{source_name}:{doc_id}": int(relevance)
                for doc_id, relevance in judged.items()
            }
        source_counts[source_name] = {
            "queries": len(source_queries),
            "passages": len(source_passages),
        }
    if len({row["id"] for row in queries}) != len(queries) or len(
        {row["id"] for row in passages}
    ) != len(passages):
        raise FrozenDataError("frozen qualified IDs are not unique")
    return {
        "queries": queries,
        "passages": passages,
        "qrels": qrels,
        "source_counts": source_counts,
    }
