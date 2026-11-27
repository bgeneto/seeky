//! `seeky-bench` binary. Internal tooling; never shipped (ADR-0008).

#![allow(clippy::print_stdout, clippy::print_stderr)]

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match seeky_bench::run(args) {
        Ok(()) => {}
        Err(failure) => {
            eprintln!("seeky-bench: {}", failure.message);
            std::process::exit(failure.code);
        }
    }
}
