# WP-0.6 OCR O2: the gate's peak working set spans the whole harness process,
# including int8 calibration; the isolated probe measures one variant's load
# and inference in a fresh process (PREREGISTRATION §7 baseline rule).
import sys

from seeky_model_export import ocr_memory
from seeky_model_export.deadline import Deadline
from seeky_model_export.system import RunningProfile


def _probe(monkeypatch, tmp_path, code):
    monkeypatch.setattr(ocr_memory, "_probe_command", lambda: [sys.executable, "-c", code])
    return ocr_memory.measure_isolated(
        tmp_path,
        "fp32",
        RunningProfile.t0_functional(),
        deadline=Deadline(60),
    )


def test_isolated_probe_reports_the_child_measurement(tmp_path, monkeypatch):
    code = (
        "import json\n"
        "print('noise from the OCR engine')\n"
        "print(json.dumps({'baseline_rss_bytes': 100, 'peak_working_set_bytes': 400,"
        " 'added_peak_rss_bytes': 300, 'pages': 2}))\n"
    )

    record = _probe(monkeypatch, tmp_path, code)

    assert record["variant"] == "fp32"
    assert record["added_peak_rss_bytes"] == 300
    assert record["o2_passed"] is True


def test_isolated_probe_that_crashes_is_a_recorded_failure(tmp_path, monkeypatch):
    record = _probe(monkeypatch, tmp_path, "import os; os._exit(3)")

    assert record["exit_code"] == 3
    assert "added_peak_rss_bytes" not in record
    assert record["o2_passed"] is False


def test_added_peak_is_never_negative():
    assert ocr_memory.added_peak(baseline=500, peak=400) == 0
    assert ocr_memory.added_peak(baseline=100, peak=400) == 300
