> **Archived — superseded.** This document is historical research. The active Seeky implementation is Rust/Tauri/TypeScript; see [../plans/seeky-implementation-plan.md](../plans/seeky-implementation-plan.md).

# 07 — Implementation Plan

This is a build plan for the minimal app described in
[`03-minimal-rag-app-blueprint.md`](minimal-rag-app-blueprint-python.md). It assumes
Python + FastAPI + SQLite for v1 and leaves Tauri/Rust as a later packaging
option.

---

## 1. Repository layout

```
minimal-rag/
  backend/
    app/
      __init__.py
      main.py                 # FastAPI app + startup
      config.py               # pydantic settings
      db.py                   # connection, migrations, helpers
      models/
        __init__.py
        embedder.py           # gety-embed-v0 / Qwen3 adapters
        reranker.py           # CrossEncoder adapter
      indexing/
        scanner.py            # walk roots, diff, enqueue
        watcher.py            # watchdog -> debounce -> enqueue
        extract.py            # PDF/DOCX/XLSX/PPTX/HTML/text
        chunker.py            # token windows + metadata
        worker.py             # task loop (extract/chunk/embed)
      retrieval/
        bm25.py               # FTS5 query
        dense.py              # exact cosine / sqlite-vec
        fusion.py             # RRF
        rerank.py             # optional cross-encoder
        prune.py              # heuristic pruner
        service.py            # orchestration
      api/
        search.py
        docs.py
        roots.py
        status.py
        settings.py
      util/
        text.py
        hashing.py
        tokens.py
    tests/
      test_chunker.py
      test_rrf.py
      test_fts.py
      test_extract.py
      eval/
        queries.jsonl
        run_eval.py
  frontend/
    src/
      App.tsx
      api/client.ts
      components/SearchBar.tsx
      components/Results.tsx
      components/Preview.tsx
      components/Status.tsx
      pages/Settings.tsx
    package.json
    vite.config.ts
  data/
    models/                   # local model files (gitignored)
    index/app.db              # SQLite (gitignored)
  sql/
    minimal_rag_schema.sql
  requirements.txt
  README.md
```

### 1.1 Dependencies

`requirements.txt`:

```text
fastapi>=0.115
uvicorn[standard]>=0.30
pydantic>=2.8
pydantic-settings>=2.4
numpy>=2.0
onnxruntime>=1.20          # or onnxruntime-gpu
tokenizers>=0.20
watchdog>=4.0
pypdf>=5.0                 # BSD; or pymupdf (AGPL)
pdfplumber>=0.11           # optional layout/tables
python-docx>=1.1
openpyxl>=3.1
python-pptx>=0.6.23
beautifulsoup4>=4.12
lxml>=5.2
charset-normalizer>=3.3
python-multipart>=0.0.9
```

Later:

```text
sentence-transformers>=3.0   # Qwen3 embeddings/reranker
transformers>=4.51
torch>=2.4
sqlite-vec>=0.1              # optional ANN
```

Frontend `package.json` (core):

```json
{
  "dependencies": {
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "react-router-dom": "^7.0.0",
    "@tanstack/react-query": "^5.0.0",
    "tailwindcss": "^4.0.0",
    "lucide-react": "^0.500.0"
  },
  "devDependencies": {
    "vite": "^6.0.0",
    "typescript": "^5.6.0",
    "@vitejs/plugin-react": "^4.3.0"
  }
}
```

Use Radix/shadcn components only when you need them; do not port Gety's entire
UI.

---

## 2. Phase plan

### Phase 0 — Skeleton (½ day)

- Create repo, venv, `requirements.txt`.
- Copy `sql/minimal_rag_schema.sql`; run it on `data/index/app.db`.
- Implement `GET /api/status` returning DB path, counts, model info.
- Implement config with the Gety model path.
- Acceptance: `uvicorn app.main:app` starts; `/api/status` returns JSON.

### Phase 1 — Scan and extract (2–3 days)

- `scanner.py`: walk roots, skip ignores, compute `(size, mtime_ns, hash)`.
- `extract.py`: PDF, DOCX, XLSX, PPTX, HTML, text; return blocks + metadata.
- Store `documents` + `blocks`; `status=extracted|failed`.
- CLI: `python -m app.indexing.scanner --root <path>`.
- Acceptance: index a 1,000-file folder; counts match; no crashes on corrupt
  files.

### Phase 2 — Chunk and FTS (1–2 days)

- `chunker.py`: token-aware 512/64, block/page metadata, content hash.
- Insert `chunks`, `chunks_fts` in one transaction per doc.
- `bm25.py` + `GET /api/search?q=` returning BM25 results.
- Acceptance: search returns titles/snippets; quoted phrases work; deletion
  removes FTS rows.

### Phase 3 — Embeddings (2–3 days)

- `embedder.py`: load `gety-embed-v0` ONNX + tokenizer; batch encode.
- Worker fills `chunk_embeddings`; track `model_id`, `dim`, `version`.
- Re-run is idempotent (skip existing `(chunk_id, model_id)`).
- Acceptance: 100% of chunks embedded; a known pair has cosine > 0.8; no
  dimension mismatches.

### Phase 4 — Dense + RRF (2 days)

- `dense.py`: load candidate vectors, NumPy exact cosine, top-K.
- `fusion.py`: RRF with k=60; chunk-level; doc aggregation.
- `GET /api/search` returns `retrievers` and both ranks.
- Acceptance: hybrid beats BM25-only on Recall@10/nDCG@10 on the gold set.

### Phase 5 — Reranker (1–2 days)

- `reranker.py`: `CrossEncoder("Qwen/Qwen3-Reranker-0.6B")`.
- Rerank top 30; timeout/fallback; return `reranked`.
- Acceptance: nDCG@10 improves; p95 within budget; fallback works when the
  model is unavailable.

### Phase 6 — API + UI (3–5 days)

- FastAPI routes for search/docs/roots/status/settings.
- React UI: search bar, filters, result list, preview, status.
- PDF/DOCX/spreadsheet preview; highlight best block.
- Acceptance: a user can add a folder, watch progress, search, open a result.

### Phase 7 — Incremental updates (2 days)

- `watchdog` observer + debounce/coalesce.
- On modify: hash check, delete/reinsert doc-derived rows, re-embed changed
  chunks.
- On delete: cascade delete; remove FTS/vector rows.
- Acceptance: add/modify/delete reflected within 2 s; no duplicates.

### Phase 8 — Qwen3 and optional ANN (3–5 days)

- Add Qwen3-Embedding-0.6B adapter; 1024-d; instruction; background migration.
- Evaluate vs Gety model; switch only if better.
- Add `sqlite-vec` or HNSW if exact search p95 exceeds target.
- Acceptance: eval table shows delta; rollback path works.

### Phase 9 — Optional pruner (future)

- Implement heuristic pruner (dedupe/MMR/token budget).
- Add a learned pruner only with labels and a measured gain.
- Acceptance: answer quality does not regress; context size drops.

---

## 3. Code skeletons

### 3.1 `db.py`

```python
import sqlite3
from pathlib import Path

DB_PATH = Path("data/index/app.db")

def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def migrate(conn: sqlite3.Connection) -> None:
    schema = Path("sql/minimal_rag_schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()
```

For production, replace `executescript` with numbered migrations and a
`schema_migrations` row per version.

### 3.2 `embedder.py`

```python
from pathlib import Path
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

class GetyEmbedder:
    model_id = "gety-embed-v0"
    dim = 384

    def __init__(self, model_dir: Path, providers=None):
        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tok.enable_truncation(max_length=512)
        self.tok.enable_padding(pad_id=1, pad_token="<pad>")
        self.sess = ort.InferenceSession(
            str(model_dir / "onnx" / "model_uint8.onnx"),
            providers=providers or ["CPUExecutionProvider"],
        )
        self.output = self.sess.get_outputs()[0].name

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch_size):
            enc = self.tok.encode_batch(texts[i:i + batch_size])
            feeds = {
                "input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
            }
            vec = self.sess.run([self.output], feeds)[0].astype(np.float32)
            vec /= np.linalg.norm(vec, axis=1, keepdims=True).clip(min=1e-12)
            out.append(vec)
        return np.vstack(out)
```

### 3.3 `bm25.py`

```python
def bm25_search(conn, query: str, limit: int = 100, filters: dict | None = None):
    sql = """
      SELECT c.id AS chunk_id, c.doc_id, bm25(chunks_fts) AS score
      FROM chunks_fts
      JOIN chunks c ON c.id = chunks_fts.rowid
      JOIN documents d ON d.id = c.doc_id
      WHERE chunks_fts MATCH ?
    """
    params: list = [query]
    if filters and filters.get("root_ids"):
        marks = ",".join("?" for _ in filters["root_ids"])
        sql += f" AND d.root_id IN ({marks})"
        params.extend(filters["root_ids"])
    sql += " ORDER BY score LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()
```

### 3.4 `dense.py`

```python
def dense_search(conn, query_vec, model_id: str, dim: int, limit: int = 100):
    rows = conn.execute(
        """
        SELECT e.chunk_id, e.vector
        FROM chunk_embeddings e
        JOIN chunks c ON c.id = e.chunk_id
        WHERE e.model_id = ? AND e.dim = ?
        """,
        (model_id, dim),
    ).fetchall()
    if not rows:
        return []
    ids = [r["chunk_id"] for r in rows]
    mat = np.frombuffer(b"".join(r["vector"] for r in rows), dtype=np.float32).reshape(-1, dim)
    scores = mat @ query_vec
    top = np.argpartition(-scores, min(limit, len(scores) - 1))[:limit]
    top = top[np.argsort(-scores[top])]
    return [(ids[i], float(scores[i])) for i in top]
```

For production, cache `mat` and `ids` in memory, or use `sqlite-vec`.

### 3.5 `fusion.py`

```python
def rrf(rankings, k=60, weights=None):
    weights = weights or [1.0] * len(rankings)
    scores = {}
    for weight, ranking in zip(weights, rankings):
        for rank, chunk_id in enumerate(ranking, 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
```

### 3.6 `main.py` search endpoint

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    limit: int = 10
    offset: int = 0
    semantic: bool = True
    rerank: bool = True
    roots: list[str] | None = None

@app.post("/api/search")
def search(req: SearchRequest):
    qvec = embedder.encode([req.query])[0]
    bm25 = bm25_search(conn, req.query, 100, {"root_ids": req.roots})
    dense = dense_search(conn, qvec, embedder.model_id, embedder.dim, 100)
    fused = rrf([[r["chunk_id"] for r in bm25], [cid for cid, _ in dense]])
    top = fused[:50]
    # join chunk text/doc metadata, rerank top 30, prune, format
    return {"query": req.query, "results": format_results(top[: req.limit])}
```

### 3.7 Reranker adapter

```python
import torch
from sentence_transformers import CrossEncoder

class Reranker:
    def __init__(self, model_name="Qwen/Qwen3-Reranker-0.6B"):
        self.model = CrossEncoder(model_name)

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        scores = self.model.predict(
            [(query, p) for p in passages],
            activation_fn=torch.nn.Sigmoid(),
        )
        return [float(s) for s in scores]
```

### 3.8 Heuristic pruner

```python
def prune(query_vec, candidates, token_budget=3000, mmr_lambda=0.7):
    # candidates: list of {chunk_id, text, vec, score, doc_id, ...}
    selected = []
    used = 0
    while candidates and used < token_budget:
        best = None
        for c in candidates:
            relevance = c["score"]
            redundancy = max((c["vec"] @ s["vec"] for s in selected), default=0.0)
            mmr = mmr_lambda * relevance - (1 - mmr_lambda) * redundancy
            if best is None or mmr > best[0]:
                best = (mmr, c)
        _, pick = best
        if used + pick["tokens"] > token_budget:
            candidates.remove(pick)
            continue
        selected.append(pick)
        used += pick["tokens"]
        candidates.remove(pick)
    return selected
```

This is a baseline, not a trained pruner.

---

## 4. API and UI contracts

### 4.1 Backend endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/search` | Hybrid search |
| GET | `/api/status` | Index counts, model, DB size |
| GET | `/api/docs/{doc_id}` | Metadata + blocks |
| GET | `/api/docs/{doc_id}/file` | Original bytes |
| POST | `/api/roots` | Add root |
| DELETE | `/api/roots/{root_id}` | Remove root + indexed data |
| POST | `/api/reindex` | Rebuild index |
| GET/PUT | `/api/settings` | Configuration |

Search response must include:

- `doc_id`, `title`, `path`, `doc_type`, `updated_at`
- `score`, `rrf_rank`, `rerank_score` (nullable)
- `retrievers` list
- `snippet`, `highlights`, `page`, `bbox`, `source_anchor`
- `took_ms`

### 4.2 UI states

1. **Empty:** add a folder.
2. **Indexing:** progress (discovered/extracted/embedded/failed).
3. **Results:** query, filters, result cards, preview.
4. **Error:** extraction failures, model missing, DB locked.
5. **Settings:** roots, excludes, model, chunking, reranker, pruner, ANN.

Do not build connector/integration UI; that is out of scope.

---

## 5. Testing

### 5.1 Unit

- Chunker never exceeds max tokens; overlap is correct; offsets map to blocks.
- RRF ordering is deterministic; tie handling is stable.
- FTS5 insert/delete/search round-trip.
- Dense cosine matches a reference `sklearn`/NumPy implementation.
- Extractor handles empty/corrupt files without raising.

### 5.2 Integration

- Index a fixture folder with PDF/DOCX/XLSX/PPTX/HTML/TXT.
- Search for known terms; assert doc IDs.
- Modify a file; assert old chunks removed and new content searchable.
- Delete a file; assert no orphan rows.
- Restart; assert progress resumes.

### 5.3 Evaluation

`tests/eval/run_eval.py`:

- Load `queries.jsonl`: `{query, relevant_doc_ids, relevant_chunk_ids}`.
- Run BM25, dense, weighted, RRF, RRF+rerank.
- Compute Recall@10, MRR@10, nDCG@10, p50/p95 latency.
- Write `eval-results.md` with the table.

### 5.4 Acceptance gates

- No orphan `chunks`/`chunk_embeddings` after delete.
- 100% of eligible chunks have an embedding for the active model.
- Search returns within 500 ms p95 on the target corpus (or documented).
- RRF+rerank beats BM25-only by a measurable margin on the gold set.
- The app starts from a clean data dir and indexes a folder end-to-end.

---

## 6. Packaging

### 6.1 Local web app

- `uvicorn app.main:app --host 127.0.0.1 --port 8787`.
- Vite dev server for UI; build static assets and serve them from FastAPI for
  production.
- Optional `GETY_API_KEY` bearer check for local non-browser clients.

### 6.2 Tauri desktop (later)

- Tauri 2 shell opens the local UI.
- Sidecar: run the Python backend as a bundled executable (PyInstaller) or
  reimplement the stable backend in Rust/Axum.
- Keep the same HTTP API contract; the UI does not care whether the backend is
  Python or Rust.
- If you use Python, bundle the model files outside the app binary; do not
  embed 100+ MB into the installer unless necessary.

---

## 7. Risks and decisions to revisit

| Decision | Revisit when |
|---|---|
| SQLite exact cosine | p95 > target or corpus > 100k chunks |
| `gety-embed-v0` | Qwen3 eval shows a meaningful lift and hardware can handle it |
| Python backend | Packaging/latency becomes a problem; port to Rust |
| No reranker in v1 | Baseline eval is stable; add Qwen3 reranker |
| Heuristic pruner | You have labels and a measured answer-quality gain |
| 512-token chunks | Long-document recall is poor; test 768–1024 with Qwen3 |
| FTS5 `unicode61` | Chinese/Japanese/code corpus needs jieba/trigram |

---

## 8. First-week checklist

- [ ] Create schema and status endpoint.
- [ ] Index 100 PDFs/DOCX files.
- [ ] Get BM25 search working with snippets.
- [ ] Embed chunks with `gety-embed-v0`; verify 384-d output.
- [ ] Add dense search and RRF.
- [ ] Build a 20-query gold set.
- [ ] Measure BM25 vs dense vs RRF.
- [ ] Add Qwen3 reranker if the baseline is stable.
- [ ] Add incremental updates.
- [ ] Write the eval table into the repo.

The goal of week one is **a working retrieval loop and a measurement**, not a
polished UI.
