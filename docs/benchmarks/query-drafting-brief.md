# Query drafting brief (model writer)

- **Status:** operational, not binding. SPEC-0004, ADR-0026, and
  [`judgment-review-prompt.md`](judgment-review-prompt.md) win where they
  differ.
- **Version:** v1 (2026-11-28). Any change to the text between the two
  `BRIEF` markers is a new version; never edit a version in place after a
  draft cites it.
- **Use:** an LLM drafting queries and their judgments by hand-reading the
  corpus (not through `qrels-drafter`) works from the block below. Every
  record it writes carries `drafted_by: llm:<model-id>@<revision>`,
  `llm_prompt_sha256` = SHA-256 of the UTF-8 text between the code fences of
  the block (exclusive of the fence lines), `state: draft`, and
  `verified_by: []`. The drafter never verifies its own records (ADR-0026);
  a different reviewer runs the review prompt on them.

<!-- BRIEF v1 BEGIN -->
```text
You draft evaluation queries and relevance judgments for a Seeky SDC judgment
set. You read the corpus yourself; you never copy text from an existing query.

INPUT
- The corpus directory: corpus.jsonl, passages.jsonl, duplicate-clusters.jsonl,
  versions.jsonl.
- The target: judgment set id, category, language slice, and how many queries.
- The existing queries of the set, to avoid near-duplicates.

QUERIES
1. Write what a real person would type: short, natural, in the query
   language. European Portuguese is the corpus variant; pt-BR spelling is fine.
2. Follow the category definitions of the review prompt exactly:
   - conceptual: the topic in the user's own words; no identifiers, codes, or
     exact titles from the targets; prefer words absent from the targets.
   - cross_language: natural in its own language; every relevant document is
     in the other language (language_slice cross_lingual).
   - exploratory: a broad need answered by several documents that cover
     different aspects.
3. Choose intents the corpus answers in more than one document where the
   category allows it, and never an intent whose only answer is a heading,
   a boilerplate line, or a bare reference number.
4. No near-duplicates: a new query differs from every other query of the set
   in intent or in target documents.

JUDGMENTS
5. Discovery first: for each query, search the passages of every document in
   the target languages for every way the corpus expresses the intent, and
   list every holder before grading.
6. Grade with the SPEC-0004 §5.5 rubric. Judge only documents in the query's
   target_languages; unjudged means absent.
   - conceptual and cross_language: a document whose passage states the
     answer is 3; a document with only a related statement is 1 or 2.
   - exploratory: name the aspects (query-local snake_case subtopic labels).
     A document covering two or more aspects is 3, one aspect 2; a document
     with only a heading or a contract deliverable on the topic is 1. Every
     grade 2/3 document lists all its aspects as labels.
7. Duplicates and versions: judge every member of a duplicate cluster and
   every version, on its own text; recency does not matter unless the query
   asks for it.
8. Evidence: every grade 2/3 document names its answer-bearing passages, each
   with its own passage judgment (3 when it states the answer); never a
   heading or boilerplate line. Grade 0/1 documents get one passage judgment
   for the passage that shows why.
9. Add a few explicit grade 0 documents from the same family that a lexical
   or semantic system could confuse with the targets, after checking that
   they do not hold the answer.
```
<!-- BRIEF v1 END -->

## Changelog

| Version | Date | Change |
|---|---|---|
| v1 | 2026-11-28 | First version, for the `sdc-smoke-v1` conceptual, cross_language, and exploratory queries drafted by `llm:claude-opus-5-5@claude-opus-5-5` |
