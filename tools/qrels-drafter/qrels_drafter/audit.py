"""Independent draft audit: minima, strata, provenance, scope, leakage.

The generator's ``judgments validate --allow-draft`` checks schemas, ordering,
and target hashes. This module adds the WP-1.4 guarantees that a draft must
already satisfy before H6: coverage minima, the exact SPEC-0004 5.4 assignment,
category-scoped provenance, and a leak scan.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import config
from .digest import digest, unit_float
from .jsonio import load_json, read_jsonl

DRAFT_FILES = (
    "queries.draft.jsonl",
    "qrels.draft.documents.jsonl",
    "qrels.draft.passages.jsonl",
    "pools.draft.jsonl",
)
_SET_ID = re.compile(r"^q-sdc-v1-\d{6}$")
_ABSOLUTE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\Users\\\\|/Users/|/home/)")
_SECRET = re.compile(
    r"(?:password|passwd|BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}|api[_-]?key|sk-[A-Za-z0-9]{16,})",
    re.IGNORECASE,
)


class AuditError(ValueError):
    pass


def _fail(message: str) -> None:
    raise AuditError(message)


def assign_splits(queries: list[dict], split_seed: str) -> dict[str, str]:
    strata: dict[tuple[str, str, str], list[str]] = {}
    for query in queries:
        key = (query["category"], query["language_slice"], query["configuration"])
        strata.setdefault(key, []).append(query["_id"])
    splits: dict[str, str] = {}
    for key in sorted(strata):
        ids = strata[key]
        if len(ids) % 2:
            _fail(f"stratum {key} has an odd number of queries ({len(ids)})")
        ordered = sorted(ids, key=lambda qid: (digest(split_seed, "query-split-order", qid), qid))
        for index in range(0, len(ordered), 2):
            first, second = ordered[index], ordered[index + 1]
            direction = min(first, second)
            if unit_float(split_seed, "query-split-direction", direction) < 0.5:
                splits[first], splits[second] = "dev", "test"
            else:
                splits[first], splits[second] = "test", "dev"
    return splits


def _check_provenance(row: dict, *, category: str | None, slice_name: str | None, where: str) -> str:
    provenance = row.get("provenance")
    if not isinstance(provenance, dict):
        _fail(f"{where}: provenance must be an object")
    if set(provenance) - {"drafted_by", "verified_by", "state", "adjudicated_by", "llm_prompt_sha256", "tool_config_sha256"}:
        _fail(f"{where}: unknown provenance field")
    if provenance.get("state") != "draft":
        _fail(f"{where}: every drafted record must stay state=draft")
    if provenance.get("verified_by") != []:
        _fail(f"{where}: every drafted record must have verified_by=[]")
    if provenance.get("adjudicated_by") is not None:
        _fail(f"{where}: a draft record must not name an adjudicator")
    drafted_by = provenance.get("drafted_by")
    if not isinstance(drafted_by, str) or not drafted_by:
        _fail(f"{where}: drafted_by is missing")
    if drafted_by.startswith("llm:"):
        if drafted_by not in {profile.drafted_by for profile in config.PROFILES.values()}:
            _fail(f"{where}: unexpected model provenance {drafted_by}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(provenance.get("llm_prompt_sha256"))):
            _fail(f"{where}: an LLM draft needs a lowercase SHA-256 llm_prompt_sha256")
        if "tool_config_sha256" in provenance:
            _fail(f"{where}: an LLM draft must not carry tool_config_sha256")
        return "llm"
    if drafted_by.startswith("tool:"):
        if drafted_by != config.drafted_by_tool():
            _fail(f"{where}: unexpected tool provenance {drafted_by}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(provenance.get("tool_config_sha256"))):
            _fail(f"{where}: a tool draft needs a lowercase SHA-256 tool_config_sha256")
        if "llm_prompt_sha256" in provenance:
            _fail(f"{where}: a tool draft must not carry llm_prompt_sha256")
        if category is not None and category not in config.TEMPLATE_CATEGORIES:
            _fail(f"{where}: a tool may not draft the {category} category (SPEC-0004 4.6)")
        if slice_name == "cross_lingual":
            _fail(f"{where}: a tool may not draft a cross_lingual record (SPEC-0004 4.6)")
        return "tool"
    _fail(f"{where}: drafted_by must be llm:<model>@<revision> or tool:<id>@<version>")
    return ""


def _check_minima(queries: list[dict], counts: dict[str, int]) -> None:
    """SPEC-0004 R16/R17 minima, checked on the combined draft."""

    if len(queries) < config.MINIMA["total"]:
        _fail(f"only {len(queries)} queries; {config.MINIMA['total']} required")
    for split, count in counts.items():
        if count < config.MINIMA["per_split"]:
            _fail(f"{split} has {count} queries; {config.MINIMA['per_split']} required")
    for category in config.CATEGORIES:
        for split in ("dev", "test"):
            count = sum(1 for query in queries if query["category"] == category and query["split"] == split)
            if count < config.MINIMA["per_category_per_split"]:
                _fail(f"{category}/{split} has {count} queries; 30 required")
    for slice_name, split_minimum, total_minimum in (
        ("pt", config.MINIMA["monolingual_per_split"], 100),
        ("en", config.MINIMA["monolingual_per_split"], 100),
        ("cross_lingual", config.MINIMA["cross_lingual_per_split"], 0),
    ):
        total = sum(1 for query in queries if query["language_slice"] == slice_name)
        if total < total_minimum:
            _fail(f"{slice_name}: {total} queries; {total_minimum} required overall")
        for split in ("dev", "test"):
            count = sum(
                1
                for query in queries
                if query["language_slice"] == slice_name and query["split"] == split
            )
            if count < split_minimum:
                _fail(f"{slice_name}/{split}: {count} queries; {split_minimum} required")
    for language in config.OTHER_LANGUAGES_MINIMUM:
        count = sum(1 for query in queries if query["language"].split("-")[0].lower() == language)
        if count < config.MINIMA["other_language_total"]:
            _fail(f"{language}: {count} queries; {config.MINIMA['other_language_total']} required")
    non_latin = sum(1 for query in queries if query["language_slice"] == "non_latin_non_regression")
    if non_latin < config.MINIMA["non_latin_total"]:
        _fail(f"non-Latin non-regression: {non_latin} queries; 10 required")


def _check_smoke(queries: list[dict]) -> None:
    """SPEC-0004 R26: at least five dev queries per category, never a test split."""

    for category in config.CATEGORIES:
        count = sum(
            1
            for query in queries
            if query["category"] == category and query["split"] == "dev"
        )
        if count < config.SMOKE_MIN_PER_CATEGORY:
            _fail(
                f"{category}/dev has {count} queries; "
                f"{config.SMOKE_MIN_PER_CATEGORY} required for sdc-smoke-v1"
            )


def audit_rows(
    queries: list[dict],
    documents: list[dict],
    passages: list[dict],
    pools: list[dict],
    *,
    check_minima: bool = True,
    corpus=None,
    spec: config.SetSpec = config.FULL_SET,
) -> dict:
    if not queries:
        _fail("the draft has no queries")
    ids = [query["_id"] for query in queries]
    if len(set(ids)) != len(ids):
        _fail("duplicate query IDs")
    pattern = re.compile(rf"^q-{re.escape(spec.set_id)}-\d{{6}}$")
    for query_id in ids:
        if not pattern.match(query_id):
            _fail(f"query ID {query_id!r} does not match q-{spec.set_id}-NNNNNN")
    for row in [*documents, *passages]:
        if row.get("judgment_set_id") != spec.set_id:
            _fail(f"{row.get('query_id')}: judgment_set_id must be {spec.set_id}")
    texts = [query["text"].casefold() for query in queries]
    if len(set(texts)) != len(texts):
        _fail("duplicate query texts: every draft query must be distinct")

    origins: dict[str, str] = {}
    tool_hashes: set[str] = set()
    llm_hashes: set[str] = set()
    for query in queries:
        category = query["category"]
        if category not in config.CATEGORIES:
            _fail(f"{query['_id']}: unknown category")
        if query["configuration"] != ("code_enabled" if category == "code_search" else "default"):
            _fail(f"{query['_id']}: wrong configuration for {category}")
        if query["language_slice"] == "cross_lingual" and category != "cross_language":
            _fail(f"{query['_id']}: only cross_language may carry the cross_lingual slice")
        if category == "cross_language":
            if query["language_slice"] != "cross_lingual":
                _fail(f"{query['_id']}: cross_language needs the cross_lingual slice")
            if query["language"].split("-")[0] in {
                target.split("-")[0] for target in query["target_languages"]
            }:
                _fail(f"{query['_id']}: a cross-language query must not target its own language")
        if category == "mixed_semantic_metadata":
            if not isinstance(query["filters"], dict) or not query["filters"]:
                _fail(f"{query['_id']}: mixed_semantic_metadata needs structured filters")
        elif query["filters"] is not None:
            _fail(f"{query['_id']}: filters must be null outside mixed_semantic_metadata")
        origin = _check_provenance(
            query,
            category=category,
            slice_name=query["language_slice"],
            where=query["_id"],
        )
        if origin == "tool" and category not in config.TEMPLATE_CATEGORIES:
            _fail(f"{query['_id']}: tool provenance outside the template-faithful categories")
        origins[query["_id"]] = origin
        if origin == "tool":
            tool_hashes.add(query["provenance"]["tool_config_sha256"])
        else:
            llm_hashes.add(query["provenance"]["llm_prompt_sha256"])

    if len(tool_hashes) > 1:
        _fail("tool-drafted records disagree on tool_config_sha256")

    # -- judgments -------------------------------------------------------
    by_query: dict[str, dict[str, dict]] = {}
    categories = {query["_id"]: query["category"] for query in queries}
    passage_grades: dict[tuple[str, str, str], int] = {}
    for row in passages:
        origin = _check_provenance(
            row,
            category=None,
            slice_name=None,
            where=f"passage qrel {row.get('query_id')}/{row.get('passage_id')}",
        )
        if row.get("query_id") not in origins:
            _fail(f"passage judgment references unknown query {row.get('query_id')}")
        if origin != origins[row["query_id"]]:
            _fail(f"{row['query_id']}: passage and query provenance kinds differ")
        key = (row["query_id"], row["document_id"], row["passage_id"])
        if key in passage_grades:
            _fail(f"duplicate passage judgment {key}")
        if not isinstance(row["grade"], int) or isinstance(row["grade"], bool) or not 0 <= row["grade"] <= 3:
            _fail(f"passage grade out of range for {key}")
        previous_end = -1
        for span in row["evidence_spans"]:
            if set(span) != {"start_utf8", "end_utf8"}:
                _fail(f"bad evidence span for {key}")
            start, end = span["start_utf8"], span["end_utf8"]
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or start >= end:
                _fail(f"evidence span is not ordered and nonempty for {key}")
            if start < previous_end:
                _fail(f"evidence spans overlap or are unordered for {key}")
            previous_end = end
        passage_grades[key] = row["grade"]

    for row in documents:
        query_id = row["query_id"]
        if query_id not in origins:
            _fail(f"document judgment references unknown query {query_id}")
        category = categories[query_id]
        origin = _check_provenance(
            row,
            category=category,
            slice_name=None,
            where=f"document qrel {query_id}/{row['document_id']}",
        )
        if origin != origins[query_id]:
            _fail(f"{query_id}: query and judgment provenance kinds differ")
        grade = row["grade"]
        if not isinstance(grade, int) or isinstance(grade, bool) or not 0 <= grade <= 3:
            _fail(f"{query_id}/{row['document_id']}: grade out of range")
        evidence = row["evidence_passage_ids"]
        if grade == 0 and evidence:
            _fail(f"{query_id}/{row['document_id']}: grade 0 must not carry evidence")
        if grade >= 2 and not evidence:
            _fail(f"{query_id}/{row['document_id']}: grades 2 and 3 need evidence passages")
        for passage_id in evidence:
            if not passage_id.startswith(row["document_id"] + ":p:"):
                _fail(f"{query_id}/{row['document_id']}: evidence passage belongs elsewhere")
            if passage_grades.get((query_id, row["document_id"], passage_id), 0) <= 0:
                _fail(f"{query_id}/{row['document_id']}: evidence needs a positive passage grade")
        labels = row["subtopic_labels"]
        if category != "exploratory" and labels:
            _fail(f"{query_id}: subtopic labels are exploratory-only")
        if category == "exploratory" and grade >= 2 and not labels:
            _fail(f"{query_id}/{row['document_id']}: exploratory grades need a subtopic label")
        by_query.setdefault(query_id, {})[row["document_id"]] = row

    for query in queries:
        judged = by_query.get(query["_id"], {})
        if not judged:
            _fail(f"{query['_id']}: no document judgments")
        if not any(row["grade"] >= 2 for row in judged.values()):
            _fail(f"{query['_id']}: no document reaches grade 2 or 3")

    # -- minima and assignment ------------------------------------------
    if spec.smoke:
        for query in queries:
            if query["split"] != "dev":
                _fail(f"{query['_id']}: sdc-smoke-v1 is dev-only")
        _check_smoke(queries)
    else:
        splits = assign_splits(queries, spec.split_seed)
        for query in queries:
            if query["split"] != splits[query["_id"]]:
                _fail(f"{query['_id']}: split does not match the SPEC-0004 5.4 assignment")
    counts: dict[str, int] = {"dev": 0, "test": 0}
    for query in queries:
        counts[query["split"]] += 1
    if check_minima and not spec.smoke:
        _check_minima(queries, counts)
    for query in queries:
        if query["language_slice"] == "non_latin_non_regression":
            if query["language"].split("-")[0].lower() in {"pt", "en"}:
                _fail(f"{query['_id']}: the non-Latin slice must stay non-Latin")
            if query["category"] not in config.TEMPLATE_CATEGORIES:
                _fail(f"{query['_id']}: non-Latin queries are non-regression only")

    # -- leak scan -------------------------------------------------------
    for row in [*queries, *documents, *passages]:
        blob = json.dumps(row, ensure_ascii=False)
        if _ABSOLUTE.search(blob):
            _fail("a record contains an absolute or personal path")
        if _SECRET.search(blob):
            _fail("a record contains a secret-like token")

    return {
        "queries": len(queries),
        "documents": len(documents),
        "passages": len(passages),
        "pools": len(pools),
        "splits": counts,
        "tool_drafted": sum(1 for origin in origins.values() if origin == "tool"),
        "llm_drafted": sum(1 for origin in origins.values() if origin == "llm"),
        "tool_config_sha256": sorted(tool_hashes)[0] if tool_hashes else None,
        "llm_prompt_hashes": len(llm_hashes),
        "language_copy": language_report(queries, documents, corpus) if corpus is not None else None,
    }


def language_report(queries: list[dict], documents: list[dict], corpus) -> dict:
    """Per-LLM-query language and no-copy audit (WP-1.4 hard gates).

    The expected language is the query's declared ``language``; the copy check
    runs the same guard as drafting against every document the query grades 3
    (the intended target and any judged relevant copy).
    """

    from .guard import guard_violation
    from .language import build_lexicons, detect_language

    lexicons = build_lexicons(corpus)
    targets: dict[str, list[str]] = {}
    for row in documents:
        if row["grade"] == 3:
            targets.setdefault(row["query_id"], []).append(row["document_id"])

    rows: list[dict] = []
    for query in queries:
        if not query["provenance"]["drafted_by"].startswith("llm:"):
            continue
        expected = query["language"].split("-")[0]
        detected = detect_language(query["text"], lexicons)
        reason = None
        for document_id in sorted(targets.get(query["_id"], [])):
            document = corpus.documents.get(document_id)
            if document is None:
                continue
            reason = guard_violation(query["text"], [document.title, document.text], config.GUARD)
            if reason is not None:
                break
        rows.append(
            {
                "query_id": query["_id"],
                "category": query["category"],
                "expected_language": expected,
                "detected_language": detected,
                "language_ok": detected == expected,
                "guard": reason,
                "ok": detected == expected and reason is None,
            }
        )
    language_failures = sum(1 for row in rows if not row["language_ok"])
    copy_failures = sum(1 for row in rows if row["guard"] is not None)
    summary = {
        "checked": len(rows),
        "language_failures": language_failures,
        "copy_failures": copy_failures,
        "failures": [
            row for row in rows if not row["ok"]
        ],
    }
    if language_failures or copy_failures:
        first = next(row for row in rows if not row["ok"])
        detail = (
            f"{first['query_id']} ({first['category']}, expected "
            f"{first['expected_language']}, detected {first['detected_language']}, "
            f"guard {first['guard']})"
        )
        _fail(
            f"LLM language/copy audit failed: {language_failures} wrong-language and "
            f"{copy_failures} copying queries; first failure {detail}"
        )
    return summary


def audit_directory(root: Path, *, check_minima: bool = True, corpus_root: Path | None = None) -> dict:
    manifest = load_json(root / "judgment-set.json")
    if manifest.get("state") != "draft":
        _fail("only a quarantined draft is audited here")
    spec = config.spec_for_set(str(manifest.get("judgment_set_id")))
    if manifest.get("judgment_set_id") != spec.set_id:
        _fail(f"judgment_set_id must be {spec.set_id}")
    if spec.smoke:
        if manifest.get("test_exposure") != "not-applicable":
            _fail("sdc-smoke-v1 test_exposure must be not-applicable")
        if manifest.get("test_pool_system_ids") != []:
            _fail("sdc-smoke-v1 must not declare a test pool panel")
    queries = read_jsonl(root / DRAFT_FILES[0])
    documents = read_jsonl(root / DRAFT_FILES[1])
    passages = read_jsonl(root / DRAFT_FILES[2])
    pools = read_jsonl(root / DRAFT_FILES[3])
    corpus = None
    if corpus_root is not None:
        from .corpus import Corpus

        corpus = Corpus.load(Path(corpus_root))
        if corpus.corpus_hash not in manifest["compatible_corpus_hashes"]:
            _fail("the corpus is not listed in compatible_corpus_hashes")
    expected = {
        "dev": sum(1 for query in queries if query["split"] == "dev"),
        "test": sum(1 for query in queries if query["split"] == "test"),
    }
    if manifest.get("query_counts") != expected:
        _fail("manifest query_counts disagree with the query records")
    return audit_rows(
        queries, documents, passages, pools, check_minima=check_minima, corpus=corpus, spec=spec
    )
