"""Run the ~1B-class Florence split-graph transcription proxy."""

from __future__ import annotations

import gc
import time
from pathlib import Path
from typing import Any

import numpy as np
import psutil
from PIL import Image

from .artifacts import sha256_file, write_json
from .benchmark import summarize_latencies
from .deadline import Deadline, GateTimeout, bounded_gate
from .metrics import character_error_rate, normalize_ocr_text, word_error_rate
from .ocr_data import load_ocr_manifest
from .system import RunningProfile, apply_profile, capture_environment, high_performance_power_scheme, wait_for_quiet_window

MAX_NEW_TOKENS = 1024
FIXED_PROMPT = "<OCR>"
TASK_PROMPT = "What is the text in the image?"
FIRST_PAGES = 3


class FlorenceRunError(RuntimeError):
    """Florence graph loading, preprocessing, or decoding failed."""


class _ProcessorShim:
    """Apply the frozen Florence task prompt and CLIP preprocessing."""

    def __init__(self, source_dir: Path) -> None:
        from transformers import BartTokenizerFast, CLIPImageProcessor

        self.tokenizer = BartTokenizerFast.from_pretrained(source_dir, local_files_only=True)
        self.image_processor = CLIPImageProcessor.from_pretrained(source_dir, local_files_only=True)

    def __call__(self, *, text: str, images: Image.Image, return_tensors: str):
        if text != FIXED_PROMPT:
            raise FlorenceRunError("only the fixed OCR task prompt is permitted")
        image_inputs = self.image_processor(images=images, return_tensors=return_tensors)
        text_inputs = self.tokenizer(TASK_PROMPT, return_tensors=return_tensors)
        return {
            "pixel_values": np.asarray(image_inputs["pixel_values"]),
            "input_ids": np.asarray(text_inputs["input_ids"], dtype=np.int64),
            "attention_mask": np.asarray(text_inputs["attention_mask"], dtype=np.int64),
        }


def _load_processor(source_dir: Path):
    try:
        return _ProcessorShim(source_dir)
    except FlorenceRunError:
        raise
    except Exception as error:
        raise FlorenceRunError("Florence tokenizer or image processor could not be loaded") from error


class _Bundle:
    def __init__(self, onnx_dir: Path, profile: RunningProfile, suffix: str) -> None:
        from .models import create_ort_session

        self.sessions: dict[str, Any] = {}
        for component in ("vision_encoder", "embed_tokens", "encoder_model", "decoder_model_merged"):
            path = onnx_dir / f"{component}{suffix}.onnx"
            if not path.is_file():
                raise FlorenceRunError(f"Florence component {component} is missing")
            self.sessions[component] = create_ort_session(path, profile)

    def close(self) -> None:
        self.sessions.clear()
        gc.collect()


def _image_batch(processor: Any, image_path: Path) -> dict[str, np.ndarray]:
    try:
        image = Image.open(image_path).convert("RGB")
        inputs = processor(text=FIXED_PROMPT, images=image, return_tensors="np")
    except Exception as error:
        raise FlorenceRunError("Florence processor rejected a rendered page") from error
    return {name: np.asarray(value) for name, value in inputs.items()}


def _run_named(session: Any, available: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    names = [item.name for item in session.get_inputs()]
    try:
        feeds = {name: available[name] for name in names}
    except KeyError as error:
        raise FlorenceRunError("Florence graph requests an input the processor did not produce") from error
    outputs = session.run(None, feeds)
    return {
        output.name: value
        for output, value in zip(session.get_outputs(), outputs, strict=True)
    }


def _decode(
    bundle: _Bundle,
    processor: Any,
    inputs: dict[str, np.ndarray],
    *,
    max_new_tokens: int = MAX_NEW_TOKENS,
    deadline: Deadline | None = None,
    stage: str = "decode",
) -> tuple[list[int], str]:
    generated: list[int] = []
    try:
        image_features = next(
            iter(_run_named(bundle.sessions["vision_encoder"], inputs).values())
        )
        prompt_ids = inputs["input_ids"]
        prompt_embeds = next(
            iter(_run_named(bundle.sessions["embed_tokens"], {"input_ids": prompt_ids}).values())
        )
        image_mask = np.ones(image_features.shape[:2], dtype=np.int64)
        prompt_mask = np.ones(prompt_embeds.shape[:2], dtype=np.int64)
        inputs_embeds = np.concatenate([image_features, prompt_embeds], axis=1)
        attention_mask = np.concatenate([image_mask, prompt_mask], axis=1)
        encoder = _run_named(
            bundle.sessions["encoder_model"],
            {"inputs_embeds": inputs_embeds, "attention_mask": attention_mask},
        )
        encoder_hidden = next(iter(encoder.values()))
        decoder = bundle.sessions["decoder_model_merged"]
        logits_name = decoder.get_outputs()[0].name
        feeds = {
            "use_cache_branch": np.array([False], dtype=np.bool_),
            "inputs_embeds": inputs_embeds[:, -1:],
            "encoder_hidden_states": encoder_hidden,
            "encoder_attention_mask": attention_mask,
        }
        for graph_input in decoder.get_inputs():
            if graph_input.name.startswith("past_key_values."):
                shape = graph_input.shape
                feeds[graph_input.name] = np.zeros(
                    (1, int(shape[1]), 0, int(shape[3])),
                    dtype=np.float32,
                )
        outputs = _run_named(decoder, feeds)
        encoder_past = {
            "past_key_values." + name[len("present.") :]: value
            for name, value in outputs.items()
            if name.startswith("present.") and ".encoder." in name
        }
        if not encoder_past:
            raise FlorenceRunError("Florence prefill returned no encoder KV cache")
        eos = processor.tokenizer.eos_token_id
        for step in range(max_new_tokens):
            if deadline is not None and step % 16 == 0:
                deadline.check(f"{stage}:token-{step}")
            token = int(np.argmax(outputs[logits_name][:, -1, :], axis=-1)[0])
            generated.append(token)
            if eos is not None and token == eos:
                break
            if len(generated) >= max_new_tokens:
                # The preregistered output bound (§3.2): keep the truncated
                # transcript; one more decoder step would pass the decoder's
                # position table.
                break
            next_embeds = next(
                iter(
                    _run_named(
                        bundle.sessions["embed_tokens"],
                        {"input_ids": np.array([[token]], dtype=np.int64)},
                    ).values()
                )
            )
            available = {
                "use_cache_branch": np.array([True], dtype=np.bool_),
                "inputs_embeds": next_embeds,
                "encoder_hidden_states": encoder_hidden,
                "encoder_attention_mask": attention_mask,
            }
            for output_name, value in outputs.items():
                if output_name.startswith("present.") and ".decoder." in output_name:
                    available["past_key_values." + output_name[len("present.") :]] = value
            available.update(encoder_past)
            outputs = _run_named(decoder, available)
        text = processor.tokenizer.decode(generated, skip_special_tokens=True)
        return generated, normalize_ocr_text(text)
    except FlorenceRunError:
        raise
    except Exception as error:
        raise FlorenceRunError(
            f"Florence greedy decode failed after {len(generated)} generated tokens"
        ) from error


def _time_and_score(
    bundle: _Bundle,
    processor: Any,
    image_paths: list[Path],
    truth: dict[str, str],
    *,
    deadline: Deadline | None = None,
    stage: str = "time-and-score",
) -> dict[str, Any]:
    pages = image_paths[:FIRST_PAGES]
    samples = []
    hypotheses: dict[str, str] = {}
    bounded: list[str] = []
    eos = processor.tokenizer.eos_token_id
    for index, path in enumerate(pages):
        if deadline is not None:
            deadline.check(f"{stage}:page-{index}")
        inputs = _image_batch(processor, path)
        started = time.perf_counter_ns()
        tokens, text = _decode(
            bundle,
            processor,
            inputs,
            deadline=deadline,
            stage=f"{stage}:page-{index}:decode",
        )
        samples.append((time.perf_counter_ns() - started) / 1_000_000_000)
        hypotheses[path.stem] = text
        if hit_token_bound(tokens, eos):
            bounded.append(path.stem)
    summary = summarize_latencies(samples, resamples=2_000)
    summary["early_stop_pages"] = FIRST_PAGES
    all_slow = all(value > 4.0 for value in samples)
    quality = {
        "CER": float(np.mean([character_error_rate(truth[key], hypotheses[key]) for key in hypotheses])),
        "WER": float(np.mean([word_error_rate(truth[key], hypotheses[key]) for key in hypotheses])),
    }
    return {
        "page": summary,
        "samples_seconds": samples,
        "quality": quality,
        "early_stop_all_above_4s": all_slow,
        "pages_at_token_bound": bounded,
        "hypotheses": hypotheses,
    }


def hit_token_bound(tokens: list[int], eos: int | None, max_new_tokens: int = MAX_NEW_TOKENS) -> bool:
    """A page that used the whole output bound without emitting EOS."""
    return len(tokens) >= max_new_tokens and (not tokens or tokens[-1] != eos)


def run_florence_gate(
    workspace: Path,
    *,
    profile: RunningProfile | None = None,
    wait_seconds: float = 900.0,
    deadline: Deadline | None = None,
) -> dict[str, Any]:
    gate_deadline = deadline or Deadline()
    selected_profile = profile or RunningProfile.t1_emulated()
    results: dict[str, Any] = {"schema": 1, "variants": {}}
    with bounded_gate(
        "florence",
        workspace=workspace,
        deadline=gate_deadline,
        results=results,
    ):
        profile_record = apply_profile(selected_profile)
        manifest, truth = load_ocr_manifest(workspace)
        image_paths = [workspace / "data" / "ocr" / page["image"] for page in manifest["pages"] if page["kind"] == "text"]
        source_dir = workspace / "models" / "florence-large-source"
        onnx_dir = workspace / "models" / "florence-large-onnx" / "onnx"
        if not source_dir.is_dir() or not onnx_dir.is_dir():
            raise FlorenceRunError("Florence source or split-graph assets are missing")
        processor = _load_processor(source_dir)
        baseline_rss = psutil.Process().memory_info().rss
        results.update(
            {
                "label": "T1-emulated, provisional",
                "model": "Florence-2-large",
                "repository": "microsoft/Florence-2-large",
                "onnx_repository": "onnx-community/Florence-2-large",
                "prompt": FIXED_PROMPT,
                "task_prompt": TASK_PROMPT,
                "max_new_tokens": MAX_NEW_TOKENS,
                "profile": profile_record,
                "environment": capture_environment(),
                "text_pages": len(image_paths),
                "baseline_rss_bytes": baseline_rss,
                "static_qdq": {
                    "attempted": False,
                    "reason": (
                        "The published split graphs expose dynamic KV-cache/control-flow inputs; "
                        "no static-shape export exists in the frozen asset set."
                    ),
                },
            }
        )
        reference_quality: dict[str, float] | None = None
        for name, suffix in (("fp32", ""), ("int8-dynamic", "_int8"), ("int4-matmulnbits", "_q4")):
            gate_deadline.check(f"florence:variant-{name}")
            bundle = None
            try:
                quiet = wait_for_quiet_window(
                    timeout_seconds=wait_seconds,
                    deadline=gate_deadline,
                )
                if not quiet["quiet"]:
                    results["variants"][name] = {"timing_skipped": "quiet window did not open"}
                    continue
                started = time.perf_counter()
                bundle = _Bundle(onnx_dir, selected_profile, suffix)
                cold_load = time.perf_counter() - started
                first_inputs = _image_batch(processor, image_paths[0])
                first_tokens, first_text = _decode(
                    bundle,
                    processor,
                    first_inputs,
                    deadline=gate_deadline,
                    stage=f"florence:{name}:first-decode",
                )
                repeat_inputs = _image_batch(processor, image_paths[0])
                repeat_tokens, repeat_text = _decode(
                    bundle,
                    processor,
                    repeat_inputs,
                    deadline=gate_deadline,
                    stage=f"florence:{name}:repeat-decode",
                )
                with high_performance_power_scheme(deadline=gate_deadline) as power:
                    measured = _time_and_score(
                        bundle,
                        processor,
                        image_paths,
                        truth,
                        deadline=gate_deadline,
                        stage=f"florence:{name}:timed",
                    )
                if reference_quality is None:
                    reference_quality = measured["quality"]
                files = []
                for component in ("vision_encoder", "embed_tokens", "encoder_model", "decoder_model_merged"):
                    gate_deadline.check(f"florence:{name}:size:{component}")
                    path = onnx_dir / f"{component}{suffix}.onnx"
                    files.append(
                        {
                            "filename": path.name,
                            "bytes": path.stat().st_size,
                            "sha256": sha256_file(path),
                        }
                    )
                model_bytes = sum(item["bytes"] for item in files)
                peak_rss = int(getattr(psutil.Process().memory_info(), "peak_wset", psutil.Process().memory_info().rss))
                quality_delta = measured["quality"]["CER"] - reference_quality["CER"]
                parity = {
                    "deterministic_repeat": first_tokens == repeat_tokens and first_text == repeat_text,
                    "CER_delta_vs_fp32": quality_delta,
                    "CER_parity_passed": quality_delta <= 0.005,
                }
                results["variants"][name] = {
                    "path_label": f"florence-large/{name}",
                    "providers": {key: session.get_providers() for key, session in bundle.sessions.items()},
                    "cold_load_seconds": cold_load,
                    "model_bytes": model_bytes,
                    "files": files,
                    "timing": {
                        "power": power,
                        "page": measured["page"],
                        "added_peak_rss_bytes_upper_bound": max(0, peak_rss - baseline_rss),
                    },
                    "quality": measured["quality"],
                    "parity": parity,
                    "parity_passed": parity["deterministic_repeat"] and parity["CER_parity_passed"],
                    "early_stop_all_above_4s": measured["early_stop_all_above_4s"],
                    "pages_at_token_bound": measured["pages_at_token_bound"],
                    "hypotheses_sha256": {
                        key: sha256_file_bytes(value.encode("utf-8")) for key, value in measured["hypotheses"].items()
                    },
                    "quiet_window": quiet,
                }
                raw_dir = workspace / "raw" / "florence"
                raw_dir.mkdir(parents=True, exist_ok=True)
                write_json(raw_dir / f"{name}.json", measured)
            except GateTimeout:
                raise
            except Exception as error:
                results["variants"][name] = {
                    "error": type(error).__name__,
                    "detail": str(error),
                    "parity_passed": False,
                }
            finally:
                if bundle is not None:
                    bundle.close()
            write_json(workspace / "results" / "florence.json", results)
    return results


def sha256_file_bytes(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()
