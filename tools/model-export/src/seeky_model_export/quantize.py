"""ONNX Runtime dynamic and static-QDQ quantization wrappers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import onnx
from onnx import version_converter
from onnxruntime.quantization import (
    CalibrationDataReader,
    CalibrationMethod,
    QuantFormat,
    QuantType,
    quantize_dynamic,
    quantize_static,
)


class QuantizationError(RuntimeError):
    """A typed quantization failure."""


def quantize_dynamic_model(
    source: str | Path,
    destination: str | Path,
    *,
    op_types: list[str] | None = None,
) -> Path:
    source_path = Path(source)
    output_path = Path(destination)
    if not source_path.is_file():
        raise QuantizationError("dynamic quantization input model is missing")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        quantize_dynamic(
            source_path,
            output_path,
            op_types_to_quantize=op_types,
            per_channel=True,
            reduce_range=False,
            weight_type=QuantType.QInt8,
            use_external_data_format=True,
        )
    except Exception as error:
        raise QuantizationError("ONNX Runtime dynamic quantization failed") from error
    return output_path


def _remove_failed_quantization(output_path: Path) -> None:
    for path in (output_path, output_path.with_name(output_path.name + ".data")):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _static_quantization_source(source_path: Path, output_path: Path) -> Path:
    model = onnx.load(source_path)
    default_opset = next(
        (item.version for item in model.opset_import if item.domain in {"", "ai.onnx"}),
        0,
    )
    if default_opset >= 13:
        return source_path
    try:
        converted = version_converter.convert_version(model, 13)
        temporary = output_path.with_name(f".{output_path.stem}-opset13.onnx")
        onnx.save(converted, temporary)
        return temporary
    except Exception as error:
        raise QuantizationError("model opset cannot be upgraded for static QDQ") from error


def quantize_static_model(
    source: str | Path,
    destination: str | Path,
    calibration_reader: CalibrationDataReader,
    *,
    op_types: list[str] | None = None,
) -> Path:
    source_path = Path(source)
    output_path = Path(destination)
    if not source_path.is_file():
        raise QuantizationError("static quantization input model is missing")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    quant_source = _static_quantization_source(source_path, output_path)
    try:
        quantize_static(
            quant_source,
            output_path,
            calibration_reader,
            quant_format=QuantFormat.QDQ,
            op_types_to_quantize=op_types,
            per_channel=True,
            reduce_range=False,
            activation_type=QuantType.QUInt8,
            weight_type=QuantType.QInt8,
            use_external_data_format=True,
            calibrate_method=CalibrationMethod.MinMax,
            calibration_providers=["CPUExecutionProvider"],
        )
        import onnxruntime as ort

        ort.InferenceSession(str(output_path), providers=["CPUExecutionProvider"])
    except Exception as error:
        _remove_failed_quantization(output_path)
        raise QuantizationError("ONNX Runtime static QDQ quantization failed") from error
    finally:
        if quant_source != source_path:
            quant_source.unlink(missing_ok=True)
    return output_path


class ArrayCalibrationReader(CalibrationDataReader):
    """Iterate finite pre-tokenized calibration arrays for one ONNX graph."""

    def __init__(self, model_path: str | Path, rows: list[dict[str, Any]]) -> None:
        self.model_path = str(model_path)
        if not rows:
            raise QuantizationError("static calibration set must not be empty")
        self._rows: Iterator[dict[str, Any] | None] = iter(rows)

    def get_next(self) -> dict[str, Any] | None:
        return next(self._rows, None)
