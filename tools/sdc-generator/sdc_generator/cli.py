"""Command-line interface (SPEC-0004 section 4.1).

Only ``fetch`` may use the network; ``build`` and ``verify`` work offline.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .errors import INTERNAL_ERROR, SdcError
from .sources import fetch_sources

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _repo_root(value: str | None) -> Path:
    if value is not None:
        return Path(value).resolve()
    return _REPO_ROOT


def _cmd_fetch(args: argparse.Namespace) -> int:
    fetched = fetch_sources(
        sources_dir=Path(args.sources),
        cache=Path(args.cache),
        repo_root=_repo_root(args.repo_root),
        source_set_ids=args.source_set or None,
        timeout=args.timeout,
    )
    print(f"fetched {len(fetched)} source item(s)")
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    from .build import build_corpus
    from .profiles import load_profile

    profile = load_profile(Path(args.profile))
    seed = args.seed or profile.default_seed
    manifest = build_corpus(
        profile_path=Path(args.profile),
        seed=seed,
        sources_dir=Path(args.sources),
        cache=Path(args.cache),
        output=Path(args.output),
        repo_root=_repo_root(args.repo_root),
    )
    print(manifest["corpus_hash"])
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    from .verify import verify_corpus

    summary = verify_corpus(Path(args.output))
    print(summary["corpus_hash"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sdc-generator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch", help="download pinned sources and licenses")
    fetch.add_argument("--sources", required=True)
    fetch.add_argument("--cache", required=True)
    fetch.add_argument("--repo-root", default=None)
    fetch.add_argument("--source-set", action="append", default=None)
    fetch.add_argument("--timeout", type=float, default=60.0)
    fetch.set_defaults(handler=_cmd_fetch)

    build = subparsers.add_parser("build", help="build a corpus profile")
    build.add_argument("--profile", required=True)
    build.add_argument("--seed", default=None)
    build.add_argument("--sources", required=True)
    build.add_argument("--cache", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--repo-root", default=None)
    build.set_defaults(handler=_cmd_build)

    verify = subparsers.add_parser("verify", help="verify a generated corpus")
    verify.add_argument("--output", required=True)
    verify.set_defaults(handler=_cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except SdcError as error:
        print(error.as_json(), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        if os.environ.get("SDC_DEBUG"):
            raise
        print(
            SdcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}").as_json(),
            file=sys.stderr,
        )
        return 1
