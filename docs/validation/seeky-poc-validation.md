# Seeky — PoC validation

This file records the commands and observed results that show the PoC is
runnable and that CPU, CUDA and NPU inference work through Gety's own model
files.

**Environment**

- Windows x64, 20 logical CPUs, 64 GB RAM
- NVIDIA GeForce RTX 3090 (compute 8.6)
- Intel AI Boost NPU
- Gety 0.7.0 installed at `C:\Users\bernh\AppData\Local\Gety`
- Rust 1.99.1, Node 26.13.1, Tauri 2.12.7 (CLI 2.12.6)

---

## 1. Backend tests (in-process, app crate)

Command:

```powershell
cd apps\seeky\src-tauri
cargo test --lib -- --test-threads=1 --nocapture
```

Observed:

```text
running 8 tests
test extract::tests::extracts_docx_text ... ok
test extract::tests::extracts_pdf_text ... ok
test extract::tests::skips_binary_text ... ok
test indexer::tests::index_and_search_roundtrip ... ok
test inference::tests::cpu_embedding_works ... ok
test inference::tests::cuda_embedding_works ... ok
test inference::tests::npu_embedding_works ... ok
test tests::maps_watch_events_to_upserts_and_removes ... ok

test result: ok. 8 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
```

The roundtrip test creates a temporary folder with TXT, MD, PDF, DOCX and a
filename-only fixture, indexes it, verifies unchanged files are skipped, edits
the budget file, renames `atlas-notes.txt`, deletes it and reindexes. The
watcher test maps create/modify/remove/rename events to the right action.

---

## 2. Build

```powershell
cd apps\seeky
npm install
npm run tauri -- build --debug --no-bundle
```

Observed:

```text
Built application at: C:\Users\bernh\Documents\Opencode\REA\Gety\apps\seeky\src-tauri\target\debug\seeky.exe
```

Launch:

```powershell
cd apps\seeky
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222'
.\src-tauri\target\debug\seeky.exe
```

Observed process:

```text
ProcessName     : seeky
MainWindowTitle : Seeky - local semantic search
Responding      : True
```

### Release build and resources

```powershell
npm run tauri -- build --no-bundle
```

Observed:

```text
Finished `release` profile [optimized] target(s) in 8m 04s
Built application at: C:\Users\bernh\Documents\Opencode\REA\Gety\apps\seeky\src-tauri\target\release\seeky.exe
```

The release binary is 11,469,824 bytes. Tauri copies the bundled NPU IR next to
it:

```text
target\release\resources\models\gety-embed-v0\openvino\model.xml   712,310 bytes
target\release\resources\models\gety-embed-v0\openvino\model.bin   118,572,517 bytes
```

A portable-layout smoke test copied only `seeky.exe` + `resources\` to
`T:\Temp\seeky-portable`. The running app resolved
`npu_model = T:\Temp\seeky-portable\resources\models\gety-embed-v0\openvino`,
loaded the NPU, and searched successfully (46 ms).

---

## 3. Runtime status (release UI IPC)

Evaluated in the running release app's WebView2 through CDP:

```js
window.__TAURI_INTERNALS__.invoke('get_status')
```

Observed:

```json
{
  "roots": 1,
  "counts": { "documents": 5, "chunks": 5, "roots": 1, "embeddings": 5 },
  "backend": "npu",
  "backend_label": "NPU",
  "available_backends": ["cpu", "cuda", "npu"],
  "engine": {
    "backend": "NPU",
    "model": "gety-embed-v0 · OpenVINO IR",
    "device": "Intel AI Boost · OpenVINO NPU",
    "detail": "384-d · 256-token bucket"
  },
  "model_root": "C:\\Users\\bernh\\AppData\\Roaming\\ai.gety\\data\\models\\gety-ai\\gety-embed-v0\\424f41cb36776481b7e2c9f619ca7ce5d5351fe0",
  "npu_model": "C:\\Users\\bernh\\Documents\\Opencode\\REA\\Gety\\apps\\seeky\\src-tauri\\target\\release\\resources\\models\\gety-embed-v0\\openvino",
  "pdfium": "C:\\Users\\bernh\\AppData\\Local\\Gety\\lib\\pdfium.dll",
  "db_path": "C:\\Users\\bernh\\AppData\\Roaming\\ai.seeky.desktop\\seeky.db",
  "model_ready": true,
  "health": {
    "indexing": false,
    "watching": true,
    "watched_roots": 1,
    "pending": 0,
    "last_indexed_at": 1795744384,
    "last_message": "Watched: 0 updated / 0 unchanged / 1 removed",
    "last_error": null,
    "current_file": null,
    "skipped": 0,
    "errors": 0,
    "details": []
  }
}
```

---

## 4. CPU / CUDA / NPU probes in the running app

Evaluated in the running app:

```js
await invoke('probe_backend', { backend: 'cpu' })
await invoke('probe_backend', { backend: 'cuda' })
await invoke('probe_backend', { backend: 'npu' })
await invoke('search_documents', { query: 'contract renewal notice', limit: 5 })
```

Observed engine identities:

| Backend | Model | Device | Detail |
|---|---|---|---|
| CPU | `gety-embed-v0 · model_uint8.onnx` | ONNX Runtime CPU | 384-d · 512 tokens |
| CUDA | `gety-embed-v0 · model_fp16.onnx` | NVIDIA GPU · CUDA EP | 384-d · 512 tokens · FP16 |
| NPU | `gety-embed-v0 · OpenVINO IR` | Intel AI Boost · OpenVINO NPU | 384-d · 256-token bucket |

Each backend returned the same five hits for "contract renewal notice". The NPU
probe/search round took 33 ms; the same query through the release UI took 26 ms
and an IPC re-run took 24 ms:

```text
renewal  TXT   1.000  matched [bm25, semantic, filename]
renewal  PDF   0.980  matched [bm25, semantic, filename]
sample   DOCX  0.660  matched [bm25, semantic]
budget   MD    0.320  matched [semantic]
project  MD    0.320  matched [semantic]
```

### Final UI flow: Settings → NPU → search

1. The NPU card was clicked with a native pointer event at its real screen
   position (not a synthetic `.click()`).
2. The card showed a spinner, then `NPU ready · Intel AI Boost · OpenVINO NPU`.
3. `get_status` reported `engine.backend = "NPU"`, `backend = "npu"`, and the
   choice persisted in SQLite (`settings.backend = "npu"`).
4. Navigating back to Search and typing `contract renewal notice` returned
   `5 results · 26 ms`, `hybrid BM25 + embeddings · NPU`, and status bar
   `NPU · 384-d`.
5. The five embeddings had been produced during indexing under CUDA. Searching
   them under NPU reused the same vectors, confirming that CPU/CUDA/NPU share a
   compatible embedding space and that switching backends does not require a
   re-index.

The UI screenshots `../assets/screenshots/seeky/settings-npu.png` and `../assets/screenshots/seeky/results.png`
show this final state. The status bar reads `NPU · 384-d` in both.

### Native open-file command

The preview's **Open file** action uses a narrow Rust command, not a broad
webview opener allowlist. Tested through IPC against the release app:

```text
open_local_file(missing-file.txt) -> "The system cannot find the file specified. (os error 2)"
open_local_file(renewal.txt)      -> ok
```

The existing file opened in the OS default editor (`Notepad++`).

---

## 5. End-to-end index + search

Demo folder `T:\Temp\seeky-demo` (mirrored in `apps/seeky/demo`):

```text
renewal.txt     plain text
budget.md       markdown
project.md      markdown
renewal.pdf     generated PDF with text
sample.docx     DOCX with text
```

Indexing result (earlier run):

```json
{
  "files": 5,
  "chunks": 5,
  "skipped": 0,
  "errors": 0,
  "removed": 1
}
```

`removed: 1` is the stale `dummy.pdf` from an earlier run; the index prune
deleted it because it no longer exists.

Search `contract renewal notice` in the UI:

```text
5 results · 26 ms
hybrid BM25 + embeddings · NPU

renewal  TXT   1.00  BM25 + SEMANTIC + FILENAME
renewal  PDF   0.98  BM25 + SEMANTIC + FILENAME
sample   DOCX  0.66  BM25 + SEMANTIC
budget   MD    0.32  SEMANTIC
project  MD    0.32  SEMANTIC
```

The PDF and DOCX results prove that the PDFium and DOCX extraction paths run
inside the Tauri app, not just in unit tests.

Screenshots:

- `../assets/screenshots/seeky/home.png`
- `../assets/screenshots/seeky/results.png` — release build, NPU selected, `5 results · 26 ms`
- `../assets/screenshots/seeky/preview.png` — release build, clean absolute path
- `../assets/screenshots/seeky/settings-npu.png` — release build, `ACTIVE` NPU card, bundled IR path
- `../assets/screenshots/seeky/files.png` — release build, indexed demo folder

---

## 6. Live watcher, incremental indexing and cancellation

Exercised against the running app with the demo folder watched:

```text
baseline: 5 demo documents
create watch-created.txt      -> 6 documents, search finds "watch-created"
modify content                -> snippet contains the new "dragonfruit" text
rename to watch-renamed.txt   -> old path removed, new path indexed
delete watch-renamed.txt      -> 5 documents, health: "1 removed"
```

Observed health messages:

```text
Watched: 1 updated / 0 unchanged / 0 removed
Watched: 0 updated / 0 unchanged / 1 removed
```

Per-folder pause/resume:

```text
set_root_watching(seeky-demo, false) -> watch_enabled=false, watched_roots=1
create paused-file.txt while paused   -> demo stays at 5 documents
set_root_watching(seeky-demo, true)  -> watcher resumes
```

Incremental reindex after a schema migration updated the five existing demo
documents once; the next run reported:

```json
{ "scanned": 5, "files": 0, "chunks": 0, "unchanged": 5,
  "skipped": 0, "errors": 0, "removed": 0, "cancelled": false }
```

Cancellation against a 500-file fixture:

```json
{ "scanned": 500, "files": 6, "chunks": 6, "unchanged": 0,
  "skipped": 0, "errors": 0, "removed": 0, "cancelled": true }
```

The fixture root was removed and its documents cascaded out after the test.
The final release build repeated the demo create/delete cycle (`5 → 6 → 5`
documents) with the same health messages.

Filename/path fusion is visible in the result tags. Searching `renewal`
returns both renewal files with:

```text
matched = ["bm25", "semantic", "filename"]
```

The Files page shows the watcher state, pending changes, last index time,
skipped/errors, recent extraction issues, and a **Cancel** button while
indexing (`../assets/screenshots/seeky/files.png`).

---

## 7. Known PoC limitations

- The first full index of a folder is still user-triggered; after that the
  watcher applies live changes. Changes made while Seeky is closed require
  **Reindex** (unchanged files are skipped).
- Filesystem events are OS-dependent and can be coalesced. Rename handling
  covers notify's both/from/to/any modes; unusual network filesystems may
  degrade to a later manual Reindex.
- PDF and DOCX are supported; XLSX/PPTX extractors are compiled but not yet
  exercised by the demo.
- No cross-encoder reranker is wired yet; retrieval is BM25 + filename/path +
  dense + RRF.
- No OCR in the PoC; Gety's OCR weights are encrypted/private.
- NPU first load compiles the OpenVINO model and can take tens of seconds; later
  searches are fast.
- CPU/CUDA paths depend on the installed Gety model directory. Set
  `SEEKY_GETY_MODEL_DIR` to override.

---

## 8. Ghidra note

The 0.7.0 `gety-service.exe` was fully analyzed with Ghidra 12.2 (11,291
procedures, 1,496 strings; `NtDeviceIoControlFile` xref and function
decompiled). The 113 MB `Gety.exe` Ghidra pass hit REA's 1-hour provider
deadline (`provider_timeout`), so Seeky's model/UI architecture uses the
completed service analysis plus static strings, PE metadata, and the SQLite
schema instead.
