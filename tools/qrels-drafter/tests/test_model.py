"""Runner wiring: pinned decode settings, GPU layers, think stripping."""

from __future__ import annotations

import unittest

from qrels_drafter import config
from qrels_drafter.model import clean_completion, llama_cpp_runner


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


if __name__ == "__main__":
    unittest.main()
