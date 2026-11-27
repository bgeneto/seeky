# WP-0.6 preregistration amendment 3: a supplementary reranker (hs-rerank-1)
# runs under the reranker rules but never changes the frozen K1 verdict, and a
# variant it cannot export, quantize, or run is a reported result.
import pytest

from seeky_model_export import encoder_run, reranker_run
from seeky_model_export.artifacts import load_json, write_json
from seeky_model_export.models import (
    ENCODER_SPECS,
    PROXY_RERANKER,
    SUPPLEMENTARY_RERANKERS,
    ModelError,
)
from seeky_model_export.quantize import QuantizationError
from seeky_model_export.report_export import export_results


def test_supplementary_reranker_pins_an_immutable_revision():
    assert SUPPLEMENTARY_RERANKERS == ("hs-rerank-1",)
    assert PROXY_RERANKER not in SUPPLEMENTARY_RERANKERS
    spec = ENCODER_SPECS["hs-rerank-1"]
    assert spec.repository == "hindsight-ai/hs-rerank-1"
    assert spec.revision == "6bc7caf42bfcd5873ed76309cd0785cb1f550f51"
    assert spec.task == "text-classification"
    assert spec.pooling == "logits"
    assert spec.derive_quantized
    assert dict(spec.published_onnx) == {"published-default": "onnx/model.onnx"}


def test_the_proxy_keeps_its_result_file_and_amendment_rows_get_their_own():
    assert reranker_run.result_filename("gte-reranker") == "reranker.json"
    assert reranker_run.result_filename("hs-rerank-1") == "reranker-hs-rerank-1.json"


def test_a_reranker_outside_the_portfolio_is_refused(tmp_path):
    with pytest.raises(reranker_run.RerankerRunError):
        reranker_run.run_reranker_gate(tmp_path, model="some-other-reranker")


def _stub_assets(tmp_path, monkeypatch):
    published = tmp_path / "variants" / "hs-rerank-1" / "published-default" / "model.onnx"
    monkeypatch.setattr(encoder_run, "download_encoder_assets", lambda workspace, spec: tmp_path / "src")
    monkeypatch.setattr(
        encoder_run,
        "_stage_published",
        lambda workspace, spec, source_dir, deadline=None: {"published-default": published},
    )
    return published


def test_failed_fp32_export_keeps_the_published_graph_and_records_why(tmp_path, monkeypatch):
    published = _stub_assets(tmp_path, monkeypatch)

    def export(source_dir, destination, spec):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"partial")
        raise ModelError("fp32 reranker ONNX export failed") from RuntimeError(
            "unsupported operator in C:\\Users\\someone\\model.py"
        )

    monkeypatch.setattr(encoder_run, "export_reranker_fp32", export)
    spec = ENCODER_SPECS["hs-rerank-1"]
    failures: dict[str, str] = {}

    variants = encoder_run._prepare_variants(tmp_path, spec, None, failures=failures)

    assert variants == {"published-default": published}
    assert failures["fp32"].startswith("RuntimeError: unsupported operator")
    assert "someone" not in failures["fp32"]
    assert failures["int8-dynamic"] == failures["int8-static-qdq"] == "no fp32 export"
    assert not (tmp_path / "variants" / "hs-rerank-1" / "fp32" / "model.onnx").exists()
    with pytest.raises(ModelError):
        encoder_run._prepare_variants(tmp_path, spec, None)


def test_failed_quantization_drops_only_that_variant(tmp_path, monkeypatch):
    published = _stub_assets(tmp_path, monkeypatch)
    fp32 = tmp_path / "variants" / "hs-rerank-1" / "fp32" / "model.onnx"

    def export(source_dir, destination, spec):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"onnx")

    def dynamic(source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"onnx")

    def static(*args, **kwargs):
        raise QuantizationError("ONNX Runtime static QDQ quantization failed")

    monkeypatch.setattr(encoder_run, "export_reranker_fp32", export)
    monkeypatch.setattr(encoder_run, "quantize_dynamic_model", dynamic)
    monkeypatch.setattr(encoder_run, "_quantize_static", static)
    failures: dict[str, str] = {}

    variants = encoder_run._prepare_variants(
        tmp_path, ENCODER_SPECS["hs-rerank-1"], None, failures=failures
    )

    assert list(variants) == ["fp32", "published-default", "int8-dynamic"]
    assert variants["fp32"] == fp32 and variants["published-default"] == published
    assert failures == {"int8-static-qdq": "QuantizationError: ONNX Runtime static QDQ quantization failed"}


class _Session:
    def __init__(self, name):
        self.name = name

    def get_providers(self):
        return ["CPUExecutionProvider"]


def test_an_unrunnable_variant_is_recorded_and_the_rest_still_run(tmp_path, monkeypatch):
    variants = {name: tmp_path / name / "model.onnx" for name in ("fp32", "published-default")}
    monkeypatch.setattr(reranker_run, "apply_profile", lambda profile: {"name": "test"})
    monkeypatch.setattr(reranker_run, "capture_environment", lambda: {})
    monkeypatch.setattr(reranker_run, "load_frozen", lambda workspace: {})
    monkeypatch.setattr(reranker_run, "embedding_view", lambda frozen, slug: {"qrels": {}})
    downloaded = []

    def download(workspace, spec):
        downloaded.append(spec.slug)
        return tmp_path / "models" / spec.slug

    def tokenizer(directory):
        # Regression: the tokenizer of a never-downloaded model was read
        # before its snapshot existed.
        assert downloaded == ["hs-rerank-1"]
        return None

    monkeypatch.setattr(reranker_run, "download_encoder_assets", download)
    monkeypatch.setattr(reranker_run, "load_tokenizer", tokenizer)
    monkeypatch.setattr(
        reranker_run,
        "_prepare_variants",
        lambda workspace, spec, tokenizer, deadline=None, failures=None: dict(variants),
    )
    monkeypatch.setattr(reranker_run, "_candidate_lists", lambda workspace, frozen: [{}])
    monkeypatch.setattr(reranker_run, "load_reference_model", lambda directory, spec: None)
    monkeypatch.setattr(reranker_run, "_reference_lists", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        reranker_run, "create_ort_session", lambda path, profile: _Session(path.parent.name)
    )

    def score(session, *args, **kwargs):
        if session.name == "fp32":
            raise ModelError("ONNX Runtime encoder execution failed") from RuntimeError(
                "Could not find an implementation for SomeOp(1)"
            )
        return []

    monkeypatch.setattr(reranker_run, "_score_lists", score)
    monkeypatch.setattr(
        reranker_run,
        "reranker_parity",
        lambda reference, candidate, qrels, k: {
            "mean_kendall_tau_b": 1.0,
            "worst_kendall_tau_b": 1.0,
            "nDCG@10_delta": 0.0,
        },
    )
    monkeypatch.setattr(reranker_run, "_variant_size", lambda directory, deadline=None, stage="": (10, []))
    monkeypatch.setattr(
        reranker_run,
        "wait_for_quiet_window",
        lambda timeout_seconds, deadline=None: {"quiet": False},
    )
    (tmp_path / "results").mkdir()

    result = reranker_run.run_reranker_gate(tmp_path, model="hs-rerank-1", wait_seconds=0.0)

    assert list(result["variants"]) == ["published-default"]
    assert result["variants"]["published-default"]["path_label"] == "hs-rerank-1/published-default"
    assert result["variant_failures"]["fp32"].startswith("RuntimeError: Could not find")
    stored = load_json(tmp_path / "results" / "reranker-hs-rerank-1.json")
    assert stored["model"] == "hs-rerank-1"
    assert not (tmp_path / "results" / "reranker.json").exists()


def _reranker(p95_ms: float) -> dict:
    return {
        "schema": 1,
        "variants": {
            "fp32": {
                "parity_passed": True,
                "model_bytes": 1000,
                "timing": {"depth_50": {"p95_ms": p95_ms}},
            }
        },
    }


def test_supplementary_reranker_is_reported_but_never_changes_frozen_k1(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    write_json(results / "reranker.json", _reranker(23_560.0))
    write_json(results / "reranker-hs-rerank-1.json", _reranker(120.0))

    summary = export_results(tmp_path, tmp_path / "out")

    assert summary["verdicts"]["k1_reranker"]["k1_fires"] is True
    assert [item["model"] for item in summary["verdicts"]["k1_reranker"]["qualified_variants"]] == [
        "gte-reranker"
    ]
    supplementary = summary["supplementary_rerankers"]
    assert supplementary["amendment"] == 3
    assert supplementary["affects_k1"] is False
    assert supplementary["qualified_variants"][0]["meets_target"] is True


def test_each_reranker_keeps_its_own_raw_timings(tmp_path):
    # The hs-rerank-1 run overwrote the proxy's raw/reranker/fp32-timings.json.
    proxy = reranker_run.raw_directory(tmp_path, "gte-reranker")
    supplementary = reranker_run.raw_directory(tmp_path, "hs-rerank-1")

    assert proxy == tmp_path / "raw" / "reranker"
    assert supplementary != proxy
