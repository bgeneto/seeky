"""Run the preregistered PP-OCRv5 pipeline and quantization variants."""

from __future__ import annotations

import gc
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import psutil

from .artifacts import failure_reason, sha256_file, write_json
from .benchmark import summarize_latencies
from .deadline import Deadline, bounded_gate
from .metrics import (
    character_error_rate,
    normalize_ocr_text,
    strip_diacritics,
    word_error_rate,
)
from .ocr_data import load_ocr_manifest
from .quantize import ArrayCalibrationReader, quantize_dynamic_model, quantize_static_model
from .system import RunningProfile, apply_profile, capture_environment, high_performance_power_scheme, wait_for_quiet_window

TIMED_PASSES = 3
WARMUP_PAGES = 3


class OcrRunError(RuntimeError):
    """An OCR model, calibration, or measurement failure."""


# Preregistration amendment 4: PP-OCRv6 tiny replaces the PP-OCRv5 mobile
# proxy. Official Paddle ONNX exports, pinned by revision and SHA-256.
OCR_MODEL = "PP-OCRv6-tiny-det + PP-OCRv6-tiny-rec"
OCR_SLUG = "ppocrv6-tiny"
OCR_GRAPHS = {
    "det": (
        "PaddlePaddle/PP-OCRv6_tiny_det_onnx",
        "2ba1506c0380b8f0b03dd142459aac66d4421f6c",
        "193bab7a04fca699a6c82e6abb5b81bdb28177f0abd4062552b04908dafb19f8",
    ),
    "rec": (
        "PaddlePaddle/PP-OCRv6_tiny_rec_onnx",
        "2612ab37152ae0a677521bae4e1e3d4fb4cf7c30",
        "9ef676d6ed3c88256a2d92c640c44f25b0c40947e111b14b8be8f594091563e6",
    ),
}
_DET_POSTPROCESS_KEYS = ("thresh", "box_thresh", "unclip_ratio", "max_candidates")


@dataclass(frozen=True)
class OcrAssets:
    """The fp32 graphs plus the vendor recipe read from ``inference.yml``."""

    det: Path
    rec: Path
    keys: Path
    det_mean: tuple[float, ...]
    det_std: tuple[float, ...]
    det_postprocess: tuple[tuple[str, float], ...]


def det_recipe(config: dict[str, Any]) -> tuple[tuple[float, ...], tuple[float, ...], tuple[tuple[str, float], ...]]:
    """Normalization and DB post-processing as the vendor config states them."""
    try:
        ops = config["PreProcess"]["transform_ops"]
        normalize = next(op["NormalizeImage"] for op in ops if isinstance(op, dict) and "NormalizeImage" in op)
        post = config["PostProcess"]
        mean = tuple(float(value) for value in normalize["mean"])
        std = tuple(float(value) for value in normalize["std"])
        postprocess = tuple((key, float(post[key])) for key in _DET_POSTPROCESS_KEYS)
    except (KeyError, TypeError, ValueError, StopIteration) as error:
        raise OcrRunError("detector inference.yml lacks the normalization or DB recipe") from error
    if len(mean) != 3 or len(std) != 3 or any(value <= 0 for value in std):
        raise OcrRunError("detector normalization must have three channels")
    return mean, std, postprocess


def rec_characters(config: dict[str, Any]) -> list[str]:
    """The CTC dictionary; RapidOCR adds the blank and the space itself."""
    try:
        characters = [str(item) for item in config["PostProcess"]["character_dict"]]
    except (KeyError, TypeError) as error:
        raise OcrRunError("recognizer inference.yml lacks the character dictionary") from error
    if not characters or any("\n" in item or "\r" in item for item in characters):
        raise OcrRunError("recognizer character dictionary is empty or malformed")
    return characters


def _load_assets(workspace: Path, *, deadline: Deadline | None = None) -> OcrAssets:
    import os
    import shutil

    import yaml
    from huggingface_hub import hf_hub_download

    model_root = workspace / "models" / OCR_SLUG
    fp32_dir = workspace / "variants" / OCR_SLUG / "fp32"
    fp32_dir.mkdir(parents=True, exist_ok=True)
    configs: dict[str, dict[str, Any]] = {}
    graphs: dict[str, Path] = {}
    for role, (repository, revision, expected) in OCR_GRAPHS.items():
        if deadline is not None:
            deadline.check(f"ocr:prepare:download-{role}")
        try:
            paths = {
                name: Path(
                    hf_hub_download(
                        repo_id=repository,
                        filename=name,
                        revision=revision,
                        local_dir=model_root / role,
                        cache_dir=workspace / "cache" / "huggingface",
                    )
                )
                for name in ("inference.onnx", "inference.yml")
            }
        except Exception as error:
            raise OcrRunError("pinned PP-OCRv6 graph could not be downloaded") from error
        if sha256_file(paths["inference.onnx"]) != expected:
            raise OcrRunError("PP-OCRv6 graph does not match its pinned SHA-256")
        try:
            # BaseLoader keeps every dictionary entry a string ("~", "1", "on").
            configs[role] = yaml.load(paths["inference.yml"].read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        except (OSError, yaml.YAMLError) as error:
            raise OcrRunError("PP-OCRv6 inference.yml cannot be read") from error
        target = fp32_dir / f"{role}.onnx"
        if not target.exists():
            try:
                os.link(paths["inference.onnx"], target)
            except OSError:
                shutil.copy2(paths["inference.onnx"], target)
        graphs[role] = target
    mean, std, postprocess = det_recipe(configs["det"])
    characters = rec_characters(configs["rec"])
    try:
        import onnxruntime as ort

        session = ort.InferenceSession(str(graphs["rec"]), providers=["CPUExecutionProvider"])
        output_classes = session.get_outputs()[0].shape[-1]
    except Exception as error:
        raise OcrRunError("PP-OCRv6 recognizer cannot be loaded") from error
    check_dictionary(output_classes, characters)
    keys = model_root / "rec_keys.txt"
    keys.write_text("\n".join(characters) + "\n", encoding="utf-8")
    return OcrAssets(graphs["det"], graphs["rec"], keys, mean, std, postprocess)


def _new_engine(
    assets: OcrAssets,
    *,
    det_path: Path | None = None,
    rec_path: Path | None = None,
    threads: int = 8,
):
    try:
        from rapidocr import LangDet, LangRec, ModelType, OCRVersion, RapidOCR

        params: dict[str, Any] = {
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Det.lang_type": LangDet.MULTI,
            "Det.model_type": ModelType.TINY,
            "Det.model_path": str(det_path or assets.det),
            "Det.mean": list(assets.det_mean),
            "Det.std": list(assets.det_std),
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Rec.lang_type": LangRec.LATIN,
            "Rec.model_type": ModelType.TINY,
            "Rec.model_path": str(rec_path or assets.rec),
            "Rec.rec_keys_path": str(assets.keys),
            "Global.use_cls": False,
            "Global.model_root_dir": str(assets.keys.parent),
            "EngineConfig.onnxruntime.intra_op_num_threads": threads,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        }
        for key, value in assets.det_postprocess:
            params[f"Det.{key}"] = int(value) if key == "max_candidates" else value
        return RapidOCR(params=params)
    except Exception as error:
        raise OcrRunError("PP-OCR engine could not be initialized") from error


def check_dictionary(output_classes: object, characters: list[str]) -> None:
    """CTC classes must equal the dictionary plus RapidOCR's blank and space."""
    if isinstance(output_classes, int) and output_classes != len(characters) + 2:
        raise OcrRunError("recognizer output classes do not match its character dictionary")


def _page_text(engine: Any, image_path: Path) -> str:
    try:
        result = engine(image_path)
    except Exception as error:
        raise OcrRunError("PP-OCR page inference failed") from error
    texts = getattr(result, "txts", None)
    if texts is None:
        return ""
    return "\n".join(str(text) for text in texts)


def _input_name(graph: Path) -> str:
    try:
        import onnxruntime as ort

        return ort.InferenceSession(str(graph), providers=["CPUExecutionProvider"]).get_inputs()[0].name
    except Exception as error:
        raise OcrRunError("OCR graph cannot be loaded for calibration") from error


def _det_input(image_path: Path, assets: OcrAssets) -> np.ndarray:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise OcrRunError("rendered OCR page cannot be decoded")
    height, width = image.shape[:2]
    scale = 736.0 / min(height, width)
    target_width = max(32, ((round(width * scale) + 31) // 32) * 32)
    target_height = max(32, ((round(height * scale) + 31) // 32) * 32)
    resized = cv2.resize(
        image,
        (target_width, target_height),
        interpolation=cv2.INTER_LINEAR,
    )
    mean = np.asarray(assets.det_mean, dtype=np.float32)
    std = np.asarray(assets.det_std, dtype=np.float32)
    normalized = (resized.astype(np.float32) / 255.0 - mean) / std
    return np.transpose(normalized, (2, 0, 1))[None, ...]


def _rec_crops(engine: Any, image_path: Path) -> list[np.ndarray]:
    try:
        result = engine(image_path, use_rec=False)
    except Exception as error:
        raise OcrRunError("PP-OCR detector calibration pass failed") from error
    boxes = getattr(result, "boxes", None)
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None or boxes is None:
        raise OcrRunError("PP-OCR detector returned no calibration boxes")
    crops = []
    for box in boxes:
        points = np.asarray(box, dtype=np.float32)
        x0, y0 = np.maximum(np.floor(points.min(axis=0)).astype(int), 0)
        x1, y1 = np.ceil(points.max(axis=0)).astype(int)
        x1, y1 = min(x1, image.shape[1]), min(y1, image.shape[0])
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        crop = image[y0:y1, x0:x1]
        target_width = max(16, min(320, round(crop.shape[1] * 48 / crop.shape[0])))
        resized = cv2.resize(crop, (target_width, 48), interpolation=cv2.INTER_LINEAR)
        normalized = (resized.astype(np.float32) / 255.0 - 0.5) / 0.5
        crops.append(np.transpose(normalized, (2, 0, 1))[None, ...])
    if not crops:
        raise OcrRunError("PP-OCR produced no recognizer calibration crops")
    return crops


def _prepare_variants(
    workspace: Path,
    image_paths: list[Path],
    profile: RunningProfile,
    assets: OcrAssets,
    *,
    deadline: Deadline | None = None,
) -> tuple[dict[str, tuple[Path, Path]], dict[str, str]]:
    if deadline is not None:
        deadline.check("ocr:prepare:fp32")
    fp32_engine = _new_engine(assets, threads=profile.ort_threads)
    fp32_det, fp32_rec = assets.det, assets.rec
    _det_input(image_paths[0], assets)
    _page_text(fp32_engine, image_paths[0])
    variants = {"fp32": (fp32_det, fp32_rec)}
    variant_root = workspace / "variants" / OCR_SLUG
    dynamic_det = variant_root / "int8-dynamic" / "det.onnx"
    dynamic_rec = variant_root / "int8-dynamic" / "rec.onnx"
    if not dynamic_det.exists():
        if deadline is not None:
            deadline.check("ocr:prepare:int8-dynamic-det")
        quantize_dynamic_model(fp32_det, dynamic_det)
    if not dynamic_rec.exists():
        if deadline is not None:
            deadline.check("ocr:prepare:int8-dynamic-rec")
        quantize_dynamic_model(fp32_rec, dynamic_rec)
    variants["int8-dynamic"] = (dynamic_det, dynamic_rec)

    static_det = variant_root / "int8-static-qdq" / "det.onnx"
    static_rec = variant_root / "int8-static-qdq" / "rec.onnx"
    failures: dict[str, str] = {}
    if not static_det.exists():
        if deadline is not None:
            deadline.check("ocr:prepare:int8-static-det")
        det_name = _input_name(fp32_det)
        det_rows = []
        for index, path in enumerate(image_paths[:8]):
            if deadline is not None:
                deadline.check(f"ocr:prepare:int8-static-det:page-{index}")
            det_rows.append({det_name: _det_input(path, assets)})
        try:
            quantize_static_model(
                fp32_det,
                static_det,
                ArrayCalibrationReader(fp32_det, det_rows),
            )
        except Exception as error:
            failures["static_det"] = failure_reason(error)
    if not static_rec.exists():
        if deadline is not None:
            deadline.check("ocr:prepare:int8-static-rec")
        try:
            rec_name = _input_name(fp32_rec)
            rec_rows = []
            for index, path in enumerate(image_paths[:8]):
                if deadline is not None:
                    deadline.check(f"ocr:prepare:int8-static-rec:page-{index}")
                for crop in _rec_crops(fp32_engine, path)[:16]:
                    rec_rows.append({rec_name: crop})
                if len(rec_rows) >= 128:
                    break
            if len(rec_rows) < 32:
                raise OcrRunError("static recognizer calibration set is too small")
            quantize_static_model(
                fp32_rec,
                static_rec,
                ArrayCalibrationReader(fp32_rec, rec_rows[:128]),
            )
        except Exception as error:
            failures["static_rec"] = failure_reason(error)
    if static_det.exists() and static_rec.exists():
        variants["int8-static-qdq"] = (static_det, static_rec)
    return variants, failures


def _scores(truth: dict[str, str], hypotheses: dict[str, str]) -> dict[str, Any]:
    page_cer = []
    page_wer = []
    page_cer_insensitive = []
    page_wer_insensitive = []
    inserted_words = 0
    reference_words = 0
    for page_id, reference in truth.items():
        if not reference:
            continue
        hypothesis = hypotheses[page_id]
        page_cer.append(character_error_rate(reference, hypothesis))
        page_wer.append(word_error_rate(reference, hypothesis))
        page_cer_insensitive.append(
            character_error_rate(strip_diacritics(reference), strip_diacritics(hypothesis))
        )
        page_wer_insensitive.append(
            word_error_rate(strip_diacritics(reference), strip_diacritics(hypothesis))
        )
        reference_words += len(normalize_ocr_text(reference).split())
    for page_id, reference in truth.items():
        if reference:
            continue
        hypothesis = hypotheses[page_id]
        inserted_words += len(normalize_ocr_text(hypothesis).split())
    return {
        "CER": float(np.mean(page_cer)),
        "WER": float(np.mean(page_wer)),
        "CER_diacritic_insensitive": float(np.mean(page_cer_insensitive)),
        "WER_diacritic_insensitive": float(np.mean(page_wer_insensitive)),
        "page_CER_p50": float(np.median(page_cer)),
        "page_CER_p95": float(np.percentile(page_cer, 95)),
        "inserted_word_rate_clean": inserted_words / reference_words,
        "no_text_pages_with_output": sum(
            bool(normalize_ocr_text(hypotheses[page_id]))
            for page_id, reference in truth.items()
            if not reference
        ),
        "no_text_page_count": sum(not reference for reference in truth.values()),
    }


def run_ocr_gate(
    workspace: Path,
    *,
    profile: RunningProfile | None = None,
    wait_seconds: float = 900.0,
    deadline: Deadline | None = None,
) -> dict[str, Any]:
    gate_deadline = deadline or Deadline()
    base_profile = profile or RunningProfile.t1_emulated()
    selected_profile = replace(base_profile, background=True)
    results: dict[str, Any] = {"schema": 1, "variants": {}}
    with bounded_gate(
        "ocr",
        workspace=workspace,
        deadline=gate_deadline,
        results=results,
    ):
        profile_record = apply_profile(selected_profile)
        manifest, truth = load_ocr_manifest(workspace)
        image_paths = [workspace / "data" / "ocr" / page["image"] for page in manifest["pages"] if page["kind"] == "text"]
        baseline_rss = psutil.Process().memory_info().rss
        assets = _load_assets(workspace, deadline=gate_deadline)
        variants, variant_failures = _prepare_variants(
            workspace,
            image_paths,
            selected_profile,
            assets,
            deadline=gate_deadline,
        )
        results.update(
            {
                "label": "T1-emulated, provisional",
                "model": OCR_MODEL,
                "amendment": 4,
                "graphs": {
                    role: {"repository": repository, "revision": revision, "sha256": sha256}
                    for role, (repository, revision, sha256) in OCR_GRAPHS.items()
                },
                "detector_recipe": {
                    "mean": list(assets.det_mean),
                    "std": list(assets.det_std),
                    **dict(assets.det_postprocess),
                },
                "profile": profile_record,
                "environment": capture_environment(),
                "page_count": len(truth),
                "text_page_count": len(image_paths),
                "no_text_page_count": len(truth) - len(image_paths),
                "timed_passes": TIMED_PASSES,
                "warmup_pages": WARMUP_PAGES,
                "baseline_rss_bytes": baseline_rss,
                "variant_failures": variant_failures,
            }
        )
        reference_hypotheses: dict[str, str] | None = None
        for name, (det_path, rec_path) in variants.items():
            gate_deadline.check(f"ocr:variant-{name}")
            gc.collect()
            started = time.perf_counter()
            try:
                engine = _new_engine(
                    assets,
                    det_path=det_path,
                    rec_path=rec_path,
                    threads=selected_profile.ort_threads,
                )
                cold_load_seconds = time.perf_counter() - started
                hypotheses: dict[str, str] = {}
                for index, record in enumerate(manifest["pages"]):
                    gate_deadline.check(f"ocr:{name}:page-{index}")
                    hypotheses[record["id"]] = _page_text(
                        engine,
                        workspace / "data" / "ocr" / record["image"],
                    )
                gate_deadline.check(f"ocr:{name}:deterministic")
                deterministic = _page_text(engine, image_paths[0]) == hypotheses[image_paths[0].stem]
            except OcrRunError as error:
                # An unsupported variant is a reported result (preregistration
                # §2), never a reason to abandon the remaining variants.
                variant_failures[name] = failure_reason(error)
                results["variant_failures"] = variant_failures
                write_json(workspace / "results" / "ocr.json", results)
                continue
            if reference_hypotheses is None:
                if name != "fp32":
                    # A quantized output is never its own reference (§2).
                    variant_failures[name] = "no fp32 reference output"
                    results["variant_failures"] = variant_failures
                    write_json(workspace / "results" / "ocr.json", results)
                    continue
                reference_hypotheses = hypotheses
            quality = _scores(truth, hypotheses)
            quality["reference_CER_delta"] = quality["CER"] - _scores(truth, reference_hypotheses)["CER"]
            quality["reference_inserted_word_rate_delta"] = (
                quality["inserted_word_rate_clean"]
                - _scores(truth, reference_hypotheses)["inserted_word_rate_clean"]
            )
            passes_parity = quality["reference_CER_delta"] <= 0.005 and quality["reference_inserted_word_rate_delta"] <= 0
            variant_dir = det_path.parent
            files = []
            for index, path in enumerate(sorted(variant_dir.glob("*.onnx*"))):
                gate_deadline.check(f"ocr:{name}:size-file-{index}")
                files.append(
                    {"filename": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
                )
            model_bytes = sum(item["bytes"] for item in files)
            variant_result: dict[str, Any] = {
                "path_label": f"{OCR_SLUG}/{name}",
                "cold_load_seconds": cold_load_seconds,
                "model_bytes": model_bytes,
                "files": files,
                "deterministic_repeat": deterministic,
                "quality": quality,
                "parity_passed": passes_parity and deterministic,
                "timing": None,
            }
            if variant_result["parity_passed"]:
                quiet = wait_for_quiet_window(
                    timeout_seconds=wait_seconds,
                    deadline=gate_deadline,
                )
                variant_result["quiet_window"] = quiet
                if quiet["quiet"]:
                    for index, path in enumerate(image_paths[:WARMUP_PAGES]):
                        gate_deadline.check(f"ocr:{name}:warmup-{index}")
                        _page_text(engine, path)
                    samples = []
                    with high_performance_power_scheme(deadline=gate_deadline) as power:
                        for timed_pass in range(TIMED_PASSES):
                            for index, path in enumerate(image_paths):
                                gate_deadline.check(
                                    f"ocr:{name}:pass-{timed_pass}:page-{index}"
                                )
                                started = time.perf_counter_ns()
                                _page_text(engine, path)
                                samples.append((time.perf_counter_ns() - started) / 1_000_000_000)
                    timing = summarize_latencies(samples, resamples=2_000)
                    timing["passes"] = TIMED_PASSES
                    timing["background_priority"] = True
                    peak_rss = int(getattr(psutil.Process().memory_info(), "peak_wset", psutil.Process().memory_info().rss))
                    variance = {
                        "power": power,
                        "page": timing,
                        "added_peak_rss_bytes_upper_bound": max(0, peak_rss - baseline_rss),
                    }
                    variant_result["timing"] = variance
                    raw_dir = workspace / "raw" / "ocr"
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    write_json(raw_dir / f"{name}-page-timings.json", {"seconds": samples})
                else:
                    variant_result["timing_skipped"] = "quiet window did not open"
            results["variants"][name] = variant_result
            write_json(workspace / "results" / "ocr.json", results)
            del engine
            gc.collect()
    return results
