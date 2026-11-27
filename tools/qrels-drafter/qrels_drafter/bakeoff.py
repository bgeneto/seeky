"""Bounded head-to-head model bake-off on fixed, held-out drafting prompts.

WP-1.4 chooses between Qwen3-0.6B and Qwen2.5-1.5B-Instruct on this task rather
than on reputation: 24 fixed prompts (8 ``conceptual``, 8 ``cross_language`` in
both directions, 8 ``exploratory``) drawn from ``sdc-s`` targets. For each model
it records valid JSON, retries, an 8-token shingle copy check, language
correctness, query length, and median wall-clock latency. Grading prompts get a
small compliance probe because a drafter that cannot grade is useless here.

Decision rule (stated before the numbers): prefer the smaller model when it
matches the larger one on valid JSON, no-copy, language correctness, and grading
compliance, and is faster; otherwise keep the larger model. A tie goes to the
smaller/faster model.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from . import config
from .corpus import Corpus, tokenize
from .guard import guard_violation
from .model import ModelError, Runner, prompt_sha256
from .semantic import LlmDrafter, _json_object, _plain_query

_PT = {"de", "da", "do", "das", "dos", "para", "com", "que", "não", "uma", "um", "em", "no", "na", "por"}
_EN = {"the", "of", "with", "for", "and", "from", "in", "to", "on", "by", "a", "an", "is"}


def build_lexicons(corpus: Corpus) -> dict[str, set[str]]:
    """Word sets from the corpus per language, for a fair language check."""

    from collections import Counter

    documents: dict[str, Counter] = {"pt": Counter(), "en": Counter()}
    for doc in corpus.documents.values():
        lang = doc.lang
        if lang not in documents:
            continue
        documents[lang].update(set(tokenize(doc.title + " " + doc.text)))
    return {
        lang: {word for word, count in counts.items() if count >= 3 and len(word) >= 3}
        for lang, counts in documents.items()
    }


def detect_language(text: str, lexicons: dict[str, set[str]] | None = None) -> str:
    tokens = tokenize(text)
    folded = text.lower()
    if lexicons:
        scores = {
            lang: sum(1 for token in tokens if token in words)
            for lang, words in lexicons.items()
        }
        if scores["pt"] != scores["en"]:
            return "pt" if scores["pt"] > scores["en"] else "en"
        if any(ch in folded for ch in "ãõçáéíóúâêôà"):
            return "pt"
        return "unknown"
    pt = sum(1 for token in tokens if token in _PT) + (2 if any(ch in folded for ch in "ãõçáéíóúâêôà") else 0)
    en = sum(1 for token in tokens if token in _EN)
    if pt > en:
        return "pt"
    if en > pt:
        return "en"
    return "unknown"


def _spread(corpus: Corpus, category: str, lang: str, count: int, drafter: LlmDrafter):
    anchors = drafter._anchors(category, lang)
    if len(anchors) <= count:
        return anchors
    step = len(anchors) // count
    return [anchors[index * step] for index in range(count)]


def tasks(corpus: Corpus, drafter: LlmDrafter) -> list[dict]:
    """24 fixed prompts: deterministic, held out from nothing (the draft is new)."""

    out: list[dict] = []
    for lang, query_language in (("pt", "pt-BR"), ("en", "en-US")):
        for doc in _spread(corpus, "conceptual", lang, 4, drafter):
            out.append({"category": "conceptual", "anchor": doc.id, "language": query_language, "target": lang})
    for index in range(4):
        for doc in _spread(corpus, "conceptual", "en", 4, drafter)[index : index + 1]:
            out.append({"category": "cross_language", "anchor": doc.id, "language": "pt-BR", "target": "en"})
        for doc in _spread(corpus, "conceptual", "pt", 4, drafter)[index : index + 1]:
            out.append({"category": "cross_language", "anchor": doc.id, "language": "en-US", "target": "pt"})
    for lang, query_language in (("pt", "pt-BR"), ("en", "en-US")):
        for doc in _spread(corpus, "exploratory", lang, 4, drafter):
            out.append({"category": "exploratory", "anchor": doc.id, "language": query_language, "target": lang})
    return out


def _ask_once(runner: Runner, task: dict, category_prompt) -> dict:
    prompt, _ = category_prompt(task)
    attempts = 0
    strict_json = False
    query = ""
    latency: list[float] = []
    while attempts < 3:
        attempts += 1
        started = time.perf_counter()
        try:
            reply = runner.complete(prompt if attempts == 1 else prompt + "\n\nReply with the JSON object only.")
        except ModelError as exc:
            return {"error": str(exc), "attempts": attempts, "latency": 0.0}
        latency.append(time.perf_counter() - started)
        parsed = _json_object(reply)
        if parsed and isinstance(parsed.get("query"), str) and parsed["query"].strip():
            strict_json = True
            query = " ".join(parsed["query"].split())
            break
        if not query:
            query = _plain_query(reply)
    return {
        "query": query,
        "strict_json": strict_json,
        "attempts": attempts,
        "latency": statistics.median(latency) if latency else 0.0,
    }


def run_bakeoff(
    corpus_root: Path,
    models: dict[str, tuple[config.ModelPin, str]],
    llama_cli: str,
    threads: int = 8,
) -> dict:
    from .model import llama_cpp_runner

    corpus = Corpus.load(corpus_root)
    lexicons = build_lexicons(corpus)
    plan = tasks(corpus, LlmDrafter(corpus, None))  # anchors need only the corpus
    report: dict = {"tasks": plan, "models": {}}
    for profile, (pin, model_path) in models.items():
        runner = llama_cpp_runner(llama_cli, model_path, pin, threads)
        drafter = LlmDrafter(corpus, runner, pin)
        rows: list[dict] = []
        for task in plan:
            doc = corpus.documents[task["anchor"]]

            def category_prompt(task: dict, doc=doc, pin=pin):
                category = task["category"]
                if category == "conceptual":
                    return drafter._query_prompt("conceptual", doc, task["language"])
                if category == "exploratory":
                    return drafter._query_prompt("exploratory", doc, task["language"])
                return drafter._query_prompt("cross_language", doc, task["language"])

            result = _ask_once(runner, task, category_prompt)
            if "error" in result:
                rows.append({**task, "error": result["error"]})
                continue
            query = result["query"]
            reason = guard_violation(query, [doc.title, doc.text], config.GUARD)
            detected = detect_language(query, lexicons)
            rows.append(
                {
                    **task,
                    "query": query,
                    "strict_json": result["strict_json"],
                    "attempts": result["attempts"],
                    "copy_violation": reason,
                    "detected_language": detected,
                    "language_ok": detected == task["language"].split("-")[0],
                    "tokens": len(tokenize(query)),
                    "latency": round(result["latency"], 2),
                }
            )

        grade_ok = 0
        grade_rows: list[dict] = []
        for task in plan[:3]:
            doc = corpus.documents[task["anchor"]]
            candidates = drafter._candidates("conceptual", doc)[:4]
            prompt, mapping = drafter._grade_prompt("conceptual", task.get("query", "topic"), candidates)
            try:
                reply = runner.complete(prompt)
            except ModelError as exc:
                grade_rows.append({"error": str(exc)})
                continue
            parsed = _json_object(reply)
            grades = (
                [
                    item
                    for item in parsed.get("grades", [])
                    if isinstance(item, dict) and item.get("candidate") in mapping and isinstance(item.get("grade"), int)
                ]
                if parsed
                else []
            )
            grade_rows.append({"valid": bool(grades), "grades": len(grades)})
            grade_ok += 1 if grades else 0

        done = [row for row in rows if "query" in row]
        report["models"][profile] = {
            "model_id": pin.model_id,
            "revision": pin.revision,
            "weight_sha256": pin.weight_sha256,
            "quantization": pin.quantization,
            "decode": pin.decode,
            "queries": len(done),
            "strict_json": sum(1 for row in done if row["strict_json"]),
            "no_copy": sum(1 for row in done if not row["copy_violation"]),
            "language_ok": sum(1 for row in done if row["language_ok"]),
            "mean_tokens": round(statistics.mean(row["tokens"] for row in done), 1) if done else 0,
            "median_latency_s": round(statistics.median(row["latency"] for row in done), 2) if done else 0,
            "retries": sum(row["attempts"] - 1 for row in done),
            "grade_probe_valid": f"{grade_ok}/3",
            "rows": rows,
            "grade_rows": grade_rows,
        }
    return report


SMALL_MODEL = "qwen3-0.6b"
LARGE_MODEL = "qwen2.5-1.5b-instruct"
GATES = {"strict_json": 23, "no_copy": 20, "grade_probe_valid": "3/3"}
LANGUAGE_MARGIN = 2


def decide(report: dict) -> tuple[str, str]:
    """Apply the stated rule and return the chosen profile with the reason.

    Gates first (valid JSON, no-copy, grading compliance), then language
    correctness -- the check that separates instruction-following on this task
    -- and a tie goes to the smaller/faster model.
    """

    data = report["models"]

    def name_for(model_id: str) -> str:
        for name, row in data.items():
            if row["model_id"] == model_id:
                return name
        raise ValueError(f"{model_id} is missing from the bake-off report")

    small = name_for(SMALL_MODEL)
    large = name_for(LARGE_MODEL)

    def qualifies(row: dict) -> bool:
        return (
            row["strict_json"] >= GATES["strict_json"]
            and row["no_copy"] >= GATES["no_copy"]
            and row["grade_probe_valid"] == GATES["grade_probe_valid"]
        )

    a, b = data[small], data[large]
    if qualifies(a) != qualifies(b):
        chosen = small if qualifies(a) else large
        return chosen, "only one model passes the validity, no-copy, and grading gates"
    if not qualifies(a):
        return large, "neither model passes every gate; keep the incumbent 1.5B profile"
    if a["language_ok"] >= b["language_ok"] + LANGUAGE_MARGIN:
        return small, "materially better language correctness at equal validity and no-copy within tolerance"
    if b["language_ok"] >= a["language_ok"] + LANGUAGE_MARGIN:
        return large, "materially better language correctness"
    if a["median_latency_s"] <= b["median_latency_s"]:
        return small, "equivalent quality; the smaller, faster model wins the tie"
    return large, "equivalent quality and the smaller model is not faster"


def render_table(report: dict) -> str:
    lines = [
        "| Model | Quant | Strict JSON | No copy | Language | Mean words | Median latency | Retries | Grade probe |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, data in report["models"].items():
        lines.append(
            f"| {data['model_id']} | {data['quantization']} | "
            f"{data['strict_json']}/{data['queries']} | {data['no_copy']}/{data['queries']} | "
            f"{data['language_ok']}/{data['queries']} | {data['mean_tokens']} | "
            f"{data['median_latency_s']} s | {data['retries']} | {data['grade_probe_valid']} |"
        )
    return "\n".join(lines)


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
