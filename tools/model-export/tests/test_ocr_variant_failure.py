# WP-0.6: an OCR variant that ONNX Runtime cannot execute is a reported
# result (preregistration §2), never a crash that drops the later variants.
from seeky_model_export import ocr_run
from seeky_model_export.artifacts import load_json


_ASSETS = ocr_run.OcrAssets(
    det=None,
    rec=None,
    keys=None,
    det_mean=(0.485, 0.456, 0.406),
    det_std=(0.229, 0.224, 0.225),
    det_postprocess=(("thresh", 0.2),),
)


class _Engine:
    def __init__(self, name):
        self.name = name


def _setup(tmp_path, monkeypatch, failing):
    variants = {}
    for name in ("fp32", "int8-dynamic", "int8-static-qdq"):
        directory = tmp_path / "variants" / name
        directory.mkdir(parents=True)
        for graph in ("det.onnx", "rec.onnx"):
            (directory / graph).write_bytes(b"onnx")
        variants[name] = (directory / "det.onnx", directory / "rec.onnx")
    manifest = {
        "pages": [
            {"id": "en-00", "kind": "text", "image": "en-00.png"},
            {"id": "blank-00", "kind": "blank", "image": "blank-00.png"},
        ]
    }
    truth = {"en-00": "hello world", "blank-00": ""}

    def page_text(engine, image_path):
        if engine.name in failing:
            raise ocr_run.OcrRunError("PP-OCR page inference failed") from RuntimeError(
                "Could not find an implementation for ConvInteger(10) node "
                "loaded from C:\\Users\\someone\\det.onnx"
            )
        return "hello world" if image_path.stem == "en-00" else ""

    monkeypatch.setattr(ocr_run, "apply_profile", lambda profile: {"name": "test"})
    monkeypatch.setattr(ocr_run, "capture_environment", lambda: {})
    monkeypatch.setattr(ocr_run, "load_ocr_manifest", lambda workspace: (manifest, truth))
    monkeypatch.setattr(ocr_run, "_load_assets", lambda workspace, deadline=None: _ASSETS)
    monkeypatch.setattr(ocr_run, "_prepare_variants", lambda *args, **kwargs: (variants, {}))
    monkeypatch.setattr(
        ocr_run,
        "_new_engine",
        lambda root, det_path=None, rec_path=None, threads=8: _Engine(det_path.parent.name),
    )
    monkeypatch.setattr(ocr_run, "_page_text", page_text)
    monkeypatch.setattr(
        ocr_run,
        "wait_for_quiet_window",
        lambda timeout_seconds, deadline=None: {"quiet": False},
    )
    (tmp_path / "results").mkdir()


def test_unsupported_ocr_variant_is_recorded_and_later_variants_still_run(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, failing={"int8-dynamic"})

    result = ocr_run.run_ocr_gate(tmp_path, wait_seconds=0.0)

    assert set(result["variants"]) == {"fp32", "int8-static-qdq"}
    reason = result["variant_failures"]["int8-dynamic"]
    assert reason.startswith("RuntimeError: Could not find an implementation for ConvInteger(10)")
    assert "someone" not in reason and "<path>" in reason
    stored = load_json(tmp_path / "results" / "ocr.json")
    assert "int8-dynamic" in stored["variant_failures"]


def test_quantized_variant_never_becomes_the_reference(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, failing={"fp32"})

    result = ocr_run.run_ocr_gate(tmp_path, wait_seconds=0.0)

    assert result["variants"] == {}
    assert result["variant_failures"]["int8-dynamic"] == "no fp32 reference output"
    assert result["variant_failures"]["int8-static-qdq"] == "no fp32 reference output"
