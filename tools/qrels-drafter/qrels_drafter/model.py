"""Local instruct-model client: llama.cpp subprocess, no network, no sockets.

The only process this module starts is the pinned local runner. Prompts, model
output, and corpus text stay on the machine: there is no socket, no URL, and no
hosted API anywhere in the drafter (SPEC-0004 R21).
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field

from . import config
from .jsonio import canonical_sha256

PROMPT_VERSION = "qrels-drafter-prompts-v1"
TIMEOUT_SECONDS = 240

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_THINK = re.compile(r"<think\b[^>]*>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)
_THINK_TAG = re.compile(r"</?think\b[^>]*>", re.IGNORECASE)


class ModelError(RuntimeError):
    pass


def clean_completion(stdout: str, *, strip_think: bool = False) -> str:
    """Strip llama-completion's colour codes, echo prefix, EOF marker, and any
    `` thinking`` block that the model emitted despite ``/no_think``."""

    text = _ANSI.sub("", stdout.replace("\r\n", "\n"))
    lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip().lower()
        if stripped == "eof by user" or stripped.startswith("> eof by user"):
            break
        if line.startswith("> "):
            line = line[2:]
        lines.append(line)
    text = "\n".join(lines).strip()
    if strip_think:
        text = _THINK.sub("", text)
        text = _THINK_TAG.sub("", text)
    text = text.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1].strip()
    return text


@dataclass
class Runner:
    """A pinned local command that answers one prompt at a time."""

    command: list[str]
    label: str
    model: config.ModelPin = config.DEFAULT_MODEL
    prompt_style: str = "stdin"  # "stdin" for the test stub, "argv" for llama.cpp
    _calls: int = field(default=0, init=False)
    _latencies: list[float] = field(default_factory=list, init=False)

    def complete(self, prompt: str) -> str:
        import time

        environment = dict(os.environ)
        # Keep the child deterministic and quiet; llama.cpp logs on stderr.
        environment.pop("LLAMA_ARG_LOG_FILE", None)
        argv = self.command
        if self.prompt_style == "argv":
            argv = [*self.command, "-p", prompt + self.model.prompt_suffix]
        started = time.perf_counter()
        try:
            finished = subprocess.run(
                argv,
                input=prompt.encode("utf-8") if self.prompt_style == "stdin" else None,
                stdin=subprocess.DEVNULL if self.prompt_style != "stdin" else None,
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
        elapsed = time.perf_counter() - started
        if finished.returncode != 0:
            raise ModelError(
                f"the local runner {self.label!r} exited {finished.returncode}"
            )
        self._calls += 1
        self._latencies.append(elapsed)
        text = clean_completion(
            finished.stdout.decode("utf-8", "replace"), strip_think=self.model.strip_think
        )
        if not text:
            raise ModelError(f"the local runner {self.label!r} returned no text")
        return text

    @property
    def calls(self) -> int:
        return self._calls

    @property
    def latencies(self) -> list[float]:
        return list(self._latencies)


def llama_cpp_runner(
    cli: str,
    model_path: str,
    model: config.ModelPin = config.DEFAULT_MODEL,
    threads: int = 8,
) -> Runner:
    decode = model.decode
    command = [
        cli,
        "-m",
        model_path,
        "-n",
        str(decode["max_tokens"]),
        "--temp",
        str(decode["temperature"]),
        "--top-k",
        str(decode["top_k"]),
        "--top-p",
        str(decode["top_p"]),
        "--presence-penalty",
        str(decode["presence_penalty"]),
        "--seed",
        str(decode["seed"]),
        "--threads",
        str(threads),
        "--no-warmup",
        "--no-display-prompt",
    ]
    return Runner(command=command, label="llama.cpp", model=model, prompt_style="argv")


def command_runner(argv: list[str], model: config.ModelPin = config.DEFAULT_MODEL) -> Runner:
    return Runner(command=list(argv), label="custom command", model=model)


def prompt_sha256(category: str, task: str, prompt: str, model: config.ModelPin = config.DEFAULT_MODEL) -> str:
    """Hash the versioned template, the actual input, and the decode settings."""

    return canonical_sha256(
        {
            "prompt_version": PROMPT_VERSION,
            "category": category,
            "task": task,
            "prompt": prompt,
            "model": model.as_dict(),
        }
    )
