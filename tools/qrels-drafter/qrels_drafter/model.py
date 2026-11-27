"""Local instruct-model client: llama.cpp subprocess, no network, no sockets.

The only process this module starts is the pinned local runner. Prompts, model
output, and corpus text stay on the machine: there is no socket, no URL, and no
hosted API anywhere in the drafter (SPEC-0004 R21).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

from . import config
from .jsonio import canonical_sha256

PROMPT_VERSION = "qrels-drafter-prompts-v1"
TIMEOUT_SECONDS = 240


class ModelError(RuntimeError):
    pass


def clean_completion(stdout: str) -> str:
    """Strip llama-completion's prompt tail and per-line ``> `` echo prefix."""

    text = stdout.replace("\r\n", "\n")
    lines: list[str] = []
    for line in text.split("\n"):
        if line.lstrip().startswith("> EOF"):
            break
        if line.startswith("> "):
            line = line[2:]
        lines.append(line)
    text = "\n".join(lines).strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1].strip()
    return text


@dataclass
class Runner:
    """A pinned local command; the prompt is written to stdin."""

    command: list[str]
    label: str
    _calls: int = field(default=0, init=False)

    def complete(self, prompt: str) -> str:
        environment = dict(os.environ)
        # Keep the child deterministic and quiet; llama.cpp logs on stderr.
        environment.pop("LLAMA_ARG_LOG_FILE", None)
        try:
            finished = subprocess.run(
                self.command,
                input=prompt.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=TIMEOUT_SECONDS,
                check=False,
                env=environment,
            )
        except OSError as exc:
            raise ModelError(f"cannot start the local runner {self.label!r}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ModelError(f"the local runner {self.label!r} timed out") from exc
        if finished.returncode != 0:
            raise ModelError(
                f"the local runner {self.label!r} exited {finished.returncode}"
            )
        self._calls += 1
        text = clean_completion(finished.stdout.decode("utf-8", "replace"))
        if not text:
            raise ModelError(f"the local runner {self.label!r} returned no text")
        return text

    @property
    def calls(self) -> int:
        return self._calls


def llama_cpp_runner(cli: str, model_path: str, threads: int = 8) -> Runner:
    command = [
        cli,
        "-m",
        model_path,
        "-n",
        str(config.DECODE["max_tokens"]),
        "--temp",
        "0",
        "--top-k",
        "1",
        "--seed",
        str(config.DECODE["seed"]),
        "--threads",
        str(threads),
        "--no-warmup",
        "--no-display-prompt",
    ]
    return Runner(command=command, label="llama.cpp")


def command_runner(argv: list[str]) -> Runner:
    return Runner(command=list(argv), label="custom command")


def prompt_sha256(category: str, task: str, prompt: str) -> str:
    """Hash the versioned template, the actual input, and the decode settings."""

    return canonical_sha256(
        {
            "prompt_version": PROMPT_VERSION,
            "category": category,
            "task": task,
            "prompt": prompt,
            "model": config.DEFAULT_MODEL.as_dict(),
            "decode": config.DECODE,
        }
    )
