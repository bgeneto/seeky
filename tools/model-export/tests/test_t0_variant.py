# WP-0.6: the T0 functional check uses the best parity-passing CPU variant
# (preregistration §4.2), never a variant that failed parity.
import pytest

from seeky_model_export.artifacts import write_json
from seeky_model_export.t0_run import T0VariantError, _pick_variant


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"onnx")
    return path


def _result(**parity):
    return {
        "schema": 1,
        "variants": {name: {"parity_passed": passed} for name, passed in parity.items()},
    }


def test_t0_skips_parity_failing_int8_and_uses_published_fp32(tmp_path):
    fp32 = _touch(tmp_path / "models" / "e5-small" / "onnx" / "model.onnx")
    _touch(tmp_path / "variants" / "e5-small" / "int8-dynamic" / "model.onnx")
    _touch(tmp_path / "variants" / "e5-small" / "int8-static-qdq" / "model.onnx")
    write_json(
        tmp_path / "results" / "encoders-e5-small.json",
        _result(**{"fp32": True, "int8-dynamic": False, "int8-static-qdq": False}),
    )

    assert _pick_variant(tmp_path, "e5-small") == ("fp32", fp32)


def test_t0_prefers_a_parity_passing_quantized_variant(tmp_path):
    _touch(tmp_path / "variants" / "gte-reranker" / "fp32" / "model.onnx")
    dynamic = _touch(tmp_path / "variants" / "gte-reranker" / "int8-dynamic" / "model.onnx")
    write_json(
        tmp_path / "results" / "reranker.json",
        _result(**{"fp32": True, "int8-dynamic": True}),
    )

    assert _pick_variant(tmp_path, "gte-reranker") == ("int8-dynamic", dynamic)


def test_t0_reranker_fp32_lives_under_variants(tmp_path):
    fp32 = _touch(tmp_path / "variants" / "gte-reranker" / "fp32" / "model.onnx")
    write_json(
        tmp_path / "results" / "reranker.json",
        _result(**{"fp32": True, "int8-dynamic": False}),
    )

    assert _pick_variant(tmp_path, "gte-reranker") == ("fp32", fp32)


def test_t0_refuses_when_no_variant_passed_parity(tmp_path):
    _touch(tmp_path / "variants" / "e5-small" / "int8-dynamic" / "model.onnx")
    write_json(
        tmp_path / "results" / "encoders-e5-small.json",
        _result(**{"int8-dynamic": False}),
    )

    with pytest.raises(T0VariantError):
        _pick_variant(tmp_path, "e5-small")


def test_t0_refuses_without_a_completed_gate_result(tmp_path):
    _touch(tmp_path / "variants" / "e5-small" / "int8-dynamic" / "model.onnx")

    with pytest.raises(T0VariantError):
        _pick_variant(tmp_path, "e5-small")
