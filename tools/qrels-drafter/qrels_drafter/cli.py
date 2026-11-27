"""Command line for the offline SDC draft drafter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

from . import config
from .audit import AuditError, audit_directory
from .model import ModelError, command_runner, llama_cpp_runner
from .pipeline import run_draft

LLAMA_CPP = {
    "release": "b12815",
    "url": "https://github.com/ggml-org/llama.cpp/releases/download/b12815/llama-b12815-bin-win-cpu-x64.zip",
    "sha256": "8167d30d05420295ade9b9db3e73d0325aca75b72ced25c030d5dd3d7b0fde5a",
    "archive": "llama-b12815-bin-win-cpu-x64.zip",
}
MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/"
    f"{config.DEFAULT_MODEL.revision}/qwen2.5-1.5b-instruct-q4_k_m.gguf"
)
MODEL_FILE = "qwen2.5-1.5b-instruct-q4_k_m.gguf"


def default_home() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".local" / "share"
    return base / "seeky-dev" / "llm"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cmd_draft(args: argparse.Namespace) -> int:
    runner = None
    if args.llm_command:
        runner = command_runner(args.llm_command)
    elif not args.templates_only:
        if not args.llama_cli or not args.model:
            print(
                "draft needs --llama-cli and --model, or --llm-command, or --templates-only",
                file=sys.stderr,
            )
            return 2
        if _sha256(Path(args.model)) != config.DEFAULT_MODEL.weight_sha256:
            print("the model file does not match the pinned weight SHA-256", file=sys.stderr)
            return 2
        runner = llama_cpp_runner(args.llama_cli, args.model, args.threads)
    summary = run_draft(Path(args.corpus), Path(args.output), runner)
    if runner is not None:
        summary["model_calls"] = runner.calls
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    summary = audit_directory(Path(args.set))
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


def _cmd_verify_model(args: argparse.Namespace) -> int:
    model = Path(args.model)
    if not model.is_file():
        print(f"missing model file: {model.name}", file=sys.stderr)
        return 1
    digest = _sha256(model)
    if digest != config.DEFAULT_MODEL.weight_sha256:
        print(f"model SHA-256 mismatch: {digest}", file=sys.stderr)
        return 1
    if args.llama_cli and not Path(args.llama_cli).is_file():
        print("missing llama.cpp runner", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "model": config.DEFAULT_MODEL.model_id,
                "revision": config.DEFAULT_MODEL.revision,
                "weight_sha256": digest,
                "license": config.DEFAULT_MODEL.license,
                "offline": True,
            },
            sort_keys=True,
        )
    )
    return 0


def _download(url: str, target: Path, expected: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, open(temporary, "wb") as handle:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
    digest = _sha256(temporary)
    if digest != expected:
        temporary.unlink(missing_ok=True)
        raise SystemExit(f"downloaded file does not match the pinned SHA-256: {digest}")
    os.replace(temporary, target)


def _cmd_fetch_model(args: argparse.Namespace) -> int:
    """The only command that may use the network (maintainer setup)."""

    home = Path(args.dest) if args.dest else default_home()
    model = home / MODEL_FILE
    if args.dry_run:
        print(json.dumps({"model": MODEL_URL, "llama_cpp": LLAMA_CPP["url"]}, indent=2))
        return 0
    if not model.is_file():
        _download(MODEL_URL, model, config.DEFAULT_MODEL.weight_sha256)
    elif _sha256(model) != config.DEFAULT_MODEL.weight_sha256:
        print("the existing model file does not match the pin", file=sys.stderr)
        return 1
    archive = home / LLAMA_CPP["archive"]
    runner_dir = home / f"llama.cpp-{LLAMA_CPP['release']}"
    if not runner_dir.is_dir():
        if not archive.is_file():
            _download(LLAMA_CPP["url"], archive, LLAMA_CPP["sha256"])
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(runner_dir)
    print(
        json.dumps(
            {
                "model": str(model),
                "model_sha256": config.DEFAULT_MODEL.weight_sha256,
                "runner": str(runner_dir),
                "llama_cli": str(runner_dir / "llama-completion.exe"),
            },
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qrels-drafter")
    commands = parser.add_subparsers(dest="command", required=True)

    draft = commands.add_parser("draft", help="draft queries and candidate judgments offline")
    draft.add_argument("--corpus", required=True)
    draft.add_argument("--output", required=True)
    draft.add_argument("--llama-cli", default=None)
    draft.add_argument("--model", default=None)
    draft.add_argument("--threads", type=int, default=8)
    draft.add_argument("--llm-command", nargs="+", default=None)
    draft.add_argument("--templates-only", action="store_true")
    draft.set_defaults(handler=_cmd_draft)

    audit = commands.add_parser("audit", help="audit a quarantined draft directory")
    audit.add_argument("--set", required=True)
    audit.set_defaults(handler=_cmd_audit)

    verify = commands.add_parser("verify-model", help="check the pinned local model offline")
    verify.add_argument("--model", required=True)
    verify.add_argument("--llama-cli", default=None)
    verify.set_defaults(handler=_cmd_verify_model)

    fetch = commands.add_parser("fetch-model", help="download the pinned model and runner")
    fetch.add_argument("--dest", default=None)
    fetch.add_argument("--dry-run", action="store_true")
    fetch.set_defaults(handler=_cmd_fetch_model)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (AuditError, ModelError, RuntimeError, ValueError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
