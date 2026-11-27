"""Runner wiring: pinned decode settings, GPU layers, think stripping, cache."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import support
from qrels_drafter import config
from qrels_drafter.model import clean_completion, command_runner, llama_cpp_runner


class RunnerWiring(unittest.TestCase):
    def test_gpu_layers_and_profile_decode_reach_llama_cpp(self):
        runner = llama_cpp_runner("llama-completion.exe", "model.gguf", config.QWEN3_0_6B, gpu_layers=99)
        command = runner.command
        self.assertEqual(command[command.index("-ngl") + 1], "99")
        self.assertEqual(command[command.index("--temp") + 1], "0.7")
        self.assertEqual(command[command.index("--top-p") + 1], "0.8")
        self.assertEqual(command[command.index("--top-k") + 1], "20")
        self.assertEqual(command[command.index("--seed") + 1], "42")

    def test_cpu_default_offloads_no_layers(self):
        runner = llama_cpp_runner("llama-completion.exe", "model.gguf", config.QWEN3_0_6B)
        self.assertEqual(runner.command[runner.command.index("-ngl") + 1], "0")

    def test_think_block_is_stripped(self):
        raw = "\x1b[33m\x1b[0m\n\n</think>\n\n{\"query\": \"maintenance schedule\"}\n\n> EOF by user\n"
        self.assertEqual(
            clean_completion(raw, strip_think=True),
            '{"query": "maintenance schedule"}',
        )

    def test_prompt_cache_replays_without_calling_the_runner(self):
        runner = command_runner([sys.executable, str(support.STUB)], config.QWEN3_0_6B)
        runner.cache_dir = Path(tempfile.mkdtemp(prefix="qrels-drafter-cache-"))
        prompt = "TASK: conceptual\nANCHOR: doc-x\nLANGUAGE: pt-BR\n"
        first = runner.complete(prompt)
        second = runner.complete(prompt)
        self.assertEqual(first, second)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(runner.cache_hits, 1)


if __name__ == "__main__":
    unittest.main()
