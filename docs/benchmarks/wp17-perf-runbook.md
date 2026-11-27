# WP-1.7 Baseline B0 — T1-Emulated Performance Runbook (Gate H3)

| Field | Value |
|---|---|
| Work package | WP-1.7 (performance half; quality half waits on H6) |
| Gate H3 | **Approved 2026-11-27** by maintainer |
| Profile | `T1-emulated`: logical CPUs `0-7` (8 CPUs), `12 GiB` (`12884901888` bytes) process memory cap via Windows Job Object, AC power / High Performance scheme, local NVMe |
| Launcher | [`tools/seeky-bench/scripts/run-t1-emulated.ps1`](../../tools/seeky-bench/scripts/run-t1-emulated.ps1) |

## 1. Why a PowerShell Job-Object launcher (not Python)

`seeky-bench perf` (SPEC-0003 R28) verifies two preconditions before declaring
a run budget-eligible (`qualifies_for_budget = true`):

1. **Process CPU affinity** must match `--cpus 0-7` (checked via Win32
   `GetProcessAffinityMask`).
2. **Quiet window** must see no running `cargo`, `rustc`, `node`, `python*`, or
   second `seeky-bench` process.

Launching from Python would trip the `python*` quiet-window rule and force
`qualifies_for_budget = false`. `run-t1-emulated.ps1` uses a Win32 Job Object
with `JOB_OBJECT_LIMIT_AFFINITY` (`0xFF`, CPUs `0-7`) and
`JOB_OBJECT_LIMIT_PROCESS_MEMORY` (`12 GiB`), so both `seeky-bench.exe` and its
cold-start child probe inherit the exact H3 profile cleanly.

## 2. Running `sdc-s` perf measurements before H6 completes

`seeky-bench perf` only issues fixed `dev` query texts and never reads or scores
relevance grades. Passing `--queries-file bench/qrels/sdc/drafts/sdc-v1/queries.draft.jsonl`
filters strictly to `split == "dev"` default queries (never loading `test` or
`code_search` queries), allowing the WP-1.7 performance half on `sdc-s` to run
immediately once the workstation has a quiet window (no WP-0.6 / `python` /
`cargo` processes active).

### Step 1 — Build the release binary (outside the timed window)

```powershell
cargo build --release -p seeky-bench
```

### Step 2 — Index `sdc-s` into an external data directory

```powershell
.\target\release\seeky-bench.exe index `
  --corpus sdc-s `
  --config tools\seeky-bench\configs\b0-poc-cpu.json `
  --data-dir %LOCALAPPDATA%\seeky-dev\b0-perf\sdc-s-cpu `
  --output %LOCALAPPDATA%\seeky-dev\b0-perf\index-cpu `
  --work-package WP-1.7 --spec SPEC-0003
```

Repeat with `tools\seeky-bench\configs\b0-poc-lexical.json` for the BM25-only
lexical reference.

### Step 3 — Verify a quiet window, then run `seeky-bench perf` under H3

Ensure no `python`, `cargo`, `rustc`, or `node` processes are running, then:

```powershell
.\tools\seeky-bench\scripts\run-t1-emulated.ps1 `
  -BenchExe .\target\release\seeky-bench.exe `
  -Corpus sdc-s `
  -Config tools\seeky-bench\configs\b0-poc-cpu.json `
  -DataDir %LOCALAPPDATA%\seeky-dev\b0-perf\sdc-s-cpu `
  -Output docs\benchmarks\results\<YYYY-MM-DD>-baseline-b0\perf-sdc-s-cpu `
  -QueriesFile bench\qrels\sdc\drafts\sdc-v1\queries.draft.jsonl `
  -Repetitions 30
```

Confirm in the emitted `results.json`:

- `environment.tier == "T1-emulated"`
- `environment.emulation.logical_cpus == [0, 1, 2, 3, 4, 5, 6, 7]`
- `environment.emulation.memory_limit_bytes == 12884901888`
- `environment.quiet_window.verified == true`
- `performance.qualifies_for_budget == true`

All T1-emulated numbers are labeled `T1-emulated` in the report per
`docs/benchmarks/methodology.md` §4.

## 3. What remains for WP-1.7 Done

1. Execute Step 2–3 on a quiet workstation after WP-0.6 completes and commit
   the resulting performance artifacts under `docs/benchmarks/results/<date>-baseline-b0/`.
2. After H6 verifies and freezes `bench/qrels/sdc/sdc-v1/`, run the B0 quality
   evaluations (`PoC`, `BM25-only`, `dense-only`, `filename-only`, and
   Gety-style `0.2/0.8` reference) and write the budgets lock ADR.
