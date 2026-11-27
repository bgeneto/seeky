# WP-1.8 Smoke Gate — Activation and Re-baseline Runbook

| Field | Value |
|---|---|
| Work package | WP-1.8 (SPEC-0003 R29–R31, §5.6) |
| Workflow | [`.github/workflows/smoke-gate.yml`](../../.github/workflows/smoke-gate.yml) |
| CI config | [`tools/seeky-bench/configs/ci-smoke-lexical.json`](../../tools/seeky-bench/configs/ci-smoke-lexical.json) |
| Decision date | 2026-11-27 (maintainer choices for runner PDFium/OCR and intentional re-baselining) |

This runbook documents the runner extraction setup, the intentional re-baseline
procedure, and the final steps required to make the WP-1.8 smoke gate a
required PR check once H6 publishes `bench/qrels/sdc/sdc-smoke-v1/` on `main`.

## 1. Runner PDFium and OCR policy

- **PDFium (enabled on `ubuntu-latest`):** `sdc-smoke` contains text PDFs whose
  body text is required for smoke retrieval coverage. The workflow downloads a
  pinned Linux x64 archive from `bblanchon/pdfium-binaries` (Apache-2.0,
  allowed under ADR-0022), verifies its exact SHA-256 digest before extracting,
  caches `${{ runner.temp }}/pdfium` across runs, and sets
  `SEEKY_PDFIUM_DLL=${{ runner.temp }}/pdfium/lib/libpdfium.so` for both the
  baseline (`main`) and candidate/repeat (PR head) runs.
  - Current pin: `chromium/8179` (`pdfium-linux-x64.tgz`, SHA-256
    `b4766a6bf2856efbcc6c3cc7d6ae9022bdc6bb36ddc1acdd92d1f1873f773f4b`).
  - Updating the pin: update `PDFIUM_TAG`, `PDFIUM_URL`, and `PDFIUM_SHA256`
    together in `.github/workflows/smoke-gate.yml`; both baseline and candidate
    use the same runner PDFium binary.
- **OCR (absent until WP-3.8):** No OCR engine ships in Phases 0–2. Scanned PDF
  and PNG variants in `sdc-smoke` remain unextracted equally on baseline and
  candidate until WP-3.8 lands an OCR pack and updates this policy.

## 2. Intentional default changes (re-baseline path)

By default (`SPEC-0003-R29`), `compare --gate wp1.8` requires identical
`config_hash` across `baseline` (`main`), `candidate` (PR head), and `repeat`.
In CI, `baseline` runs with `baseline/tools/seeky-bench/configs/ci-smoke-lexical.json`
and `candidate`/`repeat` run with `candidate/tools/seeky-bench/configs/ci-smoke-lexical.json`,
so any unannounced default or config change fails closed with `INPUT_MISMATCH`.

When a PR **intentionally** changes an engine default or the CI smoke
configuration (backed by an Accepted ADR and benchmark report):

1. Add a standalone line to the PR description naming the governing ADR:

   ```text
   smoke-rebaseline: ADR-NNNN
   ```

2. The maintainer reviews the ADR/evidence and applies the GitHub PR label
   `smoke-rebaseline`. (Without the maintainer-applied label, the line in the
   PR body has no effect; if the label is applied without a valid `ADR-NNNN`
   line, the workflow fails closed.)
3. The workflow passes `--allow-config-change ADR-NNNN` to
   `seeky-bench compare --gate wp1.8`. For manual verification via
   `workflow_dispatch`, pass the `allow_config_change` input directly.
4. What `--allow-config-change ADR-NNNN` permits and what stays enforced:
   - **Permitted:** `baseline.system.config_hash` may differ from
     `candidate.system.config_hash`. The override and both hashes are recorded
     under `gates[0].observed.config_change_override` and in `gates[0].details`.
   - **Still enforced without exception:**
     - `candidate.system.config_hash == repeat.system.config_hash` (R29/R31);
     - `baseline` matches the current `main` SHA and all runs are clean (R29/R30);
     - `sdc-smoke-v1` is published, frozen, `test_exposure = not-applicable`,
       every query and judgment is verified or adjudicated, and no code results
       are present (R30);
     - all R31 ranking invariants and identical repeat target order hold;
     - candidate macro nDCG@10 over the eight non-code categories drops by at
       most **1.0 point** versus `main` (R29).
5. Once the PR merges into `main`, `main` itself becomes the new baseline for
   all subsequent PRs automatically — no hand-edited baseline file exists.

## 3. Post-H6 activation checklist

Once H6 merges the verified, frozen `bench/qrels/sdc/sdc-smoke-v1/` onto
`main`:

1. Create the repository label `smoke-rebaseline` (if not already present).
2. Open a small test PR (or run `workflow_dispatch` on `main`) and confirm
   `Smoke gate (WP-1.8)` runs end-to-end (no longer dormant), downloads/caches
   the pinned PDFium runtime, extracts text PDFs cleanly, and passes
   `compare --gate wp1.8`.
3. Add `WP-1.8 smoke gate (sdc-smoke-v1, lexical, hardware-free)` to `main`
   branch protection as a required status check.
4. Mark WP-1.8 **Done** in `docs/plans/seeky-implementation-plan.md` §15.3 and
   update §16.
