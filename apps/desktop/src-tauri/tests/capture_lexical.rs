mod golden_capture;

/// SPEC-0002-R4: capture the lexical PoC ranking before the engine moves.
#[test]
fn capture_lexical_snapshot() -> anyhow::Result<()> {
    golden_capture::capture_or_verify(golden_capture::Mode::Lexical)
}
