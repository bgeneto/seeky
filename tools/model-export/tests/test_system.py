# WP-0.6: quiet-window and profile validation without touching host processes.
import pytest

from seeky_model_export.system import (
    ProfileError,
    RunningProfile,
    classify_busy_processes,
)


def test_cargo_and_rustc_always_block_other_lane_timing():
    processes = [
        {"pid": 10, "name": "cargo.exe", "cpu_delta": 0.0},
        {"pid": 11, "name": "rustc.exe", "cpu_delta": 0.0},
    ]
    assert classify_busy_processes(processes, own_pid=99) == [10, 11]


def test_busy_node_and_python_block_but_idle_processes_do_not():
    processes = [
        {"pid": 10, "name": "node.exe", "cpu_delta": 0.26},
        {"pid": 11, "name": "node.exe", "cpu_delta": 0.24},
        {"pid": 12, "name": "python.exe", "cpu_delta": 0.5},
        {"pid": 99, "name": "python.exe", "cpu_delta": 2.0},
    ]
    assert classify_busy_processes(processes, own_pid=99) == [10, 12]


def test_profile_validation_rejects_invalid_ranges():
    with pytest.raises(ProfileError):
        RunningProfile(name="bad", cpus=[], memory_bytes=1024, ort_threads=1)
    with pytest.raises(ProfileError):
        RunningProfile(name="bad", cpus=[0, 1], memory_bytes=0, ort_threads=2)
    with pytest.raises(ProfileError):
        RunningProfile(name="bad", cpus=[0, 1], memory_bytes=1024, ort_threads=3)
    with pytest.raises(ProfileError):
        RunningProfile(name="bad", cpus=[0, 0], memory_bytes=1024, ort_threads=1)


def test_preregistered_profiles_match_core_and_thread_counts():
    t1 = RunningProfile.t1_emulated()
    t0 = RunningProfile.t0_functional()
    assert t1.cpus == list(range(8))
    assert t1.ort_threads == 8
    assert t1.memory_bytes == 12 * 1024**3
    assert t0.cpus == list(range(4))
    assert t0.ort_threads == 4
    assert t0.memory_bytes == 6 * 1024**3
