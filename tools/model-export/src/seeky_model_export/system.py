"""Windows process profiles, quiet windows, and sanitized environment capture."""

from __future__ import annotations

import contextlib
import ctypes
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

import cpuinfo
import psutil

from .deadline import Deadline, GateTimeout, run_bounded


class ProfileError(RuntimeError):
    """A process profile could not be validated or applied."""


@dataclass(frozen=True)
class RunningProfile:
    name: str
    cpus: list[int]
    memory_bytes: int
    ort_threads: int
    background: bool = False

    def __post_init__(self) -> None:
        if not self.cpus or any(cpu < 0 for cpu in self.cpus) or len(set(self.cpus)) != len(self.cpus):
            raise ProfileError("profile CPUs must be a non-empty unique non-negative list")
        if self.memory_bytes <= 0:
            raise ProfileError("profile memory cap must be positive")
        if self.ort_threads <= 0 or self.ort_threads > len(self.cpus):
            raise ProfileError("ORT threads must be positive and no greater than the CPU subset")
        if len(self.cpus) > (psutil.cpu_count(logical=True) or 1):
            raise ProfileError("profile CPU subset exceeds this host")

    @classmethod
    def t1_emulated(cls) -> "RunningProfile":
        return cls("T1-emulated, provisional", list(range(8)), 12 * 1024**3, 8)

    @classmethod
    def t0_functional(cls) -> "RunningProfile":
        return cls("T0 functional", list(range(4)), 6 * 1024**3, 4)

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_busy_processes(processes: list[dict[str, Any]], *, own_pid: int) -> list[int]:
    busy: list[int] = []
    for process in processes:
        pid = int(process["pid"])
        if pid == own_pid:
            continue
        name = str(process["name"]).lower().removesuffix(".exe")
        delta = float(process["cpu_delta"])
        if name in {"cargo", "rustc"} or (name in {"node", "python"} and delta > 0.25):
            busy.append(pid)
    return sorted(busy)


def _process_sample() -> dict[int, tuple[str, float]]:
    sample: dict[int, tuple[str, float]] = {}
    for process in psutil.process_iter(["pid", "name"]):
        try:
            name = (process.info["name"] or "").lower().removesuffix(".exe")
            if name not in {"cargo", "rustc", "node", "python"}:
                continue
            times = process.cpu_times()
            sample[process.pid] = (name, times.user + times.system)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sample


def _busy_now(own_pid: int) -> list[int]:
    first = _process_sample()
    time.sleep(2.0)
    second = _process_sample()
    processes = []
    for pid, (name, total) in second.items():
        if pid not in first:
            delta = 0.0
        else:
            delta = max(0.0, total - first[pid][1])
        processes.append({"pid": pid, "name": name, "cpu_delta": delta})
    return classify_busy_processes(processes, own_pid=own_pid)


def wait_for_quiet_window(
    *,
    timeout_seconds: float = 900.0,
    deadline: Deadline | None = None,
) -> dict[str, Any]:
    """Wait without timing through other lanes' compilations or busy processes.

    The wait is bounded by both its own ``timeout_seconds`` and the gate
    ``deadline``; the latter raises :class:`GateTimeout` instead of running on.
    """
    started = time.monotonic()
    attempts = 0
    blocked: list[dict[str, Any]] = []
    while True:
        if deadline is not None:
            deadline.check("wait:quiet-window")
        attempts += 1
        busy = _busy_now(os.getpid())
        if not busy:
            return {
                "quiet": True,
                "attempts": attempts,
                "elapsed_seconds": time.monotonic() - started,
                "blocked_observations": blocked,
                "pid": os.getpid(),
            }
        blocked.append({"elapsed_seconds": time.monotonic() - started, "busy_pids": busy})
        limit = timeout_seconds
        if deadline is not None:
            remaining = deadline.remaining()
            deadline.check("wait:quiet-window")
            limit = min(limit, remaining)
        if time.monotonic() - started >= limit:
            return {
                "quiet": False,
                "attempts": attempts,
                "elapsed_seconds": time.monotonic() - started,
                "blocked_observations": blocked,
                "pid": os.getpid(),
            }


def _set_windows_memory_cap(memory_bytes: int) -> None:
    if os.name != "nt":
        raise ProfileError("the preregistered Job Object memory cap requires Windows")
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    job = kernel32.CreateJobObjectW(None, "Seeky-WP0.6-Memory-Cap")
    if not job:
        raise ProfileError(f"CreateJobObjectW failed with Win32 error {ctypes.get_last_error()}")
    limits = ExtendedLimitInformation()
    limits.BasicLimitInformation.LimitFlags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    limits.ProcessMemoryLimit = memory_bytes
    if not kernel32.SetInformationJobObject(
        job,
        9,  # JobObjectExtendedLimitInformation
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    ):
        raise ProfileError(f"SetInformationJobObject failed with Win32 error {ctypes.get_last_error()}")
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        raise ProfileError(f"AssignProcessToJobObject failed with Win32 error {ctypes.get_last_error()}")
    # Keep the handle open for the life of the harness process.
    globals()["_active_job_handle"] = job


def apply_profile(profile: RunningProfile) -> dict[str, Any]:
    process = psutil.Process(os.getpid())
    try:
        process.cpu_affinity(profile.cpus)
        if os.name == "nt":
            process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if profile.background else psutil.NORMAL_PRIORITY_CLASS)
        else:
            process.nice(10 if profile.background else 0)
    except (psutil.Error, OSError) as error:
        raise ProfileError("CPU affinity or process priority could not be applied") from error
    _set_windows_memory_cap(profile.memory_bytes)
    result = profile.to_public_dict()
    result["applied_cpus"] = process.cpu_affinity()
    result["pid"] = os.getpid()
    return result


POWERCFG_TIMEOUT_SECONDS = 30.0


@contextlib.contextmanager
def high_performance_power_scheme(
    *,
    deadline: Deadline | None = None,
) -> Iterator[dict[str, str]]:
    """Use a fixed scheme for one timed series and always restore the prior one.

    Setup commands are bounded by the gate ``deadline`` when given; the restore
    keeps its own fixed bound so the host is never left on the timed scheme.
    """
    if os.name != "nt":
        yield {"scheme": "not applicable", "restored": "not applicable"}
        return
    try:
        if deadline is None:
            before = subprocess.run(
                ["powercfg", "/getactivescheme"],
                check=True,
                capture_output=True,
                text=True,
                timeout=POWERCFG_TIMEOUT_SECONDS,
            ).stdout.strip()
        else:
            before = run_bounded(
                ["powercfg", "/getactivescheme"],
                deadline=deadline,
                stage="power:query",
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        match = re.search(r"GUID:\s*([0-9a-fA-F-]+)", before)
        if match is None:
            raise ProfileError("active power scheme GUID could not be parsed")
        previous_guid = match.group(1)
        subprocess.run(
            ["powercfg", "/setactive", "SCHEME_MIN"],
            check=True,
            capture_output=True,
            timeout=POWERCFG_TIMEOUT_SECONDS,
        )
    except GateTimeout:
        raise
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ProfileError("fixed High performance power scheme could not be applied") from error
    restored = False
    try:
        yield {"scheme": "High performance", "previous_guid": previous_guid}
    finally:
        subprocess.run(
            ["powercfg", "/setactive", previous_guid],
            check=True,
            capture_output=True,
            timeout=POWERCFG_TIMEOUT_SECONDS,
        )
        restored = True
    globals()["_last_power_scheme_restored"] = restored


def capture_environment() -> dict[str, Any]:
    """Capture hardware/software facts without user paths or process command lines."""
    information = cpuinfo.get_cpu_info()
    packages = {}
    for package in ("onnxruntime", "onnxruntime-openvino", "openvino", "torch", "transformers"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
    providers: list[str] = []
    try:
        import onnxruntime as ort

        providers = ort.get_available_providers()
    except ImportError:
        pass
    return {
        "capture_schema": 1,
        "os": platform.platform(),
        "os_version": platform.version(),
        "python": platform.python_version(),
        "cpu_model": information.get("brand_raw", "unknown"),
        "cpu_architecture": information.get("arch", "unknown"),
        "cpu_flags": sorted(information.get("flags", [])),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cpus": psutil.cpu_count(logical=True),
        "ram_bytes": psutil.virtual_memory().total,
        "disk_free_bytes": psutil.disk_usage(str(Path.cwd().anchor)).free,
        "packages": packages,
        "ort_available_providers": providers,
        "pid": os.getpid(),
    }


def public_json(value: Any) -> str:
    """Emit stable JSON for result files; NaN is never accepted."""
    return json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n"
