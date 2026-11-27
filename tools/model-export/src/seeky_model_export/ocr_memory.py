"""Measure OCR O2 for one variant in a fresh process.

The OCR gate reads the process-lifetime peak working set after it has also
prepared and calibrated the int8 variants, so its O2 figure is an upper bound.
This probe applies the same rule (PREREGISTRATION §7: peak minus the recorded
pre-model baseline) to a process that only loads one variant and reads every
text page once after the warm-up pages.
"""

from __future__ import annotations

import gc
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .artifacts import write_json
from .deadline import Deadline, bounded_gate
from .system import RunningProfile, apply_profile, capture_environment

O2_LIMIT_BYTES = 1_000_000_000


class OcrMemoryError(RuntimeError):
    """The isolated OCR memory probe could not run."""


def added_peak(*, baseline: int, peak: int) -> int:
    return max(0, peak - baseline)


def _probe_command() -> list[str]:
    return [sys.executable, "-m", "seeky_model_export.ocr_memory"]


def _last_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return None
    return None


def measure_isolated(
    workspace: Path,
    variant: str,
    profile: RunningProfile,
    *,
    deadline: Deadline,
) -> dict[str, Any]:
    """Run the probe in a child that inherits this process's Job Object."""
    request = {"workspace": str(workspace), "variant": variant, "threads": profile.ort_threads}
    deadline.check(f"ocr-memory:{variant}")
    try:
        completed = subprocess.run(
            _probe_command(),
            input=json.dumps(request),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1.0, deadline.remaining()),
        )
    except subprocess.TimeoutExpired:
        deadline.check(f"ocr-memory:{variant}:probe")
        return {"variant": variant, "error": "probe timed out", "o2_passed": False}
    record = _last_json(completed.stdout)
    if completed.returncode != 0 or record is None:
        return {
            "variant": variant,
            "exit_code": completed.returncode,
            "error": "probe process ended without a result",
            "o2_passed": False,
        }
    record["variant"] = variant
    record["o2_passed"] = record["added_peak_rss_bytes"] <= O2_LIMIT_BYTES
    return record


def run_ocr_memory_gate(
    workspace: Path,
    *,
    profile: RunningProfile | None = None,
    deadline: Deadline | None = None,
    variants: tuple[str, ...] = ("fp32",),
) -> dict[str, Any]:
    gate_deadline = deadline or Deadline()
    selected_profile = profile or RunningProfile.t1_emulated()
    results: dict[str, Any] = {"schema": 1, "variants": {}}
    with bounded_gate(
        "ocr-memory",
        workspace=workspace,
        deadline=gate_deadline,
        results=results,
    ):
        results.update(
            {
                "rule": "PREREGISTRATION §7 peak minus pre-model baseline, one variant per fresh process",
                "o2_limit_bytes": O2_LIMIT_BYTES,
                "profile": apply_profile(selected_profile),
                "environment": capture_environment(),
            }
        )
        for variant in variants:
            results["variants"][variant] = measure_isolated(
                workspace, variant, selected_profile, deadline=gate_deadline
            )
        write_json(workspace / "results" / "ocr-memory.json", results)
    return results


def _peak_working_set() -> int:
    import psutil

    info = psutil.Process().memory_info()
    return int(getattr(info, "peak_wset", info.rss))


def _probe_in_this_process(request: dict[str, Any]) -> dict[str, Any]:
    import psutil

    from .ocr_data import load_ocr_manifest
    from .ocr_run import OCR_SLUG, WARMUP_PAGES, _load_assets, _new_engine, _page_text

    workspace = Path(request["workspace"])
    manifest, _ = load_ocr_manifest(workspace)
    image_paths = [
        workspace / "data" / "ocr" / page["image"]
        for page in manifest["pages"]
        if page["kind"] == "text"
    ]
    assets = _load_assets(workspace)
    variant_dir = workspace / "variants" / OCR_SLUG / request["variant"]
    det, rec = variant_dir / "det.onnx", variant_dir / "rec.onnx"
    if not det.is_file() or not rec.is_file():
        raise OcrMemoryError("OCR variant graphs are missing; run the ocr gate first")
    gc.collect()
    baseline = psutil.Process().memory_info().rss
    engine = _new_engine(assets, det_path=det, rec_path=rec, threads=int(request["threads"]))
    for path in [*image_paths[:WARMUP_PAGES], *image_paths]:
        _page_text(engine, path)
    peak = _peak_working_set()
    return {
        "baseline_rss_bytes": baseline,
        "peak_working_set_bytes": peak,
        "added_peak_rss_bytes": added_peak(baseline=baseline, peak=peak),
        "pages": WARMUP_PAGES + len(image_paths),
    }


def _child_main() -> int:
    request = json.loads(sys.stdin.read())
    print(json.dumps(_probe_in_this_process(request)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(_child_main())
