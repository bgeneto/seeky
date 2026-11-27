# 08 — Evidence Ledger

This ledger records what was observed, how, and what remains inferred or
unknown. It is intentionally explicit about the auto-update that occurred
during the investigation.

---

## 1. Tooling

| Tool | Version / configuration |
|---|---|
| REA | `rea-agents 6.10.1`, SDK 2.3.1, live server `6.10.1` |
| Ghidra | 12.2 (`T:\tools\ghidra_12.2_PUBLIC`) |
| JDK | 27.0.1.1 (`C:\Program Files\Java\jdk-27.0.1.1`) |
| Ghidra heap | `GHIDRA_HEADLESS_MAXMEM=18G` for the 113 MB `Gety.exe` run |
| Node | 26.13.1 (used for local string extraction and SQLite schema reads) |
| OS | Windows, x64, 64 GB RAM, 20 logical CPUs |

> The live OpenCode `rea` MCP server was configured with
> `GHIDRA_INSTALL_DIR=%USERPROFILE%\tools\ghidra_12.1.4_PUBLIC` and
> `JAVA_HOME=...jdk-21...`. The installed 12.2 build requires JDK 25+, so the
> in-session Ghidra provider reported `unsupported_version`. Analysis was run
> through the REA CLI with `GHIDRA_INSTALL_DIR=T:\tools\ghidra_12.2_PUBLIC` and
> `JAVA_HOME=C:\Program Files\Java\jdk-27.0.1.1`.
>
> To repair the live MCP provider: update those two environment values in
> `%USERPROFILE%\.config\opencode\opencode.jsonc` and restart OpenCode. This is
> an environment fix, not a Gety finding.

---

## 2. Version timeline

| Time | Event |
|---|---|
| Start of investigation | On-disk/running `0.6.3-beta+5ac392bd…`; `Gety.exe` 105,228,656 bytes, SHA `d462efac…`. |
| During investigation | Log: `Timing detection update found: "0.7.0"`; updater staged 0.7.0. |
| 20:17 local | Install directory binaries replaced with `0.7.0-beta+03448d58…`; `Gety.exe` 113,393,008 bytes, SHA `CD43701F…`. |
| After update | Running process remained the old `0.6.3` PID; on-disk files are `0.7.0`. |
| Ghidra | First 105 MB `Gety.exe` run was stopped because the file had been replaced; `gety-service.exe` 0.7.0 was re-analyzed; 113 MB `Gety.exe` 0.7.0 analysis was started and was still running when the docs were written. |

**Consequence:** runtime artifacts (DB, logs, WebView2 cache) are 0.6.3. Static
stack/model/API findings were re-verified on 0.7.0. The two service builds are
structurally identical (same procedure/string counts).

---

## 3. Target hashes (0.7.0)

| File | Bytes | SHA-256 |
|---|---:|---|
| `Gety.exe` | 113,393,008 | `CD43701F2CB1393676D414F4D3F64BFC7273FE5506960516A0A5C6BC836416E1` |
| `gety-service.exe` | 2,493,808 | `D020C8ECC7FE305149CE5B18BEB948165C0EB4AA5867C5366217EDEF3F9D7C0F` |
| `gety-reporter.exe` | 11,610,480 | `1ABB61D1950DDF35DC008D17A3AB6DC6FCA8B663D1AC43CE84FBF50D0E1C1F92` |
| `mcp-proxy.exe` | 6,089,584 | `6D5C8F1BEABC9D1FBA8953E62E05699E639AE9148474FCFBF659F16642820952` |
| `uninstall.exe` | 114,384 | `1085626846D795429492C4617ADDA5698F3858A538230330EA46F6FC9FA47701` |

Build string: `0.7.0-beta+03448d5842950e0f88d563089bb4d651a8cdb772`,
git branch/author `GitHub`, date `2026-11-06T15:03:06+08:00`.

### 3.1 Previous build (0.6.3, for comparison)

| File | Bytes | SHA-256 |
|---|---:|---|
| `Gety.exe` | 105,228,656 | `d462efacda959b484f177f78c9bb81f155012c490c5c59b4274b5aa1b773fa56` |
| `gety-service.exe` | 2,493,808 | `017cd2f71eafe352f05a24c32eca58eeac053c01975ca5cc9953b190dedd9c0f` |
| `gety-reporter.exe` | 11,524,976 | `9fe9c47805aadda8b0f514f7d3a370270f34bee422c26370e566e94e3842036f` |
| `mcp-proxy.exe` | 6,089,584 | `e77f1ca1e8c1c85f6d099537d1273c517723ef3e4d76c83002714b0371e7cde6` |

---

## 4. Model hashes

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `model_uint8.onnx` (gety-embed-v0) | 118,130,759 | `183B375D5F27B6AB5CB8AB6C7154231652920D4AD5CDD23DE2000DA23B19324A` |
| `gety_ocr_cpu_v3.safetensors` | 50,342,620 | `3C7519E6DC7E449CEC34C1E6E04FB711198B4FF41C9AF38473B19EB47666B129` |

Paths:

```
%APPDATA%\ai.gety\data\models\gety-ai\gety-embed-v0\
  424f41cb36776481b7e2c9f619ca7ce5d5351fe0\onnx\model_uint8.onnx

%APPDATA%\ai.gety\data\models\gety-ai\gety-ocr-v0\
  038b6e4d17e55ec43ea07df3a6bcb997b0fbfb6e\gety_ocr_cpu_v3.safetensors
```

---

## 5. REA / Ghidra evidence records

### 5.1 0.7.0 service (`D020C8…`)

| Operation | Evidence ID | Result |
|---|---|---|
| `analyze` / `binary_overview` | `ev_99c7f992239035052c01733d647417a1dd07be214ee36bfefb3e4b9cc5a7213f` | 11,291 procedures, 1,496 strings, 8 segments, image base `0x140000000`. |
| `decompile` entry `0x140196ea0` | `ev_7984f440462c662d6200ad1d51705d39339c74c9262f684fce948b0a292bb2e3` | `entry → FUN_140197130(); FUN_140196d20();` |
| `xrefs` to `NtDeviceIoControlFile` (`EXTERNAL:0x63`) | `ev_1a896c9bbce7661a48da7ae9dee34d979e9c5208f4d21158ed24697a75976051` | Code xref `0x14018d305`, data xref `0x1401c8868`. |
| `function` at `0x14018d305` | `ev_6ad57d7b1bf004d7deec2a0f4c8a9d271e776f0ffbe613076986275e07839880` | Containing function `FUN_14018d100`; direct call at `0x14018d305` to `NtDeviceIoControlFile`; full pseudocode/call facts. |

The service imports `CreateFileW`, `ReadFile`, `WriteFile`,
`NtDeviceIoControlFile`, `OpenProcess`, `CreateNamedPipeW`,
`ConnectNamedPipe`, `StartServiceCtrlDispatcherW`. The raw device-I/O import
plus LocalSystem token is the basis for the “privileged I/O broker” inference.

### 5.2 0.6.3 service (`017cd2…`)

| Operation | Evidence ID | Result |
|---|---|---|
| `analyze` overview | `ev_71533714f009cc0511e93b48628c48197d63016cdf83b36c8f1a6fc057848855` | 11,291 procedures, 1,496 strings, same segments. |
| `decompile` entry | `ev_eead68849a7971e5a4ec57928cacabb282ada07667d992115b78fac74d65e2f7` | Entry function. |
| `decompile` CRT main | `ev_259e884459f02be9258969b6526aea60db9d35e1380edb437f36adfe95d8972a` | `__scrt_common_main`-style wrapper. |
| `decompile` Rust `lang_start` | `ev_84a3d62931b1f06529f0c537919e239352290583a97569645aa4a619ba896d61` | Calls `FUN_1400ca8a0` (Rust main). |
| `decompile` async main | `ev_dda40401aeda3cdcaf852085a872c3fcc21dedcc7d15a0b204239b6ba607455b` | Tokio runtime/async main path. |
| `search` string `GETY_SERVICE` | `ev_81af50de2e8fc9c856e110c8d7a30d178a2d67f14f95d289d87057df60424d0f` | Confirms `\\.\pipe\GETY_SERVICE` and `gety_service::windows`. |
| `xrefs` | `ev_99caad89ad572761542dddf8a49a2307147d541f00a4239fbbf9e1d0e4e1f373` | No direct code refs to the string copy (Rust pointer/length table). |

### 5.3 Main `Gety.exe`

- 0.6.3 and 0.7.0 static strings were extracted and compared (crate inventory,
  Rust module paths, API routes, SQL, model paths, UI assets).
- 0.7.0 `Gety.exe` Ghidra analysis (`--provider ghidra --snapshot
  T:\Temp\opencode\snap-gety070`) was started; at documentation time it was
  still running (14+ GB working set). No claims in these docs depend on the
  unfinished pass; the function-level claims come from the service analysis
  and from recovered Rust strings/type metadata.
- The initial 0.6.3 `Gety.exe` Ghidra pass was stopped when the on-disk binary
  was replaced by the auto-update.

---

## 6. Local artifact evidence

### 6.1 SQLite

Read-only commands (Node 26 `node:sqlite`, `readOnly: true`):

```js
const db = new DatabaseSync(dbPath, { readOnly: true });
db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_master ...").all();
db.prepare('SELECT COUNT(*) FROM "index_idx_folder_2"').all();
```

Observed counts are in [`data-model-and-storage.md`](data-model-and-storage.md).
No document text or user file content was selected or printed. The database
and WAL were treated as live; no writes were made.

### 6.2 Runtime logs

Files:

```
%LOCALAPPDATA%\ai.gety\logs\ai.gety.2026-11-25.app.log
%LOCALAPPDATA%\ai.gety\logs\ai.gety.2026-11-26.app.log
```

Key lines:

```
gety_client::api::server: Gety API server listening on 127.0.0.1:31226
gety_core::model_inference…: effective_backends=[OrtCuda, OrtOpenVino, OrtCpu]
gety_core::model_inference…: GPU NVIDIA GeForce RTX 3090, compute 8.6
gety_core::index: Hydrated index_idx_folder_2: 34404 rows
gety_core::index: Hydrated index_idx_ntfs_1: 16167 rows
gety_client::window: NextAppInitdEvent received - frontend is ready
```

### 6.3 WebView2 cache

Path:

```
%LOCALAPPDATA%\ai.gety\EBWebView\Default\Code Cache\js
%LOCALAPPDATA%\ai.gety\EBWebView\Default\Cache
```

Extracted strings yielded:

- React internals (`__REACT_DEVTOOLS_GLOBAL_HOOK__`, `Minified React error`,
  `react-dom`, `useEffectEvent`, `react.transitional.element`).
- `__reactRouterVersion`, `navigate()` warning.
- i18next, Radix, `cmdk`, `sonner`, `virtua`, PostHog, Sentry.
- Tailwind-style tokens and asset paths.
- Locale/i18n JSON fragments (e.g. `file_type_ocr`, OCR settings, connector
  settings).

The cache is from the **0.6.3** frontend. The 0.7.0 asset graph was extracted
from the new binary; it retains the same chunk layout and adds
`comment-ui-runtime`, `emf`, and `font-preload-demand`.

### 6.4 Runtime processes / services

```
Gety.exe --autostart                    session 2, medium integrity
gety-reporter.exe --monitor …           session 2, child of Gety.exe
gety-service.exe                        session 0, LocalSystem, service "gety-service"
```

`sc.exe qc` / `Get-CimInstance Win32_Service` confirmed:
`StartMode=Auto`, `StartName=LocalSystem`, `PathName=...\gety-service.exe`.

Named pipes observed: `GETY_CLI`, `GETY_SERVICE`.

---

## 7. Commands used (reproducible)

### 7.1 Environment

```powershell
$env:GHIDRA_INSTALL_DIR='T:\tools\ghidra_12.2_PUBLIC'
$env:JAVA_HOME='C:\Program Files\Java\jdk-27.0.1.1'
$env:GHIDRA_HEADLESS_MAXMEM='18G'
```

### 7.2 Ghidra service analysis

```powershell
npx -y rea-agents@6.10.1 analyze `
  "%LOCALAPPDATA%\Gety\gety-service.exe" `
  --provider ghidra `
  --snapshot T:\Temp\opencode\snap-svc070 `
  --format json
```

### 7.3 Decompile / xrefs / function

```powershell
npx -y rea-agents@6.10.1 decompile <path> 0x140196ea0 --snapshot ... --format json
npx -y rea-agents@6.10.1 xrefs <path> --address=EXTERNAL:0x63 --snapshot ... --format json
npx -y rea-agents@6.10.1 function <path> 0x14018d305 --snapshot ... --format json
```

### 7.4 Main binary Ghidra

```powershell
npx -y rea-agents@6.10.1 analyze `
  "%LOCALAPPDATA%\Gety\Gety.exe" `
  --provider ghidra `
  --snapshot T:\Temp\opencode\snap-gety070 `
  --format json
```

### 7.5 PE / string extraction

- REA target-free PE tools: `inspect_pe_imports`, `inspect_pe_resources`,
  `inspect_pe_load_config`, `inspect_pe_certificates`.
- Local Node string extractor (ASCII + UTF-16LE) over the four binaries; crate
  versions parsed from `index.crates.io-…\<crate>-<version>\` paths.
- Local ONNX/safetensors header inspection.

---

## 8. Observed vs inferred vs unknown

### Observed

- Tauri/Rust/React stack, versions, plugin list.
- SQLite/FTS5 schema, table counts, `chunks.embedding` BLOB, `cosine_sim_f32/i8`,
  `rarray` SQL, 0.2/0.8 fusion SQL.
- `gety-embed-v0` config/ONNX I/O and files.
- `gety-ocr-v0` files and encrypted/NaN payload behavior.
- Service binary imports/xrefs and LocalSystem process/pipe.
- API port 31226, MCP Streamable HTTP, Bearer.
- Frontend routes/windows/workers and UI library stack (0.6.3 cache).
- Auto-update from 0.6.3 to 0.7.0.

### Inferred

- The service is a privileged device/volume I/O broker (imports + LocalSystem +
  NTFS code in the UI process). Exact RPC/IOCTL surface not recovered.
- Gety's exact query/passage prefixes; the E5 model card suggests prefixes but
  the binary constants were not recovered.
- The semantic score normalization in the 0.2/0.8 fusion.
- Chunk size/overlap constants.

### Unknown

- Exact OCR topology/language coverage (encrypted).
- Exact FTS5 tokenizer options/BM25 constants beyond the SQL/function names.
- 0.7.0 frontend runtime behavior (bundle not loaded/cached).
- Billing/quota enforcement, enterprise identity, audit guarantees.
- Network traffic/privacy audit.
- Actual latency/recall on the 2.26 GB corpus (no benchmark run).

---

## 9. Limitations and provenance

- Ghidra output is decompiler-derived, not original source. `FUN_*` names are
  stripped; PDB `gety_service.pdb` is referenced but not available.
- Known Ghidra 12.2 caveats from the provider: jump-table recovery defects
  (ghidra-9996/10154), inferred non-returning calls, and Windows P0 database
  mutation limits. These are recorded in the evidence limitations.
- String extraction is bounded by printable ASCII/UTF-16 runs; compressed UI
  assets and encrypted model tensors are not decoded.
- SQLite schema was read from a live WAL database; no writes, no document
  content, no integrity check beyond the observed schema/counts.
- The app auto-updated mid-investigation; see the timeline. Do not attribute
  0.6.3 runtime behavior to 0.7.0 without re-checking.
- No target execution beyond bounded `--help` and a failed service start; no
  network capture.

---

## 10. Privacy note

The database contains personal file metadata (paths, titles, document text
blocks). This investigation read **schema and aggregate counts only**, not
document content. WebView2 cache strings were used for UI stack identification;
no personal documents were read. Model files are local artifacts; no model
weights were uploaded or redistributed.
