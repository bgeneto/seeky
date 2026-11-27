# WP-0.6: model-spec and output-pooling checks without model downloads.
import numpy as np
import pytest

from seeky_model_export.models import (
    ENCODER_SPECS,
    ModelError,
    ModelSpec,
    complete_graph_inputs,
    pool_hidden,
)


def test_preregistered_encoder_revisions_are_immutable():
    assert set(ENCODER_SPECS) == {"e5-small", "granite-modernbert", "gte-reranker"}
    for spec in ENCODER_SPECS.values():
        assert len(spec.revision) == 40
        assert int(spec.revision, 16)
        assert spec.pooling in {"mean", "cls", "logits"}


def test_model_spec_rejects_mutable_or_incomplete_identity():
    with pytest.raises(ModelError):
        ModelSpec("bad", "org/model", "main", "feature-extraction", "mean")
    with pytest.raises(ModelError):
        ModelSpec("bad", "not-a-repository", "0" * 40, "feature-extraction", "mean")


def test_mean_pooling_ignores_padding_and_normalizes():
    hidden = np.array([[[1.0, 2.0], [3.0, 4.0], [100.0, 100.0]]])
    mask = np.array([[1, 1, 0]], dtype=np.int64)
    output = pool_hidden(hidden, mask, "mean")
    assert np.allclose(output, [[2.0, 3.0]])
    normalized = pool_hidden(hidden, mask, "mean", normalize=True)
    assert np.allclose(np.linalg.norm(normalized, axis=1), 1.0)


def test_cls_pooling_and_logits_have_expected_shapes():
    hidden = np.array([[[1.0, 2.0], [3.0, 4.0]]])
    mask = np.ones((1, 2), dtype=np.int64)
    assert np.array_equal(pool_hidden(hidden, mask, "cls"), hidden[:, 0, :])
    assert np.array_equal(pool_hidden(np.array([[2.0]]), mask[:, :1], "logits"), [2.0])


def test_graph_inputs_add_zero_token_types_for_official_export():
    class Input:
        def __init__(self, name):
            self.name = name

    class Session:
        def get_inputs(self):
            return [Input("input_ids"), Input("attention_mask"), Input("token_type_ids")]

    encoded = {
        "input_ids": np.ones((2, 3), dtype=np.int64),
        "attention_mask": np.array([[1, 1, 0], [1, 0, 0]], dtype=np.int64),
        "unused": np.ones((2, 3), dtype=np.int64),
    }
    inputs = complete_graph_inputs(Session(), encoded)
    assert set(inputs) == {"input_ids", "attention_mask", "token_type_ids"}
    assert np.array_equal(inputs["token_type_ids"], np.zeros((2, 3), dtype=np.int64))


def test_graph_inputs_reject_an_unknown_required_input():
    class Input:
        def __init__(self, name):
            self.name = name

    class Session:
        def get_inputs(self):
            return [Input("input_ids"), Input("attention_mask"), Input("mystery")]

    with pytest.raises(ModelError):
        complete_graph_inputs(
            Session(),
            {
                "input_ids": np.ones((1, 2), dtype=np.int64),
                "attention_mask": np.ones((1, 2), dtype=np.int64),
            },
        )


def test_pooling_rejects_malformed_or_zero_outputs():
    with pytest.raises(ModelError):
        pool_hidden(np.array([1.0]), np.array([1]), "mean")
    with pytest.raises(ModelError):
        pool_hidden(np.zeros((1, 1, 2)), np.ones((1, 1)), "mean", normalize=True)
    with pytest.raises(ModelError):
        pool_hidden(np.ones((1, 1, 2)), np.ones((1, 1)), "unknown")
