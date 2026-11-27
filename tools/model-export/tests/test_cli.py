# WP-0.6: every gate subcommand exposes the bounded timeout flag.
import pytest

import seeky_model_export.cli as cli
from seeky_model_export.deadline import DEFAULT_GATE_TIMEOUT_SECONDS, GateTimeout

GATE_ARGV = {
    "t0": ["t0"],
    "encoders": ["encoders", "--model", "e5-small"],
    "reranker": ["reranker"],
    "ocr": ["ocr"],
    "florence": ["florence"],
    "npu": ["npu"],
}


@pytest.mark.parametrize("command", sorted(GATE_ARGV))
def test_every_gate_subcommand_accepts_a_timeout_override(command):
    args = cli.build_parser().parse_args(
        ["--workspace", "unused", *GATE_ARGV[command], "--timeout-seconds", "12.5"]
    )
    assert args.timeout_seconds == pytest.approx(12.5)


@pytest.mark.parametrize("command", sorted(GATE_ARGV))
def test_every_gate_subcommand_defaults_to_the_gate_ceiling(command):
    args = cli.build_parser().parse_args(["--workspace", "unused", *GATE_ARGV[command]])
    assert args.timeout_seconds == pytest.approx(DEFAULT_GATE_TIMEOUT_SECONDS)
    assert DEFAULT_GATE_TIMEOUT_SECONDS == 1800.0


def test_prepare_commands_have_no_timeout_flag():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["--workspace", "unused", "prepare-text", "--timeout-seconds", "5"]
        )


def test_gate_timeout_exits_nonzero_with_a_clear_message(tmp_path, monkeypatch, capsys):
    def timeout(args, workspace, deadline):
        raise GateTimeout("reranker:fp32:time", 1800.0, 1800.0)

    monkeypatch.setattr(cli, "_dispatch", timeout)
    code = cli.main(["--workspace", str(tmp_path), "reranker"])
    assert code == cli.TIMEOUT_EXIT_CODE == 124
    message = capsys.readouterr().err
    assert "reranker:fp32:time" in message
    assert "timed out" in message
    assert "results/reranker-timeout.json" in message
    assert "no K1-K4 verdict" in message


def test_nonpositive_timeout_is_rejected_before_any_gate_runs(tmp_path):
    with pytest.raises(SystemExit) as raised:
        cli.main(["--workspace", str(tmp_path), "ocr", "--timeout-seconds", "0"])
    assert raised.value.code == 2
