mod common;

/// SPEC-0002-R3, SPEC-0002-R15: lexical ranking matches the captured PoC.
#[test]
fn golden_lexical() -> common::TestResult {
    common::run_golden(common::Mode::Lexical)
}
