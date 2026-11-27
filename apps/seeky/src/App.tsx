import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import "./App.css";
import type {
  DocumentView,
  IndexHealth,
  IndexProgress,
  IndexSummary,
  Root,
  SearchHit,
  SearchResponse,
  Status,
} from "./types";

type View = "search" | "files" | "settings";

const BACKENDS = [
  {
    id: "auto",
    label: "Auto",
    detail: "NPU → CPU",
    blurb:
      "Use the NPU when available, otherwise the CPU. Never selects a GPU.",
  },
  {
    id: "cpu",
    label: "CPU",
    detail: "ONNX Runtime · uint8",
    blurb: "Universal fallback. Smallest model, lowest memory.",
  },
  {
    id: "cuda",
    label: "CUDA",
    detail: "RTX / ONNX Runtime · FP16",
    blurb: "Fastest path on NVIDIA GPUs.",
  },
  {
    id: "npu",
    label: "NPU",
    detail: "Intel AI Boost · OpenVINO",
    blurb: "Low-power inference on Intel Core Ultra NPUs.",
  },
] as const;

function basename(path: string) {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

function parentPath(path: string) {
  const parts = path.split(/[\\/]/);
  parts.pop();
  return parts.slice(-2).join("\\");
}

function cleanPath(path: string) {
  if (path.startsWith("\\\\?\\UNC\\")) return "\\\\" + path.slice(8);
  if (path.startsWith("\\\\?\\")) return path.slice(4);
  return path;
}

function formatBytes(bytes: number) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatWhen(timestamp: number | null | undefined) {
  if (!timestamp) return "never";
  return new Date(timestamp * 1000).toLocaleString();
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function Highlighted({ text, query }: { text: string; query: string }) {
  const terms = useMemo(
    () =>
      query
        .split(/\s+/)
        .map((term) => term.trim())
        .filter((term) => term.length > 2)
        .slice(0, 6),
    [query],
  );
  if (!terms.length) return <>{text}</>;
  const pattern = new RegExp(`(${terms.map(escapeRegExp).join("|")})`, "gi");
  const isTerm = new RegExp(`^(?:${terms.map(escapeRegExp).join("|")})$`, "i");
  const parts = text.split(pattern);
  return (
    <>
      {parts.map((part, index) =>
        isTerm.test(part) ? <mark key={index}>{part}</mark> : part,
      )}
    </>
  );
}

function Icon({
  name,
}: {
  name:
    | "search"
    | "folder"
    | "sliders"
    | "database"
    | "bolt"
    | "file"
    | "x"
    | "arrow";
}) {
  const paths: Record<string, string> = {
    search: "M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm10 2-4.35-4.35",
    folder:
      "M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z",
    sliders:
      "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6",
    database:
      "M12 2c4.97 0 9 1.79 9 4s-4.03 4-9 4-9-1.79-9-4 4.03-4 9-4Z M3 6v6c0 2.21 4.03 4 9 4s9-1.79 9-4V6 M3 12v6c0 2.21 4.03 4 9 4s9-1.79 9-4v-6",
    bolt: "M13 2 3 14h7l-1 8 10-12h-7l1-8Z",
    file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Z M14 2v6h6",
    x: "M18 6 6 18M6 6l12 12",
    arrow: "M5 12h14M12 5l7 7-7 7",
  };
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}

function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [view, setView] = useState<View>("search");
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selected, setSelected] = useState<DocumentView | null>(null);
  const [progress, setProgress] = useState<IndexProgress | null>(null);
  const [indexing, setIndexing] = useState<string | null>(null);
  const [probing, setProbing] = useState<string | null>(null);
  const searchSeq = useRef(0);

  async function refresh() {
    try {
      const next = await invoke<Status>("get_status");
      setStatus(next);
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => {
    refresh();
    const progressListener = listen<IndexProgress>(
      "index-progress",
      (event) => {
        setProgress(event.payload);
      },
    );
    const healthListener = listen<IndexHealth>("index-health", (event) => {
      setStatus((current) =>
        current ? { ...current, health: event.payload } : current,
      );
      if (!event.payload.indexing) {
        refresh();
      }
    });
    const timer = window.setInterval(() => {
      refresh();
    }, 2000);
    return () => {
      progressListener.then((unlisten) => unlisten()).catch(() => undefined);
      healthListener.then((unlisten) => unlisten()).catch(() => undefined);
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (view !== "search") setSelected(null);
  }, [view]);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResponse(null);
      setSearching(false);
      return;
    }
    const seq = ++searchSeq.current;
    setSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        const result = await invoke<SearchResponse>("search_documents", {
          query: trimmed,
          limit: 24,
        });
        if (seq === searchSeq.current) {
          setResponse(result);
          setError(null);
        }
      } catch (err) {
        if (seq === searchSeq.current) {
          setError(String(err));
          setResponse(null);
        }
      } finally {
        if (seq === searchSeq.current) setSearching(false);
      }
    }, 240);
    return () => window.clearTimeout(timer);
  }, [query]);

  async function addFolder() {
    try {
      const picked = await open({
        directory: true,
        multiple: false,
        title: "Add a folder to Seeky",
      });
      if (!picked || Array.isArray(picked)) return;
      const root = await invoke<Root>("add_root", { path: picked });
      await refresh();
      setView("files");
      setNotice(
        root.watch_enabled
          ? "Folder added. Watching for changes — index it to make it searchable."
          : "Folder added, but watching failed. Check Index health, then index it manually.",
      );
    } catch (err) {
      setError(String(err));
    }
  }

  async function removeRoot(root: Root) {
    try {
      await invoke("remove_root", { id: root.id });
      await refresh();
      setNotice(`Removed ${cleanPath(root.path)} and its indexed documents.`);
    } catch (err) {
      setError(String(err));
    }
  }

  async function toggleWatch(root: Root) {
    try {
      const updated = await invoke<Root>("set_root_watching", {
        id: root.id,
        enabled: !root.watch_enabled,
      });
      await refresh();
      setNotice(
        updated.watch_enabled
          ? `Watching ${basename(updated.path)} for changes.`
          : `Paused watching ${basename(updated.path)}.`,
      );
    } catch (err) {
      setError(String(err));
      await refresh();
    }
  }

  async function indexRoot(root: Root) {
    setIndexing(root.path);
    setError(null);
    setNotice(null);
    setProgress({
      phase: "scan",
      current: 0,
      total: 0,
      file: root.path,
      message: "Scanning…",
    });
    try {
      const summary = await invoke<IndexSummary>("start_index", {
        path: root.path,
      });
      if (summary.cancelled) {
        setNotice(
          `Index cancelled after ${summary.files} files / ${summary.chunks} chunks.`,
        );
      } else {
        const parts = [`${summary.files} updated`];
        if (summary.unchanged) parts.push(`${summary.unchanged} unchanged`);
        parts.push(`${summary.chunks} chunks`);
        if (summary.skipped) parts.push(`${summary.skipped} skipped`);
        if (summary.removed) parts.push(`${summary.removed} removed`);
        setNotice(parts.join(" · "));
      }
      await refresh();
    } catch (err) {
      setError(String(err));
    } finally {
      setIndexing(null);
      setProgress(null);
    }
  }

  async function cancelIndexing() {
    try {
      await invoke("cancel_index");
      setNotice("Cancellation requested. The current file will finish first.");
    } catch (err) {
      setError(String(err));
    }
  }

  async function chooseBackend(backend: string) {
    setProbing(backend);
    setError(null);
    try {
      const info = await invoke<{
        backend: string;
        device: string;
        model: string;
      }>("probe_backend", { backend });
      await refresh();
      setNotice(`${info.backend} ready · ${info.device}`);
    } catch (err) {
      setError(String(err));
      await refresh();
    } finally {
      setProbing(null);
    }
  }

  async function openDocument(hit: SearchHit) {
    try {
      const doc = await invoke<DocumentView | null>("get_document", {
        id: hit.doc_id,
      });
      setSelected(doc);
      if (!doc) setError("Document not found in the index.");
    } catch (err) {
      setError(String(err));
    }
  }

  async function openFile() {
    if (!selected) return;
    try {
      await invoke("open_local_file", { path: selected.path });
    } catch (err) {
      setError(String(err));
    }
  }

  const counts = status?.counts;
  const health = status?.health;
  const progressPercent =
    progress && progress.total > 0
      ? Math.min(100, Math.round((progress.current / progress.total) * 100))
      : 0;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">s</span>
          <span className="brand-name">
            seeky<span className="brand-dot">.</span>
          </span>
        </div>
        <div className="brand-tag">local semantic search</div>

        <nav className="nav">
          <button
            className={view === "search" ? "nav-item active" : "nav-item"}
            onClick={() => setView("search")}
          >
            <Icon name="search" />
            Search
          </button>
          <button
            className={view === "files" ? "nav-item active" : "nav-item"}
            onClick={() => setView("files")}
          >
            <Icon name="folder" />
            Local Files
          </button>
          <button
            className={view === "settings" ? "nav-item active" : "nav-item"}
            onClick={() => setView("settings")}
          >
            <Icon name="sliders" />
            Settings
          </button>
        </nav>

        <div className="sidebar-spacer" />
        <div className="backend-card">
          <div className="backend-card-label">
            <Icon name="bolt" />
            Inference
          </div>
          <div className="backend-card-value">
            {status?.engine?.backend ?? status?.backend_label ?? "not loaded"}
          </div>
          <div className="backend-card-detail">
            {status?.engine?.detail ?? "384-d Gety embeddings"}
          </div>
        </div>
        <div className="sidebar-foot">
          <span>{counts?.documents ?? 0} files</span>
          <span>{counts?.chunks ?? 0} chunks</span>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="searchbox">
            <Icon name="search" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search keyword, phrase, or meaning…"
              spellCheck={false}
              autoFocus
            />
            {searching && <span className="spinner" />}
            {query && !searching && (
              <button
                className="clear"
                onClick={() => setQuery("")}
                aria-label="Clear search"
              >
                <Icon name="x" />
              </button>
            )}
          </div>
          <button className="ghost-button" onClick={() => setView("files")}>
            <Icon name="folder" />
            Add folder
          </button>
        </header>

        {error && (
          <div className="banner error">
            <span>{error}</span>
            <button onClick={() => setError(null)}>Dismiss</button>
          </div>
        )}
        {notice && (
          <div className="banner notice">
            <span>{notice}</span>
            <button onClick={() => setNotice(null)}>Dismiss</button>
          </div>
        )}

        <div
          className={
            selected && view === "search" ? "content with-preview" : "content"
          }
        >
          <section className="results-area">
            {view === "search" && (
              <>
                {!query.trim() && (
                  <div className="hero">
                    <div className="hero-kicker">PRIVATE · LOCAL · FAST</div>
                    <h1>
                      Meet Seeky,
                      <br />
                      your personal semantic file search.
                    </h1>
                    <p>
                      Index your folders once. Then ask in plain language and
                      get the passages that matter — with citations, on your
                      machine.
                    </p>
                    <div className="hero-actions">
                      <button className="primary" onClick={addFolder}>
                        Add a folder
                      </button>
                      <button
                        className="secondary"
                        onClick={() => setView("settings")}
                      >
                        Choose CPU / CUDA / NPU
                      </button>
                    </div>
                    <div className="hero-stats">
                      <div>
                        <strong>{counts?.documents ?? 0}</strong>
                        <span>files indexed</span>
                      </div>
                      <div>
                        <strong>{counts?.chunks ?? 0}</strong>
                        <span>semantic chunks</span>
                      </div>
                      <div>
                        <strong>{status?.engine?.backend ?? "—"}</strong>
                        <span>active backend</span>
                      </div>
                    </div>
                  </div>
                )}

                {query.trim() && (
                  <div className="results-head">
                    <span>
                      {searching
                        ? "Searching…"
                        : response
                          ? `${response.hits.length} results · ${response.took_ms} ms`
                          : "No results yet"}
                    </span>
                    {response && (
                      <span className="result-meta">
                        {response.semantic_used
                          ? "hybrid BM25 + embeddings"
                          : "BM25 only"}{" "}
                        · {response.backend}
                      </span>
                    )}
                  </div>
                )}

                {query.trim() &&
                  response &&
                  response.hits.length === 0 &&
                  !searching && (
                    <div className="empty-state">
                      <Icon name="search" />
                      <h3>No matches</h3>
                      <p>
                        Try a broader phrase, or add and index another folder.
                      </p>
                    </div>
                  )}

                <div className="result-list">
                  {response?.hits.map((hit) => (
                    <button
                      key={hit.chunk_id}
                      className={
                        selected?.id === hit.doc_id
                          ? "result selected"
                          : "result"
                      }
                      onClick={() => openDocument(hit)}
                    >
                      <div className="result-icon">
                        <Icon name="file" />
                      </div>
                      <div className="result-body">
                        <div className="result-title-row">
                          <span className="result-title">{hit.title}</span>
                          <span className="score">{hit.score.toFixed(2)}</span>
                        </div>
                        <div className="result-path">
                          {parentPath(hit.path)} · {hit.ext.toUpperCase()}
                          {hit.page ? ` · p.${hit.page}` : ""}
                        </div>
                        <p className="result-snippet">
                          <Highlighted text={hit.snippet} query={query} />
                        </p>
                        <div className="result-tags">
                          {hit.matched.map((kind) => (
                            <span key={kind} className={`tag ${kind}`}>
                              {kind === "semantic"
                                ? "semantic"
                                : kind === "filename"
                                  ? "filename"
                                  : "BM25"}
                            </span>
                          ))}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </>
            )}

            {view === "files" && (
              <div className="page">
                <div className="page-head">
                  <div>
                    <div className="eyebrow">INDEX</div>
                    <h2>Local Files</h2>
                    <p>
                      Folders Seeky can watch and search. Nothing leaves this
                      machine.
                    </p>
                  </div>
                  <button className="primary" onClick={addFolder}>
                    <Icon name="folder" />
                    Add folder
                  </button>
                </div>

                <div className="root-list">
                  {status?.roots.length === 0 && (
                    <div className="empty-state">
                      <Icon name="folder" />
                      <h3>No folders yet</h3>
                      <p>Add a folder to start building your local index.</p>
                    </div>
                  )}
                  {status?.roots.map((root) => (
                    <div className="root-card" key={root.id}>
                      <div className="root-icon">
                        <Icon name="folder" />
                      </div>
                      <div className="root-body">
                        <div className="root-title">{basename(root.path)}</div>
                        <div className="root-path">{cleanPath(root.path)}</div>
                        <div className="root-meta">
                          {root.documents} documents ·{" "}
                          {root.documents > 0 ? "indexed" : "ready to index"}
                        </div>
                      </div>
                      <div className="root-actions">
                        <button
                          className={`watch-button ${root.watch_enabled ? "on" : ""}`}
                          onClick={() => toggleWatch(root)}
                          aria-pressed={root.watch_enabled}
                          title={
                            root.watch_enabled
                              ? "Pause filesystem watching"
                              : "Resume filesystem watching"
                          }
                        >
                          <span className="watch-dot" />
                          {root.watch_enabled ? "Watching" : "Paused"}
                        </button>
                        <button
                          className="secondary"
                          onClick={() => indexRoot(root)}
                          disabled={
                            Boolean(indexing) || Boolean(health?.indexing)
                          }
                        >
                          {indexing === root.path
                            ? "Indexing…"
                            : root.documents > 0
                              ? "Reindex"
                              : "Index"}
                        </button>
                        <button
                          className="icon-button"
                          onClick={() => removeRoot(root)}
                          aria-label="Remove folder"
                        >
                          <Icon name="x" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="health-panel">
                  <div className="health-heading">
                    <div>
                      <div className="panel-heading">Index health</div>
                      <p>
                        {health?.last_message ?? "No indexing activity yet."}
                      </p>
                    </div>
                    <div className="health-actions">
                      {health?.indexing && (
                        <button
                          className="ghost-button"
                          onClick={cancelIndexing}
                        >
                          Cancel
                        </button>
                      )}
                      <span
                        className={`health-state ${health?.indexing ? "busy" : ""}`}
                      >
                        {health?.indexing ? "Indexing" : "Idle"}
                      </span>
                    </div>
                  </div>
                  <div className="health-grid">
                    <div>
                      <span>Watcher</span>
                      <strong>
                        {health?.watching
                          ? `Watching ${health.watched_roots} folder${health.watched_roots === 1 ? "" : "s"}`
                          : "Paused"}
                      </strong>
                    </div>
                    <div>
                      <span>Pending changes</span>
                      <strong>{health?.pending ?? 0}</strong>
                    </div>
                    <div>
                      <span>Last indexed</span>
                      <strong>{formatWhen(health?.last_indexed_at)}</strong>
                    </div>
                    <div>
                      <span>Skipped / errors</span>
                      <strong>
                        {health?.skipped ?? 0} / {health?.errors ?? 0}
                      </strong>
                    </div>
                  </div>
                  {health?.current_file && (
                    <div className="health-current">
                      Processing <code>{cleanPath(health.current_file)}</code>
                    </div>
                  )}
                  {health?.last_error && (
                    <div className="health-error">{health.last_error}</div>
                  )}
                  {health && health.details.length > 0 && (
                    <details className="health-details">
                      <summary>
                        Recent extraction issues ({health.details.length})
                      </summary>
                      <ul>
                        {health.details.slice(0, 6).map((detail, index) => (
                          <li key={`${index}-${detail}`}>{detail}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                  <p className="health-hint">
                    Live changes are applied automatically. Use Reindex to pick
                    up edits made while Seeky was closed.
                  </p>
                </div>

                <div className="type-panel">
                  <div className="panel-heading">Supported today</div>
                  <div className="type-grid">
                    {[
                      ["PDF", "text + pages"],
                      ["DOCX", "paragraphs"],
                      ["XLSX", "sheet cells"],
                      ["PPTX", "slide text"],
                      ["TXT / MD", "plain text"],
                      ["HTML", "readable text"],
                      ["CODE", "source files"],
                    ].map(([label, detail]) => (
                      <div className="type-chip" key={label}>
                        <strong>{label}</strong>
                        <span>{detail}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="callout">
                  <Icon name="database" />
                  <div>
                    <strong>How indexing works</strong>
                    <p>
                      Seeky extracts text, chunks it, embeds every chunk with
                      <code> gety-embed-v0</code>, and stores both BM25 and
                      vector indexes in one SQLite file.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {view === "settings" && (
              <div className="page">
                <div className="page-head">
                  <div>
                    <div className="eyebrow">INFERENCE</div>
                    <h2>Hardware & models</h2>
                    <p>
                      Switch backends without changing the index. All models are
                      local.
                    </p>
                  </div>
                </div>

                <div className="backend-grid">
                  {BACKENDS.map((backend) => {
                    const available =
                      backend.id === "auto" ||
                      backend.id === "cpu" ||
                      status?.available_backends.includes(backend.id);
                    const selected = (status?.backend ?? "auto") === backend.id;
                    return (
                      <button
                        key={backend.id}
                        className={`backend-option ${selected ? "selected" : ""} ${!available ? "unavailable" : ""}`}
                        onClick={() => chooseBackend(backend.id)}
                        disabled={!available || Boolean(probing)}
                      >
                        <div className="backend-option-head">
                          <strong>{backend.label}</strong>
                          {selected && <span className="pill">active</span>}
                          {!available && (
                            <span className="pill muted">unavailable</span>
                          )}
                        </div>
                        <div className="backend-option-detail">
                          {backend.detail}
                        </div>
                        <p>{backend.blurb}</p>
                        {probing === backend.id && (
                          <span className="spinner inline" />
                        )}
                      </button>
                    );
                  })}
                </div>

                <div className="settings-grid">
                  <div className="setting-card">
                    <div className="panel-heading">Active engine</div>
                    {status?.engine ? (
                      <dl>
                        <dt>Backend</dt>
                        <dd>{status.engine.backend}</dd>
                        <dt>Device</dt>
                        <dd>{status.engine.device}</dd>
                        <dt>Model</dt>
                        <dd>{status.engine.model}</dd>
                        <dt>Shape</dt>
                        <dd>{status.engine.detail}</dd>
                      </dl>
                    ) : (
                      <p className="muted">
                        No engine loaded yet. Choose a backend or run a
                        search/index.
                      </p>
                    )}
                  </div>
                  <div className="setting-card">
                    <div className="panel-heading">Index</div>
                    <dl>
                      <dt>Documents</dt>
                      <dd>{counts?.documents ?? 0}</dd>
                      <dt>Chunks</dt>
                      <dd>{counts?.chunks ?? 0}</dd>
                      <dt>Embeddings</dt>
                      <dd>{counts?.embeddings ?? 0}</dd>
                      <dt>Roots</dt>
                      <dd>{counts?.roots ?? 0}</dd>
                    </dl>
                  </div>
                  <div className="setting-card wide">
                    <div className="panel-heading">Model paths</div>
                    <dl>
                      <dt>Gety model</dt>
                      <dd className="path">
                        {cleanPath(status?.model_root ?? "not found")}
                      </dd>
                      <dt>OpenVINO IR</dt>
                      <dd className="path">
                        {cleanPath(status?.npu_model ?? "not found")}
                      </dd>
                      <dt>PDFium</dt>
                      <dd className="path">
                        {cleanPath(status?.pdfium ?? "not found")}
                      </dd>
                      <dt>Database</dt>
                      <dd className="path">
                        {cleanPath(status?.db_path ?? "not found")}
                      </dd>
                    </dl>
                  </div>
                </div>

                <div className="callout">
                  <Icon name="bolt" />
                  <div>
                    <strong>Backend notes</strong>
                    <p>
                      CUDA uses the FP16 Gety export and NVIDIA’s runtime. NPU
                      uses the OpenVINO IR on Intel AI Boost. CPU uses the uint8
                      ONNX export. The first load compiles/loads the model and
                      may take a few seconds.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </section>

          {selected && view === "search" && (
            <aside className="preview">
              <div className="preview-head">
                <div>
                  <div className="preview-kicker">PREVIEW</div>
                  <h3>{selected.title}</h3>
                  <div className="preview-path">{cleanPath(selected.path)}</div>
                </div>
                <button
                  className="icon-button"
                  onClick={() => setSelected(null)}
                  aria-label="Close preview"
                >
                  <Icon name="x" />
                </button>
              </div>
              <div className="preview-meta">
                <span>{selected.ext.toUpperCase()}</span>
                <span>{formatBytes(selected.size)}</span>
                <span>
                  {new Date(selected.modified * 1000).toLocaleDateString()}
                </span>
              </div>
              <div className="preview-body">
                <Highlighted
                  text={selected.content.slice(0, 12000)}
                  query={query}
                />
              </div>
              <div className="preview-foot">
                <button className="primary" onClick={openFile}>
                  Open file
                  <Icon name="arrow" />
                </button>
              </div>
            </aside>
          )}
        </div>

        <footer className="statusbar">
          <div className="status-left">
            <span className="dot" />
            {indexing || health?.indexing ? (
              <span>
                {indexing
                  ? `Indexing ${basename(indexing)} · ${progress?.message ?? "working…"}`
                  : `Watching · ${
                      health?.current_file
                        ? cleanPath(health.current_file)
                        : "applying changes…"
                    }`}
              </span>
            ) : (
              <span>
                {counts?.documents ?? 0} files searchable ·{" "}
                {counts?.chunks ?? 0} chunks
              </span>
            )}
          </div>
          {indexing && (
            <div className="progress">
              <div style={{ width: `${progressPercent}%` }} />
            </div>
          )}
          <div className="status-right">
            <span>
              {status?.engine?.backend ?? status?.backend_label ?? "not loaded"}
            </span>
            <span className="status-sep">·</span>
            <span>384-d</span>
          </div>
        </footer>
      </main>
    </div>
  );
}

export default App;
