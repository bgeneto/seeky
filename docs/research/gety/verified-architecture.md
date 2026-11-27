> **Research note.** This is reverse-engineering context, not the active build contract. Code snippets are illustrative; Seeky is implemented in Rust/Tauri/TypeScript. See the [implementation plan](../../plans/seeky-implementation-plan.md).

# 01 — Gety Verified Architecture

**Target:** `%LOCALAPPDATA%\Gety`
**On-disk build documented:** `0.7.0-beta+03448d5842950e0f88d563089bb4d651a8cdb772`
**Runtime build during capture:** `0.6.3-beta+5ac392bd067163c5bb5727773d9abca84d2a2032`
**Method:** REA 6.10.1 static/Ghidra analysis, PE inspection, read-only SQLite
schema inspection, WebView2 cache inspection, runtime log/process inspection,
and local model-file parsing. No target code was executed except bounded
`--help`/service-start attempts, which failed safely.

Labels used below:

- **Observed** — directly read from a shipped artifact or local runtime state.
- **Inferred** — a conclusion that fits multiple observations but is not
  directly named by the artifact.
- **Unknown** — not established by available evidence.

---

## 1. Distribution inventory

The installation is per-user under `%LOCALAPPDATA%\Gety` and uses a separate
per-user data root under `%APPDATA%\ai.gety\data`.

| File | Size (bytes) | Role | SHA-256 (prefix) |
|---|---:|---|---|
| `Gety.exe` | 113,393,008 | Tauri desktop app + Rust client/core + UI assets | `CD43701F2CB13936…` |
| `gety-service.exe` | 2,493,808 | LocalSystem Windows service + named-pipe IPC/device broker | `D020C8ECC7FE3051…` |
| `gety-reporter.exe` | 11,610,480 | Out-of-process crash/panic reporter (egui + Sentry minidumper) | `1ABB61D1950DDF35…` |
| `mcp-proxy.exe` | 6,089,584 | stdio ↔ Streamable HTTP MCP bridge | `6D5C8F1BEABC9D1F…` |
| `uninstall.exe` | 114,384 | Uninstaller, version 0.7.0 | `1085626846D79542…` |
| `deno.exe` | 101,328,320 | Bundled Deno 2.8.1 connector runtime | — |
| `aria2c.exe` | 5,665,136 | Download engine for models/runtimes | — |
| `lib/ort/onnxruntime.dll` | 16,972,656 | ONNX Runtime | — |
| `lib/pdfium.dll` | 7,227,248 | PDF rendering/extraction | — |
| `lib/models/gety-embed-v0/*` | ~17 MB tokenizer + config | Shipped tokenizer/config; weights are downloaded | — |

The four Rust binaries are unsigned PE32+ x86-64 images (no Authenticode
signatures observed). `Gety.exe` has a Common Controls 6.0 manifest and no
requested execution level (default `asInvoker`). The installer is 0.7.0; the
embedded `Gety.exe` file version resource is a placeholder `0.0.1`, so version
must be read from the build string or uninstaller.

### 1.1 Runtime processes observed

```
explorer.exe (session 2)
└─ Gety.exe --autostart                         (session 2, medium integrity)
   └─ gety-reporter.exe --monitor --ipc <temp>  (crash watchdog)
services.exe (session 0)
└─ gety-service.exe                             (LocalSystem, Windows service)
```

- `gety-service` is registered as a Windows service (display name
  **Gety Service**, start mode **Auto**, account **LocalSystem**).
- `Gety.exe` is registered in `HKCU\...\Run` as `Gety.exe --autostart`.
- `gety-reporter.exe` was launched with `--monitor`, the app PID, a temporary
  IPC socket, Sentry DSN, release string, and a machine ID.
- `mcp-proxy.exe`, `deno.exe`, and `aria2c.exe` start on demand; they were not
  running at capture time.

### 1.2 Named pipes and IPC

- `\\.\pipe\GETY_SERVICE` — created by the LocalSystem service.
- `\\.\pipe\GETY_CLI` — app/CLI endpoint; the binary contains the SDDL
  `D:P(A;;GA;;;OW)(A;;GA;;;SY)` (owner + SYSTEM full access).
- IPC uses **`remoc` 0.18.3** (`chmux` multiplexed ports) over `interprocess`
  named pipes and Tokio.

The service is **not** a second copy of the search engine. It is a small
privileged broker:

- Ghidra 0.7.0 overview: 11,291 procedures, 1,496 strings, 8 segments,
  image base `0x140000000` (Evidence `ev_99c7f992239035052c01733d647417a1dd07be214ee36bfefb3e4b9cc5a7213f`).
- Imports include `CreateFileW`, `ReadFile`, `WriteFile`,
  **`NtDeviceIoControlFile`**, `OpenProcess`, `CreateNamedPipeW`,
  `ConnectNamedPipe`, and `StartServiceCtrlDispatcherW`.
- `NtDeviceIoControlFile` has xrefs at `0x14018d305` and `0x1401c8868`
  (Evidence `ev_1a896c9bbce7661a48da7ae9dee34d979e9c5208f4d21158ed24697a75976051`).
- The containing function `FUN_14018d100` was decompiled; it has a direct call
  at `0x14018d305` to the imported device-I/O routine
  (Evidence `ev_6ad57d7b1bf004d7deec2a0f4c8a9d271e776f0ffbe613076986275e07839880`).

**Inference:** the service proxies privileged device/volume I/O (e.g. NTFS
volume handles and FSCTLs) to the unprivileged UI/core, which owns the MFT
parser. This matches the service's LocalSystem token, the `gety-core` NTFS MFT
modules in `Gety.exe`, and the observed `connector::fs::ntfs::utils::iocp`
runtime logs. The exact RPC method names and IOCTL codes were not recovered.

---

## 2. Technology stack

### 2.1 Desktop shell and UI

| Layer | Observed technology |
|---|---|
| Desktop framework | **Tauri 2.9.5**, `tauri-runtime-wry 2.9.3`, `wry 0.53.5`, `tao 0.34.5` |
| WebView | Microsoft Edge WebView2 (`EBWebView` data dir, Chromium 157 snapshot) |
| Frontend | **React 19.1.0** (WebView2 code cache), React DOM, React Router |
| Build | Vite, hashed `/assets/*.js` chunks, Tauri custom protocol `http://tauri.localhost` |
| Styling | Tailwind-style utility classes with custom tokens (`bg-page`, `bg-solid`, `text-on-solid`, `border-border-brand`, `gety-blue`, dark mode) |
| UI primitives | Radix UI collection/slot primitives, `cmdk` command palette, `sonner` toasts, `virtua` virtual lists |
| i18n | `i18next` / `react-i18next`, many lazily loaded locale chunks |
| Analytics/errors | PostHog (`posthog-js` 1.242.1) and Sentry browser SDK |
| Document UI | PDF.js worker, custom `docx-snapshot.worker`, `char-mapping.worker`, spreadsheet preview, `dom-export`, ProseMirror error strings, `react-markdown`, highlight.js, `xlsx` |
| Tauri plugins | autostart, clipboard-manager, deep-link, dialog, drag, global-shortcut, opener, os, shell, single-instance, updater, window-state |

The UI is a single-page app with multiple Tauri windows. Observed routes in the
0.6.3 cache:

```
/home
/search
/library
/doc
/connectors
/connector
/settings/general
/settings/fs-connector
/settings/custom-connectors
/settings/integrations
/settings/user
/settings/about
/welcome
/about
/notification
/permission
```

Separate windows/pages: `custom-notification.html`, `dialog/permission.html`,
and a docs-viewer command path. The 0.7.0 asset graph adds
`comment-ui-runtime`, `emf`, and `font-preload-demand` chunks while retaining
the same core Vite chunk layout.

> **Caveat:** exact React version is observed in the 0.6.3 WebView2 cache. The
> 0.7.0 frontend bundle has not been loaded/cached on this machine, so its
> React version is not independently observed. The chunk graph and Tauri
> versions are confirmed from 0.7.0 binary strings.

### 2.2 Rust crate inventory (selected, 0.7.0)

| Area | Crates (version) |
|---|---|
| Async/runtime | `tokio 1.49`, `tokio-util 0.7.18`, `futures-*`, `async-stream` |
| HTTP/API | `axum 0.8.8`, `axum-extra`, `tower-http 0.6.11`, `hyper 1.8.1`, `reqwest 0.13.2`, `tokio-tungstenite`/`tungstenite 0.27` |
| MCP | `rmcp 1.6.0` (official Rust MCP SDK, Streamable HTTP server/router) |
| IPC | `remoc 0.18.3`, `interprocess 2.2.3`, `tonic 0.12.3`, `prost 0.13.5` |
| Storage | `rusqlite` (git), `r2d2_sqlite 0.35`, `r2d2 0.8.10`, `yada 0.7` |
| Search | FTS5 in SQLite, custom BM25, `jieba-rs` (git), `daachorse 3.0.1`, custom pinyin matcher |
| Models | `ort` (git), `openvino 0.11`, `openvino-finder`, `tokenizers` (git), `ndarray 0.17`, `half 2.7`, `nvml-wrapper-sys` |
| Documents | `pdfium-render` (git), `pdf-inspector 1.17`, `lopdf 0.42`, `anydoc 0.2.4` (DOCX/PPTX/ODF/CSV/EPUB), `docx-rs` (git), `calamine 0.32`, `cfb 0.7/0.14`, `zip`, `quick-xml`, `html-to-markdown` (git), `html5ever 0.39`, `lol_html` |
| Images/OCR | `image 0.25.9`, `fast_image_resize 5.5`, `rav1e`/`ravif` (AVIF), `image-webp`, `exr`, `fax`, `png`, `jpeg-decoder`, `tiff` |
| Windows | `windows 0.52`, `windows-service 0.8`, `windows-registry 0.6`, `wmi 0.12`, `sysinfo 0.36`, `powerstate`, `machineid-rs` (0.6.3) |
| Security | `ring`, `rustls 0.23`, `aws-lc-rs` (0.6.3), `jsonwebtoken 9.3`, `minisign-verify`, `aes`, `sha2`, `blake3` |
| Observability | `sentry 0.47`, `tracing`, `tracing-subscriber`, `tracing-appender` |
| Crash UI | `eframe`/`egui 0.35`, `egui_glow`, `vello_cpu 0.0.9`, `minidumper` (git `crash-handling`) |

The 0.7.0 build adds a Deno connector **catalog/registry/update** layer
(`catalog`, `github`, `npm`, `package`, `versions`, `changelog`, `consent`,
`permissions`) and model-loading optimizations (`mapped_weights`,
`shared_arena`). It also adds `chardetng` for text encoding detection.

### 2.3 Sidecars

| Sidecar | Contract |
|---|---|
| `deno.exe` 2.8.1 | Runs custom TypeScript/JavaScript connectors. NDJSON over stdin/stdout, 512 KiB soft batch, 16 MiB hard frame, 10 MiB content cap, 10-minute idle timeout, `poll_done` terminal frame, state checkpoint only after a complete poll. Bundled runner uses `--allow-all`; 0.7.0 adds declared/canonical permission review and reporting around the Deno runtime. |
| `aria2c.exe` | Downloads model/runtime assets. `Gety` starts, watches, and restarts it; missing sidecar disables component downloads. |
| `mcp-proxy.exe` | CLI: `mcp-proxy.exe [OPTIONS] <URL>`, `--headers`, `--transport-type auto|streamable-http`, `--debug`, `--max-disconnected-time`, `--initial-retry-interval`, `--override-protocol-version`. Bridges stdio-only MCP clients to Gety's Streamable HTTP endpoint with Bearer headers. |
| `gety-reporter.exe` | `--monitor` attaches via IPC to the main process, captures a minidump (`MiniDumpWriteDump`), uploads to Sentry if enabled, shows an egui crash/panic UI, and can restart in safe mode. CrashContext fields include backtrace, machine ID, app version, dump path, telemetry flag, trace/span IDs. |

---

## 3. Component and module map

### 3.1 `gety-client` (in `Gety.exe`, Tauri side)

Observed source paths from Rust panic metadata:

```
gety-client/src-tauri/src/
  main.rs
  window.rs
  cli_ipc.rs
  doc_protocol.rs
  custom_system_notification.rs
  notifications.rs
  event_tracking.rs
  file_http.rs
  shortcut.rs
  operation_context.rs                 (0.7.0)
  api/
    credentials.rs
    data_sharing.rs
    server.rs | server/doc.rs | server/search.rs | server/connectors.rs
    mcp/mod.rs | mcp/doc.rs | mcp/schema.rs
    layer/auth.rs | layer/data_sharing.rs
  mcp/
    mod.rs | utils.rs | integration.rs
    integration/{claude_desktop,claude_code? ,codex,cursor,copilot_cli,
      gemini_cli,kimi_code,deepseek_harness,antigravity,cherry_studio,
      lm_studio,openclaw,opencode,vscode,windsurf,workbuddy,hermes,
      grok_build}.rs
    integration/util/{atomic_write,json_config,toml_config,yaml_patch}.rs
  setup/
    mod.rs | gety_core.rs | hotkey.rs | tray.rs | logger/mod.rs
    proxy.rs | sentry.rs | crash_reporter.rs | battery_saver.rs
  tauri_commands/
    auth.rs | connector.rs | connector/docs_viewer.rs | debug.rs | diagnose.rs
    indexing.rs | network.rs | notification.rs | search.rs | settings.rs
    settings/{cli,data_migration,dirs,integration,ocr,offline_package,python,quota}.rs
    updater.rs | utils.rs | window.rs | window/data_sharing.rs | wizard.rs
  web_server/
    mod.rs | middleware.rs | sse.rs
```

Key client-side responsibilities:

- Tauri command surface and typed IPC (`tauri-specta`).
- Window lifecycle (`main`, `custom-notification`, `permission-dialog`), tray,
  global hotkey, dock visibility, autostart, single instance, deep links.
- Local API server + MCP server + data-sharing middleware + auth.
- MCP client integrations for ~17 AI tools; writes each tool's native config
  (JSON/TOML/YAML) and installs a `gety` MCP server entry with Bearer auth.
- Crash reporter supervision, Sentry, logging, proxy setup.
- Updater, release channels, offline asset packages.
- CLI IPC over `GETY_CLI`.

### 3.2 `gety-core` (linked into `Gety.exe`)

Observed source paths:

```
gety-core/src/
  account/utils.rs
  app/
    mod.rs | settings.rs | diagnose.rs | diagnose_mft.rs
    index_status.rs | battery_saver.rs | compute_governor.rs
    connector_operations.rs | policy_reconcile.rs | full_text_backfill.rs
    connector_updates.rs (0.7.0) | version_switch.rs (0.7.0)
    first_launch/{mod,wizard,scan_target}.rs
  bundled.rs
  common/{indexing_gate,priority_task,task_queue}.rs
  connector/
    mod.rs | prod_connectors.rs
    fs/{mod,filter,meta,observer,processor,utils}.rs
    fs/ntfs/{mod,mft_reader,parser,service,volume,list_nfts_volumes}.rs
    fs/ntfs/utils/iocp.rs
    impls/{folder_connector,ntfs_connector,python_connector}.rs
    impls/deno/{connector,factory,registry,catalog,changelog,consent,download,
      github,npm,package,sweep,switch,transition,versions}.rs
  content/
    extractor/{dispatch,excel,html,pptx,preprocess,simple,windows,image_ocr,
      text_encoding,word/{mod,converter}}.rs
    image.rs | score.rs
  core/connector_manager/{manager,connector_wrapper,connectors_container,
    connectors_meta_table,pinned_folder_filter_table}.rs
  download/model_assets.rs
  event_tracking/mod.rs
  file_type/{policy,registry}.rs
  index/{block_repository,doc,doc_info_store,migrations,spreadsheet_anchor_repository}.rs
  indexing_strategy/{fast_text,full_text,full_text/backfill}.rs
  logging/{notification,retryable_manager,tracing_notification}.rs
  model_inference/
    environment/{initialization,ort,openvino,utils}.rs
    instance/{ort,openvino_npu}.rs
    {cuda_capture_gate,cuda_drop_reaper,cuda_fallback,input_validation,
     mapped_weights,pacer,safe_mode,service,session,shared_arena,ort_cuda}.rs
  net/proxy.rs
  ocr/mod.rs
  python/{client,gety_python_server,log,manager}.rs
  quota/mod.rs
  search/{query,search_flow,searcher,pinyin,string_matcher/*,snippet_generator}.rs
  search_service/{mod,facet_processor,folder_scope,search_scope,session}.rs
  semantic/{chunks,embedding,embedding/{pooling,tokenizer},model,q4,
    q4_embedding_index,semantic_indexing_strategy,semantic_service,text_splitters/*}.rs
  settings/{gety_settings,manager,proxy}.rs
  sqlite/{embedding,error,migration,tokenizer,min_interval_semantics}.rs
  sqlite/fts5/{auxiliary,bm25,bm25_v2,min_interval_rank}.rs
  usage_tracking/mod.rs
  utils/{fs,image,iterator,localized_path,machine,path_normalize,serde,glob,hub}.rs
  windows_service/mod.rs
```

Key responsibilities:

- Connector lifecycle and scheduling (folder, NTFS volume, Deno, Python).
- Content extraction and layout model (pages/blocks/bboxes/spreadsheet cells).
- SQLite index, migrations, FTS5, embeddings, task queues.
- Semantic service, model inference, accelerator selection/fallback, safe mode.
- Search service, facets, snippets/highlights, quotas.
- Settings, data migration, policy reconciliation, usage tracking.
- Windows service helper and privileged I/O coordination.

### 3.3 `gety-service`

A small LocalSystem service. It does not contain the search/index code. It
provides the `\\.\pipe\GETY_SERVICE` remoc/chmux endpoint and raw device/process
I/O imports. The 0.7.0 and 0.6.3 builds have identical Ghidra inventories
(11,291 procedures and 1,496 strings); a byte-level code diff was not performed,
so “inventory-identical” is the supported claim, not “byte-identical.”

### 3.4 `gety-reporter`

Out-of-process crash/panic UI. It uses egui/eframe + vello CPU rendering,
`minidumper`, `MiniDumpWriteDump`, Sentry, and a `CrashContext` with 17 fields.
It is not part of the search path.

### 3.5 `mcp-proxy`

A stdio ↔ Streamable HTTP bridge for MCP clients that cannot speak HTTP
directly. It forwards a configured URL and headers (typically `Authorization:
Bearer <Gety API key>`), supports reconnects, and can override the protocol
version.

---

## 4. Indexing architecture

### 4.1 Connector types observed

| Connector | Implementation | Notes |
|---|---|---|
| Folder | `connector/fs/folder` | Filesystem watcher (`notify`), glob filters, hidden/system/temp rules, network-path detection, incremental/rescan/full-rescan modes. |
| NTFS volume | `connector/fs/ntfs` | MFT reader, volume enumeration, parser, IOCP utilities. Privileged volume access is inferred to be brokered by `gety-service`. |
| Deno custom | `connector/impls/deno` | Manifest + TypeScript/JavaScript poll function; NDJSON wire protocol. |
| Python | `connector/impls/python_connector` | Legacy/optional Python connector support; Python manager can create a venv, install server requirements, and stream logs. |

0.7.0 adds a Deno **catalog** sourced from `@gety-connectors/catalog` (npm),
GitHub Release/npm install sources, changelogs, version switching, permission
review/consent, and a directory sweep for installed connectors.

### 4.2 File types and extraction

Observed extraction stack:

- **PDF:** PDFium (`pdfium-render`), `pdf-inspector` (text/layout/tables),
  `lopdf` for object-level PDF access. Table detection includes heuristics,
  chart masking, column/row clustering, and Markdown rendering.
- **Word:** `anydoc` DOCX/ODF, `docx-rs`, `cfb` for legacy OLE/encrypted
  containers, HTML-to-Markdown conversion. Handles comments, headers/footers,
  footnotes, tables, images.
- **Excel:** `calamine`, plus custom spreadsheet cell anchors and preview stats.
- **PowerPoint:** `anydoc` PPTX/PPT, slide text/shape extraction.
- **HTML:** `html5ever`, `lol_html`, `html-to-markdown`, charset detection
  (`encoding_rs`, `chardetng` in 0.7.0).
- **Text/markup:** plain text, Markdown, HTML, CSV; encoding detection and
  normalization.
- **Images:** image decoders + OCR (`image_ocr` extractor).
- **Windows:** shell metadata/property extraction (`content/extractor/windows`).

Extraction status values observed in the schema/code:

```
pending, fast_complete, awaiting_deep, full_complete, failed
```

Content formats: `plaintext`, `markdown`.

### 4.3 Indexing stages

```
discover → title/metadata index → fast text extraction → FTS5/BM25
        → deep extraction (OCR/tables/spreadsheets) → semantic chunks
        → embeddings → chunks.embedding
```

- Task queues: `task_queue_content`, `task_queue_deep_extraction`, with
  `priority`, `polled`, `deferred`, `task_key`.
- Indexing control: pause one hour / today / until manual resume; boost mode;
  battery saver; compute governor; thread priority; safe mode after crashes.
- Per-connector physical tables are created dynamically, e.g.
  `index_idx_folder_2`, `blocks_idx_folder_2`, `FullTextIndexingStrategy_1`.
- `full_text_index_backfills` tracks resumable FTS backfills.
- Incremental scans reuse existing docs; `rescan_with_reuse` and `full_rescan`
  modes are distinct.

### 4.4 Runtime scale observed

The inspected database (`0.6.3`) contained:

| Object | Rows / value |
|---|---:|
| `gety_data_v1.db` size | 2,262,179,840 bytes (2.26 GB) |
| Page size / count | 4,096 B / 552,306 |
| `index_idx_folder_2` | 34,404 docs |
| `index_idx_ntfs_1` | 16,167 docs |
| `blocks_idx_folder_2` | 1,241,951 blocks |
| `blocks_idx_ntfs_1` | 10,005 blocks |
| `chunks` | 1,028,792 chunks |
| `FullTextIndexingStrategy_1` | 3,550 indexed docs |
| `FullTextIndexingStrategy_2` | 16,220 indexed docs |
| `spreadsheet_cell_anchors_idx_folder_2` | 328,321 anchors |
| `connectors` | 2 rows (`folder_2`, `ntfs_1`) |
| `migrations` | 15 |

This is a real, large local corpus, not a toy database. It validates that the
SQLite/FTS5 design scales to millions of blocks and chunks on a desktop.

---

## 5. Storage and data model

### 5.1 Database

- SQLite via `rusqlite` + `r2d2` pool.
- `journal_mode=WAL`, `page_size=4096`, UTF-8, no auto-vacuum.
- Per-connector tables with a numeric suffix. The suffix is an internal index
  ID, not the connector name.
- FTS5 virtual tables are contentless (`content=''`,
  `contentless_delete=1`, `tokenize='simple'`).
- `chunks.embedding` is a BLOB; `embedding_version` and `embedding_status`
  track migration/backfill.

### 5.2 Core tables (observed DDL, abbreviated)

```sql
CREATE TABLE connectors (
  iid INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  version INTEGER,
  type TEXT,
  name TEXT NOT NULL UNIQUE,
  config TEXT,
  auth TEXT,
  index_meta TEXT,
  runtime_config TEXT,
  last_state TEXT,
  last_update_time TEXT,
  description TEXT,
  fs_connector_config TEXT,
  connector_settings TEXT
);

CREATE TABLE "index_idx_folder_2" (
  iid INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  parent_id TEXT,
  title TEXT NOT NULL,
  metadata TEXT,
  doc_updated_at TEXT NOT NULL,
  hide_from_search BOOLEAN DEFAULT FALSE,
  doc_type TEXT NOT NULL DEFAULT 'other',
  original_file_size INTEGER,
  extraction_status TEXT,
  content_format TEXT NOT NULL DEFAULT 'plaintext',
  content TEXT
);

CREATE TABLE blocks_idx_folder_2 (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_iid INTEGER NOT NULL,
  parent_block_id INTEGER,
  page_num INTEGER,
  block_type TEXT NOT NULL,
  bytes_offset INTEGER NOT NULL,
  bytes_length INTEGER NOT NULL,
  bbox TEXT,
  original_id TEXT,
  text TEXT,
  source TEXT,
  content_hash BLOB,
  FOREIGN KEY (doc_iid) REFERENCES index_idx_folder_2(iid) ON DELETE CASCADE
);

CREATE TABLE chunks (
  chunk_id INTEGER PRIMARY KEY,
  index_iid INTEGER NOT NULL,
  doc_iid INTEGER NOT NULL,
  field_iid INTEGER NOT NULL,
  start_offset_bytes INTEGER NOT NULL,
  end_offset_bytes INTEGER NOT NULL,
  chunk_char_len INTEGER NOT NULL,
  embedding BLOB,
  embedding_version INTEGER,
  embedding_status INTEGER NOT NULL DEFAULT 0,
  chunk_idx INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE spreadsheet_cell_anchors_idx_folder_2 (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_iid INTEGER NOT NULL,
  content_utf16_start INTEGER NOT NULL,
  content_utf16_end INTEGER NOT NULL,
  sheet_index INTEGER NOT NULL,
  row_index INTEGER NOT NULL,
  column_index INTEGER NOT NULL,
  FOREIGN KEY (doc_iid) REFERENCES index_idx_folder_2(iid) ON DELETE CASCADE
);

CREATE TABLE task_queue_content (
  task_key TEXT, polled INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 0,
  deferred INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE task_queue_deep_extraction (
  task_key TEXT, polled INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 0,
  deferred INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE daily_usage (
  feature_type TEXT NOT NULL, usage_date TEXT NOT NULL,
  usage_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (feature_type, usage_date)
) WITHOUT ROWID;

CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL, action TEXT NOT NULL, actor TEXT,
  payload TEXT DEFAULT '{}', duration_ms INTEGER,
  success INTEGER NOT NULL DEFAULT 1, error_info TEXT,
  created_at TEXT NOT NULL
);
```

Indexes exist for doc, page, parent, content hash, title, extraction status,
`hide_from_search`, and pending chunks. The `chunks` indexes include
`(index_iid, doc_iid)`, `(index_iid, field_iid, doc_iid)`, and partial indexes
for `embedding_status = 0` and `embedding_status = 1`.

### 5.3 Where the vectors live — definitive answer

**Gety does not use a vector database.** It uses SQLite:

- Embeddings are stored in `chunks.embedding` as a BLOB.
- The query path calls SQLite scalar functions:
  - `cosine_sim_f32(embedding, query_vector)`
  - `cosine_sim_i8(embedding, query_vector)`
- `embedding_version` selects the representation. The binary contains a
  migration that quantizes embeddings from f32 to i8:
  `Starting migration to quantize embeddings from f32 to i8`.
- `UPDATE chunks SET embedding = ?, embedding_version = 3 ...` and the check
  `Skipping chunk_id — blob size not divisible by 4` show the f32 representation.
- Semantic SQL:
  ```sql
  SELECT chunk_id, index_iid, doc_iid, field_iid,
         start_offset_bytes, end_offset_bytes,
         cosine_sim(embedding, ?) AS cosine_similarity
  FROM chunks
  WHERE embedding_status = 1 AND embedding_version = ?
    AND (...)
  ORDER BY cosine_similarity DESC
  LIMIT ?;
  ```
- Candidate ID lists are passed with `rarray(?)`, an array-expansion helper
  registered on the SQLite connection. It is **not** an ANN index.
- A separate in-memory module `semantic/q4_embedding_index.rs` builds a `q4`
  embedding index (likely 4-bit; exact packing was not recovered) for
  pruning/shrinking. It is not the persistent
  storage format and not a general vector database. The code has
  `Q4_DIMS` checks and “Q4 pruning/shrink” tasks.

**Scale implication:** exhaustive cosine over all chunks works for Gety's
desktop corpus because candidate sets are filtered by `index_iid`, `doc_iid`,
and `rarray` ID lists, and the expensive scan is done inside SQLite in native
code. It will not scale indefinitely; the minimal app should measure and then
introduce ANN if needed.

No `sqlite-vec`, `sqlite-vss`, `usearch`, `hnsw`, `faiss`, `annoy`, `qdrant`,
`lancedb`, or `duckdb` appears in the crate inventory or strings.

---

## 6. Search and ranking

### 6.1 Query surface

Observed search parameters (Rust/TS types and API):

```
query
limit, offset
semantic_search / no_semantic_search
exact_phrase
connectors / connector_names_filter
extensions
match_scopes (title, content, semantic)
sort_by (default | update_time)
sort_order (ascending | descending)
update_time_from, update_time_to
folders
enable_faceting
facet_filters
ui (CLI opens the UI instead of printing)
```

Results include:

```
connector_id, connector_type_key, doc_id, doc_type, content_format,
title, snippets, matched_strategies, match_score, total_pages,
meta_info, recently_updated, semantic_only_match, source_anchors
```

Highlights carry UTF-16 offsets and page numbers; spreadsheet anchors carry
sheet/row/column and a UTF-16 range.

### 6.2 Lexical path

- SQLite FTS5, contentless (`content=''`, `contentless_delete=1`), simple
  tokenizer.
- Custom BM25 implementations (`bm25`, `bm25_v2`, `min_interval_rank`).
- Chinese segmentation via `jieba-rs`; pinyin search and pinyin matching;
  keyword string matcher; Unicode NFKC normalization.
- Exact-phrase support.
- Facets: connector, file type, time buckets (`Last24Hours`, `LastAWeek`,
  `LastAMonth`, `LastAYear`, `Older`), match scope.

### 6.3 Dense path

- Query embedded with `gety-embed-v0` (384-d).
- Cosine similarity over `chunks.embedding`, filtered by index/doc IDs.
- Results carry chunk offsets, field ID, and doc ID, then map back to blocks
  for snippets/highlights.

### 6.4 Fusion

Recovered SQL:

```sql
(0.2 * -bm25() + 0.8 * (semantic_score)) AS total_score
```

That is **weighted linear score fusion**, with 20% lexical and 80% semantic
weight. It is not Reciprocal Rank Fusion. The exact normalization of the
semantic term and the handling of missing modalities are not fully recovered.

### 6.5 What is absent

- No cross-encoder reranker (`rerank`/`cross-encoder` strings absent; no
  reranker model files).
- No learned pruner (`prun` hits are Q4 index pruning/shrinking and unrelated
  words, not a context-pruning model).
- No RRF.
- No HNSW/ANN/vector database.
- No generative answer model.

Snippets are generated from block text and match offsets; they are not proof
of a semantic pruning model.

---

## 7. Models and inference

### 7.1 `gety-embed-v0`

Installed path:

```
%APPDATA%\ai.gety\data\models\gety-ai\gety-embed-v0\
  424f41cb36776481b7e2c9f619ca7ce5d5351fe0\
    config.json
    tokenizer.json
    tokenizer_config.json
    special_tokens_map.json
    onnx/model_uint8.onnx          118,130,759 bytes
    onnx_cuda/model_fp16.onnx      235,074,703 bytes
```

Configuration (observed):

| Field | Value |
|---|---|
| Architecture | `BertModel` |
| Hidden size | 384 |
| Layers | 12 |
| Heads | 12 |
| Intermediate | 1,536 |
| Vocab | 250,037 |
| Max positions | 512 |
| Tokenizer | `XLMRobertaTokenizer` |
| Model type | `bert` |
| Transformers version in config | 4.57.6 |

ONNX I/O (observed in `model_uint8.onnx`):

- Inputs: `input_ids`, `attention_mask`
- Output: `sentence_embedding`
- Pooling and L2 normalization are baked into the graph (confirmed by the
  public model card and by the absence of a separate pooling node in the
  exported graph).

Public model card: fine-tuned from `intfloat/multilingual-e5-small`, MIT
license, 384 dimensions, 512 tokens, masked mean pooling + L2 normalization,
CPU uint8 112 MB, CUDA FP16 224 MB, CoreML FP16, OpenVINO INT8/FP16 for Intel
NPU. The installed hashes:

- `model_uint8.onnx`: `183B375D5F27B6AB5CB8AB6C7154231652920D4AD5CDD23DE2000DA23B19324A`
- `gety_ocr_cpu_v3.safetensors`: `3C7519E6DC7E449CEC34C1E6E04FB711198B4FF41C9AF38473B19EB47666B129`

The exact query/document prefixes used by Gety were **not recovered** as
literal strings. The public E5 model uses `query: ` / `passage: ` prefixes; the
minimal app should A/B test with and without them rather than assuming.

### 7.2 `gety-ocr-v0`

Installed path:

```
%APPDATA%\ai.gety\data\models\gety-ai\gety-ocr-v0\
  038b6e4d17e55ec43ea07df3a6bcb997b0fbfb6e\
    gety_ocr_cpu_v3.safetensors   50,342,620 bytes
    gety_ocr_cuda_v4.safetensors 180,262,124 bytes
```

Additional variants referenced in the binary: `gety_ocr_npu_v5.safetensors`
and `gety_ocr_coreml_v2.safetensors`.

Observed OCR engine modules from `gety-private`:

```
src/ocr/classification/classifier.rs
src/ocr/geometry/sorting.rs
src/ocr/common/shape_router.rs
```

This is **inferred** from the module/string names to be a detection +
orientation-classification + recognition pipeline, with dynamic shape bucketing
(`pad_enumerated`), range-width packing, fast detection resize, and geometry
sorting. The safetensors header is readable,
but the tensor payloads are high-entropy/NaN when interpreted as F32, and the
binary contains `gety-ocr-v1-salt`, HKDF length checks, and AES-GCM failure
strings. **Conclusion:** the OCR weights are encrypted/obfuscated at rest; the
architecture cannot be reconstructed from the file, and the model is not a
drop-in artifact for another app without the private key/runtime.

### 7.3 Inference runtime

- ONNX Runtime dynamically loaded from `%APPDATA%\ai.gety\data\ep\onnxruntime.dll`.
- Execution providers: `OrtCuda` (CUDA + cuDNN), `OrtOpenVino` (Intel NPU),
  `OrtCpu`; CoreML on macOS.
- Runtime log from the inspected machine:
  `effective_backends=[OrtCuda, OrtOpenVino, OrtCpu]`,
  GPU `NVIDIA GeForce RTX 3090`, CUDA driver 610.88.
- CUDA/cuDNN DLLs are downloaded into
  `%APPDATA%\ai.gety\data\third_party_libs\cuda`; OpenVINO into
  `...\third_party_libs\openvino`.
- NVML probes GPU compute capability; safe mode and CUDA fallback paths exist.
- 0.7.0 adds memory-mapped model weights (`GETY_ORT_MAPPED_WEIGHTS`), a shared
  arena, and arena shrinkage.

---

## 8. UI architecture

### 8.1 Shell

- Tauri 2.9.5 + WebView2; assets served from `http://tauri.localhost`.
- Main window + custom notification window + permission dialog; tray menu;
  global hotkey; deep links; dock visibility (macOS); autostart.
- Custom titlebar drag regions (`data-tauri-drag-region`), window-state
  persistence.

### 8.2 Frontend

- React 19.1, React Router, i18next.
- Tailwind-style tokens; Radix primitives; `cmdk` command palette; `sonner`
  toasts; `virtua` virtualized lists.
- PostHog + Sentry.
- PDF.js worker, DOCX snapshot worker, character-mapping worker, spreadsheet
  preview, document export, markdown rendering, highlight.js, xlsx.
- Lazy-loaded locale chunks for many languages.
- 0.7.0 adds a `comment-ui-runtime` chunk and EMF/WMF/font-preload handling.

### 8.3 Main screens and flows

- **Home / Library:** indexed sources, recent docs, activity.
- **Search:** query box, filters/facets, result list, snippets, semantic tag,
  preview panel, open file / open containing folder.
- **Document preview:** PDF/DOCX/spreadsheet/image, page navigation, text
  highlights, spreadsheet cell anchors, comments (0.7.0).
- **Connectors:** add folder/drive, filters, schedule, index viewer,
  diagnostics, rebuild/optimize.
- **Settings:** general, file types, OCR, storage location, acceleration,
  proxy, Python/PIP registry, AI integrations, account/quota, updates, about.
- **Wizard:** first-run folder selection, scan, privacy onboarding.
- **Tray:** indexing/OCR/semantic status, pause one hour/today/manual, boost,
  open app, settings, quit.
- **Permission dialog:** data-sharing approval for API/MCP callers.

### 8.4 UI evidence from the user-provided screenshots

The `docs/assets/screenshots/gety/` folder (captured 2026-11-26) confirms the visual and
interaction model:

- **Home:** `gety.ai` mark; search field with placeholder
  “Search keyword, phrase, or meaning. @ to use filter”; centered tagline
  “Meet Gety, your personal AI file search engine”; bottom status
  “19,872 files searchable · AI indexing continues when idle”.
- **Status popover:** Fast search (`19,872 files searchable`), Content search
  (`Ready`), AI indexing (`Continues when idle`) with `Pause` and `Full speed`
  actions, Document OCR (`Ready`), Semantic search
  (`99% · 672 chunks remaining`).
- **Settings sidebar:** `Back to app`, `General`, `User`, `Local Files`,
  `AI Integrations` (HOT), `Connectors` (BETA), `About`.
- **General:** keyboard shortcut, appearance (`Dark (Beta)`), language,
  autostart, click-result-title behavior (`Show preview`), data collection
  toggle, background task priority (`Normal`), power saving mode, CUDA
  acceleration, NPU acceleration, data directory, storage breakdown, offline
  asset export/import, proxy.
- **Storage breakdown:** ~2.27 GB data/index, ~2.62 GB AI engine and
  dependencies, 573.06 MB AI models, 97.04 KB Python/Deno runtimes, 2.06 GB
  CUDA/OpenVINO runtime libraries, ~480 KB temporary/update leftovers.
- **Local Files:** root cards (e.g. a drive and a Nextcloud folder) with
  document counts, last-update text, and real-time update status; `Add path`;
  file-type grid for Text, Markdown, PDF, Word, PowerPoint, Excel, HTML, WPS,
  and Image, each with independent OCR/Semantic toggles.
- **Offline asset package:** exports a subset of downloaded assets, with
  per-component sizes (AI models, inference acceleration, CUDA, OpenVINO).
- **Visual system:** dark theme, left sidebar, compact top title bar, pill
  switches, rounded cards, blue accent, subtle wave background on home.

These screenshots are visual evidence only; they are not part of the REA
evidence ledger. They corroborate the route/feature map and the indexing-status
model already recovered from strings and the database.

---

## 9. Interfaces

### 9.1 Local REST API

- Axum server on `127.0.0.1:31226` (runtime log).
- Bearer token per integration; optional LAN access + API key.
- Routes observed:

```
POST /api/v1/search
GET  /api/v1/connectors
GET  /api/v1/connectors/{connector_id}/docs/{doc_id}
GET  /api/v1/connectors/{connector_id}/docs/{doc_id}/file
```

Search body fields include `query`, `limit`, `offset`, `semantic_search`,
`connector_names_filter`, `folders`, `update_time_filter`, `sort_by`,
`sort_order`, extensions, and match scopes.

### 9.2 MCP

- `rmcp 1.6.0`, Streamable HTTP at `http://127.0.0.1:31226/mcp`.
- Bearer auth.
- Tools observed as literals: `search`, `get_document`. Connector listing and
  file retrieval also exist in the API/UI surface (`/api/v1/connectors`,
  `.../file`); the exact MCP tool names for those are defined in
  `api/mcp/schema.rs` and were not fully recovered as strings.
- Server methods: `initialize`, `tools/list`, `tools/call`, `resources/list`,
  `resources/updated`, `prompts/get`, `completion/complete`, `logging/setLevel`.
- stdio clients use `mcp-proxy.exe`.

### 9.3 CLI

- `bin/gety` / `bin/gety.cmd` exec `Gety.exe` with arguments.
- Talks to the app over `GETY_CLI`.
- Commands include `gety search ...`, `gety connector list`, `gety doc ...`,
  `--json`, `--ui`, filters, pagination, `--no-semantic-search`.
- The CLI is installed to PATH by the app; a `gety-cli` Agent Skill is
  published at `github.com/gety-ai/gety-skills`.

---

## 10. Security, privacy, and update behavior

- **No code signing** observed on the four Rust binaries.
- UI runs at medium integrity; the service runs as LocalSystem.
- API/MCP uses Bearer tokens; data-sharing middleware can require per-request
  approval (`ask_every_time`) or allow silently (`always_allow`).
- LAN access is optional and off by default in the inspected settings.
- Credentials are stored encrypted (`AesEncrypted` with nonce/ciphertext);
  JWT account tokens; machine ID is derived and forwarded to the crash
  reporter.
- Telemetry is off in the inspected settings; PostHog/Sentry code is present
  and configurable.
- Updater: Tauri updater plugin, release channels `stable`/`beta`/`dev`,
  `app.gety.ai/api/client/v1/releases/...`, downloads from `dl.gety.ai` /
  `dl.gety-cdn.com`, minisign signature verification. The observed machine
  auto-updated from 0.6.3 to 0.7.0 during this investigation.
- Offline asset packages can pre-stage models/runtimes for air-gapped installs.
- Privacy caveat: local retrieval does not mean local downstream inference.
  The REST/MCP layer can return snippets or full document bytes to an external
  AI tool. The API key and sharing policy are the boundary.

---

## 11. Confirmed absences (important for the rebuild)

| Capability | Status |
|---|---|
| Reranker model / cross-encoder | **Absent** in the installed build. |
| Neural context pruner | **Absent**. Snippets are extraction/highlight heuristics. |
| RRF / reciprocal rank fusion | **Absent**; fixed 0.2/0.8 weighted score fusion. |
| Vector DB / HNSW / FAISS / sqlite-vec | **Absent**; SQLite BLOB + exact cosine UDF. |
| Generative answer LLM | **Absent**; retrieval only. |
| Cloud connectors | Not part of the minimal scope; Gety 0.7.0 has a connector catalog, but the docs/blueprint drop it. |
| AI-client integrations | Present in Gety, deliberately omitted from the minimal app. |

These absences are the opportunity: the minimal app can add RRF, a reranker,
and a pruner with a cleaner architecture than Gety's fixed fusion.

---

## 12. Open questions / limits

- Exact FTS5 tokenizer configuration and BM25 parameter values beyond the
  observed SQL/function names.
- Exact query/document prefixes for `gety-embed-v0` in production.
- Exact chunk size/overlap constants (`CHUNK_SIZE_MAX_BYTES` exists; value not
  recovered).
- Exact semantic-score normalization and missing-modality behavior in the
  0.2/0.8 fusion.
- Exact RPC method/IOCTL surface of `gety-service`.
- OCR network topology (encrypted weights).
- 0.7.0 frontend runtime behavior (not loaded/cached at capture time).
- No packet capture or network audit.

These are documented rather than guessed. The build blueprint does not depend
on recovering them; it specifies measurable defaults and experiments.
