import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import "./App.css";
import { useI18n } from "./i18n/I18nProvider";
import { LOCALE_PREFERENCES, type LocalePreference } from "./i18n/locale";
import type { I18n, MessageKey, MessageValues } from "./i18n/messages";
import { OPERATION_ERROR_KEYS, progressPhaseKey } from "./i18n/operations";
import {
  PREVIEW_DEFAULT,
  PREVIEW_MIN,
  PREVIEW_WIDTH_KEY,
  clampPreviewWidth,
  keyboardResize,
  maxPreviewWidth,
  parsePreviewWidth,
} from "./layout/previewWidth";
import { browserStorage, createPreferenceStore } from "./preferences";
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

/** A notice is re-rendered from its key, so it follows locale changes. */
type Notice =
  { key: MessageKey; values?: MessageValues } | { summary: IndexSummary };

const BACKENDS: readonly {
  id: string;
  label: MessageKey;
  detail: MessageKey;
  description: MessageKey;
}[] = [
  {
    id: "auto",
    label: "settings.backend.auto.label",
    detail: "settings.backend.auto.detail",
    description: "settings.backend.auto.description",
  },
  {
    id: "cpu",
    label: "settings.backend.cpu.label",
    detail: "settings.backend.cpu.detail",
    description: "settings.backend.cpu.description",
  },
  {
    id: "cuda",
    label: "settings.backend.cuda.label",
    detail: "settings.backend.cuda.detail",
    description: "settings.backend.cuda.description",
  },
  {
    id: "npu",
    label: "settings.backend.npu.label",
    detail: "settings.backend.npu.detail",
    description: "settings.backend.npu.description",
  },
];

const SUPPORTED_TYPES: readonly [MessageKey, MessageKey][] = [
  ["folders.supported.pdf.label", "folders.supported.pdf"],
  ["folders.supported.docx.label", "folders.supported.docx"],
  ["folders.supported.xlsx.label", "folders.supported.xlsx"],
  ["folders.supported.pptx.label", "folders.supported.pptx"],
  ["folders.supported.text.label", "folders.supported.text"],
  ["folders.supported.html.label", "folders.supported.html"],
  ["folders.supported.code.label", "folders.supported.code"],
];

const MATCH_TAGS: Record<string, MessageKey> = {
  semantic: "search.tag.semantic",
  filename: "search.tag.filename",
  bm25: "search.tag.bm25",
};

const LOCALE_OPTIONS: Record<LocalePreference, MessageKey> = {
  system: "settings.locale.option.system",
  en: "settings.locale.option.en",
  pt: "settings.locale.option.pt",
};

const layoutStore = createPreferenceStore(browserStorage);

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

function formatWhen(i18n: I18n, timestamp: number | null | undefined) {
  // Only a missing timestamp is "never"; epoch zero is a valid time (§4.2).
  if (timestamp === null || timestamp === undefined) {
    return i18n.t("common.time.never");
  }
  return i18n.dateTime(timestamp);
}

function summaryText(i18n: I18n, summary: IndexSummary) {
  const { t } = i18n;
  if (summary.cancelled) {
    return t("folders.notice.indexCancelled", {
      summary: i18n.list([
        t("common.count.files", { count: summary.files }),
        t("indexing.summary.chunks", { count: summary.chunks }),
      ]),
    });
  }
  const parts = [t("indexing.summary.updated", { count: summary.files })];
  if (summary.unchanged) {
    parts.push(t("indexing.summary.unchanged", { count: summary.unchanged }));
  }
  parts.push(t("indexing.summary.chunks", { count: summary.chunks }));
  if (summary.skipped) {
    parts.push(t("indexing.summary.skipped", { count: summary.skipped }));
  }
  if (summary.removed) {
    parts.push(t("indexing.summary.removed", { count: summary.removed }));
  }
  return i18n.list(parts);
}

function noticeText(i18n: I18n, notice: Notice) {
  return "summary" in notice
    ? summaryText(i18n, notice.summary)
    : i18n.t(notice.key, notice.values);
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
  const { i18n, preference, setPreference } = useI18n();
  const { t } = i18n;
  const [status, setStatus] = useState<Status | null>(null);
  const [view, setView] = useState<View>("search");
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  // Raw IPC errors are diagnostic data; the UI shows an operation message (R8).
  const [error, setError] = useState<MessageKey | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [selected, setSelected] = useState<DocumentView | null>(null);
  const [progress, setProgress] = useState<IndexProgress | null>(null);
  const [indexing, setIndexing] = useState<string | null>(null);
  const [probing, setProbing] = useState<string | null>(null);
  const searchSeq = useRef(0);
  const contentRef = useRef<HTMLDivElement>(null);
  const [previewWidth, setPreviewWidth] = useState(() =>
    parsePreviewWidth(layoutStore.read(PREVIEW_WIDTH_KEY)),
  );

  function contentWidth() {
    return contentRef.current?.getBoundingClientRect().width ?? 0;
  }

  function commitPreviewWidth(width: number) {
    setPreviewWidth(width);
    layoutStore.write(PREVIEW_WIDTH_KEY, String(width));
  }

  // SPEC-0014-R17: drag the separator; the width persists on release.
  function startPreviewResize(event: ReactPointerEvent<HTMLDivElement>) {
    const rect = contentRef.current?.getBoundingClientRect();
    if (event.button !== 0 || !rect) return;
    event.preventDefault();
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing");
    let latest = clampPreviewWidth(previewWidth, rect.width);
    const move = (moveEvent: PointerEvent) => {
      latest = clampPreviewWidth(rect.right - moveEvent.clientX, rect.width);
      setPreviewWidth(latest);
    };
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      document.body.classList.remove("resizing");
      commitPreviewWidth(latest);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  }

  function onPreviewResizeKey(event: ReactKeyboardEvent<HTMLDivElement>) {
    const width = contentWidth();
    const next = keyboardResize(
      clampPreviewWidth(previewWidth, width),
      event.key,
      width,
    );
    if (next === null) return;
    event.preventDefault();
    commitPreviewWidth(next);
  }

  async function refresh() {
    try {
      const next = await invoke<Status>("get_status");
      setStatus(next);
    } catch {
      setError(OPERATION_ERROR_KEYS.refresh);
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
      } catch {
        if (seq === searchSeq.current) {
          setError(OPERATION_ERROR_KEYS.search);
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
        title: t("folders.dialog.addTitle"),
      });
      if (!picked || Array.isArray(picked)) return;
      const root = await invoke<Root>("add_root", { path: picked });
      await refresh();
      setView("files");
      setNotice({
        key: root.watch_enabled
          ? "folders.notice.addedWatching"
          : "folders.notice.addedWatchFailed",
      });
    } catch {
      setError(OPERATION_ERROR_KEYS.addFolder);
    }
  }

  async function removeRoot(root: Root) {
    try {
      await invoke("remove_root", { id: root.id });
      await refresh();
      setNotice({
        key: "folders.notice.removed",
        values: { folder: cleanPath(root.path) },
      });
    } catch {
      setError(OPERATION_ERROR_KEYS.removeFolder);
    }
  }

  async function toggleWatch(root: Root) {
    try {
      const updated = await invoke<Root>("set_root_watching", {
        id: root.id,
        enabled: !root.watch_enabled,
      });
      await refresh();
      setNotice({
        key: updated.watch_enabled
          ? "folders.notice.watchResumed"
          : "folders.notice.watchPaused",
        values: { folder: basename(updated.path) },
      });
    } catch {
      setError(OPERATION_ERROR_KEYS.watch);
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
      message: "",
    });
    try {
      const summary = await invoke<IndexSummary>("start_index", {
        path: root.path,
      });
      setNotice({ summary });
      await refresh();
    } catch {
      setError(OPERATION_ERROR_KEYS.startIndex);
    } finally {
      setIndexing(null);
      setProgress(null);
    }
  }

  async function cancelIndexing() {
    try {
      await invoke("cancel_index");
      setNotice({ key: "folders.notice.cancelRequested" });
    } catch {
      setError(OPERATION_ERROR_KEYS.cancelIndex);
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
      setNotice({
        key: "settings.backend.noticeReady",
        values: { backend: info.backend, device: info.device },
      });
    } catch {
      setError(OPERATION_ERROR_KEYS.probeBackend);
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
      if (!doc) setError("errors.document.notFound");
    } catch {
      setError(OPERATION_ERROR_KEYS.loadPreview);
    }
  }

  async function openFile() {
    if (!selected) return;
    try {
      await invoke("open_document", { id: selected.id });
    } catch {
      setError(OPERATION_ERROR_KEYS.openFile);
    }
  }

  const counts = status?.counts;
  const health = status?.health;
  const documents = counts?.documents ?? 0;
  const chunks = counts?.chunks ?? 0;
  const progressPercent =
    progress && progress.total > 0
      ? Math.min(100, Math.round((progress.current / progress.total) * 100))
      : 0;
  const engineName =
    status?.engine?.backend ??
    status?.backend_label ??
    t("common.status.notLoaded");

  function healthMessage() {
    if (health?.indexing) return t("common.state.working");
    if (!health || health.last_indexed_at === null) {
      return t("folders.health.noActivity");
    }
    return t("folders.health.state.idle");
  }

  function pathValue(path: string | null | undefined) {
    return path ? cleanPath(path) : t("common.status.notFound");
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">s</span>
          <span className="brand-name">
            seeky<span className="brand-dot">.</span>
          </span>
        </div>
        <div className="brand-tag">{t("common.brand.tagline")}</div>

        <nav className="nav">
          <button
            className={view === "search" ? "nav-item active" : "nav-item"}
            onClick={() => setView("search")}
          >
            <Icon name="search" />
            {t("nav.search")}
          </button>
          <button
            className={view === "files" ? "nav-item active" : "nav-item"}
            onClick={() => setView("files")}
          >
            <Icon name="folder" />
            {t("nav.folders")}
          </button>
          <button
            className={view === "settings" ? "nav-item active" : "nav-item"}
            onClick={() => setView("settings")}
          >
            <Icon name="sliders" />
            {t("nav.settings")}
          </button>
        </nav>

        <div className="sidebar-spacer" />
        <div className="backend-card">
          <div className="backend-card-label">
            <Icon name="bolt" />
            {t("common.inference.label")}
          </div>
          <div className="backend-card-value">{engineName}</div>
          <div className="backend-card-detail">
            {status?.engine?.detail ?? t("common.status.notLoaded")}
          </div>
        </div>
        <div className="sidebar-foot">
          <span>{t("common.count.files", { count: documents })}</span>
          <span>{t("common.count.chunks", { count: chunks })}</span>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="searchbox">
            <Icon name="search" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("search.input.placeholder")}
              spellCheck={false}
              autoFocus
            />
            {searching && <span className="spinner" />}
            {query && !searching && (
              <button
                className="clear"
                onClick={() => setQuery("")}
                aria-label={t("search.input.action.clear")}
              >
                <Icon name="x" />
              </button>
            )}
          </div>
          <button className="ghost-button" onClick={() => setView("files")}>
            <Icon name="folder" />
            {t("search.action.addFolder")}
          </button>
        </header>

        {error && (
          <div className="banner error">
            <span>{t(error)}</span>
            <button onClick={() => setError(null)}>
              {t("common.action.dismiss")}
            </button>
          </div>
        )}
        {notice && (
          <div className="banner notice">
            <span>{noticeText(i18n, notice)}</span>
            <button onClick={() => setNotice(null)}>
              {t("common.action.dismiss")}
            </button>
          </div>
        )}

        <div
          ref={contentRef}
          className={
            selected && view === "search" ? "content with-preview" : "content"
          }
          style={{ "--preview-width": `${previewWidth}px` } as CSSProperties}
        >
          <section className="results-area">
            {view === "search" && (
              <>
                {!query.trim() && (
                  <div className="hero">
                    <div className="hero-kicker">{t("search.hero.kicker")}</div>
                    <h1>{t("search.hero.title")}</h1>
                    <p>{t("search.hero.body")}</p>
                    <div className="hero-actions">
                      <button className="primary" onClick={addFolder}>
                        {t("search.hero.action.addFolder")}
                      </button>
                      <button
                        className="secondary"
                        onClick={() => setView("settings")}
                      >
                        {t("search.hero.action.chooseBackend")}
                      </button>
                    </div>
                    <div className="hero-stats">
                      <div>
                        <strong>{i18n.number(documents)}</strong>
                        <span>{t("search.hero.stats.filesIndexed")}</span>
                      </div>
                      <div>
                        <strong>{i18n.number(chunks)}</strong>
                        <span>{t("search.hero.stats.semanticChunks")}</span>
                      </div>
                      <div>
                        <strong>
                          {status?.engine?.backend ??
                            t("common.status.notAvailable")}
                        </strong>
                        <span>{t("search.hero.stats.activeBackend")}</span>
                      </div>
                    </div>
                  </div>
                )}

                {query.trim() && (
                  <div className="results-head">
                    <span>
                      {searching
                        ? t("search.status.searching")
                        : response
                          ? t("search.results.count", {
                              count: response.hits.length,
                              elapsedMs: Math.max(
                                0,
                                Math.round(response.took_ms),
                              ),
                            })
                          : t("search.status.noResultsYet")}
                    </span>
                    {response && (
                      <span className="result-meta">
                        {response.semantic_used
                          ? t("search.mode.hybrid")
                          : t("search.mode.lexical")}{" "}
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
                      <h3>{t("search.empty.title")}</h3>
                      <p>{t("search.empty.body")}</p>
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
                          <span className="score">
                            {i18n.number(hit.score, {
                              minimumFractionDigits: 2,
                              maximumFractionDigits: 2,
                            })}
                          </span>
                        </div>
                        <div className="result-path">
                          {parentPath(hit.path)} · {hit.ext.toUpperCase()}
                          {hit.page
                            ? ` · ${t("search.result.page", {
                                page: i18n.number(hit.page, {
                                  useGrouping: false,
                                }),
                              })}`
                            : ""}
                        </div>
                        <p className="result-snippet">
                          <Highlighted text={hit.snippet} query={query} />
                        </p>
                        <div className="result-tags">
                          {hit.matched
                            .filter((kind) => kind in MATCH_TAGS)
                            .map((kind) => (
                              <span key={kind} className={`tag ${kind}`}>
                                {t(MATCH_TAGS[kind])}
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
                    <div className="eyebrow">{t("folders.eyebrow")}</div>
                    <h2>{t("folders.title")}</h2>
                    <p>{t("folders.description")}</p>
                  </div>
                  <button className="primary" onClick={addFolder}>
                    <Icon name="folder" />
                    {t("folders.action.add")}
                  </button>
                </div>

                <div className="root-list">
                  {status?.roots.length === 0 && (
                    <div className="empty-state">
                      <Icon name="folder" />
                      <h3>{t("folders.empty.title")}</h3>
                      <p>{t("folders.empty.body")}</p>
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
                          {t("folders.root.meta.documents", {
                            count: root.documents,
                          })}{" "}
                          ·{" "}
                          {root.documents > 0
                            ? t("folders.root.status.indexed")
                            : t("folders.root.status.readyToIndex")}
                        </div>
                      </div>
                      <div className="root-actions">
                        <button
                          className={`watch-button ${root.watch_enabled ? "on" : ""}`}
                          onClick={() => toggleWatch(root)}
                          aria-pressed={root.watch_enabled}
                          title={
                            root.watch_enabled
                              ? t("folders.root.action.pauseWatching")
                              : t("folders.root.action.resumeWatching")
                          }
                        >
                          <span className="watch-dot" />
                          {root.watch_enabled
                            ? t("common.state.watching")
                            : t("common.state.paused")}
                        </button>
                        <button
                          className="secondary"
                          onClick={() => indexRoot(root)}
                          disabled={
                            Boolean(indexing) || Boolean(health?.indexing)
                          }
                        >
                          {indexing === root.path
                            ? t("folders.root.action.indexing")
                            : root.documents > 0
                              ? t("folders.root.action.reindex")
                              : t("folders.root.action.index")}
                        </button>
                        <button
                          className="icon-button"
                          onClick={() => removeRoot(root)}
                          aria-label={t("folders.root.action.remove")}
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
                      <div className="panel-heading">
                        {t("folders.health.title")}
                      </div>
                      <p>{healthMessage()}</p>
                    </div>
                    <div className="health-actions">
                      {health?.indexing && (
                        <button
                          className="ghost-button"
                          onClick={cancelIndexing}
                        >
                          {t("folders.health.action.cancel")}
                        </button>
                      )}
                      <span
                        className={`health-state ${health?.indexing ? "busy" : ""}`}
                      >
                        {health?.indexing
                          ? t("common.state.indexing")
                          : t("folders.health.state.idle")}
                      </span>
                    </div>
                  </div>
                  <div className="health-grid">
                    <div>
                      <span>{t("folders.health.watcher.label")}</span>
                      <strong>
                        {health?.watching
                          ? t("folders.health.watcher.watching", {
                              count: health.watched_roots,
                            })
                          : t("common.state.paused")}
                      </strong>
                    </div>
                    <div>
                      <span>{t("folders.health.pending")}</span>
                      <strong>{i18n.number(health?.pending ?? 0)}</strong>
                    </div>
                    <div>
                      <span>{t("folders.health.lastIndexed")}</span>
                      <strong>
                        {formatWhen(i18n, health?.last_indexed_at)}
                      </strong>
                    </div>
                    <div>
                      <span>{t("folders.health.skippedErrors")}</span>
                      <strong>
                        {i18n.number(health?.skipped ?? 0)} /{" "}
                        {i18n.number(health?.errors ?? 0)}
                      </strong>
                    </div>
                  </div>
                  {health?.current_file && (
                    <div className="health-current">
                      {t("folders.health.processing")}{" "}
                      <code>{cleanPath(health.current_file)}</code>
                    </div>
                  )}
                  {health?.last_error && (
                    <div className="health-error">
                      {t("folders.health.lastError")}
                    </div>
                  )}
                  {health && health.details.length > 0 && (
                    <div className="health-details">
                      {t("folders.health.recentIssues", {
                        count: health.details.length,
                      })}
                    </div>
                  )}
                  <p className="health-hint">{t("folders.health.hint")}</p>
                </div>

                <div className="type-panel">
                  <div className="panel-heading">
                    {t("folders.supported.title")}
                  </div>
                  <div className="type-grid">
                    {SUPPORTED_TYPES.map(([label, detail]) => (
                      <div className="type-chip" key={label}>
                        <strong>{t(label)}</strong>
                        <span>{t(detail)}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="callout">
                  <Icon name="database" />
                  <div>
                    <strong>{t("folders.how.title")}</strong>
                    <p>{t("folders.how.body")}</p>
                  </div>
                </div>
              </div>
            )}

            {view === "settings" && (
              <div className="page">
                <div className="page-head">
                  <div>
                    <div className="eyebrow">{t("settings.eyebrow")}</div>
                    <h2>{t("settings.title")}</h2>
                    <p>{t("settings.description")}</p>
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
                          <strong>{t(backend.label)}</strong>
                          {selected && (
                            <span className="pill">
                              {t("settings.backend.active")}
                            </span>
                          )}
                          {!available && (
                            <span className="pill muted">
                              {t("settings.backend.unavailable")}
                            </span>
                          )}
                        </div>
                        <div className="backend-option-detail">
                          {t(backend.detail)}
                        </div>
                        <p>{t(backend.description)}</p>
                        {probing === backend.id && (
                          <span className="spinner inline" />
                        )}
                      </button>
                    );
                  })}
                </div>

                <div className="settings-grid">
                  <div className="setting-card">
                    <div className="panel-heading">
                      {t("settings.engine.title")}
                    </div>
                    {status?.engine ? (
                      <dl>
                        <dt>{t("settings.engine.backend")}</dt>
                        <dd>{status.engine.backend}</dd>
                        <dt>{t("settings.engine.device")}</dt>
                        <dd>{status.engine.device}</dd>
                        <dt>{t("settings.engine.model")}</dt>
                        <dd>{status.engine.model}</dd>
                        <dt>{t("settings.engine.shape")}</dt>
                        <dd>{status.engine.detail}</dd>
                      </dl>
                    ) : (
                      <p className="muted">{t("settings.engine.empty")}</p>
                    )}
                  </div>
                  <div className="setting-card">
                    <div className="panel-heading">
                      {t("settings.index.title")}
                    </div>
                    <dl>
                      <dt>{t("settings.index.documents")}</dt>
                      <dd>{i18n.number(documents)}</dd>
                      <dt>{t("settings.index.chunks")}</dt>
                      <dd>{i18n.number(chunks)}</dd>
                      <dt>{t("settings.index.embeddings")}</dt>
                      <dd>{i18n.number(counts?.embeddings ?? 0)}</dd>
                      <dt>{t("settings.index.roots")}</dt>
                      <dd>{i18n.number(counts?.roots ?? 0)}</dd>
                    </dl>
                  </div>
                  <div className="setting-card">
                    <div className="panel-heading">
                      {t("settings.preferences.title")}
                    </div>
                    <label className="preference-row">
                      <span>{t("settings.locale.label")}</span>
                      <select
                        value={preference}
                        onChange={(event) =>
                          setPreference(event.target.value as LocalePreference)
                        }
                      >
                        {LOCALE_PREFERENCES.map((option) => (
                          <option
                            key={option}
                            value={option}
                            lang={option === "system" ? undefined : option}
                          >
                            {t(LOCALE_OPTIONS[option])}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <div className="setting-card wide">
                    <div className="panel-heading">
                      {t("settings.paths.title")}
                    </div>
                    <dl>
                      <dt>{t("settings.paths.embeddingModel")}</dt>
                      <dd className="path">{pathValue(status?.model_root)}</dd>
                      <dt>{t("settings.paths.openvinoIr")}</dt>
                      <dd className="path">{pathValue(status?.npu_model)}</dd>
                      <dt>{t("settings.paths.pdfium")}</dt>
                      <dd className="path">{pathValue(status?.pdfium)}</dd>
                      <dt>{t("settings.paths.database")}</dt>
                      <dd className="path">{pathValue(status?.db_path)}</dd>
                    </dl>
                  </div>
                </div>

                <div className="callout">
                  <Icon name="bolt" />
                  <div>
                    <strong>{t("settings.backendNotes.title")}</strong>
                    <p>{t("settings.backendNotes.body")}</p>
                  </div>
                </div>
              </div>
            )}
          </section>

          {selected && view === "search" && (
            <aside className="preview">
              <div
                className="preview-resizer"
                role="separator"
                aria-orientation="vertical"
                aria-label={t("preview.action.resize")}
                title={t("preview.action.resize")}
                aria-valuemin={PREVIEW_MIN}
                aria-valuemax={maxPreviewWidth(contentWidth())}
                aria-valuenow={clampPreviewWidth(previewWidth, contentWidth())}
                tabIndex={0}
                onPointerDown={startPreviewResize}
                onKeyDown={onPreviewResizeKey}
                onDoubleClick={() => commitPreviewWidth(PREVIEW_DEFAULT)}
              />
              <div className="preview-head">
                <div>
                  <div className="preview-kicker">{t("preview.kicker")}</div>
                  <h3>{selected.title}</h3>
                  <div className="preview-path">{cleanPath(selected.path)}</div>
                </div>
                <button
                  className="icon-button"
                  onClick={() => setSelected(null)}
                  aria-label={t("preview.action.close")}
                >
                  <Icon name="x" />
                </button>
              </div>
              <div className="preview-meta">
                <span>{selected.ext.toUpperCase()}</span>
                <span>{i18n.bytes(selected.size)}</span>
                <span>{i18n.date(selected.modified)}</span>
              </div>
              <div className="preview-body">
                <Highlighted
                  text={selected.content.slice(0, 12000)}
                  query={query}
                />
              </div>
              <div className="preview-foot">
                <button className="primary" onClick={openFile}>
                  {t("preview.action.openFile")}
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
                  ? `${t("status.indexingFolder", { folder: basename(indexing) })} · ${t(progressPhaseKey(progress?.phase))}`
                  : `${t("status.watching")} · ${
                      health?.current_file
                        ? cleanPath(health.current_file)
                        : t("common.state.applyingChanges")
                    }`}
              </span>
            ) : (
              <span>
                {t("status.filesSearchable", { count: documents })} ·{" "}
                {t("common.count.chunks", { count: chunks })}
              </span>
            )}
          </div>
          {indexing && (
            <div className="progress">
              <div style={{ width: `${progressPercent}%` }} />
            </div>
          )}
          <div className="status-right">
            <span>{engineName}</span>
            <span className="status-sep">·</span>
            <span>
              {status?.engine?.detail ?? t("common.status.notAvailable")}
            </span>
          </div>
        </footer>
      </main>
    </div>
  );
}

export default App;
