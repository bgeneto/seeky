"""Immutable proxy assets, lazy reference loaders, and ONNX Runtime sessions."""

from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .artifacts import sha256_file
from .system import RunningProfile


class ModelError(RuntimeError):
    """A typed model identity, export, or inference failure."""


@dataclass(frozen=True)
class ModelSpec:
    slug: str
    repository: str
    revision: str
    task: str
    pooling: str

    def __post_init__(self) -> None:
        if not self.slug or "/" not in self.repository or self.repository.startswith("/"):
            raise ModelError("model repository identity is incomplete")
        if len(self.revision) != 40:
            raise ModelError("model revision must be an immutable full commit hash")
        try:
            int(self.revision, 16)
        except ValueError as error:
            raise ModelError("model revision must be hexadecimal") from error
        if self.pooling not in {"mean", "cls", "logits"}:
            raise ModelError("unsupported model output pooling")


ENCODER_SPECS = {
    "e5-small": ModelSpec(
        "e5-small",
        "intfloat/multilingual-e5-small",
        "614241f622f53c4eeff9890bdc4f31cfecc418b3",
        "feature-extraction",
        "mean",
    ),
    "granite-modernbert": ModelSpec(
        "granite-modernbert",
        "ibm-granite/granite-embedding-97m-multilingual-r2",
        "835ad14087e140460703cf0fae09f97d469d65c2",
        "feature-extraction",
        "cls",
    ),
    "gte-reranker": ModelSpec(
        "gte-reranker",
        "Alibaba-NLP/gte-multilingual-reranker-base",
        "9ba3cad4568fc0c9299265c963d1eb11df23840d",
        "text-classification",
        "logits",
    ),
}

FLORENCE_REPOSITORY = "microsoft/Florence-2-large"
FLORENCE_REVISION = "21a599d414c4d928c9032694c424fb94458e3594"
FLORENCE_ONNX_REPOSITORY = "onnx-community/Florence-2-large"
FLORENCE_ONNX_REVISION = "b7751295927207b2a8c2f354af8baadea5b0404b"

_TOKENIZER_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "sentence_bert_config.json",
    "modules.json",
    "1_Pooling/config.json",
)


def model_directory(workspace: Path, spec: ModelSpec) -> Path:
    return workspace / "models" / spec.slug


def download_encoder_assets(workspace: Path, spec: ModelSpec) -> Path:
    destination = model_directory(workspace, spec)
    destination.mkdir(parents=True, exist_ok=True)
    patterns = [*_TOKENIZER_FILES, "model.safetensors"]
    if spec.slug in {"e5-small", "granite-modernbert"}:
        patterns.append("onnx/model.onnx")
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=spec.repository,
            revision=spec.revision,
            allow_patterns=patterns,
            local_dir=destination,
            cache_dir=workspace / "cache" / "huggingface",
        )
    except Exception as error:
        raise ModelError("immutable model snapshot could not be downloaded") from error
    return destination


def download_florence_assets(workspace: Path, *, variants: Iterable[str] = ("fp32",)) -> dict[str, Path]:
    """Download source and selected split graphs, never into a worktree."""
    source_dir = workspace / "models" / "florence-large-source"
    onnx_dir = workspace / "models" / "florence-large-onnx"
    source_dir.mkdir(parents=True, exist_ok=True)
    onnx_dir.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=FLORENCE_REPOSITORY,
            revision=FLORENCE_REVISION,
            allow_patterns=[
                "*.json",
                "*.py",
                "*.jinja",
                "*.txt",
                "*.model",
                "model.safetensors",
                "LICENSE",
            ],
            local_dir=source_dir,
            cache_dir=workspace / "cache" / "huggingface",
        )
        graph_names = {
            "vision_encoder",
            "encoder_model",
            "embed_tokens",
            "decoder_model_merged",
        }
        suffixes = {"fp32": "", "int8": "_int8", "q4": "_q4"}
        patterns = ["*.json", "*.txt", "LICENSE"]
        for variant in variants:
            if variant not in suffixes:
                raise ModelError("unsupported Florence variant requested")
            suffix = suffixes[variant]
            patterns.extend(f"onnx/{name}{suffix}.onnx" for name in graph_names)
        snapshot_download(
            repo_id=FLORENCE_ONNX_REPOSITORY,
            revision=FLORENCE_ONNX_REVISION,
            allow_patterns=patterns,
            local_dir=onnx_dir,
            cache_dir=workspace / "cache" / "huggingface",
        )
    except ModelError:
        raise
    except Exception as error:
        raise ModelError("Florence split-graph assets could not be downloaded") from error
    return {"source": source_dir, "onnx": onnx_dir}


def manifest_for_directory(directory: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or ".cache" in path.parts:
            continue
        records.append(
            {
                "filename": path.relative_to(directory).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not records:
        raise ModelError("model directory is empty")
    return records


def pool_hidden(
    hidden: object,
    attention_mask: object,
    pooling: str,
    *,
    normalize: bool = False,
) -> np.ndarray:
    output = np.asarray(hidden, dtype=np.float32)
    mask = np.asarray(attention_mask)
    if not np.isfinite(output).all():
        raise ModelError("model output contains non-finite values")
    if pooling == "logits":
        if output.ndim != 2 or output.shape[1] != 1:
            raise ModelError("reranker output must have shape [batch, 1]")
        return output[:, 0]
    if output.ndim != 3 or mask.shape != output.shape[:2]:
        raise ModelError("encoder output and attention mask have incompatible shapes")
    if pooling == "cls":
        pooled = output[:, 0, :]
    elif pooling == "mean":
        weights = mask.astype(np.float32)
        if np.any(np.sum(weights, axis=1) <= 0):
            raise ModelError("attention mask contains an empty sequence")
        pooled = np.sum(output * weights[:, :, None], axis=1) / np.sum(weights, axis=1)[:, None]
    else:
        raise ModelError("unsupported model output pooling")
    if normalize:
        norms = np.linalg.norm(pooled, axis=1)
        if np.any(norms == 0):
            raise ModelError("cannot normalize a zero embedding")
        pooled = pooled / norms[:, None]
    return pooled


def load_tokenizer(model_dir: Path):
    try:
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    except Exception as error:
        raise ModelError("local tokenizer could not be loaded") from error


def tokenize(
    tokenizer: Any,
    texts: list[str],
    *,
    pair_texts: list[str] | None = None,
    max_length: int,
    pad_to_max: bool = False,
) -> dict[str, np.ndarray]:
    """Truncate at max_length; only fixed-shape graphs request max padding."""
    if not texts or (pair_texts is not None and len(texts) != len(pair_texts)):
        raise ModelError("tokenization inputs must be non-empty and paired")
    padding = "max_length" if pad_to_max else True
    try:
        if pair_texts is None:
            encoded = tokenizer(
                texts,
                padding=padding,
                truncation=True,
                max_length=max_length,
                return_tensors="np",
            )
        else:
            encoded = tokenizer(
                texts,
                pair_texts,
                padding=padding,
                truncation=True,
                max_length=max_length,
                return_tensors="np",
            )
    except Exception as error:
        raise ModelError("tokenization failed") from error
    return {name: np.asarray(value, dtype=np.int64) for name, value in encoded.items()}


def create_ort_session(
    model_path: Path,
    profile: RunningProfile,
    *,
    providers: list[Any] | None = None,
    disable_cpu_fallback: bool = False,
    verbose: bool = False,
):
    try:
        import onnxruntime as ort
    except ImportError as error:
        raise ModelError("ONNX Runtime is not installed in this environment") from error
    if not model_path.is_file():
        raise ModelError("ONNX model file does not exist")
    options = ort.SessionOptions()
    options.intra_op_num_threads = profile.ort_threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.log_severity_level = 0 if verbose else 3
    options.log_verbosity_level = 1 if verbose else 0
    if disable_cpu_fallback:
        options.add_session_config_entry("session.disable_cpu_ep_fallback", "1")
    try:
        return ort.InferenceSession(
            str(model_path),
            sess_options=options,
            providers=providers or ["CPUExecutionProvider"],
        )
    except Exception as error:
        raise ModelError("ONNX Runtime session creation failed") from error


def complete_graph_inputs(
    session: Any,
    encoded: dict[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """Drop extras and synthesize the standard zero id inputs some exports require."""
    names = {item.name for item in session.get_inputs()}
    inputs = {name: value for name, value in encoded.items() if name in names}
    if "input_ids" not in inputs or "attention_mask" not in inputs:
        raise ModelError("tokenized inputs do not match ONNX graph inputs")
    missing = names.difference(inputs)
    for name in missing:
        if name == "token_type_ids":
            inputs[name] = np.zeros_like(inputs["attention_mask"], dtype=np.int64)
        elif name == "position_ids":
            sequence = inputs["attention_mask"].shape[1]
            inputs[name] = np.broadcast_to(
                np.arange(sequence, dtype=np.int64),
                inputs["attention_mask"].shape,
            ).copy()
        else:
            raise ModelError("tokenized inputs do not match ONNX graph inputs")
    return inputs


def run_encoder_session(
    session: Any,
    encoded: dict[str, np.ndarray],
    spec: ModelSpec,
) -> np.ndarray:
    inputs = complete_graph_inputs(session, encoded)
    try:
        outputs = session.run(None, inputs)
    except Exception as error:
        raise ModelError("ONNX Runtime encoder execution failed") from error
    if not outputs:
        raise ModelError("ONNX graph returned no outputs")
    mask = encoded.get("attention_mask")
    if mask is None:
        raise ModelError("attention_mask is required for output pooling")
    return pool_hidden(outputs[0], mask, spec.pooling, normalize=spec.pooling != "logits")


def load_reference_model(model_dir: Path, spec: ModelSpec):
    try:
        import torch
        from transformers import AutoModel, AutoModelForSequenceClassification

        torch.set_num_threads(os.cpu_count() or 1)
        if spec.task == "text-classification":
            model = AutoModelForSequenceClassification.from_pretrained(
                model_dir,
                local_files_only=True,
                dtype=torch.float32,
            )
        else:
            model = AutoModel.from_pretrained(
                model_dir,
                local_files_only=True,
                dtype=torch.float32,
            )
        return model.eval()
    except Exception as error:
        raise ModelError("PyTorch reference model could not be loaded") from error


def run_reference_model(
    model: Any,
    encoded: dict[str, np.ndarray],
    spec: ModelSpec,
) -> np.ndarray:
    try:
        import torch

        accepted = set(inspect.signature(model.forward).parameters)
        tensors = {
            name: torch.from_numpy(value)
            for name, value in encoded.items()
            if name in accepted
        }
        with torch.inference_mode():
            result = model(**tensors)
        if spec.task == "text-classification":
            output = result.logits
        elif hasattr(result, "last_hidden_state"):
            output = result.last_hidden_state
        else:
            output = result[0]
        numpy_output = output.detach().cpu().numpy()
    except Exception as error:
        raise ModelError("PyTorch reference execution failed") from error
    mask = encoded.get("attention_mask")
    if mask is None:
        raise ModelError("attention_mask is required for reference pooling")
    return pool_hidden(numpy_output, mask, spec.pooling, normalize=spec.pooling != "logits")


def export_embedder_static_fp32(
    model_dir: Path,
    destination: Path,
    spec: ModelSpec,
    *,
    batch_size: int = 1,
    sequence_length: int = 32,
) -> Path:
    if spec.task != "feature-extraction":
        raise ModelError("static embedder export requires a feature-extraction model")
    if batch_size <= 0 or sequence_length <= 0:
        raise ModelError("static export shapes must be positive")
    model = load_reference_model(model_dir, spec)
    tokenizer = load_tokenizer(model_dir)
    encoded = tokenize(
        tokenizer,
        ["static export query"] * batch_size,
        max_length=sequence_length,
    )
    try:
        import torch

        accepted = set(inspect.signature(model.forward).parameters)
        inputs = {
            name: torch.from_numpy(value)
            for name, value in encoded.items()
            if name in accepted
        }
        names = list(inputs)
        destination.parent.mkdir(parents=True, exist_ok=True)
        torch.onnx.export(
            model,
            (),
            str(destination),
            kwargs=inputs,
            input_names=names,
            output_names=["last_hidden_state"],
            dynamic_axes=None,
            opset_version=17,
            do_constant_folding=True,
            dynamo=False,
        )
    except Exception as error:
        raise ModelError("static fp32 embedder ONNX export failed") from error
    return destination


def export_reranker_fp32(model_dir: Path, destination: Path, spec: ModelSpec) -> Path:
    if spec.task != "text-classification":
        raise ModelError("only the reranker uses this export helper")
    model = load_reference_model(model_dir, spec)
    tokenizer = load_tokenizer(model_dir)
    encoded = tokenize(
        tokenizer,
        ["export query"],
        pair_texts=["export passage"],
        max_length=8,
    )
    try:
        import torch

        accepted = set(inspect.signature(model.forward).parameters)
        inputs = {
            name: torch.from_numpy(value)
            for name, value in encoded.items()
            if name in accepted
        }
        names = list(inputs)
        destination.parent.mkdir(parents=True, exist_ok=True)
        torch.onnx.export(
            model,
            (),
            str(destination),
            kwargs=inputs,
            input_names=names,
            output_names=["logits"],
            dynamic_axes={name: {0: "batch", 1: "sequence"} for name in names},
            opset_version=17,
            do_constant_folding=True,
            dynamo=False,
        )
    except Exception as error:
        raise ModelError("fp32 reranker ONNX export failed") from error
    return destination
