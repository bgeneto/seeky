//! Development-only round-trip harness for SPEC-0004-R7.
//!
//! Usage: `sdc-engine-roundtrip <pdfium-dll> <file>`
//!
//! Extracts a rendered file with the real engine extractor and writes the text
//! to stdout. The Python test suite compares it with canonical truth.

use std::path::Path;
use std::process::ExitCode;

fn main() -> ExitCode {
    let mut args = std::env::args_os().skip(1);
    let Some(pdfium) = args.next() else {
        eprintln!("usage: sdc-engine-roundtrip <pdfium-dll> <file>");
        return ExitCode::FAILURE;
    };
    let Some(file) = args.next() else {
        eprintln!("usage: sdc-engine-roundtrip <pdfium-dll> <file>");
        return ExitCode::FAILURE;
    };
    match seeky_extract::extract(Path::new(&file), Path::new(&pdfium)) {
        Ok(text) => {
            print!("{text}");
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("extract failed: {error}");
            ExitCode::FAILURE
        }
    }
}
