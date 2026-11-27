"""Bounded monotonic deadlines for the WP-0.6 gate.

A gate measurement must never block for an unbounded time. Every gate builds
one :class:`Deadline`, checks it before each variant, list, batch, repetition,
and wait, and passes the remaining budget to bounded external calls. On expiry
the gate raises :class:`GateTimeout`, which is turned into
``results/<gate>-timeout.json`` holding only the completed variants. Partial
evidence never carries a K1-K4 verdict.
"""

from __future__ import annotations

import contextlib
import subprocess
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

from .artifacts import write_json

DEFAULT_GATE_TIMEOUT_SECONDS = 1800.0


class GateTimeout(RuntimeError):
    """A gate stage exceeded its wall-clock budget."""

    def __init__(self, stage: str, elapsed_seconds: float, limit_seconds: float) -> None:
        super().__init__(
            f"gate stage {stage!r} exceeded {limit_seconds:.1f}s "
            f"after {elapsed_seconds:.1f}s"
        )
        self.stage = stage
        self.elapsed_seconds = elapsed_seconds
        self.limit_seconds = limit_seconds


class Deadline:
    """A monotonic wall-clock budget enforced by explicit stage checks."""

    def __init__(
        self,
        limit_seconds: float = DEFAULT_GATE_TIMEOUT_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not limit_seconds > 0:
            raise ValueError("gate timeout must be a positive number of seconds")
        self._clock = clock
        self._limit = float(limit_seconds)
        self._started = clock()

    @property
    def limit_seconds(self) -> float:
        return self._limit

    def elapsed_seconds(self) -> float:
        return self._clock() - self._started

    def remaining(self) -> float:
        """Seconds left in the budget, never negative."""
        return max(0.0, self._limit - self.elapsed_seconds())

    def check(self, stage: str) -> None:
        """Raise :class:`GateTimeout` once the budget is spent."""
        elapsed = self.elapsed_seconds()
        if elapsed >= self._limit:
            raise GateTimeout(stage, elapsed, self._limit)

    def clamp(self, stage: str, requested_seconds: float) -> float:
        """Return the smaller of a requested wait and the remaining budget."""
        self.check(stage)
        return min(float(requested_seconds), self.remaining())


def run_bounded(
    command: Sequence[str],
    *,
    deadline: Deadline,
    stage: str,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """Run an external process bounded by the remaining gate budget."""
    remaining = deadline.remaining()
    if remaining <= 0.0:
        deadline.check(stage)
    try:
        return subprocess.run(command, timeout=remaining, **kwargs)
    except subprocess.TimeoutExpired as error:
        raise GateTimeout(
            stage,
            deadline.elapsed_seconds(),
            deadline.limit_seconds,
        ) from error


def write_timeout_artifact(
    *,
    gate: str,
    workspace: Path,
    results: dict[str, Any],
    completed_variants: Sequence[str],
    timeout: GateTimeout,
) -> Path:
    """Write completed evidence atomically without any gate verdict."""
    artifact = {
        "schema": 1,
        "status": "timed_out",
        "gate": gate,
        "stage": timeout.stage,
        "elapsed_seconds": timeout.elapsed_seconds,
        "limit_seconds": timeout.limit_seconds,
        "completed_variants": sorted(completed_variants),
        "verdicts": None,
        "partial": results,
    }
    return write_json(Path(workspace) / "results" / f"{gate}-timeout.json", artifact)


@contextlib.contextmanager
def bounded_gate(
    gate: str,
    *,
    workspace: Path,
    deadline: Deadline,
    results: dict[str, Any],
    completed_key: str = "variants",
) -> Iterator[None]:
    """Run a gate body; a timeout writes ``<gate>-timeout.json`` first.

    The body records each variant only after it completes, so the artifact
    holds completed items alone. The timeout is re-raised for the caller to
    report and exit nonzero.
    """
    try:
        yield
    except GateTimeout as timeout:
        write_timeout_artifact(
            gate=gate,
            workspace=workspace,
            results=results,
            completed_variants=list(results.get(completed_key, {})),
            timeout=timeout,
        )
        raise
