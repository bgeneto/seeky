mod common;

/// SPEC-0002-R3, SPEC-0002-R15: CPU-hybrid ranking matches the captured PoC.
#[test]
#[cfg_attr(
    not(feature = "hw-tests"),
    ignore = "needs local gety-embed-v0, ONNX Runtime, and PDFium; run with --features hw-tests"
)]
fn golden_hybrid_cpu() -> common::TestResult {
    common::run_golden(common::Mode::HybridCpu)
}
