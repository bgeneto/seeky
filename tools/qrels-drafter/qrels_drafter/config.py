"""Versioned drafter configuration (SPEC-0004 4.6, 5.4).

The plan in this module is the input selection: which categories the
deterministic templates own, which need the local instruct model, how many
draft queries each stratum receives, and the guard thresholds. All of it is
hashed into every tool-drafted record's ``tool_config_sha256``.
"""

from __future__ import annotations

from dataclasses import dataclass

VERSION = "0.1.0"
TOOL_ID = "qrels-drafter"
JUDGMENT_SET_ID = "sdc-v1"
DRAFT_SEED = "sdc-v1-draft-v1"
SPLIT_SEED = "sdc-v1-split-v1"
SCHEMA_VERSION = 1

# SPEC-0004 4.6: a deterministic tool drafts only where copying is faithful.
TEMPLATE_CATEGORIES = (
    "known_item",
    "exact_identifier",
    "needle_in_haystack",
    "mixed_semantic_metadata",
    "filename_partial",
    "code_search",
)
LLM_CATEGORIES = ("conceptual", "exploratory", "cross_language")
CATEGORIES = (
    "known_item",
    "conceptual",
    "exact_identifier",
    "cross_language",
    "needle_in_haystack",
    "exploratory",
    "mixed_semantic_metadata",
    "code_search",
    "filename_partial",
)

# Slice -> monolingual BCP-47 tag. ``other`` cycles es/fr/de; ``non_latin``
# cycles ja/el. Their counts are per category, both splits together.
SLICE_LANGUAGE = {
    "pt": "pt-BR",
    "en": "en-US",
    "es": "es-ES",
    "fr": "fr-FR",
    "de": "de-DE",
    "ja": "ja-JP",
    "el": "el-GR",
}
OTHER_LANGUAGES = ("es", "fr", "de")
NON_LATIN_LANGUAGES = ("ja", "el")

# Draft queries per category and slice, dev plus test together. Every stratum
# (category, language_slice, configuration) is even by construction.
#
# ``needle_in_haystack`` is English-only because every long-report document in
# the committed sdc-s generation is ``en-US``; a Portuguese needle query would
# have no target. SPEC-0004 R17 sets no language minimum for this category.
PLAN = {
    "known_item": {"pt": 28, "en": 28, "other": 24, "non_latin": 8},
    "exact_identifier": {"pt": 24, "en": 24, "other": 24, "non_latin": 8},
    "needle_in_haystack": {"en": 80},
    "mixed_semantic_metadata": {"pt": 36, "en": 36, "other": 12},
    "filename_partial": {"pt": 28, "en": 28, "other": 16, "non_latin": 8},
    "code_search": {"en": 80},
    "conceptual": {"pt": 40, "en": 40},
    "exploratory": {"pt": 40, "en": 40},
    "cross_language": {"cross_lingual": 80},
}

# Minimums from SPEC-0004 R16/R17, restated so the drafter refuses to write a
# draft that could never pass split freeze.
MINIMA = {
    "total": 600,
    "per_split": 300,
    "per_category_per_split": 30,
    "monolingual_per_split": 40,
    "cross_lingual_per_split": 30,
    "other_language_total": 20,
    "non_latin_total": 10,
}
OTHER_LANGUAGES_MINIMUM = ("es", "fr", "de")

# Anti-copy guard for LLM drafts: a template that copies target wording would
# favour lexical retrieval (SPEC-0004 4.6, brief for WP-1.4).
GUARD = {
    "shingle_tokens": 8,
    "verbatim_tokens": 5,
}


@dataclass(frozen=True)
class ModelPin:
    """An immutable local instruct model profile."""

    profile: str
    repo: str
    model_id: str
    revision: str
    weight_sha256: str
    weight_file: str
    license: str
    quantization: str
    prompt_suffix: str
    strip_think: bool
    decode: dict

    @property
    def drafted_by(self) -> str:
        return f"llm:{self.model_id}@{self.revision}"

    def as_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "repo": self.repo,
            "model_id": self.model_id,
            "revision": self.revision,
            "weight_sha256": self.weight_sha256,
            "weight_file": self.weight_file,
            "license": self.license,
            "quantization": self.quantization,
            "decode": self.decode,
            "prompt_suffix": self.prompt_suffix,
        }


QWEN25_1_5B = ModelPin(
    profile="qwen2.5-1.5b-instruct",
    repo="Qwen/Qwen2.5-1.5B-Instruct-GGUF",
    model_id="qwen2.5-1.5b-instruct",
    revision="91cad51170dc346986eccefdc2dd33a9da36ead9",
    weight_sha256="6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
    weight_file="qwen2.5-1.5b-instruct-q4_k_m.gguf",
    license="Apache-2.0",
    quantization="Q4_K_M GGUF",
    prompt_suffix="",
    strip_think=False,
    decode={
        "temperature": 0.0,
        "top_k": 1,
        "top_p": 1.0,
        "presence_penalty": 0.0,
        "seed": 42,
        "max_tokens": 160,
    },
)

QWEN3_0_6B = ModelPin(
    profile="qwen3-0.6b",
    repo="Qwen/Qwen3-0.6B-GGUF",
    model_id="qwen3-0.6b",
    revision="23749fefcc72300e3a2ad315e1317431b06b590a",
    weight_sha256="9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031",
    weight_file="Qwen3-0.6B-Q8_0.gguf",
    license="Apache-2.0",
    quantization="Q8_0 GGUF",
    prompt_suffix=" /no_think",
    strip_think=True,
    decode={
        "temperature": 0.7,
        "top_k": 20,
        "top_p": 0.8,
        "presence_penalty": 1.5,
        "seed": 42,
        "max_tokens": 200,
    },
)

PROFILES = {profile.profile: profile for profile in (QWEN25_1_5B, QWEN3_0_6B)}
DEFAULT_PROFILE = "qwen3-0.6b"
DEFAULT_MODEL = PROFILES[DEFAULT_PROFILE]


def tool_config(corpus_hash: str) -> dict[str, object]:
    """The canonical configuration hashed into every tool-drafted record."""

    return {
        "tool": f"{TOOL_ID}@{VERSION}",
        "schema_version": SCHEMA_VERSION,
        "judgment_set_id": JUDGMENT_SET_ID,
        "draft_seed": DRAFT_SEED,
        "split_seed": SPLIT_SEED,
        "corpus_hash": corpus_hash,
        "plan": PLAN,
        "categories": list(TEMPLATE_CATEGORIES),
        "guard": GUARD,
        "languages": SLICE_LANGUAGE,
    }


def tool_config_sha256(corpus_hash: str) -> str:
    from .jsonio import canonical_sha256

    return canonical_sha256(tool_config(corpus_hash))


def drafted_by_tool() -> str:
    return f"tool:{TOOL_ID}@{VERSION}"
