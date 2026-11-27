# WP-0.6 harness regressions found in the final gate run: the Florence decode
# overran its preregistered 1,024-token bound, the static NPU export broke under
# Transformers 5 and traced the wrong sequence length, and a never-downloaded
# reranker read its tokenizer before its snapshot existed (test_amendment3).
import numpy as np
import pytest

from seeky_model_export import florence_run


class _Info:
    def __init__(self, name, shape=None):
        self.name = name
        self.shape = shape


class _Session:
    def __init__(self, inputs, outputs, run):
        self._inputs = inputs
        self._outputs = outputs
        self._run = run

    def get_inputs(self):
        return self._inputs

    def get_outputs(self):
        return self._outputs

    def run(self, names, feeds):
        return self._run(feeds)


class _Bundle:
    def __init__(self, token):
        self.decoder_calls = 0
        vocab = 8
        hidden = 4

        def decoder(feeds):
            self.decoder_calls += 1
            logits = np.zeros((1, 1, vocab), dtype=np.float32)
            logits[0, 0, token] = 1.0
            past = feeds["past_key_values.0.decoder.key"]
            grown = np.zeros((1, 2, past.shape[2] + 1, 2), dtype=np.float32)
            return [logits, grown, np.zeros((1, 2, 3, 2), dtype=np.float32)]

        self.sessions = {
            "vision_encoder": _Session(
                [_Info("pixel_values")],
                [_Info("image_features")],
                lambda feeds: [np.ones((1, 2, hidden), dtype=np.float32)],
            ),
            "embed_tokens": _Session(
                [_Info("input_ids")],
                [_Info("inputs_embeds")],
                lambda feeds: [np.ones((1, feeds["input_ids"].shape[1], hidden), dtype=np.float32)],
            ),
            "encoder_model": _Session(
                [_Info("inputs_embeds"), _Info("attention_mask")],
                [_Info("last_hidden_state")],
                lambda feeds: [feeds["inputs_embeds"]],
            ),
            "decoder_model_merged": _Session(
                [
                    _Info("use_cache_branch"),
                    _Info("inputs_embeds"),
                    _Info("encoder_hidden_states"),
                    _Info("encoder_attention_mask"),
                    _Info("past_key_values.0.decoder.key", [1, 2, "past", 2]),
                    _Info("past_key_values.0.encoder.key", [1, 2, "enc", 2]),
                ],
                [
                    _Info("logits"),
                    _Info("present.0.decoder.key"),
                    _Info("present.0.encoder.key"),
                ],
                decoder,
            ),
        }


class _Tokenizer:
    eos_token_id = 2

    def decode(self, tokens, skip_special_tokens=True):
        return " ".join(str(token) for token in tokens)


class _Processor:
    tokenizer = _Tokenizer()


def _inputs():
    return {
        "pixel_values": np.zeros((1, 3, 2, 2), dtype=np.float32),
        "input_ids": np.array([[0, 5, 2]], dtype=np.int64),
    }


def test_florence_decode_stops_at_the_bound_without_another_decoder_step():
    bundle = _Bundle(token=5)  # never emits EOS

    tokens, _ = florence_run._decode(bundle, _Processor(), _inputs(), max_new_tokens=3)

    assert tokens == [5, 5, 5]
    # Prefill plus one step per kept token except the last: never a step past
    # the bound, which overflowed the real decoder's position table.
    assert bundle.decoder_calls == 3
    assert florence_run.hit_token_bound(tokens, eos=2, max_new_tokens=3)


def test_florence_decode_that_emits_eos_is_not_bounded():
    bundle = _Bundle(token=2)

    tokens, _ = florence_run._decode(bundle, _Processor(), _inputs(), max_new_tokens=3)

    assert tokens == [2]
    assert not florence_run.hit_token_bound(tokens, eos=2, max_new_tokens=3)


def test_static_embedder_export_traces_the_padded_static_shape(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    onnx = pytest.importorskip("onnx")
    from seeky_model_export import models

    config = transformers.BertConfig(
        vocab_size=32,
        hidden_size=8,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=16,
        max_position_embeddings=64,
    )
    torch.manual_seed(0)
    model = transformers.BertModel(config).eval()

    class _Tok:
        def __call__(self, texts, **kwargs):
            length = kwargs.get("max_length") if kwargs.get("padding") == "max_length" else 4
            ids = np.ones((len(texts), length), dtype=np.int64)
            return {
                "input_ids": ids,
                "attention_mask": np.ones_like(ids),
                "token_type_ids": np.zeros_like(ids),
            }

    monkeypatch.setattr(models, "load_reference_model", lambda directory, spec: model)
    monkeypatch.setattr(models, "load_tokenizer", lambda directory: _Tok())
    destination = tmp_path / "static" / "model.onnx"

    models.export_embedder_static_fp32(
        tmp_path, destination, models.ENCODER_SPECS["e5-small"], sequence_length=32
    )

    graph = onnx.load(destination).graph
    dims = [d.dim_value for d in graph.input[0].type.tensor_type.shape.dim]
    assert dims == [1, 32]


def test_npu_probe_is_frozen_tokens_the_openvino_env_can_read(tmp_path):
    # The OpenVINO environment has no Transformers: the gate reads the token
    # IDs the CPU prepare step froze, and refuses to run without them.
    from seeky_model_export import npu_run

    with pytest.raises(npu_run.NpuRunError):
        npu_run.load_npu_inputs(tmp_path)
    path = npu_run.npu_inputs_path(tmp_path)
    path.parent.mkdir(parents=True)
    ids = np.arange(npu_run.NPU_QUERIES * npu_run.NPU_SEQUENCE).reshape(npu_run.NPU_QUERIES, -1)
    np.savez(path, input_ids=ids, attention_mask=np.ones_like(ids))

    encoded = npu_run.load_npu_inputs(tmp_path)

    assert encoded["input_ids"].dtype == np.int64
    assert np.array_equal(encoded["input_ids"], ids)
    np.savez(path, input_ids=ids[:, :4], attention_mask=np.ones_like(ids[:, :4]))
    with pytest.raises(npu_run.NpuRunError):
        npu_run.load_npu_inputs(tmp_path)
