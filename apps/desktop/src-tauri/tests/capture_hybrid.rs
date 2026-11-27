mod golden_capture;

/// SPEC-0002-R4: capture the CPU-hybrid PoC ranking before the engine moves.
#[test]
#[cfg_attr(
    not(feature = "hw-tests"),
    ignore = "needs local gety-embed-v0, ONNX Runtime, and PDFium; run with --features hw-tests"
)]
fn capture_hybrid_cpu_snapshot() -> anyhow::Result<()> {
    golden_capture::capture_or_verify(golden_capture::Mode::HybridCpu)
}
