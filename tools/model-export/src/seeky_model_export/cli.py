"""Command line entry point for the offline WP-0.6 gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .artifacts import ensure_external_workspace, write_json
from .data import acquire_gutenberg_texts, acquire_text_data
from .deadline import DEFAULT_GATE_TIMEOUT_SECONDS, Deadline, GateTimeout
from .encoder_run import run_encoder_gate
from .florence_run import run_florence_gate
from .models import EMBEDDERS, PROXY_RERANKER, RERANKERS
from .npu_run import run_npu_gate
from .ocr_data import render_ocr_pages
from .ocr_memory import run_ocr_memory_gate
from .ocr_run import run_ocr_gate
from .report_export import export_results
from .reranker_run import run_reranker_gate
from .system import RunningProfile
from .t0_run import run_t0_functional

TIMEOUT_EXIT_CODE = 124
GATE_COMMANDS = ("encoders", "reranker", "ocr", "ocr-memory", "florence", "npu")


def _workspace(value: str) -> Path:
    return ensure_external_workspace(value)


def _profile(name: str) -> RunningProfile:
    return RunningProfile.t1_emulated() if name == "t1" else RunningProfile.t0_functional()


def _timeout_artifact(args: argparse.Namespace) -> str:
    if args.command == "encoders":
        return f"results/encoders-{args.model}-timeout.json"
    if args.command == "t0":
        return "results/t0-functional-timeout.json"
    return f"results/{args.command}-timeout.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seeky-model-export")
    parser.add_argument("--workspace", required=True, help="artifact directory outside every Git worktree")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("prepare-text", help="acquire frozen MIRACL/mMARCO samples")
    subcommands.add_parser("prepare-ocr", help="render public-domain OCR pages")
    t0 = subcommands.add_parser("t0", help="run the T0 functional check")
    t0.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_GATE_TIMEOUT_SECONDS,
        help="whole-gate wall-clock ceiling in seconds",
    )
    exporter = subcommands.add_parser("export-results", help="sanitize results and compute verdicts")
    exporter.add_argument("--destination", required=True)

    for name in GATE_COMMANDS:
        command = subcommands.add_parser(name)
        command.add_argument("--profile", choices=["t1", "t0"], default="t1")
        command.add_argument("--wait-seconds", type=float, default=900.0)
        command.add_argument(
            "--timeout-seconds",
            type=float,
            default=DEFAULT_GATE_TIMEOUT_SECONDS,
            help=(
                "whole-gate wall-clock ceiling in seconds; expiry writes "
                "results/<gate>-timeout.json and exits 124"
            ),
        )
        if name == "encoders":
            command.add_argument("--model", choices=list(EMBEDDERS), required=True)
        if name == "reranker":
            command.add_argument("--model", choices=list(RERANKERS), default=PROXY_RERANKER)
    return parser


def _dispatch(args: argparse.Namespace, workspace: Path, deadline: Deadline | None) -> int:
    if args.command == "prepare-text":
        frozen = acquire_text_data(workspace)
        print(
            json.dumps(
                {
                    "miracl_passages": len(frozen["miracl"]["passages"]),
                    "mmarco_passages": len(frozen["mmarco"]["passages"]),
                    "frozen_sha256": frozen["frozen_sha256"],
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "prepare-ocr":
        acquire_gutenberg_texts(workspace)
        manifest = render_ocr_pages(workspace)
        print(json.dumps({"pages": len(manifest["pages"])}, sort_keys=True))
        return 0
    if args.command == "export-results":
        summary = export_results(workspace, Path(args.destination))
        print(json.dumps(summary["verdicts"], sort_keys=True))
        return 0
    if args.command == "t0":
        result = run_t0_functional(workspace, deadline=deadline)
        print(json.dumps({"passed": result["passed"], "checks": result["checks"]}, sort_keys=True))
        return 0
    if args.command == "encoders":
        result = run_encoder_gate(
            workspace,
            args.model,
            profile=_profile(args.profile),
            wait_seconds=args.wait_seconds,
            deadline=deadline,
        )
        summary = {
            name: {
                "parity_passed": value["parity_passed"],
                "query_p95_ms": None if not value["timing"] else value["timing"]["query"]["p95_ms"],
                "passages_per_second": (
                    None if not value["timing"] else value["timing"]["passage"]["passages_per_second"]
                ),
            }
            for name, value in result["variants"].items()
        }
        print(json.dumps(summary, sort_keys=True))
        return 0
    if args.command == "reranker":
        result = run_reranker_gate(
            workspace,
            profile=_profile(args.profile),
            wait_seconds=args.wait_seconds,
            deadline=deadline,
            model=args.model,
        )
        summary = {
            name: {
                "parity_passed": value["parity_passed"],
                "depth_50_p95_ms": None if not value["timing"] else value["timing"]["depth_50"]["p95_ms"],
            }
            for name, value in result["variants"].items()
        }
        print(json.dumps(summary, sort_keys=True))
        return 0
    if args.command == "ocr":
        result = run_ocr_gate(
            workspace,
            profile=_profile(args.profile),
            wait_seconds=args.wait_seconds,
            deadline=deadline,
        )
        summary = {
            name: {
                "parity_passed": value["parity_passed"],
                "page_p95_ms": None if not value["timing"] else value["timing"]["page"]["p95_ms"],
                "peak_added_bytes": (
                    None if not value["timing"] else value["timing"]["added_peak_rss_bytes_upper_bound"]
                ),
                "CER": value["quality"]["CER"],
            }
            for name, value in result["variants"].items()
        }
        print(json.dumps(summary, sort_keys=True))
        return 0
    if args.command == "florence":
        result = run_florence_gate(
            workspace,
            profile=_profile(args.profile),
            wait_seconds=args.wait_seconds,
            deadline=deadline,
        )
        summary = {
            name: {
                "parity_passed": value.get("parity_passed", False),
                "early_stop": value.get("early_stop_all_above_4s"),
                "page_p95_ms": (
                    None if not value.get("timing") else value["timing"]["page"]["p95_ms"]
                ),
            }
            for name, value in result["variants"].items()
        }
        print(json.dumps(summary, sort_keys=True))
        return 0
    if args.command == "ocr-memory":
        result = run_ocr_memory_gate(workspace, profile=_profile(args.profile), deadline=deadline)
        print(json.dumps(result["variants"], sort_keys=True))
        return 0
    if args.command == "npu":
        result = run_npu_gate(workspace, profile=_profile(args.profile), deadline=deadline)
        print(json.dumps({"k3_passed": result["k3_passed"]}, sort_keys=True))
        return 0
    write_json(workspace / "results" / "unexpected.json", {"error": "unhandled command"})
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    workspace = _workspace(args.workspace)

    deadline = None
    if args.command in (*GATE_COMMANDS, "t0"):
        try:
            deadline = Deadline(args.timeout_seconds)
        except ValueError as error:
            parser.error(str(error))

    try:
        return _dispatch(args, workspace, deadline)
    except GateTimeout as timeout:
        print(
            f"seeky-model-export: {args.command} timed out at {timeout.stage} after "
            f"{timeout.elapsed_seconds:.1f}s (limit {timeout.limit_seconds:.1f}s); "
            f"completed variants are in {_timeout_artifact(args)} and no K1-K4 "
            "verdict was emitted",
            file=sys.stderr,
        )
        return TIMEOUT_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
