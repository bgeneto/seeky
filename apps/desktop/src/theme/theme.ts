// Theme preference, OS tracking, and native synchronization (SPEC-0014
// §4.3-4.5, §5.2, R11-R13). Pure logic: the Tauri/webview side is behind
// `ThemeAdapter`, so tests run with fakes and no Tauri runtime.
import type { PreferenceStore } from "../preferences.ts";
import { dark, light, type ThemeTokens } from "./tokens.ts";

export type EffectiveTheme = "light" | "dark";
export type ThemePreference = "system" | EffectiveTheme;

export const THEME_STORAGE_KEY = "seeky.ui.theme.v1";
export const THEME_PREFERENCES: readonly ThemePreference[] = [
  "system",
  "light",
  "dark",
];
export const THEMES: Readonly<Record<EffectiveTheme, ThemeTokens>> = {
  light,
  dark,
};

export function parseThemePreference(value: unknown): ThemePreference {
  return value === "light" || value === "dark" || value === "system"
    ? value
    : "system";
}

/** An explicit preference wins; `system` uses the OS, then `light`. */
export function resolveTheme(
  preference: ThemePreference,
  osTheme: EffectiveTheme | null,
): EffectiveTheme {
  if (preference !== "system") return preference;
  return osTheme ?? "light";
}

/** OS information and native window calls (Tauri in the app, fakes in tests). */
export interface ThemeAdapter {
  /** `prefers-color-scheme`, or null when the webview gives no usable answer. */
  mediaTheme(): EffectiveTheme | null;
  /** The native window's theme (`getCurrentWindow().theme()`). */
  nativeTheme(): Promise<EffectiveTheme | null>;
  /** `null` restores OS tracking; an override passes its explicit value. */
  setNativeTheme(theme: EffectiveTheme | null): Promise<void>;
  /** Window and webview background. */
  setNativeBackground(color: string): Promise<void>;
  show(): Promise<void>;
  /** Media-query and native theme events; returns the unsubscribe function. */
  onOsThemeChange(listener: (theme: EffectiveTheme | null) => void): () => void;
}

export interface RootLike {
  style: { setProperty(name: string, value: string): void };
  setAttribute(name: string, value: string): void;
}

/** Writes the token set as `--color-<token>` plus `data-theme`/`color-scheme`. */
export function applyThemeToRoot(root: RootLike, theme: EffectiveTheme) {
  const tokens = THEMES[theme];
  for (const [token, value] of Object.entries(tokens)) {
    root.style.setProperty(`--color-${token}`, value);
  }
  root.style.setProperty("color-scheme", theme);
  root.setAttribute("data-theme", theme);
}

export interface ThemeController {
  preference(): ThemePreference;
  effective(): EffectiveTheme;
  /** Resolves the OS theme (media, then native, then `light`) and syncs. */
  initialize(): Promise<void>;
  setPreference(preference: ThemePreference): EffectiveTheme;
  /** Subscribes to OS changes; idempotent, reference-counted teardown. */
  start(): () => void;
  subscribe(listener: () => void): () => void;
  /** Resolves when queued native calls have finished (they never reject). */
  settled(): Promise<void>;
}

export function createThemeController(options: {
  store: PreferenceStore;
  adapter: ThemeAdapter;
  apply: (theme: EffectiveTheme) => void;
  onDiagnostic?: (what: string) => void;
}): ThemeController {
  const { store, adapter, apply } = options;
  const diagnostic = options.onDiagnostic ?? (() => {});
  const listeners = new Set<() => void>();
  let preference = parseThemePreference(
    safe(() => store.read(THEME_STORAGE_KEY)),
  );
  let os = safe(() => adapter.mediaTheme());
  let effective = resolveTheme(preference, os);
  let queue: Promise<void> = Promise.resolve();
  let starts = 0;
  let unsubscribeOs: (() => void) | null = null;

  function safe<T>(read: () => T): T | null {
    try {
      return read();
    } catch {
      return null;
    }
  }

  /** Runs native calls in order; a rejection is recorded, never thrown. */
  function native(what: string, call: () => Promise<void>) {
    queue = queue.then(async () => {
      try {
        await call();
      } catch {
        diagnostic(what);
      }
    });
    return queue;
  }

  function notify() {
    for (const listener of [...listeners]) listener();
  }

  /** Applies a new effective theme; returns whether anything was notified. */
  function update(next: EffectiveTheme, force = false): boolean {
    const changed = next !== effective;
    effective = next;
    if (!changed && !force) return false;
    apply(effective);
    const background = THEMES[effective].bg;
    native("native background", () => adapter.setNativeBackground(background));
    notify();
    return true;
  }

  async function queryNative(): Promise<EffectiveTheme | null> {
    try {
      return await adapter.nativeTheme();
    } catch {
      diagnostic("native theme query");
      return null;
    }
  }

  function onOsTheme(theme: EffectiveTheme | null) {
    // An override ignores OS events; the native window may even report the
    // override itself, which must not be mistaken for the OS value.
    if (preference !== "system" || theme === null) return;
    os = theme;
    update(resolveTheme(preference, os));
  }

  return {
    preference: () => preference,
    effective: () => effective,

    async initialize() {
      if (os === null) os = await queryNative();
      effective = resolveTheme(preference, os);
      const target = preference === "system" ? null : preference;
      native("native theme", () => adapter.setNativeTheme(target));
      update(effective, true);
      await queue;
    },

    setPreference(next) {
      preference = parseThemePreference(next);
      store.write(THEME_STORAGE_KEY, preference);
      if (preference === "system") {
        // The last OS value seen applies at once. While an override is
        // active the webview reports the override, not the OS: on Windows,
        // tauri-runtime-wry copies every window ThemeChanged into WebView2
        // PreferredColorScheme. So after setTheme(null) restores OS tracking,
        // the window theme is asked first and the media query second.
        native("native theme", () => adapter.setNativeTheme(null));
        native("native theme query", async () => {
          if (preference !== "system") return;
          const current =
            (await queryNative()) ?? safe(() => adapter.mediaTheme());
          if (current !== null) onOsTheme(current);
        });
      } else {
        const explicit = preference;
        native("native theme", () => adapter.setNativeTheme(explicit));
      }
      if (!update(resolveTheme(preference, os))) notify();
      return effective;
    },

    start() {
      starts += 1;
      if (starts === 1) unsubscribeOs = adapter.onOsThemeChange(onOsTheme);
      let stopped = false;
      return () => {
        if (stopped) return;
        stopped = true;
        starts -= 1;
        if (starts === 0) {
          unsubscribeOs?.();
          unsubscribeOs = null;
        }
      };
    },

    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    settled: () => queue,
  };
}

/**
 * Startup ordering (§4.5): sync the theme while the window is hidden, render,
 * then always show the window, even when native calls or rendering fail.
 */
export async function initializeWindow(options: {
  controller: ThemeController;
  adapter: ThemeAdapter;
  render: () => void;
  onDiagnostic?: (what: string) => void;
  /** Upper bound for native startup calls; a hung call never blocks show. */
  timeoutMs?: number;
}): Promise<void> {
  const diagnostic = options.onDiagnostic ?? (() => {});
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<"timeout">((resolve) => {
    timer = setTimeout(() => resolve("timeout"), options.timeoutMs ?? 2000);
  });
  try {
    const outcome = await Promise.race([
      options.controller.initialize(),
      timeout,
    ]);
    if (outcome === "timeout") diagnostic("theme initialization timeout");
  } catch {
    diagnostic("theme initialization");
  } finally {
    clearTimeout(timer);
  }
  try {
    options.render();
  } finally {
    try {
      await options.adapter.show();
    } catch {
      diagnostic("window show");
    }
  }
}
