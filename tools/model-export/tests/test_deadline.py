# WP-0.6: bounded gate deadline, partial artifacts, and bounded processes.
import json
import subprocess

import pytest

import seeky_model_export.deadline as deadline_module
from seeky_model_export.deadline import (
    DEFAULT_GATE_TIMEOUT_SECONDS,
    Deadline,
    GateTimeout,
    bounded_gate,
    run_bounded,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_deadline_raises_at_expiry_and_reports_the_stage():
    clock = FakeClock()
    deadline = Deadline(5.0, clock=clock)

    clock.advance(4.9)
    deadline.check("encoders:fp32")
    assert deadline.remaining() == pytest.approx(0.1)

    clock.advance(0.2)
    with pytest.raises(GateTimeout) as raised:
        deadline.check("encoders:fp32:batch-7")
    assert raised.value.stage == "encoders:fp32:batch-7"
    assert raised.value.elapsed_seconds == pytest.approx(5.1)
    assert raised.value.limit_seconds == pytest.approx(5.0)
    assert deadline.remaining() == 0.0


def test_deadline_rejects_a_nonpositive_budget_and_clamps_waits():
    with pytest.raises(ValueError):
        Deadline(0.0)
    clock = FakeClock()
    deadline = Deadline(10.0, clock=clock)
    clock.advance(8.0)
    assert deadline.clamp("wait:quiet-window", 900.0) == pytest.approx(2.0)
    assert Deadline().limit_seconds == DEFAULT_GATE_TIMEOUT_SECONDS


def test_slow_gate_body_times_out_with_a_partial_artifact_only(tmp_path):
    clock = FakeClock()
    deadline = Deadline(10.0, clock=clock)
    results = {"schema": 1, "variants": {}}

    with pytest.raises(GateTimeout) as raised:
        with bounded_gate("fake-gate", workspace=tmp_path, deadline=deadline, results=results):
            deadline.check("fake-gate:fp32")
            clock.advance(4.0)
            results["variants"]["fp32"] = {"parity_passed": True}
            deadline.check("fake-gate:int8-dynamic")
            clock.advance(4.0)
            results["variants"]["int8-dynamic"] = {"parity_passed": True}
            deadline.check("fake-gate:int8-static-qdq")
            clock.advance(6.0)
            deadline.check("fake-gate:int8-static-qdq:batch-0")

    assert raised.value.stage == "fake-gate:int8-static-qdq:batch-0"
    artifact_path = tmp_path / "results" / "fake-gate-timeout.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["status"] == "timed_out"
    assert artifact["stage"] == "fake-gate:int8-static-qdq:batch-0"
    assert artifact["elapsed_seconds"] == pytest.approx(14.0)
    assert artifact["limit_seconds"] == pytest.approx(10.0)
    assert artifact["completed_variants"] == ["fp32", "int8-dynamic"]
    assert artifact["verdicts"] is None
    assert sorted(artifact["partial"]["variants"]) == ["fp32", "int8-dynamic"]
    assert not any(key.lower().startswith(("k1", "k2", "k3", "k4")) for key in artifact)


def test_fast_gate_body_completes_without_a_timeout_artifact(tmp_path):
    clock = FakeClock()
    deadline = Deadline(10.0, clock=clock)
    results = {"schema": 1, "variants": {}}

    with bounded_gate("fake-gate", workspace=tmp_path, deadline=deadline, results=results):
        deadline.check("fake-gate:fp32")
        clock.advance(2.0)
        results["variants"]["fp32"] = {"parity_passed": True}

    assert results == {"schema": 1, "variants": {"fp32": {"parity_passed": True}}}
    assert not (tmp_path / "results" / "fake-gate-timeout.json").exists()
    assert deadline.remaining() == pytest.approx(8.0)


def test_encoder_gate_writes_a_timeout_artifact_with_no_verdict(tmp_path, monkeypatch):
    import seeky_model_export.encoder_run as encoder_run

    clock = FakeClock()

    def slow_frozen(workspace):
        clock.advance(5.0)
        return {}

    monkeypatch.setattr(encoder_run, "load_frozen", slow_frozen)
    monkeypatch.setattr(
        encoder_run,
        "embedding_view",
        lambda frozen, slug: {"source_counts": {}, "queries": [], "passages": []},
    )

    with pytest.raises(GateTimeout):
        encoder_run.run_encoder_gate(
            tmp_path,
            "e5-small",
            deadline=Deadline(5.0, clock=clock),
        )

    artifact = json.loads(
        (tmp_path / "results" / "encoders-e5-small-timeout.json").read_text(encoding="utf-8")
    )
    assert artifact["status"] == "timed_out"
    assert artifact["stage"] == "encoders:e5-small:load-frozen"
    assert artifact["completed_variants"] == []
    assert artifact["verdicts"] is None
    assert not (tmp_path / "results" / "encoders-e5-small.json").exists()


def test_run_bounded_passes_the_remaining_budget_and_maps_process_timeout(monkeypatch):
    clock = FakeClock()
    deadline = Deadline(5.0, clock=clock)
    seen: dict[str, float] = {}

    def fake_run(command, timeout, **kwargs):
        seen["timeout"] = timeout
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(deadline_module.subprocess, "run", fake_run)
    with pytest.raises(GateTimeout) as raised:
        run_bounded(["powercfg", "/getactivescheme"], deadline=deadline, stage="power:query")
    assert seen["timeout"] == pytest.approx(5.0)
    assert raised.value.stage == "power:query"
