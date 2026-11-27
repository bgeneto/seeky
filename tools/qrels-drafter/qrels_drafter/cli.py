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
    profile = config.PROFILES[args.profile]
    runner = None
    if args.llm_command:
        runner = command_runner(args.llm_command, profile)
    elif not args.templates_only:
        model = Path(args.model) if args.model else default_home() / profile.weight_file
        if not args.llama_cli:
            print("draft needs --llama-cli (or --llm-command, or --templates-only)", file=sys.stderr)
            return 2
        if not model.is_file():
            print(f"missing model file: {model.name}", file=sys.stderr)
            return 2
        if _sha256(model) != profile.weight_sha256:
            print(
                f"the model file does not match the pinned {profile.profile} weight SHA-256",
                file=sys.stderr,
            )
            return 2
        runner = llama_cpp_runner(args.llama_cli, str(model), profile, args.threads, args.gpu_layers)
    summary = run_draft(Path(args.corpus), Path(args.output), runner)
    if runner is not None:
        summary["model_calls"] = runner.calls
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    summary = audit_directory(
        Path(args.set),
        corpus_root=Path(args.corpus) if args.corpus else None,
    )
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


def _cmd_verify_model(args: argparse.Namespace) -> int:
    profile = config.PROFILES[args.profile]
    model = Path(args.model) if args.model else default_home() / profile.weight_file
    if not model.is_file():
        print(f"missing model file: {model.name}", file=sys.stderr)
        return 1
    digest = _sha256(model)
    if digest != profile.weight_sha256:
        print(f"model SHA-256 mismatch: {digest}", file=sys.stderr)
        return 1
    if args.llama_cli and not Path(args.llama_cli).is_file():
        print("missing llama.cpp runner", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "profile": profile.profile,
                "model": profile.model_id,
                "revision": profile.revision,
                "weight_sha256": digest,
                "license": profile.license,
                "decode": profile.decode,
                "offline": True,
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_bakeoff(args: argparse.Namespace) -> int:
    from .bakeoff import decide, render_table, run_bakeoff, write_report

    model_dir = Path(args.model_dir) if args.model_dir else default_home()
    if not args.llama_cli:
        print("bakeoff needs --llama-cli", file=sys.stderr)
        return 2
    models: dict[str, tuple[config.ModelPin, str]] = {}
    for name in args.profiles:
        profile = config.PROFILES[name]
        path = model_dir / profile.weight_file
        if not path.is_file() or _sha256(path) != profile.weight_sha256:
            print(f"{name}: missing or unpinned model file {path.name}", file=sys.stderr)
            return 2
        models[name] = (profile, str(path))
    report = run_bakeoff(Path(args.corpus), models, args.llama_cli, args.threads)
    chosen, reason = decide(report)
    report["decision"] = {"profile": chosen, "reason": reason}
    if args.out:
        write_report(report, Path(args.out))
    print(render_table(report))
    print(json.dumps({"chosen": chosen, "reason": reason}, sort_keys=True))
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
    wanted = [config.PROFILES[name] for name in args.profiles]
    if args.dry_run:
        print(
            json.dumps(
                {
                    profile.profile: {
                        "url": f"https://huggingface.co/{profile.repo}/resolve/{profile.revision}/{profile.weight_file}",
                        "sha256": profile.weight_sha256,
                    }
                    for profile in wanted
                },
                indent=2,
            )
        )
        return 0
    downloaded: dict[str, str] = {}
    for profile in wanted:
        model = home / profile.weight_file
        if not model.is_file():
            _download(
                f"https://huggingface.co/{profile.repo}/resolve/{profile.revision}/{profile.weight_file}",
                model,
                profile.weight_sha256,
            )
        elif _sha256(model) != profile.weight_sha256:
            print(f"{profile.weight_file} does not match the pin", file=sys.stderr)
            return 1
        downloaded[profile.profile] = str(model)
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
                "models": downloaded,
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
    draft.add_argument("--profile", default=config.DEFAULT_PROFILE, choices=sorted(config.PROFILES))
    draft.add_argument("--threads", type=int, default=8)
    draft.add_argument(
        "--gpu-layers",
        type=int,
        default=0,
        help="llama.cpp -ngl; 99 offloads all layers to a CUDA dev runner",
    )
    draft.add_argument("--llm-command", nargs="+", default=None)
    draft.add_argument("--templates-only", action="store_true")
    draft.set_defaults(handler=_cmd_draft)

    audit = commands.add_parser("audit", help="audit a quarantined draft directory")
    audit.add_argument("--set", required=True)
    audit.add_argument("--corpus", default=None, help="also run the language and no-copy audit")
    audit.set_defaults(handler=_cmd_audit)

    verify = commands.add_parser("verify-model", help="check a pinned local model offline")
    verify.add_argument("--profile", default=config.DEFAULT_PROFILE, choices=sorted(config.PROFILES))
    verify.add_argument("--model", default=None)
    verify.add_argument("--llama-cli", default=None)
    verify.set_defaults(handler=_cmd_verify_model)

    bakeoff = commands.add_parser("bakeoff", help="bounded head-to-head model comparison")
    bakeoff.add_argument("--corpus", required=True)
    bakeoff.add_argument("--llama-cli", required=True)
    bakeoff.add_argument("--model-dir", default=None)
    bakeoff.add_argument("--threads", type=int, default=8)
    bakeoff.add_argument("--profiles", nargs="+", default=sorted(config.PROFILES))
    bakeoff.add_argument("--out", default=None)
    bakeoff.set_defaults(handler=_cmd_bakeoff)

    fetch = commands.add_parser("fetch-model", help="download the pinned models and runner")
    fetch.add_argument("--dest", default=None)
    fetch.add_argument("--profiles", nargs="+", default=sorted(config.PROFILES))
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
