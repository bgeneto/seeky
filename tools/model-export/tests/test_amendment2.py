# WP-0.6 preregistration amendment 2: supplementary embedders (bekko-a8m,
# gety-embed-v0) run under the embedder rules but never change the frozen K1.
import numpy as np
import onnx
import onnxruntime as ort
import pytest
from onnx import TensorProto, helper, numpy_helper

from seeky_model_export.artifacts import write_json
from seeky_model_export.frozen import embedding_view
from seeky_model_export.models import (
    ENCODER_SPECS,
    PROXY_EMBEDDERS,
    SUPPLEMENTARY_EMBEDDERS,
    ModelError,
    pool_hidden,
    run_encoder_session,
    upcast_fp16_model,
)
from seeky_model_export.report_export import export_results


def test_amendment_specs_pin_immutable_revisions_and_stay_supplementary():
    assert SUPPLEMENTARY_EMBEDDERS == ("bekko-a8m", "gety-embed-v0")
    assert set(SUPPLEMENTARY_EMBEDDERS).isdisjoint(PROXY_EMBEDDERS)
    bekko = ENCODER_SPECS["bekko-a8m"]
    assert bekko.repository == "hotchpotch/bekko-embedding-v1-a8m"
    assert bekko.revision == "c721113d59a1d91b447450324f51c4b3332c924a"
    assert bekko.reference == "pytorch"
    gety = ENCODER_SPECS["gety-embed-v0"]
    assert gety.repository == "gety-ai/gety-embed-v0"
    assert gety.revision == "424f41cb36776481b7e2c9f619ca7ce5d5351fe0"
    assert gety.reference == "fp16-upcast"
    assert not gety.derive_quantized


def test_gety_uses_e5_prefixes_and_bekko_uses_none():
    frozen = {
        "schema": 1,
        "miracl": {"queries": [{"id": "q", "text": "what"}], "passages": [{"id": "p", "text": "this"}]},
        "mmarco": {"queries": [{"id": "q", "text": "o que"}], "passages": [{"id": "p", "text": "isto"}]},
    }
    gety = embedding_view(frozen, "gety-embed-v0")
    bekko = embedding_view(frozen, "bekko-a8m")
    assert gety["queries"][0]["text"] == "query: what"
    assert gety["passages"][0]["text"] == "passage: this"
    assert bekko["queries"][0]["text"] == "what"
    assert bekko["passages"][0]["text"] == "this"


def test_pooled_output_is_normalized_and_must_be_two_dimensional():
    pooled = pool_hidden(np.array([[3.0, 4.0]]), np.ones((1, 5)), "pooled", normalize=True)
    assert np.allclose(pooled, [[0.6, 0.8]])
    with pytest.raises(ModelError):
        pool_hidden(np.ones((1, 5, 2)), np.ones((1, 5)), "pooled", normalize=True)


class _Output:
    def __init__(self, name):
        self.name = name


class _Input:
    def __init__(self, name):
        self.name = name


class _FakeSession:
    def get_inputs(self):
        return [_Input("input_ids"), _Input("attention_mask")]

    def get_outputs(self):
        return [_Output("token_embeddings"), _Output("sentence_embedding")]

    def run(self, names, inputs):
        return [np.ones((1, 3, 2), dtype=np.float32), np.array([[0.0, 2.0]], dtype=np.float32)]


def test_encoder_session_reads_the_named_sentence_output():
    encoded = {
        "input_ids": np.ones((1, 3), dtype=np.int64),
        "attention_mask": np.ones((1, 3), dtype=np.int64),
    }
    vectors = run_encoder_session(_FakeSession(), encoded, ENCODER_SPECS["gety-embed-v0"])
    assert np.allclose(vectors, [[0.0, 1.0]])


def test_fp16_upcast_keeps_values_and_removes_every_half_tensor(tmp_path):
    weight = np.array([0.5, -1.25, 3.0], dtype=np.float16)
    graph = helper.make_graph(
        [
            helper.make_node("Cast", ["x"], ["xh"], to=TensorProto.FLOAT16),
            helper.make_node(
                "Constant",
                [],
                ["c"],
                value=numpy_helper.from_array(np.array([1.0, 1.0, 1.0], dtype=np.float16), "c"),
            ),
            helper.make_node("Add", ["xh", "w"], ["s"]),
            helper.make_node("Add", ["s", "c"], ["y"]),
        ],
        "tiny",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [3])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT16, [3])],
        [numpy_helper.from_array(weight, "w")],
    )
    source = tmp_path / "fp16.onnx"
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 10  # the newest IR that the pinned ONNX Runtime 1.22 loads
    onnx.save(model, source)

    target = upcast_fp16_model(source, tmp_path / "fp32" / "model.onnx")

    model = onnx.load(target)
    assert all(item.data_type != TensorProto.FLOAT16 for item in model.graph.initializer)
    assert model.graph.output[0].type.tensor_type.elem_type == TensorProto.FLOAT
    session = ort.InferenceSession(str(target), providers=["CPUExecutionProvider"])
    x = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    (y,) = session.run(None, {"x": x})
    assert y.dtype == np.float32
    assert np.allclose(y, x + weight.astype(np.float32) + 1.0)


def _embedder(qps: float, p95: float) -> dict:
    return {
        "schema": 1,
        "variants": {
            "fp32": {
                "parity_passed": True,
                "model_bytes": 1000,
                "timing": {
                    "query": {"p95_ms": p95},
                    "passage": {"passages_per_second": qps},
                },
            }
        },
    }


def test_supplementary_rows_are_reported_but_never_change_frozen_k1(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    write_json(results / "encoders-e5-small.json", _embedder(30.0, 3.0))
    write_json(results / "encoders-bekko-a8m.json", _embedder(400.0, 2.0))

    summary = export_results(tmp_path, tmp_path / "out")

    assert summary["verdicts"]["k1_embedder"]["k1_fires"] is True
    supplementary = summary["supplementary_embedders"]
    assert supplementary["affects_k1"] is False
    assert [row["model"] for row in supplementary["qualified_variants"]] == ["bekko-a8m"]
    assert supplementary["qualified_variants"][0]["meets_targets"] is True
    assert (tmp_path / "out" / "raw-results" / "encoders-bekko-a8m.json").exists()
