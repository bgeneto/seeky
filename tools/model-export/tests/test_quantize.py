# WP-0.6: tiny synthetic quantization checks, not performance measurements.
import numpy as np
import onnx
from onnx import TensorProto, helper
import pytest

from seeky_model_export.quantize import (
    CalibrationDataReader,
    QuantizationError,
    quantize_dynamic_model,
    quantize_static_model,
)


def _matmul_graph(path, *, opset=17):
    weights = helper.make_tensor(
        "weights",
        TensorProto.FLOAT,
        [2, 2],
        [0.25, -0.5, 0.75, 1.0],
    )
    graph = helper.make_graph(
        [helper.make_node("MatMul", ["input", "weights"], ["output"])],
        "tiny-matmul",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 2])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 2])],
        [weights],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", opset)])
    model.ir_version = 10
    onnx.checker.check_model(model)
    onnx.save(model, path)


def _reader(model_path):
    class Reader(CalibrationDataReader):
        def __init__(self):
            self.model_path = str(model_path)
            self._rows = iter(
                [
                    {"input": np.array([[1.0, 2.0]], dtype=np.float32)},
                    {"input": np.array([[3.0, 4.0]], dtype=np.float32)},
                ]
            )

        def get_next(self):
            return next(self._rows, None)

    return Reader()


def test_dynamic_quantization_produces_a_valid_quantized_graph(tmp_path):
    source = tmp_path / "source.onnx"
    destination = tmp_path / "dynamic.onnx"
    _matmul_graph(source)
    quantize_dynamic_model(source, destination)
    model = onnx.load(destination)
    onnx.checker.check_model(model)
    operators = {node.op_type for node in model.graph.node}
    assert operators.intersection({"MatMulInteger", "QLinearMatMul", "QuantizeLinear"})


def test_static_qdq_upgrades_an_old_source_opset(tmp_path):
    source = tmp_path / "source.onnx"
    destination = tmp_path / "static.onnx"
    _matmul_graph(source, opset=11)
    quantize_static_model(source, destination, _reader(source))
    model = onnx.load(destination)
    onnx.checker.check_model(model)
    operators = {node.op_type for node in model.graph.node}
    assert "QuantizeLinear" in operators
    assert "DequantizeLinear" in operators


def test_quantization_rejects_missing_input(tmp_path):
    with pytest.raises(QuantizationError):
        quantize_dynamic_model(tmp_path / "missing.onnx", tmp_path / "out.onnx")
